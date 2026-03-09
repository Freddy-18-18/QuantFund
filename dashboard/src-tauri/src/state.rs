use serde::{Deserialize, Serialize};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

// ─── Serialisable types (mirrored to TypeScript) ────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct EquityPoint {
    /// Unix milliseconds.
    pub ts: i64,
    pub equity: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PositionSnapshot {
    pub instrument: String,
    /// "Buy" | "Sell"
    pub side: String,
    pub volume: f64,
    pub entry_price: f64,
    pub unrealized_pnl: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct RiskSnapshot {
    pub equity: f64,
    pub balance: f64,
    pub daily_pnl: f64,
    pub current_drawdown_pct: f64,
    pub max_drawdown_pct: f64,
    pub open_positions: usize,
    pub total_closed_trades: usize,
    /// true = kill-switch engaged.
    pub kill_switch_active: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OrderLogEntry {
    pub ts: i64,
    pub event_type: String,
    pub instrument: String,
    pub side: String,
    pub volume: f64,
    pub price: f64,
    pub note: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct LatencySample {
    pub label: String,
    /// Microseconds.
    pub latency_us: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct ConnectionStatus {
    /// "SIMULATION" | "PAPER" | "LIVE"
    pub mode: String,
    pub connected: bool,
    pub symbols: Vec<String>,
    pub ping_ms: f64,
}

/// The master snapshot sent to the frontend on every update.
#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct DashboardSnapshot {
    pub equity_curve: Vec<EquityPoint>,
    pub positions: Vec<PositionSnapshot>,
    pub risk: RiskSnapshot,
    pub order_log: Vec<OrderLogEntry>,
    pub latency: Vec<LatencySample>,
    pub connection: ConnectionStatus,
    pub progress_pct: f64,
    pub tick_count: u64,
    pub total_ticks: u64,
}

// ─── Application state (shared between commands and engine thread) ───────────

pub struct AppState {
    pub snapshot: DashboardSnapshot,
    /// Whether a backtest is currently running.
    pub running: bool,
    /// Set to `true` to request cancellation of a running backtest.
    pub cancel_flag: Arc<AtomicBool>,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            snapshot: DashboardSnapshot::default(),
            running: false,
            cancel_flag: Arc::new(AtomicBool::new(false)),
        }
    }
}

impl AppState {
    /// Reset the cancel flag and return a clone of the Arc for the engine.
    pub fn arm_cancel_flag(&self) -> Arc<AtomicBool> {
        self.cancel_flag.store(false, Ordering::Relaxed);
        Arc::clone(&self.cancel_flag)
    }
}
