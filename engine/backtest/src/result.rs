use rust_decimal::Decimal;

use crate::config::BacktestConfig;
use crate::metrics::PerformanceMetrics;
use quantfund_core::{Position, Timestamp};

/// Complete backtest result.
#[derive(Clone, Debug)]
pub struct BacktestResult {
    pub config: BacktestConfig,
    pub metrics: PerformanceMetrics,
    pub equity_curve: Vec<(Timestamp, Decimal)>,
    pub closed_positions: Vec<Position>,
    pub total_ticks_processed: u64,
    pub elapsed_time_ms: u64,
    pub ticks_per_second: f64,
}

impl BacktestResult {
    /// Return a formatted multi-line summary of the key performance metrics.
    pub fn summary(&self) -> String {
        let m = &self.metrics;
        format!(
            "\
╔══════════════════════════════════════════════════════╗
║                  BACKTEST SUMMARY                    ║
╠══════════════════════════════════════════════════════╣
║  Ticks processed:    {total_ticks:>12}                   ║
║  Elapsed time:       {elapsed:>12} ms                ║
║  Throughput:         {tps:>12.0} ticks/s             ║
╠══════════════════════════════════════════════════════╣
║  Total trades:       {trades:>12}                   ║
║  Win rate:           {win_rate:>11.2}%                   ║
║  Profit factor:      {pf:>12.3}                   ║
║  Expectancy:         {exp:>12.2}                   ║
╠══════════════════════════════════════════════════════╣
║  Total P&L:          {pnl:>12}                   ║
║  Gross profit:       {gp:>12}                   ║
║  Gross loss:         {gl:>12}                   ║
║  Total commission:   {comm:>12}                   ║
╠══════════════════════════════════════════════════════╣
║  Max drawdown:       {mdd:>12}                   ║
║  Max drawdown %:     {mdd_pct:>11.2}%                   ║
║  Sharpe ratio:       {sharpe:>12.3}                   ║
║  Sortino ratio:      {sortino:>12.3}                   ║
║  Calmar ratio:       {calmar:>12.3}                   ║
║  Recovery factor:    {rf:>12.3}                   ║
╠══════════════════════════════════════════════════════╣
║  Avg win:            {avg_win:>12}                   ║
║  Avg loss:           {avg_loss:>12}                   ║
║  Largest win:        {lw:>12}                   ║
║  Largest loss:       {ll:>12}                   ║
║  Avg duration:       {dur:>10.1} s                   ║
╚══════════════════════════════════════════════════════╝",
            total_ticks = self.total_ticks_processed,
            elapsed = self.elapsed_time_ms,
            tps = self.ticks_per_second,
            trades = m.total_trades,
            win_rate = m.win_rate * 100.0,
            pf = m.profit_factor,
            exp = m.expectancy,
            pnl = m.total_pnl,
            gp = m.gross_profit,
            gl = m.gross_loss,
            comm = m.total_commission,
            mdd = m.max_drawdown,
            mdd_pct = m.max_drawdown_pct * 100.0,
            sharpe = m.sharpe_ratio,
            sortino = m.sortino_ratio,
            calmar = m.calmar_ratio,
            rf = m.recovery_factor,
            avg_win = m.avg_win,
            avg_loss = m.avg_loss,
            lw = m.largest_win,
            ll = m.largest_loss,
            dur = m.avg_trade_duration_secs,
        )
    }
}
