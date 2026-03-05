use std::collections::HashMap;

use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use tracing::{debug, info};

use quantfund_core::{
    FillEvent, InstrumentId, Position, PositionStatus, Price, Side, StrategyId, Timestamp,
};

/// Tracks portfolio state throughout the backtest.
pub struct Portfolio {
    /// Current balance (cash).
    balance: Decimal,
    /// Open positions by a simple incrementing ID.
    positions: HashMap<u64, Position>,
    /// Closed positions.
    closed_positions: Vec<Position>,
    /// Next position ID.
    next_position_id: u64,
    /// Peak equity for drawdown calculation.
    peak_equity: Decimal,
    /// Current equity.
    equity: Decimal,
    /// Equity curve: (timestamp, equity) pairs.
    equity_curve: Vec<(Timestamp, Decimal)>,
    /// Daily P&L tracking.
    daily_pnl: Decimal,
    /// Maximum drawdown fraction seen so far.
    max_drawdown: Decimal,
}

impl Portfolio {
    pub fn new(initial_balance: Decimal) -> Self {
        Self {
            balance: initial_balance,
            positions: HashMap::new(),
            closed_positions: Vec::new(),
            next_position_id: 1,
            peak_equity: initial_balance,
            equity: initial_balance,
            equity_curve: Vec::new(),
            daily_pnl: dec!(0),
            max_drawdown: dec!(0),
        }
    }

    /// Creates a new `Position` from a fill event and returns the assigned position ID.
    pub fn open_position(
        &mut self,
        fill: &FillEvent,
        strategy_id: StrategyId,
        sl: Option<Price>,
        tp: Option<Price>,
    ) -> u64 {
        let id = self.next_position_id;
        self.next_position_id += 1;

        let position = Position {
            id,
            instrument_id: fill.instrument_id.clone(),
            strategy_id: strategy_id.clone(),
            side: fill.side,
            volume: fill.volume,
            open_price: fill.fill_price,
            close_price: None,
            sl,
            tp,
            open_time: fill.timestamp,
            close_time: None,
            pnl_gross: dec!(0),
            pnl_net: dec!(0),
            commission: fill.commission,
            slippage_entry: fill.slippage,
            slippage_exit: dec!(0),
            max_favorable_excursion: dec!(0),
            max_adverse_excursion: dec!(0),
            status: PositionStatus::Open,
        };

        info!(
            position_id = id,
            instrument = %fill.instrument_id,
            side = %fill.side,
            volume = %fill.volume,
            price = %fill.fill_price,
            strategy = %strategy_id,
            "position opened"
        );

        self.positions.insert(id, position);
        id
    }

    /// Closes an open position with the given fill event.
    /// Returns the realized net P&L, or `None` if the position was not found.
    pub fn close_position(&mut self, position_id: u64, fill: &FillEvent) -> Option<Decimal> {
        let mut position = self.positions.remove(&position_id)?;

        let open_price = *position.open_price;
        let close_price = *fill.fill_price;
        let volume = *position.volume;

        let pnl_gross = match position.side {
            Side::Buy => (close_price - open_price) * volume,
            Side::Sell => (open_price - close_price) * volume,
        };

        let total_commission = position.commission + fill.commission;
        let pnl_net = pnl_gross - total_commission;

        position.close_price = Some(fill.fill_price);
        position.close_time = Some(fill.timestamp);
        position.pnl_gross = pnl_gross;
        position.pnl_net = pnl_net;
        position.commission = total_commission;
        position.slippage_exit = fill.slippage;
        position.status = PositionStatus::Closed;

        self.balance += pnl_net;
        self.daily_pnl += pnl_net;

        info!(
            position_id = position_id,
            instrument = %position.instrument_id,
            side = %position.side,
            pnl_gross = %pnl_gross,
            pnl_net = %pnl_net,
            commission = %total_commission,
            "position closed"
        );

        self.closed_positions.push(position);
        Some(pnl_net)
    }

    /// Recalculates equity from balance plus the sum of unrealized P&L across all
    /// open positions. Updates peak equity and records an equity curve point.
    ///
    /// `current_prices` maps each instrument to its current `(bid, ask)` pair.
    pub fn update_equity(
        &mut self,
        timestamp: Timestamp,
        current_prices: &HashMap<InstrumentId, (Price, Price)>,
    ) {
        let unrealized: Decimal = self
            .positions
            .values()
            .map(|pos| {
                if let Some(&(bid, ask)) = current_prices.get(&pos.instrument_id) {
                    pos.unrealized_pnl(bid, ask)
                } else {
                    dec!(0)
                }
            })
            .sum();

        self.equity = self.balance + unrealized;

        if self.equity > self.peak_equity {
            self.peak_equity = self.equity;
        }

        // Track max drawdown.
        let dd = self.drawdown();
        if dd > self.max_drawdown {
            self.max_drawdown = dd;
        }

        self.equity_curve.push((timestamp, self.equity));
    }

    /// Current equity value.
    pub fn equity(&self) -> Decimal {
        self.equity
    }

    /// Current cash balance.
    pub fn balance(&self) -> Decimal {
        self.balance
    }

    /// Current drawdown as a fraction: `(peak - equity) / peak`.
    /// Returns zero if peak equity is zero or equity is at or above peak.
    pub fn drawdown(&self) -> Decimal {
        if self.peak_equity <= dec!(0) {
            return dec!(0);
        }
        let dd = self.peak_equity - self.equity;
        if dd <= dec!(0) {
            dec!(0)
        } else {
            dd / self.peak_equity
        }
    }

    /// Maximum drawdown fraction observed so far.
    pub fn max_drawdown(&self) -> Decimal {
        self.max_drawdown
    }

    /// Reference to all currently open positions.
    pub fn open_positions(&self) -> &HashMap<u64, Position> {
        &self.positions
    }

    /// Slice of all closed positions.
    pub fn closed_positions(&self) -> &[Position] {
        &self.closed_positions
    }

    /// The complete equity curve recorded during the backtest.
    pub fn equity_curve(&self) -> &[(Timestamp, Decimal)] {
        &self.equity_curve
    }

    /// Total number of completed (closed) trades.
    pub fn total_trades(&self) -> usize {
        self.closed_positions.len()
    }

    /// Reset daily P&L tracking (call at end-of-day boundary).
    pub fn reset_daily_pnl(&mut self) {
        debug!(daily_pnl = %self.daily_pnl, "resetting daily P&L");
        self.daily_pnl = dec!(0);
    }

    /// Current daily P&L (used by risk engine).
    pub fn daily_pnl(&self) -> Decimal {
        self.daily_pnl
    }
}
