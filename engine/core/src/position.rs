use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use serde::{Deserialize, Serialize};

use crate::instrument::InstrumentId;
use crate::types::{Price, Side, StrategyId, Timestamp, Volume};

// ─── PositionStatus ──────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum PositionStatus {
    Open,
    Closed,
}

// ─── Position ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Position {
    pub id: u64,
    pub instrument_id: InstrumentId,
    pub strategy_id: StrategyId,
    pub side: Side,
    pub volume: Volume,
    pub open_price: Price,
    pub close_price: Option<Price>,
    pub sl: Option<Price>,
    pub tp: Option<Price>,
    pub open_time: Timestamp,
    pub close_time: Option<Timestamp>,
    /// Gross profit/loss (before commission).
    pub pnl_gross: Decimal,
    /// Net profit/loss (after commission).
    pub pnl_net: Decimal,
    pub commission: Decimal,
    pub slippage_entry: Decimal,
    pub slippage_exit: Decimal,
    /// Maximum Favorable Excursion — largest unrealized gain during the trade's life.
    pub max_favorable_excursion: Decimal,
    /// Maximum Adverse Excursion — largest unrealized loss during the trade's life.
    pub max_adverse_excursion: Decimal,
    pub status: PositionStatus,
}

impl Position {
    /// Calculate unrealized P&L given the current market prices.
    ///
    /// For a **Buy** position the exit price is the current bid;
    /// for a **Sell** position the exit price is the current ask.
    pub fn unrealized_pnl(&self, current_bid: Price, current_ask: Price) -> Decimal {
        if self.status == PositionStatus::Closed {
            return dec!(0);
        }

        let exit_price = match self.side {
            Side::Buy => *current_bid,
            Side::Sell => *current_ask,
        };

        let open = *self.open_price;
        let vol = *self.volume;

        match self.side {
            Side::Buy => (exit_price - open) * vol,
            Side::Sell => (open - exit_price) * vol,
        }
    }

    pub fn is_open(&self) -> bool {
        self.status == PositionStatus::Open
    }

    /// Duration the position has been (or was) held, in nanoseconds.
    /// Returns `None` if the position is still open and has no close time.
    pub fn duration(&self) -> Option<i64> {
        self.close_time
            .map(|ct| ct.as_nanos() - self.open_time.as_nanos())
    }
}
