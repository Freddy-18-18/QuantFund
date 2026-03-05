/// Wire protocol between the Rust bridge and the MQL5 EA connector.
///
/// All messages are **single-line JSON** terminated by `\n`.
/// The MQL5 side reads/writes the same JSON fields by name.
///
/// ## Outbound (Rust → MT5)
/// [`BridgeMessage`] is the envelope Rust sends to the EA.
///
/// ## Inbound (MT5 → Rust)
/// [`BridgeResponse`] is the envelope the EA sends back.
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

use quantfund_core::event::{FillEvent, TickEvent};
use quantfund_core::instrument::InstrumentId;
use quantfund_core::order::{Order, OrderType, TimeInForce};
use quantfund_core::types::{OrderId, Price, Side, Timestamp, Volume};

// ─── Outbound: Rust → MT5 ────────────────────────────────────────────────────

/// Top-level envelope for every message sent from the Rust engine to the MT5
/// EA connector.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum BridgeMessage {
    /// Submit a new order to the broker.
    NewOrder(Mt5OrderRequest),
    /// Modify SL/TP on an existing position or pending order.
    ModifyOrder(Mt5ModifyRequest),
    /// Cancel a pending order.
    CancelOrder(Mt5CancelRequest),
    /// Close an open position.
    ClosePosition(Mt5CloseRequest),
    /// Heartbeat / keepalive ping.
    Ping { seq: u64 },
}

// ─── Mt5OrderRequest ─────────────────────────────────────────────────────────

/// Translates a Rust [`Order`] into the flat structure the MQL5 EA can use
/// directly with `OrderSend()` / `CTrade::Buy()` / `CTrade::Sell()`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5OrderRequest {
    /// Original Rust `OrderId` (UUID string).  The EA echoes this back in
    /// every response so we can correlate fills.
    pub order_id: String,

    /// MT5 magic number — maps 1:1 to `Order::magic_number`.
    pub magic: u64,

    /// Symbol name exactly as MT5 knows it, e.g. `"EURUSD"`, `"XAUUSD"`.
    pub symbol: String,

    /// `"buy"` or `"sell"`.
    pub action: String,

    /// Order type: `"market"`, `"limit"`, `"stop"`, or `"stop_limit"`.
    pub order_type: String,

    /// Volume in lots (e.g. `0.1`).
    pub volume: String, // Decimal serialised as string to avoid f64 loss.

    /// Limit price (for `limit` and `stop_limit` orders).  `null` for market.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub price: Option<String>,

    /// Stop trigger price (for `stop` and `stop_limit` orders).  `null` for others.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stop_price: Option<String>,

    /// Stop-loss price.  `null` if not set.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sl: Option<String>,

    /// Take-profit price.  `null` if not set.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tp: Option<String>,

    /// Time-in-force: `"gtc"`, `"ioc"`, `"fok"`, or `"gtd"`.
    pub time_in_force: String,

    /// Unix milliseconds when the order was created in Rust.
    pub timestamp_ms: i64,

    /// Optional human-readable comment (max 31 chars for MT5).
    #[serde(skip_serializing_if = "String::is_empty")]
    pub comment: String,
}

impl Mt5OrderRequest {
    /// Convert a Rust [`Order`] into an [`Mt5OrderRequest`].
    pub fn from_order(order: &Order) -> Self {
        let action = match order.side {
            Side::Buy => "buy",
            Side::Sell => "sell",
        }
        .to_owned();

        let order_type = match order.order_type {
            OrderType::Market => "market",
            OrderType::Limit => "limit",
            OrderType::Stop => "stop",
            OrderType::StopLimit => "stop_limit",
        }
        .to_owned();

        let time_in_force = match &order.time_in_force {
            TimeInForce::GoodTilCancelled => "gtc",
            TimeInForce::ImmediateOrCancel => "ioc",
            TimeInForce::FillOrKill => "fok",
            TimeInForce::GoodTilDate(_) => "gtd",
        }
        .to_owned();

        Self {
            order_id: order.id.to_string(),
            magic: order.magic_number,
            symbol: order.instrument_id.as_str().to_owned(),
            action,
            order_type,
            volume: order.volume.to_string(),
            price: order.price.map(|p| p.to_string()),
            stop_price: order.stop_price.map(|p| p.to_string()),
            sl: order.sl.map(|p| p.to_string()),
            tp: order.tp.map(|p| p.to_string()),
            time_in_force,
            timestamp_ms: order.timestamp.as_millis(),
            comment: order.comment.chars().take(31).collect(),
        }
    }
}

// ─── Mt5ModifyRequest ────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5ModifyRequest {
    pub order_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub new_sl: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub new_tp: Option<String>,
}

// ─── Mt5CancelRequest ────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5CancelRequest {
    pub order_id: String,
}

// ─── Mt5CloseRequest ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5CloseRequest {
    /// The `order_id` from the original `NewOrder` message that opened the position.
    pub order_id: String,
    /// Volume to close; `null` means close the entire position.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub volume: Option<String>,
}

// ─── Inbound: MT5 → Rust ─────────────────────────────────────────────────────

/// Top-level envelope for every message sent from the MT5 EA connector back
/// to the Rust engine.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum BridgeResponse {
    /// Full fill confirmation.
    Fill(Mt5Deal),
    /// Partial fill confirmation.
    PartialFill(Mt5PartialDeal),
    /// Order rejected by broker.
    Rejection(Mt5Rejection),
    /// Order acknowledged (pending order placed but not yet filled).
    Ack(Mt5Ack),
    /// Order cancelled successfully.
    Cancelled(Mt5Ack),
    /// Position closed.
    Closed(Mt5Deal),
    /// Tick data pushed by the EA (used in tick-forwarding mode).
    Tick(Mt5Tick),
    /// Account update pushed periodically by the EA.
    AccountUpdate(Mt5AccountUpdate),
    /// Pong response to a Ping.
    Pong { seq: u64 },
    /// EA-side error (e.g. internal EA error, not a broker rejection).
    Error { message: String },
}

// ─── Mt5Deal ─────────────────────────────────────────────────────────────────

/// A completed deal (full fill) reported by the MT5 EA connector.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5Deal {
    /// Original Rust `OrderId` echoed back by the EA.
    pub order_id: String,

    /// MT5 deal ticket (unique deal number assigned by the broker).
    pub deal_ticket: u64,

    /// MT5 position ticket.
    pub position_ticket: u64,

    /// Symbol name.
    pub symbol: String,

    /// `"buy"` or `"sell"`.
    pub action: String,

    /// Fill volume in lots.
    pub volume: String,

    /// Actual fill price (broker-confirmed).
    pub fill_price: String,

    /// Commission charged in account currency.
    pub commission: String,

    /// Swap in account currency.
    pub swap: String,

    /// Unix milliseconds of the deal execution time on the broker side.
    pub timestamp_ms: i64,
}

impl Mt5Deal {
    /// Convert an [`Mt5Deal`] into a Rust [`FillEvent`].
    ///
    /// `order_id` is looked up from the string — panics if the UUID is malformed,
    /// which should never happen since we generated it ourselves.
    pub fn to_fill_event(&self) -> Result<FillEvent, crate::error::BridgeError> {
        let order_id = parse_order_id(&self.order_id)?;
        let instrument_id = InstrumentId::new(&self.symbol);
        let side = parse_side(&self.action)?;
        let fill_price = parse_price(&self.fill_price)?;
        let volume = parse_volume(&self.volume)?;
        let commission = parse_decimal(&self.commission)?;
        let timestamp = Timestamp::from_millis(self.timestamp_ms);

        Ok(FillEvent {
            timestamp,
            order_id,
            instrument_id,
            side,
            fill_price,
            volume,
            slippage: Decimal::ZERO, // Live slippage measured post-hoc; use 0 in event.
            commission,
        })
    }
}

// ─── Mt5PartialDeal ──────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5PartialDeal {
    pub order_id: String,
    pub deal_ticket: u64,
    pub symbol: String,
    pub action: String,
    pub filled_volume: String,
    pub remaining_volume: String,
    pub fill_price: String,
    pub commission: String,
    pub timestamp_ms: i64,
}

// ─── Mt5Rejection ────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5Rejection {
    /// Original Rust `OrderId`.
    pub order_id: String,
    /// MT5 `retcode` (e.g. 10006 = REQUEST_REJECTED).
    pub retcode: i32,
    /// Human-readable description from `TradeResultRetcodeDescription()`.
    pub message: String,
}

// ─── Mt5Ack ──────────────────────────────────────────────────────────────────

/// Acknowledgement that a pending order was placed on the broker.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5Ack {
    pub order_id: String,
    /// MT5 order ticket assigned by the broker.
    pub mt5_ticket: u64,
    pub timestamp_ms: i64,
}

// ─── Mt5Tick ─────────────────────────────────────────────────────────────────

/// Market data tick pushed from the EA to the Rust engine (tick-forwarding mode).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5Tick {
    pub symbol: String,
    pub bid: String,
    pub ask: String,
    pub bid_volume: String,
    pub ask_volume: String,
    pub timestamp_ms: i64,
}

impl Mt5Tick {
    /// Convert to a Rust [`TickEvent`].
    pub fn to_tick_event(&self) -> Result<TickEvent, crate::error::BridgeError> {
        let bid = parse_price(&self.bid)?;
        let ask = parse_price(&self.ask)?;
        let bid_volume = parse_volume(&self.bid_volume)?;
        let ask_volume = parse_volume(&self.ask_volume)?;
        let spread = *ask - *bid;
        let timestamp = Timestamp::from_millis(self.timestamp_ms);
        let instrument_id = InstrumentId::new(&self.symbol);

        Ok(TickEvent {
            timestamp,
            instrument_id,
            bid,
            ask,
            bid_volume,
            ask_volume,
            spread,
        })
    }
}

// ─── Mt5AccountUpdate ────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mt5AccountUpdate {
    pub balance: String,
    pub equity: String,
    pub margin: String,
    pub free_margin: String,
    pub timestamp_ms: i64,
}

// ─── Parsing helpers ─────────────────────────────────────────────────────────

fn parse_order_id(s: &str) -> Result<OrderId, crate::error::BridgeError> {
    use uuid::Uuid;
    let uuid = Uuid::parse_str(s).map_err(|e| {
        crate::error::BridgeError::Deserialization(format!("invalid order_id '{s}': {e}"))
    })?;
    // SAFETY: OrderId(Uuid) — we reconstruct via the same internal layout.
    // OrderId is repr-transparent over Uuid; we use from_uuid here indirectly.
    Ok(quantfund_core::types::OrderId::from_uuid(uuid))
}

fn parse_side(s: &str) -> Result<Side, crate::error::BridgeError> {
    match s {
        "buy" | "Buy" => Ok(Side::Buy),
        "sell" | "Sell" => Ok(Side::Sell),
        other => Err(crate::error::BridgeError::Deserialization(format!(
            "unknown side '{other}'"
        ))),
    }
}

fn parse_price(s: &str) -> Result<Price, crate::error::BridgeError> {
    let d: Decimal = s.parse().map_err(|e| {
        crate::error::BridgeError::Deserialization(format!("invalid price '{s}': {e}"))
    })?;
    Ok(Price::new(d))
}

fn parse_volume(s: &str) -> Result<Volume, crate::error::BridgeError> {
    let d: Decimal = s.parse().map_err(|e| {
        crate::error::BridgeError::Deserialization(format!("invalid volume '{s}': {e}"))
    })?;
    Ok(Volume::new(d))
}

fn parse_decimal(s: &str) -> Result<Decimal, crate::error::BridgeError> {
    s.parse().map_err(|e| {
        crate::error::BridgeError::Deserialization(format!("invalid decimal '{s}': {e}"))
    })
}
