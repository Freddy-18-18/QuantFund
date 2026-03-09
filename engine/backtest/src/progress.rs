/// Types emitted by [`BacktestRunner::run`] via the optional progress callback.
///
/// Designed to be converted directly into the Tauri dashboard snapshot
/// without re-running any calculations.
use rust_decimal::Decimal;

use quantfund_core::{Position, Timestamp};

// ─── FillSummary ─────────────────────────────────────────────────────────────

/// Lightweight fill record accumulate between progress callbacks.
#[derive(Clone, Debug)]
pub struct FillSummary {
    pub timestamp_ms: i64,
    pub instrument: String,
    /// "Buy" | "Sell"
    pub side: String,
    pub volume: f64,
    pub fill_price: f64,
    pub slippage: f64,
    pub commission: f64,
}

// ─── BacktestProgress ────────────────────────────────────────────────────────

/// Snapshot of the running backtest state, emitted every `progress_interval` ticks.
#[derive(Clone, Debug)]
pub struct BacktestProgress {
    // ── Throughput ──────────────────────────────────────────────────────────
    pub tick_count: u64,
    pub total_ticks: u64,
    /// 0.0 – 100.0
    pub progress_pct: f64,

    // ── Portfolio ───────────────────────────────────────────────────────────
    pub equity: Decimal,
    pub balance: Decimal,
    pub daily_pnl: Decimal,

    // ── Risk ────────────────────────────────────────────────────────────────
    /// Fraction 0–1 (e.g., 0.03 = 3%)
    pub current_drawdown: Decimal,
    pub max_drawdown: Decimal,

    // ── Positions ───────────────────────────────────────────────────────────
    pub open_positions: Vec<Position>,
    pub total_closed_trades: usize,

    // ── Equity curve (downsampled to ≤ 2 000 points) ────────────────────────
    pub equity_curve: Vec<(Timestamp, Decimal)>,

    // ── Fills since last callback ───────────────────────────────────────────
    pub recent_fills: Vec<FillSummary>,
}
