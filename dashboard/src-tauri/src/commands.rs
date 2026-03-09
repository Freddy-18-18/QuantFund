use std::sync::{Arc, Mutex};

use tauri::{Emitter, Manager, State};

use crate::database::{get_data_stats, DbPool};
use crate::finnhub::{
    EconomicEvent, FinnhubClient,
};
use crate::mt5_connection::{
    Mt5AccountInfo, Mt5Deal, Mt5Order, Mt5Position, Mt5SymbolInfo,
};
use crate::state::AppState;
use crate::xauusd_engine::{run_xauusd_backtest, XauusdBacktestConfig, XauusdBacktestResult};

pub use crate::state::DashboardSnapshot;

// ── Snapshot ──────────────────────────────────────────────────────────────────

/// Returns the latest dashboard snapshot synchronously.
#[tauri::command]
pub fn get_snapshot(state: State<Arc<Mutex<AppState>>>) -> DashboardSnapshot {
    state.lock().unwrap().snapshot.clone()
}

// ── Legacy synthetic backtest (EURUSD simulation) ─────────────────────────────

/// Kicks off the synthetic backtest in a background thread.
#[tauri::command]
pub fn start_backtest(
    state: State<Arc<Mutex<AppState>>>,
    app_handle: tauri::AppHandle,
) -> Result<(), String> {
    {
        let mut s = state.lock().unwrap();
        if s.running {
            return Err("backtest already running".into());
        }
        s.running = true;
    }

    let state_arc = Arc::clone(&state);
    std::thread::spawn(move || {
        crate::engine::run_backtest(state_arc, app_handle);
    });

    Ok(())
}

/// Signals the legacy engine to stop after the current tick.
#[tauri::command]
pub fn stop_engine(state: State<Arc<Mutex<AppState>>>) {
    state.lock().unwrap().running = false;
}

// ── XAUUSD backtest ───────────────────────────────────────────────────────────

/// Get database statistics for XAUUSD data.
#[tauri::command]
pub async fn fetch_data_stats(
    pool: State<'_, Option<DbPool>>,
    symbol: String,
    timeframe: String,
) -> Result<crate::database::DataStats, String> {
    let pool = pool.inner();
    let client = match pool {
        Some(p) => p.get().await.map_err(|e| format!("Pool error: {}", e))?,
        None => return Err("Database not available. Please ensure PostgreSQL is running.".into()),
    };

    get_data_stats(&*client, &symbol, &timeframe)
        .await
        .map_err(|e| format!("DB error: {:#}", e))
}

/// Run XAUUSD backtest with custom configuration.
/// Returns `Err("Cancelled")` if the user cancelled via `cancel_backtest`.
#[tauri::command]
pub async fn start_xauusd_backtest(
    state: State<'_, Arc<Mutex<AppState>>>,
    app_handle: tauri::AppHandle,
    config: XauusdBacktestConfig,
) -> Result<XauusdBacktestResult, String> {
    // Arm the cancel flag (reset to false) and get a shareable Arc.
    let cancel_flag = state.lock().unwrap().arm_cancel_flag();

    let db_config = crate::database::DbConfig::default();

    let result = run_xauusd_backtest(config, db_config, cancel_flag, move |progress, message| {
        let _ = app_handle.emit("backtest-progress", (progress, message));
    })
    .await;

    match result {
        Ok(r) => Ok(r),
        Err(e) if e.to_string() == "Cancelled" => Err("Cancelled".into()),
        Err(e) => Err(format!("Backtest failed: {}", e)),
    }
}

/// Cancel a running XAUUSD backtest.
/// The engine will abort at the next progress callback.
#[tauri::command]
pub fn cancel_backtest(state: State<Arc<Mutex<AppState>>>) {
    use std::sync::atomic::Ordering;
    state
        .lock()
        .unwrap()
        .cancel_flag
        .store(true, Ordering::Relaxed);
}

// ── Strategy catalogue ────────────────────────────────────────────────────────

/// Load all strategies, including unavailable (future) ones.
#[tauri::command]
pub fn load_strategies() -> Result<Vec<StrategyInfo>, String> {
    Ok(vec![
        StrategyInfo {
            id: "sma_crossover".to_string(),
            name: "SMA Crossover".to_string(),
            description: "Simple Moving Average crossover strategy — golden/death cross signals."
                .to_string(),
            available: true,
            parameters: vec![
                StrategyParameter {
                    name: "fast_period".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "20".to_string(),
                    min: Some(5.0),
                    max: Some(100.0),
                },
                StrategyParameter {
                    name: "slow_period".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "50".to_string(),
                    min: Some(10.0),
                    max: Some(200.0),
                },
                StrategyParameter {
                    name: "position_size".to_string(),
                    param_type: "float".to_string(),
                    default_value: "0.1".to_string(),
                    min: Some(0.01),
                    max: Some(1.0),
                },
            ],
        },
        StrategyInfo {
            id: "mean_reversion".to_string(),
            name: "Mean Reversion".to_string(),
            description: "Bollinger Bands mean reversion — enters at bands, exits at middle.".to_string(),
            available: true,
            parameters: vec![
                StrategyParameter {
                    name: "period".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "20".to_string(),
                    min: Some(10.0),
                    max: Some(100.0),
                },
                StrategyParameter {
                    name: "std_dev".to_string(),
                    param_type: "float".to_string(),
                    default_value: "2.0".to_string(),
                    min: Some(1.0),
                    max: Some(4.0),
                },
                StrategyParameter {
                    name: "position_size".to_string(),
                    param_type: "float".to_string(),
                    default_value: "0.1".to_string(),
                    min: Some(0.01),
                    max: Some(1.0),
                },
            ],
        },
        StrategyInfo {
            id: "momentum".to_string(),
            name: "Momentum RSI".to_string(),
            description: "RSI-based momentum strategy — buys oversold, sells overbought.".to_string(),
            available: true,
            parameters: vec![
                StrategyParameter {
                    name: "rsi_period".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "14".to_string(),
                    min: Some(5.0),
                    max: Some(50.0),
                },
                StrategyParameter {
                    name: "oversold".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "30".to_string(),
                    min: Some(10.0),
                    max: Some(40.0),
                },
                StrategyParameter {
                    name: "overbought".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "70".to_string(),
                    min: Some(60.0),
                    max: Some(90.0),
                },
                StrategyParameter {
                    name: "position_size".to_string(),
                    param_type: "float".to_string(),
                    default_value: "0.1".to_string(),
                    min: Some(0.01),
                    max: Some(1.0),
                },
            ],
        },
        StrategyInfo {
            id: "breakout".to_string(),
            name: "Channel Breakout".to_string(),
            description: "Price channel breakout — enters on new highs/lows.".to_string(),
            available: true,
            parameters: vec![
                StrategyParameter {
                    name: "lookback".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "20".to_string(),
                    min: Some(10.0),
                    max: Some(100.0),
                },
                StrategyParameter {
                    name: "position_size".to_string(),
                    param_type: "float".to_string(),
                    default_value: "0.1".to_string(),
                    min: Some(0.01),
                    max: Some(1.0),
                },
            ],
        },
        StrategyInfo {
            id: "scalping".to_string(),
            name: "Scalping".to_string(),
            description: "High-frequency scalping on small price movements.".to_string(),
            available: false,
            parameters: vec![
                StrategyParameter {
                    name: "ema_fast".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "5".to_string(),
                    min: Some(3.0),
                    max: Some(20.0),
                },
                StrategyParameter {
                    name: "ema_slow".to_string(),
                    param_type: "integer".to_string(),
                    default_value: "13".to_string(),
                    min: Some(8.0),
                    max: Some(50.0),
                },
                StrategyParameter {
                    name: "position_size".to_string(),
                    param_type: "float".to_string(),
                    default_value: "0.05".to_string(),
                    min: Some(0.01),
                    max: Some(0.5),
                },
            ],
        },
    ])
}

// ── Persistence ───────────────────────────────────────────────────────────────

/// Persist the current strategy configuration to the app's config directory.
#[tauri::command]
pub fn save_strategy_config(
    app_handle: tauri::AppHandle,
    config: XauusdBacktestConfig,
) -> Result<(), String> {
    let config_dir = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| format!("Cannot resolve config dir: {}", e))?;

    std::fs::create_dir_all(&config_dir)
        .map_err(|e| format!("Cannot create config dir: {}", e))?;

    let path = config_dir.join("strategy_config.json");
    let json =
        serde_json::to_string_pretty(&config).map_err(|e| format!("Serialise error: {}", e))?;

    std::fs::write(&path, json).map_err(|e| format!("Write error: {}", e))?;

    tracing::info!("Strategy config saved to {}", path.display());
    Ok(())
}

/// Load a previously saved strategy configuration, if any.
#[tauri::command]
pub fn load_strategy_config(
    app_handle: tauri::AppHandle,
) -> Result<Option<XauusdBacktestConfig>, String> {
    let path = app_handle
        .path()
        .app_config_dir()
        .map_err(|e| format!("Cannot resolve config dir: {}", e))?
        .join("strategy_config.json");

    if !path.exists() {
        return Ok(None);
    }

    let raw = std::fs::read_to_string(&path).map_err(|e| format!("Read error: {}", e))?;
    let cfg: XauusdBacktestConfig =
        serde_json::from_str(&raw).map_err(|e| format!("Parse error: {}", e))?;

    Ok(Some(cfg))
}

// ── DTOs ──────────────────────────────────────────────────────────────────────

#[derive(serde::Serialize, serde::Deserialize)]
pub struct StrategyInfo {
    pub id: String,
    pub name: String,
    pub description: String,
    /// false = coming soon; the frontend should disable selection.
    pub available: bool,
    pub parameters: Vec<StrategyParameter>,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct StrategyParameter {
    pub name: String,
    pub param_type: String,
    pub default_value: String,
    pub min: Option<f64>,
    pub max: Option<f64>,
}

// ── MT5 Connection Commands ────────────────────────────────────────────────────

#[derive(serde::Serialize, serde::Deserialize)]
#[allow(dead_code)]
pub struct Mt5ConnectionConfig {
    pub path: Option<String>,
}

#[tauri::command]
pub async fn mt5_initialize(path: Option<String>) -> Result<bool, String> {
    let mt5_path = path.unwrap_or_else(|| {
        "C:\\Program Files\\MetaTrader 5\\terminal64.exe".to_string()
    });

    let python_code = format!(r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
try:
    import MetaTrader5 as mt5
    if mt5.initialize(path=r'{}'):
        print('MT5 initialized successfully')
        print(f'MT5 version: {{mt5.__version__}}')
        account_info = mt5.account_info()
        if account_info is not None:
            print(f'Login: {{account_info.login}}')
            print(f'Server: {{account_info.server}}')
            print(f'Balance: {{account_info.balance}}')
        else:
            print('No account logged in')
    else:
        print(f'initialize() failed: {{mt5.last_error()}}')
except Exception as e:
    print(f'Error: {{e}}')
"#, mt5_path.replace("\\", "\\\\"));

    let result = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&result.stdout);
    let stderr = String::from_utf8_lossy(&result.stderr);
    tracing::info!("MT5 init output: {} | stderr: {}", stdout, stderr);
    
    Ok(result.status.success())
}

#[tauri::command]
pub async fn mt5_get_account_info() -> Result<Option<Mt5AccountInfo>, String> {
    let python_code = r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print('NOT_INITIALIZED')
    sys.exit(0)

account = mt5.account_info()
if account is None:
    print('NO_ACCOUNT')
    sys.exit(0)

data = {
    'login': account.login,
    'server': account.server,
    'currency': account.currency,
    'balance': float(account.balance),
    'equity': float(account.equity),
    'margin': float(account.margin),
    'free_margin': float(account.margin_free),
    'margin_level': float(account.margin_level) if account.margin_level else 0.0,
    'profit': float(account.profit),
    'leverage': account.leverage
}
print(json.dumps(data))
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    if stdout.contains("NOT_INITIALIZED") || stdout.contains("NO_ACCOUNT") {
        return Ok(None);
    }

    let account: Mt5AccountInfo = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(Some(account))
}

#[tauri::command]
pub async fn mt5_get_positions() -> Result<Vec<Mt5Position>, String> {
    let python_code = r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print('[]')
    sys.exit(0)

positions = mt5.positions_get()
if positions is None or len(positions) == 0:
    print('[]')
    sys.exit(0)

result = []
for pos in positions:
    result.append({
        'ticket': pos.ticket,
        'symbol': pos.symbol,
        'volume': float(pos.volume),
        'open_price': float(pos.price_open),
        'current_price': float(pos.price_current),
        'profit': float(pos.profit),
        'side': 'Buy' if pos.type == 0 else 'Sell',
        'open_time': str(pos.time_update)
    })
print(json.dumps(result))
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let positions: Vec<Mt5Position> = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(positions)
}

#[tauri::command]
pub async fn mt5_get_orders() -> Result<Vec<Mt5Order>, String> {
    let python_code = r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print('[]')
    sys.exit(0)

orders = mt5.orders_get()
if orders is None or len(orders) == 0:
    print('[]')
    sys.exit(0)

result = []
for order in orders:
    result.append({
        'ticket': order.ticket,
        'symbol': order.symbol,
        'volume': float(order.volume_initial),
        'price': float(order.price_open),
        'order_type': order.type_str,
        'status': 'Pending',
        'open_time': str(order.time_setup)
    })
print(json.dumps(result))
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let orders: Vec<Mt5Order> = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(orders)
}

#[tauri::command]
pub async fn mt5_get_deals(_from_date: Option<String>, _to_date: Option<String>) -> Result<Vec<Mt5Deal>, String> {
    let python_code = r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json
from datetime import datetime, timedelta

if not mt5.initialize():
    print('[]')
    sys.exit(0)

from_date = datetime.now() - timedelta(days=30)
to_date = datetime.now()

deals = mt5.history_deals_get(from_date, to_date)
if deals is None or len(deals) == 0:
    print('[]')
    sys.exit(0)

result = []
for deal in deals:
    if deal.entry == 0:
        entry = 'IN'
    elif deal.entry == 1:
        entry = 'OUT'
    else:
        entry = 'UNKNOWN'
    result.append({
        'ticket': deal.ticket,
        'order': deal.order,
        'symbol': deal.symbol,
        'volume': float(deal.volume),
        'price': float(deal.price),
        'profit': float(deal.profit),
        'side': 'Buy' if deal.type == 0 else 'Sell',
        'entry': entry,
        'time': str(deal.time)
    })
print(json.dumps(result))
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let deals: Vec<Mt5Deal> = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(deals)
}

#[tauri::command]
pub async fn mt5_get_symbols(group: Option<String>) -> Result<Vec<Mt5SymbolInfo>, String> {
    let group_filter = group.unwrap_or_else(|| "*".to_string());
    
    let python_code = format!(r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print('[]')
    sys.exit(0)

symbols = mt5.symbols_get(group='{}')
if symbols is None or len(symbols) == 0:
    print('[]')
    sys.exit(0)

result = []
for sym in symbols[:50]:
    info = mt5.symbol_info(sym.name)
    if info is None:
        continue
    result.append({{
        'symbol': sym.name,
        'bid': float(info.bid) if info.bid else 0.0,
        'ask': float(info.ask) if info.ask else 0.0,
        'spread': float(info.spread),
        'digits': info.digits,
        'volume_min': float(info.volume_min),
        'volume_max': float(info.volume_max),
        'volume_step': float(info.volume_step)
    }})
print(json.dumps(result))
"#, group_filter);

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let symbols: Vec<Mt5SymbolInfo> = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(symbols)
}

#[tauri::command]
pub async fn mt5_shutdown() -> Result<bool, String> {
    let python_code = r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
result = mt5.shutdown()
print('OK' if result else 'FAIL')
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    Ok(output.status.success())
}

#[tauri::command]
pub async fn mt5_is_initialized() -> Result<bool, String> {
    let python_code = r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
initialized = mt5.initialize()
print('true' if initialized else 'false')
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    Ok(stdout.trim() == "true")
}

// ── Multi-Broker Commands ──────────────────────────────────────────────────────

#[derive(serde::Serialize, serde::Deserialize, Clone)]
pub struct BrokerConnection {
    pub id: String,
    pub name: String,
    pub broker_type: String,
    pub server: String,
    pub connected: bool,
    pub account_info: Option<Mt5AccountInfo>,
    pub last_sync: Option<String>,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct BrokerConfig {
    pub name: String,
    pub broker_type: String,
    pub server: String,
    pub login: Option<i64>,
    pub password: Option<String>,
}

static BROKERS: std::sync::LazyLock<std::sync::Mutex<Vec<BrokerConnection>>> = 
    std::sync::LazyLock::new(|| std::sync::Mutex::new(vec![
        BrokerConnection {
            id: "default".to_string(),
            name: "Primary MT5".to_string(),
            broker_type: "MT5".to_string(),
            server: "Demo-Server".to_string(),
            connected: false,
            account_info: None,
            last_sync: None,
        }
    ]));

#[tauri::command]
pub fn get_broker_connections() -> Result<Vec<BrokerConnection>, String> {
    let brokers = BROKERS.lock().unwrap();
    Ok(brokers.clone())
}

#[tauri::command]
pub async fn connect_broker(config: BrokerConfig) -> Result<BrokerConnection, String> {
    let python_code = format!(r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json
import uuid

broker_id = str(uuid.uuid4())[:8]

if not mt5.initialize():
    print(json.dumps({{'success': False, 'error': 'Failed to initialize MT5'}}))
    sys.exit(0)

account = mt5.account_info()
if account is None:
    print(json.dumps({{'success': False, 'error': 'No account logged in'}}))
    sys.exit(0)

result = {{
    'success': True,
    'broker': {{
        'id': broker_id,
        'name': '{}',
        'broker_type': '{}',
        'server': account.server,
        'connected': True,
        'login': account.login,
        'balance': float(account.balance),
        'equity': float(account.equity),
        'profit': float(account.profit)
    }}
}}
print(json.dumps(result))
"#, config.name, config.broker_type);

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    #[derive(serde::Deserialize)]
    struct ConnectResult {
        success: bool,
        broker: Option<BrokerConnection>,
        error: Option<String>,
    }
    
    let result: ConnectResult = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {}", e))?;
    
    if result.success {
        if let Some(broker) = result.broker {
            let mut brokers = BROKERS.lock().unwrap();
            brokers.push(broker.clone());
            return Ok(broker);
        }
    }
    
    Err(result.error.unwrap_or_else(|| "Unknown error".to_string()))
}

#[tauri::command]
pub fn disconnect_broker(broker_id: String) -> Result<bool, String> {
    let mut brokers = BROKERS.lock().unwrap();
    if let Some(pos) = brokers.iter().position(|b| b.id == broker_id) {
        brokers[pos].connected = false;
        Ok(true)
    } else {
        Err("Broker not found".to_string())
    }
}

#[tauri::command]
pub fn remove_broker(broker_id: String) -> Result<bool, String> {
    let mut brokers = BROKERS.lock().unwrap();
    if let Some(pos) = brokers.iter().position(|b| b.id == broker_id) {
        if broker_id != "default" {
            brokers.remove(pos);
        }
        Ok(true)
    } else {
        Err("Broker not found".to_string())
    }
}

#[tauri::command]
pub async fn sync_broker(broker_id: String) -> Result<BrokerConnection, String> {
    let python_code = r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json
from datetime import datetime

if not mt5.initialize():
    print(json.dumps({'success': False, 'error': 'Failed to initialize MT5'}))
    sys.exit(0)

account = mt5.account_info()
if account is None:
    print(json.dumps({'success': False, 'error': 'No account'}))
    sys.exit(0)

positions = mt5.positions_get()
deals = mt5.history_deals_get(datetime.now().replace(hour=0, minute=0), datetime.now())

result = {
    'success': True,
    'account': {
        'login': account.login,
        'server': account.server,
        'balance': float(account.balance),
        'equity': float(account.equity),
        'margin': float(account.margin),
        'free_margin': float(account.margin_free),
        'profit': float(account.profit),
        'leverage': account.leverage
    },
    'positions': len(positions) if positions else 0,
    'deals': len(deals) if deals else 0
}
print(json.dumps(result))
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    #[derive(serde::Deserialize)]
    struct SyncResult {
        success: bool,
        account: Option<Mt5AccountInfo>,
        error: Option<String>,
    }
    
    let result: SyncResult = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {}", e))?;
    
    if result.success {
        let mut brokers = BROKERS.lock().unwrap();
        if let Some(pos) = brokers.iter().position(|b| b.id == broker_id) {
            brokers[pos].connected = true;
            brokers[pos].account_info = result.account;
            brokers[pos].last_sync = Some(chrono::Utc::now().to_rfc3339());
            return Ok(brokers[pos].clone());
        }
    }
    
    Err(result.error.unwrap_or_else(|| "Unknown error".to_string()))
}

#[tauri::command]
pub async fn get_all_positions() -> Result<Vec<serde_json::Value>, String> {
    let python_code = r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print('[]')
    sys.exit(0)

positions = mt5.positions_get()
if not positions:
    print('[]')
    sys.exit(0)

result = []
for pos in positions:
    result.append({
        'ticket': pos.ticket,
        'symbol': pos.symbol,
        'volume': float(pos.volume),
        'open_price': float(pos.price_open),
        'current_price': float(pos.price_current),
        'profit': float(pos.profit),
        'side': 'buy' if pos.type == 0 else 'sell',
        'broker': 'Primary MT5'
    })
print(json.dumps(result))
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let positions: Vec<serde_json::Value> = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {}", e))?;
    
    Ok(positions)
}

#[tauri::command]
pub fn get_portfolio_summary() -> Result<serde_json::Value, String> {
    let brokers = BROKERS.lock().unwrap();
    
    let total_equity: f64 = brokers.iter()
        .filter(|b| b.connected)
        .filter_map(|b| b.account_info.as_ref())
        .map(|a| a.equity)
        .sum();
    
    let total_balance: f64 = brokers.iter()
        .filter(|b| b.connected)
        .filter_map(|b| b.account_info.as_ref())
        .map(|a| a.balance)
        .sum();
    
    let total_profit: f64 = brokers.iter()
        .filter(|b| b.connected)
        .filter_map(|b| b.account_info.as_ref())
        .map(|a| a.profit)
        .sum();
    
    let connected_count = brokers.iter().filter(|b| b.connected).count();
    
    Ok(serde_json::json!({
        "total_equity": total_equity,
        "total_balance": total_balance,
        "total_profit": total_profit,
        "broker_count": brokers.len(),
        "connected_count": connected_count,
        "brokers": brokers.iter().map(|b| {
            serde_json::json!({
                "id": b.id,
                "name": b.name,
                "connected": b.connected,
                "equity": b.account_info.as_ref().map(|a| a.equity).unwrap_or(0.0),
                "balance": b.account_info.as_ref().map(|a| a.balance).unwrap_or(0.0)
            })
        }).collect::<Vec<_>>()
    }))
}

// ── News & AI Commands ─────────────────────────────────────────────────────────

#[derive(serde::Serialize, serde::Deserialize, Clone)]
pub struct NewsItem {
    pub id: String,
    pub title: String,
    pub summary: String,
    pub source: String,
    pub url: String,
    pub published_at: String,
    pub sentiment: Option<String>,
    pub symbols: Vec<String>,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct AiAnalysis {
    pub summary: String,
    pub sentiment: String,
    pub sentiment_score: f64,
    pub key_events: Vec<String>,
    pub impact_on_xauusd: String,
    pub trading_recommendation: String,
    pub risk_level: String,
}

#[tauri::command]
pub async fn fetch_financial_news() -> Result<Vec<NewsItem>, String> {
    finnhub_get_market_news(Some("forex".to_string())).await
}

#[tauri::command]
pub async fn analyze_news_with_ai(news_items: Vec<NewsItem>) -> Result<AiAnalysis, String> {
    let news_json = serde_json::to_string(&news_items)
        .map_err(|e| format!("Serialize error: {}", e))?;

    let python_code = r#"
import json
import sys

try:
    import google.generativeai as genai
    
    API_KEY = 'AIzaSyDykBKNeOp7tesDEK1BjzlJroTi-xTlEWI'
    
    genai.configure(api_key=API_KEY)
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    news_json = sys.argv[1] if len(sys.argv) > 1 else '[]'
    news_data = json.loads(news_json)
    
    news_text = '\\n'.join([f"- {n['title']}: {n['summary']}" for n in news_data[:5]])
    
    prompt = f'''You are a professional financial analyst AI. Analyze the following news items related to XAUUSD (Gold) and provide trading insights.

News items:
{news_text}

Provide a JSON response with exactly this structure:
{{
    "summary": "A brief 2-3 sentence summary of the current market sentiment",
    "sentiment": "BULLISH, BEARISH, or NEUTRAL",
    "sentiment_score": a number from -1.0 to 1.0,
    "key_events": ["event1", "event2", "event3"],
    "impact_on_xauusd": "POSITIVE, NEGATIVE, or MIXED",
    "trading_recommendation": "BUY, SELL, or HOLD with brief reasoning",
    "risk_level": "LOW, MEDIUM, or HIGH"
}}'''
    
    response = model.generate_content(prompt)
    
    text = response.text
    
    if '```json' in text:
        text = text.split('```json')[1].split('```')[0]
    elif '```' in text:
        text = text.split('```')[1].split('```')[0]
    
    result = json.loads(text.strip())
    print(json.dumps(result))
    
except Exception as e:
    error_result = {
        'summary': f'Error analyzing news: {str(e)}',
        'sentiment': 'NEUTRAL',
        'sentiment_score': 0.0,
        'key_events': [],
        'impact_on_xauusd': 'MIXED',
        'trading_recommendation': 'HOLD',
        'risk_level': 'MEDIUM'
    }
    print(json.dumps(error_result))
"#.to_string();

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code, &news_json])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    
    if !stderr.is_empty() {
        tracing::warn!("AI analysis stderr: {}", stderr);
    }
    
    let analysis: AiAnalysis = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(analysis)
}

#[tauri::command]
pub async fn get_market_sentiment() -> Result<AiAnalysis, String> {
    let news = fetch_financial_news().await?;
    analyze_news_with_ai(news).await
}

// ── MT5 Trading Commands ─────────────────────────────────────────────────────

#[derive(serde::Serialize, serde::Deserialize)]
pub struct Mt5OrderRequest {
    pub symbol: String,
    pub volume: f64,
    pub side: String,
    pub price: Option<f64>,
    pub sl: Option<f64>,
    pub tp: Option<f64>,
    pub comment: Option<String>,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct Mt5TradeResult {
    pub success: bool,
    pub order_ticket: Option<i64>,
    pub deal_ticket: Option<i64>,
    pub message: String,
}

#[tauri::command]
pub async fn mt5_place_order(request: Mt5OrderRequest) -> Result<Mt5TradeResult, String> {
    let side_int = if request.side.to_lowercase() == "buy" { 0 } else { 1 };
    let comment = request.comment.unwrap_or_else(|| "QuantFund".to_string());
    
    let python_code = format!(r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print(json.dumps({{'success': False, 'order_ticket': None, 'deal_ticket': None, 'message': 'MT5 not initialized'}}))
    sys.exit(0)

symbol = '{}'
symbol_info = mt5.symbol_info(symbol)
if symbol_info is None:
    print(json.dumps({{'success': False, 'order_ticket': None, 'deal_ticket': None, 'message': 'Symbol not found'}}))
    sys.exit(0)

if not symbol_info.visible:
    mt5.symbol_select(symbol, True)

side_int = {}
price = symbol_info.ask if side_int == 0 else symbol_info.bid

request_dict = {{
    'action': mt5.TRADE_ACTION_DEAL,
    'symbol': symbol,
    'volume': {},
    'type': side_int,
    'price': price,
    'deviation': 20,
    'magic': 234000,
    'comment': '{}',
    'type_time': mt5.ORDER_TIME_GTC,
    'type_filling': mt5.ORDER_FILLING_IOC,
}}
"#, 
        request.symbol,
        side_int,
        request.volume,
        comment
    );

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let result: Mt5TradeResult = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(result)
}

#[tauri::command]
pub async fn mt5_close_position(ticket: i64, volume: Option<f64>) -> Result<Mt5TradeResult, String> {
    let python_code = format!(r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print(json.dumps({{'success': False, 'order_ticket': None, 'deal_ticket': None, 'message': 'MT5 not initialized'}}))
    sys.exit(0)

positions = mt5.positions_get(ticket={})
if not positions:
    print(json.dumps({{'success': False, 'order_ticket': None, 'deal_ticket': None, 'message': 'Position not found'}}))
    sys.exit(0)

pos = positions[0]
symbol_info = mt5.symbol_info(pos.symbol)
close_volume = {} if {} else pos.volume

if pos.type == 0:
    close_price = symbol_info.bid
    close_type = 1
else:
    close_price = symbol_info.ask
    close_type = 0

request = {{
    'action': mt5.TRADE_ACTION_DEAL,
    'symbol': pos.symbol,
    'volume': close_volume,
    'type': close_type,
    'position': pos.ticket,
    'price': close_price,
    'deviation': 20,
    'magic': 234000,
    'comment': 'Close from QuantFund',
    'type_time': mt5.ORDER_TIME_GTC,
    'type_filling': mt5.ORDER_FILLING_IOC,
}}

result = mt5.order_send(request)

if result.retcode != mt5.TRADE_RETCODE_DONE:
    print(json.dumps({{
        'success': False,
        'order_ticket': None,
        'deal_ticket': None,
        'message': str(result.comment)
    }}))
else:
    print(json.dumps({{
        'success': True,
        'order_ticket': result.order,
        'deal_ticket': result.deal,
        'message': 'Position closed successfully'
    }}))
"#, 
        ticket,
        volume.map(|v| v.to_string()).unwrap_or_else(|| "None".to_string()),
        volume.is_some()
    );

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let result: Mt5TradeResult = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(result)
}

#[tauri::command]
pub async fn mt5_modify_position(ticket: i64, sl: Option<f64>, tp: Option<f64>) -> Result<Mt5TradeResult, String> {
    let python_code = format!(r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print(json.dumps({{'success': False, 'order_ticket': None, 'deal_ticket': None, 'message': 'MT5 not initialized'}}))
    sys.exit(0)

positions = mt5.positions_get(ticket={})
if not positions:
    print(json.dumps({{'success': False, 'order_ticket': None, 'deal_ticket': None, 'message': 'Position not found'}}))
    sys.exit(0)

pos = positions[0]

request = {{
    'action': mt5.TRADE_ACTION_SLTP,
    'symbol': pos.symbol,
    'position': pos.ticket,
    'sl': {},
    'tp': {},
    'magic': 234000,
}}

result = mt5.order_send(request)

if result.retcode != mt5.TRADE_RETCODE_DONE:
    print(json.dumps({{
        'success': False,
        'order_ticket': None,
        'deal_ticket': None,
        'message': str(result.comment)
    }}))
else:
    print(json.dumps({{
        'success': True,
        'order_ticket': pos.ticket,
        'deal_ticket': None,
        'message': 'Position modified successfully'
    }}))
"#, 
        ticket,
        sl.map(|s| s.to_string()).unwrap_or_else(|| "pos.sl".to_string()),
        tp.map(|t| t.to_string()).unwrap_or_else(|| "pos.tp".to_string())
    );

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let result: Mt5TradeResult = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(result)
}

#[tauri::command]
pub async fn mt5_cancel_order(ticket: i64) -> Result<Mt5TradeResult, String> {
    let python_code = format!(r#"
import sys
sys.path.insert(0, r'C:\Users\Fredd\AppData\Roaming\MetaQuotes\Terminal\Common\Modules')
import MetaTrader5 as mt5
import json

if not mt5.initialize():
    print(json.dumps({{'success': False, 'order_ticket': None, 'deal_ticket': None, 'message': 'MT5 not initialized'}}))
    sys.exit(0)

result = mt5.order_delete({})

if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
    print(json.dumps({{
        'success': False,
        'order_ticket': None,
        'deal_ticket': None,
        'message': 'Failed to cancel order'
    }}))
else:
    print(json.dumps({{
        'success': True,
        'order_ticket': {},
        'deal_ticket': None,
        'message': 'Order cancelled successfully'
    }}))
"#, ticket, ticket);

    let output = tokio::process::Command::new("python")
        .args(["-c", &python_code])
        .output()
        .await
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    let result: Mt5TradeResult = serde_json::from_str(&stdout)
        .map_err(|e| format!("Parse error: {} - stdout: {}", e, stdout))?;
    
    Ok(result)
}

// ── Finnhub API Commands ───────────────────────────────────────────────────────

fn convert_timestamp(ts: i64) -> String {
    chrono::DateTime::from_timestamp(ts, 0)
        .map(|dt| dt.format("%Y-%m-%dT%H:%M:%S").to_string())
        .unwrap_or_else(|| "N/A".to_string())
}

#[allow(dead_code)]
fn convert_date(ts: i64) -> String {
    chrono::DateTime::from_timestamp(ts, 0)
        .map(|dt| dt.format("%Y-%m-%d").to_string())
        .unwrap_or_else(|| "N/A".to_string())
}

#[tauri::command]
pub async fn finnhub_get_market_news(category: Option<String>) -> Result<Vec<NewsItem>, String> {
    let client = FinnhubClient::new();
    let cat = category.unwrap_or_else(|| "general".to_string());
    
    let news = client
        .get_market_news(&cat)
        .await
        .map_err(|e| format!("Failed to fetch market news: {}", e))?;
    
    let items: Vec<NewsItem> = news
        .into_iter()
        .map(|n| NewsItem {
            id: n.id.to_string(),
            title: n.headline,
            summary: n.summary,
            source: n.source,
            url: n.url,
            published_at: convert_timestamp(n.datetime),
            sentiment: None,
            symbols: n
                .related
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect(),
        })
        .collect();
    
    Ok(items)
}

#[tauri::command]
pub async fn finnhub_get_company_news(
    symbol: String,
    from: Option<String>,
    to: Option<String>,
) -> Result<Vec<NewsItem>, String> {
    let client = FinnhubClient::new();
    
    let now = chrono::Utc::now();
    let from_date = from.unwrap_or_else(|| (now - chrono::Duration::days(7)).format("%Y-%m-%d").to_string());
    let to_date = to.unwrap_or_else(|| now.format("%Y-%m-%d").to_string());
    
    let news = client
        .get_company_news(&symbol, &from_date, &to_date)
        .await
        .map_err(|e| format!("Failed to fetch company news: {}", e))?;
    
    let items: Vec<NewsItem> = news
        .into_iter()
        .map(|n| NewsItem {
            id: n.id.to_string(),
            title: n.headline,
            summary: n.summary,
            source: n.source,
            url: n.url,
            published_at: convert_timestamp(n.datetime),
            sentiment: None,
            symbols: vec![symbol.clone()],
        })
        .collect();
    
    Ok(items)
}

#[derive(serde::Serialize, serde::Deserialize, Clone)]
pub struct EconomicEventDto {
    pub id: String,
    pub event: String,
    pub date: String,
    pub time: Option<String>,
    pub country: String,
    pub currency: String,
    pub impact: String,
    pub actual: Option<String>,
    pub previous: Option<String>,
    pub forecast: Option<String>,
}

impl From<EconomicEvent> for EconomicEventDto {
    fn from(e: EconomicEvent) -> Self {
        let impact = match e.importance {
            3 => "HIGH",
            2 => "MEDIUM",
            _ => "LOW",
        };
        Self {
            id: e.event_id,
            event: e.event,
            date: e.date,
            time: e.time,
            country: e.country,
            currency: e.currency,
            impact: impact.to_string(),
            actual: e.actual,
            previous: e.previous,
            forecast: e.consensus,
        }
    }
}

#[tauri::command]
pub async fn finnhub_get_economic_calendar(
    from: Option<String>,
    to: Option<String>,
) -> Result<Vec<EconomicEventDto>, String> {
    let client = FinnhubClient::new();
    
    let now = chrono::Utc::now();
    let from_date = from.unwrap_or_else(|| (now - chrono::Duration::days(7)).format("%Y-%m-%d").to_string());
    let to_date = to.unwrap_or_else(|| (now + chrono::Duration::days(30)).format("%Y-%m-%d").to_string());
    
    let events = client
        .get_economic_calendar(&from_date, &to_date)
        .await
        .map_err(|e| format!("Failed to fetch economic calendar: {}", e))?;
    
    let dtos: Vec<EconomicEventDto> = events.into_iter().map(EconomicEventDto::from).collect();
    
    Ok(dtos)
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct AggregateIndicatorDto {
    pub symbol: String,
    pub buy: i32,
    pub sell: i32,
    pub neutral: i32,
    pub signal: String,
}

#[tauri::command]
pub async fn finnhub_get_technical_indicator(
    symbol: String,
    resolution: Option<String>,
) -> Result<AggregateIndicatorDto, String> {
    let client = FinnhubClient::new();
    let res = resolution.unwrap_or_else(|| "D".to_string());
    
    let indicator = client
        .get_aggregate_indicator(&symbol, &res)
        .await
        .map_err(|e| format!("Failed to fetch indicator: {}", e))?;
    
    let signal = if indicator.technical.buy > indicator.technical.sell + indicator.technical.sell / 2 {
        "BUY"
    } else if indicator.technical.sell > indicator.technical.buy + indicator.technical.buy / 2 {
        "SELL"
    } else {
        "NEUTRAL"
    };
    
    Ok(AggregateIndicatorDto {
        symbol: indicator.s,
        buy: indicator.technical.buy,
        sell: indicator.technical.sell,
        neutral: indicator.technical.neutral,
        signal: signal.to_string(),
    })
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct CompanyProfileDto {
    pub name: String,
    pub ticker: String,
    pub exchange: String,
    pub industry: String,
    pub weburl: String,
    pub logo: String,
    pub market_cap: f64,
    pub shares_outstanding: f64,
    pub ipo_date: String,
    pub country: String,
    pub currency: String,
}

#[tauri::command]
pub async fn finnhub_get_company_profile(symbol: String) -> Result<CompanyProfileDto, String> {
    let client = FinnhubClient::new();
    
    let profile = client
        .get_company_profile(&symbol)
        .await
        .map_err(|e| format!("Failed to fetch company profile: {}", e))?;
    
    Ok(CompanyProfileDto {
        name: profile.name.unwrap_or_default(),
        ticker: profile.ticker.unwrap_or_default(),
        exchange: profile.exchange.unwrap_or_default(),
        industry: profile.finnhub_industry.unwrap_or_default(),
        weburl: profile.weburl.unwrap_or_default(),
        logo: profile.logo.unwrap_or_default(),
        market_cap: profile.market_capitalization.unwrap_or(0.0),
        shares_outstanding: profile.share_outstanding.unwrap_or(0.0),
        ipo_date: profile.ipo.unwrap_or_default(),
        country: profile.country.unwrap_or_default(),
        currency: profile.currency.unwrap_or_default(),
    })
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct RecommendationDto {
    pub period: String,
    pub strong_buy: i32,
    pub buy: i32,
    pub hold: i32,
    pub sell: i32,
    pub strong_sell: i32,
    pub total: i32,
    pub buy_percent: f64,
}

#[tauri::command]
pub async fn finnhub_get_recommendations(symbol: String) -> Result<Vec<RecommendationDto>, String> {
    let client = FinnhubClient::new();
    
    let recommendations = client
        .get_stock_recommendations(&symbol)
        .await
        .map_err(|e| format!("Failed to fetch recommendations: {}", e))?;
    
    let dtos: Vec<RecommendationDto> = recommendations
        .trends
        .into_iter()
        .map(|r| {
            let total = r.strong_buy + r.buy + r.hold + r.sell + r.strong_sell;
            let buy_percent = if total > 0 {
                ((r.strong_buy + r.buy) as f64 / total as f64) * 100.0
            } else {
                0.0
            };
            RecommendationDto {
                period: r.period,
                strong_buy: r.strong_buy,
                buy: r.buy,
                hold: r.hold,
                sell: r.sell,
                strong_sell: r.strong_sell,
                total,
                buy_percent,
            }
        })
        .collect();
    
    Ok(dtos)
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct SocialSentimentDto {
    pub symbol: String,
    pub reddit_sentiment: f64,
    pub twitter_sentiment: f64,
    pub reddit_posts: i32,
    pub twitter_posts: i32,
}

#[tauri::command]
pub async fn finnhub_get_social_sentiment(symbol: String) -> Result<SocialSentimentDto, String> {
    let client = FinnhubClient::new();
    
    let sentiment = client
        .get_social_sentiment(&symbol)
        .await
        .map_err(|e| format!("Failed to fetch social sentiment: {}", e))?;
    
    let latest = sentiment.sentiment.first();
    
    Ok(SocialSentimentDto {
        symbol: sentiment.symbol,
        reddit_sentiment: latest
            .and_then(|s| s.reddit_post_sentiment)
            .unwrap_or(0.0),
        twitter_sentiment: latest
            .and_then(|s| s.twitter_sentiment)
            .unwrap_or(0.0),
        reddit_posts: latest.and_then(|s| s.reddit_posts).unwrap_or(0),
        twitter_posts: latest.and_then(|s| s.twitter_posts).unwrap_or(0),
    })
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct MarketStatusDto {
    pub is_open: bool,
    pub session: String,
    pub market_type: String,
}

#[tauri::command]
pub async fn finnhub_get_market_status() -> Result<MarketStatusDto, String> {
    let client = FinnhubClient::new();
    
    let status = client
        .get_market_status()
        .await
        .map_err(|e| format!("Failed to fetch market status: {}", e))?;
    
    Ok(MarketStatusDto {
        is_open: status.is_open,
        session: status.session,
        market_type: status.market_type,
    })
}

#[tauri::command]
pub async fn finnhub_get_earnings_calendar(
    from: Option<String>,
    to: Option<String>,
) -> Result<Vec<serde_json::Value>, String> {
    let client = FinnhubClient::new();
    
    let now = chrono::Utc::now();
    let from_date = from.unwrap_or_else(|| now.format("%Y-%m-%d").to_string());
    let to_date = to.unwrap_or_else(|| (now + chrono::Duration::days(30)).format("%Y-%m-%d").to_string());
    
    let calendar = client
        .get_earnings_calendar(&from_date, &to_date)
        .await
        .map_err(|e| format!("Failed to fetch earnings calendar: {}", e))?;
    
    let events: Vec<serde_json::Value> = calendar
        .earnings_calendar
        .into_iter()
        .map(|e| {
            serde_json::json!({
                "date": e.date,
                "symbol": e.symbol,
                "name": e.name,
                "eps": e.eps,
                "eps_estimate": e.eps_estimate,
                "revenue": e.revenue,
                "revenue_estimate": e.revenue_estimate,
                "hour": e.hour,
            })
        })
        .collect();
    
    Ok(events)
}

#[tauri::command]
pub async fn finnhub_get_covid_data() -> Result<Vec<serde_json::Value>, String> {
    let client = FinnhubClient::new();
    
    let data = client
        .get_covid_data()
        .await
        .map_err(|e| format!("Failed to fetch COVID data: {}", e))?;
    
    let result: Vec<serde_json::Value> = data
        .into_iter()
        .map(|c| {
            serde_json::json!({
                "country": c.country,
                "cases": c.case,
                "deaths": c.death,
                "recovered": c.recovered,
                "date": c.date,
            })
        })
        .collect();
    
    Ok(result)
}
