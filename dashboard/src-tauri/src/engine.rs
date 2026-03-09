use std::sync::{Arc, Mutex};

use rust_decimal::prelude::ToPrimitive;
use rust_decimal_macros::dec;
use tauri::Emitter;

use quantfund_backtest::{BacktestConfig, BacktestProgress, BacktestRunner};
use quantfund_core::{InstrumentId, Timestamp};
use quantfund_data::{SyntheticTickConfig, TickReplay};
use quantfund_execution::ExecutionModelConfig;
use quantfund_risk::RiskConfig;
use quantfund_strategy::{SmaCrossover, SmaCrossoverConfig};

use crate::state::{
    AppState, ConnectionStatus, DashboardSnapshot, EquityPoint, LatencySample, OrderLogEntry,
    PositionSnapshot, RiskSnapshot,
};

/// Build a `DashboardSnapshot` from a `BacktestProgress`.
fn progress_to_snapshot(p: &BacktestProgress) -> DashboardSnapshot {
    // ── Equity curve ────────────────────────────────────────────────────────
    let equity_curve: Vec<EquityPoint> = p
        .equity_curve
        .iter()
        .map(|(ts, eq)| EquityPoint {
            ts: ts.as_millis(),
            equity: eq.to_f64().unwrap_or(0.0),
        })
        .collect();

    // ── Open positions ───────────────────────────────────────────────────────
    let positions: Vec<PositionSnapshot> = p
        .open_positions
        .iter()
        .map(|pos| PositionSnapshot {
            instrument: pos.instrument_id.to_string(),
            side: pos.side.to_string(),
            volume: (*pos.volume).to_f64().unwrap_or(0.0),
            entry_price: (*pos.open_price).to_f64().unwrap_or(0.0),
            unrealized_pnl: 0.0,
        })
        .collect();

    // ── Risk snapshot ────────────────────────────────────────────────────────
    let dd_pct = p.current_drawdown.to_f64().unwrap_or(0.0) * 100.0;
    let max_dd_pct = p.max_drawdown.to_f64().unwrap_or(0.0) * 100.0;
    let daily_pnl_f = p.daily_pnl.to_f64().unwrap_or(0.0);
    let equity_f = p.equity.to_f64().unwrap_or(1.0);
    let kill_switch_active = dd_pct > 20.0 || (daily_pnl_f / equity_f) < -0.05;

    let risk = RiskSnapshot {
        equity: equity_f,
        balance: p.balance.to_f64().unwrap_or(0.0),
        daily_pnl: daily_pnl_f,
        current_drawdown_pct: dd_pct,
        max_drawdown_pct: max_dd_pct,
        open_positions: p.open_positions.len(),
        total_closed_trades: p.total_closed_trades,
        kill_switch_active,
    };

    // ── Order log (from recent fills) ────────────────────────────────────────
    let order_log: Vec<OrderLogEntry> = p
        .recent_fills
        .iter()
        .map(|f| OrderLogEntry {
            ts: f.timestamp_ms,
            event_type: "Fill".into(),
            instrument: f.instrument.clone(),
            side: f.side.clone(),
            volume: f.volume,
            price: f.fill_price,
            note: format!("slip={:.5} comm={:.2}", f.slippage, f.commission),
        })
        .collect();

    // ── Bridge latency (simulation = 0 µs) ───────────────────────────────────
    let latency = vec![
        LatencySample {
            label: "Order Submit".into(),
            latency_us: 0.0,
        },
        LatencySample {
            label: "Fill Notify".into(),
            latency_us: 0.0,
        },
        LatencySample {
            label: "Risk Check".into(),
            latency_us: 0.0,
        },
    ];

    // ── Connection status ────────────────────────────────────────────────────
    let connection = ConnectionStatus {
        mode: "SIMULATION".into(),
        connected: true,
        symbols: vec!["EURUSD".into()],
        ping_ms: 0.0,
    };

    DashboardSnapshot {
        equity_curve,
        positions,
        risk,
        order_log,
        latency,
        connection,
        progress_pct: p.progress_pct,
        tick_count: p.tick_count,
        total_ticks: p.total_ticks,
    }
}

/// Run a synthetic backtest and emit `state-update` events on every progress tick.
/// Called from `commands::start_backtest` inside a dedicated OS thread.
pub fn run_backtest(state: Arc<Mutex<AppState>>, app_handle: tauri::AppHandle) {
    let instrument = InstrumentId::new("EURUSD");

    // ── BacktestConfig ───────────────────────────────────────────────────────
    let config = BacktestConfig {
        instruments: vec![instrument.clone()],
        start_time: Timestamp::from_millis(1_700_000_000_000),
        end_time: Timestamp::from_millis(1_700_100_000_000),
        initial_balance: dec!(100_000),
        leverage: dec!(100),
        risk_config: RiskConfig::default(),
        execution_config: ExecutionModelConfig::default(),
        seed: 42,
        commission_per_lot: dec!(7),
    };

    // ── Synthetic tick data ──────────────────────────────────────────────────
    let synth_config = SyntheticTickConfig {
        instrument_id: instrument.clone(),
        num_ticks: 1_000_000,
        initial_price: dec!(1.08500),
        half_spread: dec!(0.00005),
        volatility: 0.10,
        drift: 0.0,
        seed: 42,
        tick_interval_ns: 100_000_000, // 100 ms
        start_timestamp_ns: 1_700_000_000_000_000_000,
        base_volume: dec!(100),
    };

    let ticks = quantfund_data::generate_synthetic_ticks(&synth_config);
    let mut replay = TickReplay::from_ticks(ticks);

    // ── Strategy ─────────────────────────────────────────────────────────────
    let strategy_config = SmaCrossoverConfig {
        instruments: vec![instrument.clone()],
        fast_period: 10,
        slow_period: 30,
    };
    let strategies: Vec<Box<dyn quantfund_strategy::Strategy>> =
        vec![Box::new(SmaCrossover::new(strategy_config))];

    // ── Runner with progress callback ────────────────────────────────────────
    let state_for_cb = Arc::clone(&state);
    let app_for_cb = app_handle.clone();

    let mut runner = BacktestRunner::new(config, strategies).on_progress(10_000, move |p| {
        let running = state_for_cb.lock().unwrap().running;
        if !running {
            return;
        }
        let snapshot = progress_to_snapshot(&p);
        state_for_cb.lock().unwrap().snapshot = snapshot.clone();
        let _ = app_for_cb.emit("state-update", snapshot);
    });

    let _result = runner.run(&mut replay);

    // Mark finished and emit final state.
    state.lock().unwrap().running = false;
    let final_snapshot = state.lock().unwrap().snapshot.clone();
    let _ = app_handle.emit("state-update", final_snapshot);
}
