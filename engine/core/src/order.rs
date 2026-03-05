use serde::{Deserialize, Serialize};

use crate::instrument::InstrumentId;
use crate::types::{OrderId, Price, Side, StrategyId, Timestamp, Volume};

// ─── OrderType ───────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderType {
    Market,
    Limit,
    Stop,
    StopLimit,
}

// ─── OrderStatus ─────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderStatus {
    Created,
    Validated,
    Sent,
    Acknowledged,
    PartiallyFilled,
    Filled,
    Rejected,
    Cancelled,
}

// ─── TimeInForce ─────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum TimeInForce {
    GoodTilCancelled,
    ImmediateOrCancel,
    FillOrKill,
    GoodTilDate(Timestamp),
}

// ─── Order ───────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Order {
    pub id: OrderId,
    pub timestamp: Timestamp,
    pub strategy_id: StrategyId,
    pub instrument_id: InstrumentId,
    pub side: Side,
    pub order_type: OrderType,
    pub volume: Volume,
    /// Limit price — required for `Limit` and `StopLimit` orders.
    pub price: Option<Price>,
    /// Stop trigger price — required for `Stop` and `StopLimit` orders.
    pub stop_price: Option<Price>,
    /// Stop-loss price.
    pub sl: Option<Price>,
    /// Take-profit price.
    pub tp: Option<Price>,
    pub time_in_force: TimeInForce,
    pub status: OrderStatus,
    /// Broker "magic number" tag.
    pub magic_number: u64,
    pub comment: String,
}

impl Order {
    /// Convenience constructor for a market order.
    pub fn market(
        instrument_id: InstrumentId,
        side: Side,
        volume: Volume,
        strategy_id: StrategyId,
    ) -> Self {
        Self {
            id: OrderId::new(),
            timestamp: Timestamp::now(),
            strategy_id,
            instrument_id,
            side,
            order_type: OrderType::Market,
            volume,
            price: None,
            stop_price: None,
            sl: None,
            tp: None,
            time_in_force: TimeInForce::ImmediateOrCancel,
            status: OrderStatus::Created,
            magic_number: 0,
            comment: String::new(),
        }
    }

    /// Convenience constructor for a limit order.
    pub fn limit(
        instrument_id: InstrumentId,
        side: Side,
        volume: Volume,
        price: Price,
        strategy_id: StrategyId,
    ) -> Self {
        Self {
            id: OrderId::new(),
            timestamp: Timestamp::now(),
            strategy_id,
            instrument_id,
            side,
            order_type: OrderType::Limit,
            volume,
            price: Some(price),
            stop_price: None,
            sl: None,
            tp: None,
            time_in_force: TimeInForce::GoodTilCancelled,
            status: OrderStatus::Created,
            magic_number: 0,
            comment: String::new(),
        }
    }
}
