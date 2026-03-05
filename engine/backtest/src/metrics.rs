use quantfund_core::{Position, Timestamp};
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

/// Complete backtest performance metrics.
#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct PerformanceMetrics {
    pub total_trades: usize,
    pub winning_trades: usize,
    pub losing_trades: usize,
    pub win_rate: f64,
    pub total_pnl: Decimal,
    pub gross_profit: Decimal,
    pub gross_loss: Decimal,
    pub profit_factor: f64,
    pub max_drawdown: Decimal,
    pub max_drawdown_pct: f64,
    pub sharpe_ratio: f64,
    pub sortino_ratio: f64,
    pub calmar_ratio: f64,
    pub avg_win: Decimal,
    pub avg_loss: Decimal,
    pub largest_win: Decimal,
    pub largest_loss: Decimal,
    pub avg_trade_duration_secs: f64,
    pub total_commission: Decimal,
    pub total_slippage: Decimal,
    pub recovery_factor: f64,
    pub expectancy: f64,
}

/// Calculate comprehensive performance metrics from closed positions and the
/// equity curve.
pub fn calculate_metrics(
    closed_positions: &[Position],
    equity_curve: &[(Timestamp, Decimal)],
    initial_balance: Decimal,
) -> PerformanceMetrics {
    let mut m = PerformanceMetrics::default();

    if closed_positions.is_empty() {
        return m;
    }

    // ── Win / loss classification ────────────────────────────────────────────

    let mut gross_profit = dec!(0);
    let mut gross_loss = dec!(0);
    let mut total_pnl = dec!(0);
    let mut largest_win = dec!(0);
    let mut largest_loss = dec!(0);
    let mut total_commission = dec!(0);
    let mut total_slippage = dec!(0);
    let mut total_duration_nanos: i64 = 0;
    let mut duration_count: usize = 0;

    for pos in closed_positions {
        let pnl = pos.pnl_net;
        total_pnl += pnl;
        total_commission += pos.commission;
        total_slippage += pos.slippage_entry + pos.slippage_exit;

        if pnl > dec!(0) {
            m.winning_trades += 1;
            gross_profit += pnl;
            if pnl > largest_win {
                largest_win = pnl;
            }
        } else if pnl < dec!(0) {
            m.losing_trades += 1;
            gross_loss += pnl.abs();
            if pnl.abs() > largest_loss {
                largest_loss = pnl.abs();
            }
        }
        // pnl == 0 counts as neither win nor loss

        if let Some(dur) = pos.duration() {
            total_duration_nanos += dur;
            duration_count += 1;
        }
    }

    m.total_trades = closed_positions.len();
    m.total_pnl = total_pnl;
    m.gross_profit = gross_profit;
    m.gross_loss = gross_loss;
    m.largest_win = largest_win;
    m.largest_loss = largest_loss;
    m.total_commission = total_commission;
    m.total_slippage = total_slippage;

    // ── Averages ─────────────────────────────────────────────────────────────

    if m.winning_trades > 0 {
        m.avg_win = gross_profit / Decimal::from(m.winning_trades as u64);
    }
    if m.losing_trades > 0 {
        m.avg_loss = gross_loss / Decimal::from(m.losing_trades as u64);
    }

    if m.total_trades > 0 {
        m.win_rate = m.winning_trades as f64 / m.total_trades as f64;
    }

    // profit_factor = gross_profit / gross_loss
    if gross_loss > dec!(0) {
        m.profit_factor = to_f64(gross_profit) / to_f64(gross_loss);
    } else if gross_profit > dec!(0) {
        m.profit_factor = f64::INFINITY;
    }

    // Average trade duration in seconds.
    if duration_count > 0 {
        let total_secs = total_duration_nanos as f64 / 1_000_000_000.0;
        m.avg_trade_duration_secs = total_secs / duration_count as f64;
    }

    // ── Expectancy ───────────────────────────────────────────────────────────
    // expectancy = avg_win * win_rate - avg_loss * (1 - win_rate)

    m.expectancy = to_f64(m.avg_win) * m.win_rate - to_f64(m.avg_loss) * (1.0 - m.win_rate);

    // ── Equity-curve-based metrics ───────────────────────────────────────────

    if equity_curve.len() >= 2 {
        // Max drawdown from equity curve.
        let (max_dd, max_dd_pct) = compute_max_drawdown(equity_curve);
        m.max_drawdown = max_dd;
        m.max_drawdown_pct = max_dd_pct;

        // Returns series for Sharpe / Sortino.
        let returns = compute_returns(equity_curve);

        if returns.len() >= 2 {
            let annualization_factor = (252.0_f64).sqrt();

            // Sharpe = mean(returns) / std(returns) * sqrt(252)
            let mean_ret = mean(&returns);
            let std_ret = std_dev(&returns, mean_ret);
            if std_ret > 0.0 {
                m.sharpe_ratio = (mean_ret / std_ret) * annualization_factor;
            }

            // Sortino = mean(returns) / downside_std * sqrt(252)
            let downside_std = downside_deviation(&returns, 0.0);
            if downside_std > 0.0 {
                m.sortino_ratio = (mean_ret / downside_std) * annualization_factor;
            }

            // CAGR for Calmar.
            let final_equity = to_f64(equity_curve.last().unwrap().1);
            let init = to_f64(initial_balance);
            if init > 0.0 && final_equity > 0.0 {
                let n_points = equity_curve.len() as f64;
                // Approximate years from the number of equity-curve points.
                let years = n_points / 252.0;

                if years > 0.0 {
                    let cagr = (final_equity / init).powf(1.0 / years) - 1.0;

                    // Calmar = CAGR / max_drawdown_pct
                    if m.max_drawdown_pct > 0.0 {
                        m.calmar_ratio = cagr / m.max_drawdown_pct;
                    }
                }
            }
        }

        // Recovery factor = total_pnl / max_drawdown
        if m.max_drawdown > dec!(0) {
            m.recovery_factor = to_f64(total_pnl) / to_f64(m.max_drawdown);
        }
    }

    m
}

// ── Helper functions ─────────────────────────────────────────────────────────

/// Convert `Decimal` to `f64` (lossy but necessary for ratio calculations).
fn to_f64(d: Decimal) -> f64 {
    use rust_decimal::prelude::ToPrimitive;
    d.to_f64().unwrap_or(0.0)
}

/// Compute period-over-period returns from the equity curve.
fn compute_returns(equity_curve: &[(Timestamp, Decimal)]) -> Vec<f64> {
    equity_curve
        .windows(2)
        .filter_map(|w| {
            let prev = to_f64(w[0].1);
            let curr = to_f64(w[1].1);
            if prev != 0.0 {
                Some((curr - prev) / prev)
            } else {
                None
            }
        })
        .collect()
}

/// Walk through equity curve to find the maximum peak-to-trough drawdown.
/// Returns `(absolute_drawdown, fractional_drawdown)`.
fn compute_max_drawdown(equity_curve: &[(Timestamp, Decimal)]) -> (Decimal, f64) {
    let mut peak = dec!(0);
    let mut max_dd = dec!(0);

    for &(_, eq) in equity_curve {
        if eq > peak {
            peak = eq;
        }
        let dd = peak - eq;
        if dd > max_dd {
            max_dd = dd;
        }
    }

    let max_dd_pct = if peak > dec!(0) {
        to_f64(max_dd) / to_f64(peak)
    } else {
        0.0
    };

    (max_dd, max_dd_pct)
}

fn mean(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    values.iter().sum::<f64>() / values.len() as f64
}

fn std_dev(values: &[f64], mean_val: f64) -> f64 {
    if values.len() < 2 {
        return 0.0;
    }
    let variance =
        values.iter().map(|v| (v - mean_val).powi(2)).sum::<f64>() / (values.len() - 1) as f64;
    variance.sqrt()
}

/// Downside deviation: standard deviation of returns below the target.
fn downside_deviation(returns: &[f64], target: f64) -> f64 {
    let downside: Vec<f64> = returns
        .iter()
        .filter(|&&r| r < target)
        .map(|r| (r - target).powi(2))
        .collect();

    if downside.is_empty() {
        return 0.0;
    }

    let sum: f64 = downside.iter().sum();
    // Use total returns count as denominator for semi-deviation.
    (sum / returns.len() as f64).sqrt()
}
