use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

use crate::instrument::InstrumentId;
use crate::order::Order;
use crate::types::{OrderId, Price, Side, StrategyId, Timeframe, Timestamp, Volume};

// ─── Central Event Enum ──────────────────────────────────────────────────────

/// Every subsystem in the engine communicates exclusively through this enum.
#[derive(Clone, Debug)]
pub enum Event {
    // Market data
    Tick(TickEvent),
    Bar(BarEvent),

    // Strategy signals
    Signal(SignalEvent),

    // Risk decisions
    RiskApproval(RiskApprovalEvent),
    RiskRejection(RiskRejectionEvent),

    // Order lifecycle
    OrderNew(OrderNewEvent),
    OrderCancel(OrderCancelEvent),
    OrderModify(OrderModifyEvent),

    // Execution
    Fill(FillEvent),
    PartialFill(PartialFillEvent),
    Rejection(RejectionEvent),

    // System
    Heartbeat(HeartbeatEvent),
    SessionOpen(SessionEvent),
    SessionClose(SessionEvent),
}

impl Event {
    /// Extract the timestamp from any event variant.
    pub fn timestamp(&self) -> Timestamp {
        match self {
            Event::Tick(e) => e.timestamp,
            Event::Bar(e) => e.timestamp,
            Event::Signal(e) => e.timestamp,
            Event::RiskApproval(e) => e.timestamp,
            Event::RiskRejection(e) => e.timestamp,
            Event::OrderNew(e) => e.timestamp,
            Event::OrderCancel(e) => e.timestamp,
            Event::OrderModify(e) => e.timestamp,
            Event::Fill(e) => e.timestamp,
            Event::PartialFill(e) => e.timestamp,
            Event::Rejection(e) => e.timestamp,
            Event::Heartbeat(e) => e.timestamp,
            Event::SessionOpen(e) => e.timestamp,
            Event::SessionClose(e) => e.timestamp,
        }
    }

    /// Extract the instrument ID from any event variant, if applicable.
    pub fn instrument_id(&self) -> Option<&InstrumentId> {
        match self {
            Event::Tick(e) => Some(&e.instrument_id),
            Event::Bar(e) => Some(&e.instrument_id),
            Event::Signal(e) => Some(&e.instrument_id),
            Event::RiskApproval(_) => None,
            Event::RiskRejection(_) => None,
            Event::OrderNew(e) => Some(&e.order.instrument_id),
            Event::OrderCancel(_) => None,
            Event::OrderModify(_) => None,
            Event::Fill(e) => Some(&e.instrument_id),
            Event::PartialFill(_) => None,
            Event::Rejection(_) => None,
            Event::Heartbeat(_) => None,
            Event::SessionOpen(_) => None,
            Event::SessionClose(_) => None,
        }
    }

    /// A static string tag for logging / metrics.
    pub fn event_type(&self) -> &'static str {
        match self {
            Event::Tick(_) => "Tick",
            Event::Bar(_) => "Bar",
            Event::Signal(_) => "Signal",
            Event::RiskApproval(_) => "RiskApproval",
            Event::RiskRejection(_) => "RiskRejection",
            Event::OrderNew(_) => "OrderNew",
            Event::OrderCancel(_) => "OrderCancel",
            Event::OrderModify(_) => "OrderModify",
            Event::Fill(_) => "Fill",
            Event::PartialFill(_) => "PartialFill",
            Event::Rejection(_) => "Rejection",
            Event::Heartbeat(_) => "Heartbeat",
            Event::SessionOpen(_) => "SessionOpen",
            Event::SessionClose(_) => "SessionClose",
        }
    }
}

// ─── Market Data Events ──────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TickEvent {
    pub timestamp: Timestamp,
    pub instrument_id: InstrumentId,
    pub bid: Price,
    pub ask: Price,
    pub bid_volume: Volume,
    pub ask_volume: Volume,
    /// Spread = ask − bid (pre-computed for convenience).
    pub spread: Decimal,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BarEvent {
    pub timestamp: Timestamp,
    pub instrument_id: InstrumentId,
    pub timeframe: Timeframe,
    pub open: Price,
    pub high: Price,
    pub low: Price,
    pub close: Price,
    pub volume: Volume,
}

// ─── Strategy Signals ────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SignalEvent {
    pub timestamp: Timestamp,
    pub strategy_id: StrategyId,
    pub instrument_id: InstrumentId,
    /// `None` means flat / no directional bias.
    pub side: Option<Side>,
    /// Conviction strength in `[-1.0, 1.0]`. Negative = bearish, positive = bullish.
    pub strength: f64,
    /// Arbitrary key-value metadata for downstream consumption.
    pub metadata: serde_json::Value,
}

// ─── Risk Decisions ──────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RiskApprovalEvent {
    pub timestamp: Timestamp,
    pub order_id: OrderId,
    pub strategy_id: StrategyId,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RiskRejectionEvent {
    pub timestamp: Timestamp,
    pub order_id: OrderId,
    pub strategy_id: StrategyId,
    pub reason: String,
}

// ─── Order Lifecycle ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OrderNewEvent {
    pub timestamp: Timestamp,
    pub order: Order,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OrderCancelEvent {
    pub timestamp: Timestamp,
    pub order_id: OrderId,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OrderModifyEvent {
    pub timestamp: Timestamp,
    pub order_id: OrderId,
    pub new_sl: Option<Price>,
    pub new_tp: Option<Price>,
}

// ─── Execution Events ────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FillEvent {
    pub timestamp: Timestamp,
    pub order_id: OrderId,
    pub instrument_id: InstrumentId,
    pub side: Side,
    pub fill_price: Price,
    pub volume: Volume,
    pub slippage: Decimal,
    pub commission: Decimal,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PartialFillEvent {
    pub timestamp: Timestamp,
    pub order_id: OrderId,
    pub filled_volume: Volume,
    pub remaining_volume: Volume,
    pub fill_price: Price,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RejectionEvent {
    pub timestamp: Timestamp,
    pub order_id: OrderId,
    pub reason: RejectionReason,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum RejectionReason {
    InsufficientMargin,
    InvalidPrice,
    MaxPositionsReached,
    RiskLimitExceeded,
    BrokerRejected(String),
    Other(String),
}

// ─── System Events ───────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HeartbeatEvent {
    pub timestamp: Timestamp,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SessionEvent {
    pub timestamp: Timestamp,
    pub session: TradingSession,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum TradingSession {
    Asian,
    London,
    NewYork,
    Overlap,
}
