/// XAUUSD-specific backtesting engine with institutional metrics
use anyhow::Result;
use quantfund_backtest::{BacktestConfig, BacktestProgress, BacktestResult, BacktestRunner};
use quantfund_core::{InstrumentId, Price, TickEvent, Timestamp, Volume};
use quantfund_data::TickReplay;
use quantfund_execution::ExecutionModelConfig;
use quantfund_risk::RiskConfig;
use quantfund_strategy::{
    ChannelBreakout, ChannelBreakoutConfig, FredSignalStrategy, FredSignalStrategyConfig,
    MeanReversion, MeanReversionConfig, MomentumRsi, MomentumRsiConfig, SmaCrossover,
    SmaCrossoverConfig, Strategy,
};
use rust_decimal::prelude::ToPrimitive;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};

use crate::database::{load_xauusd_data, DbConfig, OhlcvBar};

/// Backtest configuration for XAUUSD
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct XauusdBacktestConfig {
    pub initial_capital: Decimal,
    pub start_date: Option<String>,
    pub end_date: Option<String>,
    pub strategy_type: String,
    pub strategy_params: StrategyParams,
    pub risk_params: RiskParams,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StrategyParams {
    #[serde(default = "default_fast_period")]
    pub fast_period: usize,
    #[serde(default = "default_slow_period")]
    pub slow_period: usize,
    pub position_size: Decimal,

    // Mean Reversion (Bollinger)
    #[serde(default)]
    pub period: Option<usize>,
    #[serde(default)]
    pub std_dev: Option<f64>,

    // Momentum RSI
    #[serde(default)]
    pub rsi_period: Option<usize>,
    #[serde(default)]
    pub overbought: Option<f64>,
    #[serde(default)]
    pub oversold: Option<f64>,

    // Channel Breakout
    #[serde(default)]
    pub lookback: Option<usize>,
}

fn default_fast_period() -> usize { 20 }
fn default_slow_period() -> usize { 50 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskParams {
    pub max_position_size: Decimal,
    pub max_leverage: Decimal,
    pub max_drawdown_pct: Decimal,
}

impl Default for XauusdBacktestConfig {
    fn default() -> Self {
        Self {
            initial_capital: dec!(100000.0),
            start_date: None,
            end_date: None,
            strategy_type: "sma_crossover".to_string(),
            strategy_params: StrategyParams {
                fast_period: 20,
                slow_period: 50,
                position_size: dec!(0.1),
                period: None,
                std_dev: None,
                rsi_period: None,
                overbought: None,
                oversold: None,
                lookback: None,
            },
            risk_params: RiskParams {
                max_position_size: dec!(10.0),
                max_leverage: dec!(2.0),
                max_drawdown_pct: dec!(0.20),
            },
        }
    }
}

/// Enhanced backtest result with XAUUSD-specific metrics
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct XauusdBacktestResult {
    pub base_result: BacktestResultSummary,
    pub xauusd_metrics: XauusdMetrics,
    /// Downsampled equity curve for chart rendering (ts_ms, equity)
    pub equity_curve: Vec<(i64, f64)>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BacktestResultSummary {
    pub total_trades: usize,
    pub winning_trades: usize,
    pub losing_trades: usize,
    pub win_rate: f64,
    pub total_pnl: Decimal,
    pub total_return_pct: f64,
    pub sharpe_ratio: f64,
    pub sortino_ratio: f64,
    pub max_drawdown: f64,
    pub max_drawdown_pct: f64,
    pub calmar_ratio: f64,
    pub profit_factor: f64,
    pub avg_win: Decimal,
    pub avg_loss: Decimal,
    pub largest_win: Decimal,
    pub largest_loss: Decimal,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct XauusdMetrics {
    pub avg_holding_period_bars: f64,
    pub avg_price_move_pips: f64,
    pub best_trade_hour: Option<u32>,
    pub worst_trade_hour: Option<u32>,
    pub volatility_adjusted_return: f64,
}

/// Run XAUUSD backtest against real database data.
///
/// `cancel_flag` — set to `true` from the outside to abort the run cleanly.
pub async fn run_xauusd_backtest(
    config: XauusdBacktestConfig,
    db_config: DbConfig,
    cancel_flag: Arc<AtomicBool>,
    progress_callback: impl Fn(f64, String) + Send + 'static,
) -> Result<XauusdBacktestResult> {
    // Wrap callback so it can be shared across the spawn_blocking boundary
    let cb: Arc<Mutex<Box<dyn Fn(f64, String) + Send + 'static>>> =
        Arc::new(Mutex::new(Box::new(progress_callback)));

    // ── Step 1: Load data from PostgreSQL ─────────────────────────────────────
    emit(&cb, 0.0, "Loading XAUUSD data from database...");

    let client = crate::database::connect(&db_config).await?;

    let start_date = config.start_date.as_ref().and_then(|s| {
        chrono::DateTime::parse_from_rfc3339(s)
            .ok()
            .map(|dt| dt.with_timezone(&chrono::Utc))
    });

    let end_date = config.end_date.as_ref().and_then(|s| {
        chrono::DateTime::parse_from_rfc3339(s)
            .ok()
            .map(|dt| dt.with_timezone(&chrono::Utc))
    });

    let bars = load_xauusd_data(&client, "XAUUSD", "M1", start_date, end_date, None).await?;

    if bars.is_empty() {
        anyhow::bail!("No data available for the specified date range");
    }

    emit(&cb, 10.0, &format!("Loaded {} M1 bars", bars.len()));

    // ── Step 2: Convert OHLCV bars to tick stream ─────────────────────────────
    let instrument_id = InstrumentId::new("XAUUSD");
    let ticks = bars_to_ticks(&bars, &instrument_id);

    let start_time = bars.first().unwrap().timestamp;
    let end_time = bars.last().unwrap().timestamp;

    emit(&cb, 15.0, &format!("Converted to {} ticks", ticks.len()));

    // ── Step 3: Build strategy ─────────────────────────────────────────────────
    let strategy = create_strategy(&config)?;

    // ── Step 4: Build BacktestConfig ──────────────────────────────────────────
    let risk_config = RiskConfig {
        max_position_size: config.risk_params.max_position_size,
        max_drawdown_per_strategy: config.risk_params.max_drawdown_pct,
        kill_switch_drawdown: config.risk_params.max_drawdown_pct * dec!(2.0),
        ..Default::default()
    };

    let backtest_config = BacktestConfig {
        instruments: vec![instrument_id],
        start_time,
        end_time,
        initial_balance: config.initial_capital,
        leverage: config.risk_params.max_leverage,
        risk_config,
        execution_config: ExecutionModelConfig::default(),
        seed: 42,
        commission_per_lot: dec!(0.50),
    };

    let initial_capital = config.initial_capital;

    emit(&cb, 20.0, "Starting backtest engine...");

    // ── Step 5: Run the backtest on a blocking thread ─────────────────────────
    // BacktestRunner::run is synchronous (CPU-intensive); use spawn_blocking
    // so we don't block the async runtime.
    let cb_for_runner = Arc::clone(&cb);
    let cancel_for_runner = Arc::clone(&cancel_flag);
    let result: BacktestResult = tokio::task::spawn_blocking(move || {
        let mut replay = TickReplay::from_ticks(ticks);

        // Progress interval: emit ~200 updates over the full run
        let interval = (replay.total() as u64 / 200).max(1_000);

        let cb_runner = Arc::clone(&cb_for_runner);
        let mut runner = BacktestRunner::new(backtest_config, vec![strategy]).on_progress(
            interval,
            move |p: BacktestProgress| {
                // Abort if cancelled — panic propagates through spawn_blocking as JoinError
                if cancel_for_runner.load(Ordering::Relaxed) {
                    panic!("__BACKTEST_CANCELLED__");
                }

                // Map runner's 0–100% into our 20–98% band
                let pct = 20.0 + (p.progress_pct / 100.0) * 78.0;
                let equity = p.equity.to_f64().unwrap_or(0.0);
                let msg = format!(
                    "Running {:.1}% — equity ${:.2} — {} trades",
                    p.progress_pct, equity, p.total_closed_trades
                );
                if let Ok(f) = cb_runner.lock() {
                    f(pct, msg);
                }
            },
        );

        runner.run(&mut replay)
    })
    .await
    .map_err(|e| {
        // Distinguish intentional cancellation from real panics
        if cancel_flag.load(Ordering::Relaxed) {
            anyhow::anyhow!("Cancelled")
        } else {
            anyhow::anyhow!("Backtest thread panicked: {}", e)
        }
    })?;

    // ── Step 6: Emit final progress and map result ─────────────────────────────
    emit(
        &cb,
        100.0,
        &format!(
            "Complete! {} trades | PnL: {}",
            result.metrics.total_trades, result.metrics.total_pnl
        ),
    );

    Ok(map_backtest_result(result, initial_capital))
}

// ─── Private helpers ──────────────────────────────────────────────────────────

/// Emit a progress update through the shared callback.
fn emit(cb: &Arc<Mutex<Box<dyn Fn(f64, String) + Send + 'static>>>, pct: f64, msg: &str) {
    if let Ok(f) = cb.lock() {
        f(pct, msg.to_string());
    }
}

/// Convert OHLCV bars into a synthetic tick stream for the replay engine.
///
/// Each M1 bar is expanded into **4 ticks** to simulate intra-bar price
/// movement and give the strategy something to react to:
///
/// - Tick 0 (t+0s)  : open price
/// - Tick 1 (t+15s) : low  (bullish bar) | high (bearish bar)
/// - Tick 2 (t+30s) : high (bullish bar) | low  (bearish bar)
/// - Tick 3 (t+59s) : close price
///
/// XAUUSD spread: ~$0.30 (half-spread = $0.15).
fn bars_to_ticks(bars: &[OhlcvBar], instrument_id: &InstrumentId) -> Vec<TickEvent> {
    let half_spread = dec!(0.15); // $0.30 total spread — realistic for XAUUSD M1
    let bar_ms: i64 = 60_000; // 1-minute bar in milliseconds

    let mut ticks = Vec::with_capacity(bars.len() * 4);

    for bar in bars {
        let t = bar.timestamp.as_millis();
        let is_bullish = *bar.close >= *bar.open;

        // Open tick
        ticks.push(make_tick(instrument_id, t, *bar.open, half_spread));

        // High / Low ordering — simulate typical intra-bar path
        if is_bullish {
            ticks.push(make_tick(instrument_id, t + bar_ms / 4, *bar.low, half_spread));
            ticks.push(make_tick(instrument_id, t + bar_ms / 2, *bar.high, half_spread));
        } else {
            ticks.push(make_tick(instrument_id, t + bar_ms / 4, *bar.high, half_spread));
            ticks.push(make_tick(instrument_id, t + bar_ms / 2, *bar.low, half_spread));
        }

        // Close tick (1ms before bar end to stay within the bar)
        ticks.push(make_tick(instrument_id, t + bar_ms - 1, *bar.close, half_spread));
    }

    ticks
}

/// Build a single `TickEvent` from a mid price and half-spread.
fn make_tick(
    instrument_id: &InstrumentId,
    ts_ms: i64,
    mid: Decimal,
    half_spread: Decimal,
) -> TickEvent {
    let bid = mid - half_spread;
    let ask = mid + half_spread;
    let spread = ask - bid;

    TickEvent {
        timestamp: Timestamp::from_millis(ts_ms),
        instrument_id: instrument_id.clone(),
        bid: Price::new(bid),
        ask: Price::new(ask),
        bid_volume: Volume::new(dec!(100)),
        ask_volume: Volume::new(dec!(100)),
        spread,
    }
}

/// Create the requested strategy from the config.
fn create_strategy(config: &XauusdBacktestConfig) -> Result<Box<dyn Strategy>> {
    match config.strategy_type.as_str() {
        "sma_crossover" => {
            let strategy_config = SmaCrossoverConfig {
                fast_period: config.strategy_params.fast_period,
                slow_period: config.strategy_params.slow_period,
                instruments: vec![InstrumentId::new("XAUUSD")],
            };
            Ok(Box::new(SmaCrossover::new(strategy_config)))
        }
        "mean_reversion" => {
            let strategy_config = MeanReversionConfig {
                period: config.strategy_params.period.unwrap_or(20),
                std_dev: config.strategy_params.std_dev.unwrap_or(2.0),
                position_size: config.strategy_params.position_size.to_f64().unwrap_or(0.1),
                instruments: vec![InstrumentId::new("XAUUSD")],
            };
            Ok(Box::new(MeanReversion::new(strategy_config)))
        }
        "momentum_rsi" => {
            let strategy_config = MomentumRsiConfig {
                rsi_period: config.strategy_params.rsi_period.unwrap_or(14),
                overbought: config.strategy_params.overbought.unwrap_or(70.0),
                oversold: config.strategy_params.oversold.unwrap_or(30.0),
                position_size: config.strategy_params.position_size.to_f64().unwrap_or(0.1),
                instruments: vec![InstrumentId::new("XAUUSD")],
            };
            Ok(Box::new(MomentumRsi::new(strategy_config)))
        }
        "channel_breakout" => {
            let strategy_config = ChannelBreakoutConfig {
                lookback: config.strategy_params.lookback.unwrap_or(20),
                position_size: config.strategy_params.position_size.to_f64().unwrap_or(0.1),
                instruments: vec![InstrumentId::new("XAUUSD")],
            };
            Ok(Box::new(ChannelBreakout::new(strategy_config)))
        }
        "fred_macro" => {
            let strategy_config = FredSignalStrategyConfig {
                instruments: vec![InstrumentId::new("XAUUSD")],
                strategy_id: "fred-macro".to_string(),
                signal_ttl_ns: 24 * 3600 * 1_000_000_000,
            };
            // Note: In a real environment, you need an endpoint to fetch vectors
            // For now we instantiate with an empty vec to let it compile.
            Ok(Box::new(FredSignalStrategy::new(strategy_config, vec![])))
        }
        other => anyhow::bail!("Unknown strategy type: {}", other),
    }
}

/// Map the engine's `BacktestResult` into the dashboard's `XauusdBacktestResult`.
fn map_backtest_result(result: BacktestResult, initial_capital: Decimal) -> XauusdBacktestResult {
    let m = &result.metrics;

    // Return % (e.g. 15.42 for +15.42%)
    let total_return_pct = if initial_capital > dec!(0) {
        m.total_pnl
            .to_f64()
            .unwrap_or(0.0)
            / initial_capital.to_f64().unwrap_or(1.0)
            * 100.0
    } else {
        0.0
    };

    // XAUUSD-specific metrics derived from closed positions
    let (best_hour, worst_hour) = compute_best_worst_hour(&result.closed_positions);
    let avg_price_move_pips = compute_avg_price_move_pips(&result.closed_positions);
    let avg_holding_period_bars = m.avg_trade_duration_secs / 60.0; // M1 bars = 60 s

    // Downsample equity curve to (timestamp_ms, equity_f64) for the frontend chart
    let equity_curve: Vec<(i64, f64)> = result
        .equity_curve
        .iter()
        .map(|(ts, eq)| (ts.as_millis(), eq.to_f64().unwrap_or(0.0)))
        .collect();

    XauusdBacktestResult {
        base_result: BacktestResultSummary {
            total_trades: m.total_trades,
            winning_trades: m.winning_trades,
            losing_trades: m.losing_trades,
            win_rate: m.win_rate * 100.0,
            total_pnl: m.total_pnl,
            total_return_pct,
            sharpe_ratio: m.sharpe_ratio,
            sortino_ratio: m.sortino_ratio,
            max_drawdown: m.max_drawdown.to_f64().unwrap_or(0.0),
            max_drawdown_pct: m.max_drawdown_pct * 100.0,
            calmar_ratio: m.calmar_ratio,
            profit_factor: m.profit_factor,
            avg_win: m.avg_win,
            avg_loss: -m.avg_loss,      // stored positive in metrics; negate for UI
            largest_win: m.largest_win,
            largest_loss: -m.largest_loss, // same
        },
        xauusd_metrics: XauusdMetrics {
            avg_holding_period_bars,
            avg_price_move_pips,
            best_trade_hour: best_hour,
            worst_trade_hour: worst_hour,
            volatility_adjusted_return: m.sharpe_ratio, // proxy
        },
        equity_curve,
    }
}

/// Group closed positions by their entry hour and return the hours with the
/// best and worst average net PnL.
fn compute_best_worst_hour(
    closed_positions: &[quantfund_core::Position],
) -> (Option<u32>, Option<u32>) {
    if closed_positions.is_empty() {
        return (None, None);
    }

    // hour (0-23) -> (total_pnl, count)
    let mut hour_stats: HashMap<u32, (Decimal, usize)> = HashMap::new();

    for pos in closed_positions {
        // Extract UTC hour from open_time
        let hour = ((pos.open_time.as_millis() / 1_000 / 3_600) % 24) as u32;
        let entry = hour_stats.entry(hour).or_insert((dec!(0), 0));
        entry.0 += pos.pnl_net;
        entry.1 += 1;
    }

    let mut best_hour: Option<u32> = None;
    let mut worst_hour: Option<u32> = None;
    let mut best_avg: Option<Decimal> = None;
    let mut worst_avg: Option<Decimal> = None;

    for (hour, (total, count)) in &hour_stats {
        if *count == 0 {
            continue;
        }
        let avg = total / Decimal::from(*count as u64);
        if best_avg.map_or(true, |b| avg > b) {
            best_avg = Some(avg);
            best_hour = Some(*hour);
        }
        if worst_avg.map_or(true, |w| avg < w) {
            worst_avg = Some(avg);
            worst_hour = Some(*hour);
        }
    }

    (best_hour, worst_hour)
}

/// Average price move in XAUUSD pips ($0.01) across all closed positions.
fn compute_avg_price_move_pips(closed_positions: &[quantfund_core::Position]) -> f64 {
    if closed_positions.is_empty() {
        return 0.0;
    }

    let total_pips: Decimal = closed_positions
        .iter()
        .filter_map(|pos| {
            pos.close_price.map(|cp| {
                // Absolute price move in pips (XAUUSD pip = $0.01)
                let diff = (*cp - *pos.open_price).abs();
                diff / dec!(0.01)
            })
        })
        .sum();

    let count = closed_positions
        .iter()
        .filter(|p| p.close_price.is_some())
        .count();

    if count == 0 {
        return 0.0;
    }

    total_pips.to_f64().unwrap_or(0.0) / count as f64
}
