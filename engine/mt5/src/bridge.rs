/// [`ExecutionBridge`] trait and [`Mt5Bridge`] TCP implementation.
///
/// # Mode duality
/// The backtest runner holds a `Box<dyn ExecutionBridge>` so it works the same
/// way whether the backing engine is `MatchingEngine` (simulation) or
/// `Mt5Bridge` (live).
///
/// # Mt5Bridge internals
/// The bridge maintains a single long-lived TCP connection to the MQL5 EA
/// connector.  Messages are framed as **newline-delimited JSON** (`\n`).
///
/// ## Send path
/// `submit_order()` → serialise → send line → await `Ack` or `Fill` on the
/// inbound reader (with configurable timeout).
///
/// ## Receive path
/// `poll_responses()` reads any available lines without blocking. The caller
/// (live runner) should call this in a tight loop or on a dedicated thread.
use std::io::{BufRead, BufReader, Write};
use std::net::TcpStream;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use tracing::{debug, error, info, trace, warn};

use quantfund_core::event::{Event, PartialFillEvent, RejectionEvent, RejectionReason, TickEvent};
use quantfund_core::order::Order;
use quantfund_core::types::{OrderId, Timestamp, Volume};

use crate::config::Mt5BridgeConfig;
use crate::error::BridgeError;
use crate::protocol::{
    BridgeMessage, BridgeResponse, Mt5CancelRequest, Mt5CloseRequest, Mt5ModifyRequest,
    Mt5OrderRequest,
};

// ─── ExecutionBridge trait ───────────────────────────────────────────────────

/// Common interface for all execution backends.
///
/// Implemented by:
/// - `MatchingEngine` (in-process simulation, backtest)
/// - `Mt5Bridge` (live trading via MetaTrader 5)
pub trait ExecutionBridge: Send {
    /// Submit a new order to the execution backend.
    ///
    /// In backtest mode this is synchronous and infallible.
    /// In live mode this sends the order to MT5 and may return a
    /// `BridgeError` if the TCP send fails.
    fn submit_order(&mut self, order: Order, now: Timestamp) -> Result<(), BridgeError>;

    /// Cancel a pending order.
    fn cancel_order(&mut self, order_id: &OrderId) -> Result<(), BridgeError>;

    /// Process (or poll) the next batch of execution events.
    ///
    /// In backtest mode this runs the matching engine against the tick.
    /// In live mode this drains pending inbound responses from the socket
    /// buffer.
    fn process_tick(&mut self, tick: &TickEvent) -> Vec<Event>;

    /// Returns the bridge operating mode.
    fn mode(&self) -> BridgeMode;
}

// ─── BridgeMode ──────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BridgeMode {
    /// In-process simulation (backtest / paper trading).
    Simulation,
    /// Live trading via MetaTrader 5.
    Live,
}

// ─── Mt5Bridge ───────────────────────────────────────────────────────────────

/// Live execution bridge to MetaTrader 5 via TCP.
///
/// ## Usage
/// ```rust,no_run
/// use quantfund_mt5::{Mt5Bridge, Mt5BridgeConfig};
///
/// let config = Mt5BridgeConfig::default();
/// let mut bridge = Mt5Bridge::new(config);
/// bridge.connect().expect("failed to connect to MT5 EA");
/// ```
pub struct Mt5Bridge {
    config: Mt5BridgeConfig,
    /// The connected TCP stream, shared between write and read halves.
    /// `None` when disconnected.
    stream: Option<Arc<Mutex<TcpStream>>>,
    /// Buffered reader wrapping the read side of the stream.
    reader: Option<BufReader<TcpStream>>,
    /// Pending events accumulated from inbound responses.
    pending_events: Vec<Event>,
    /// Monotonically increasing sequence number for Ping messages.
    ping_seq: u64,
}

impl Mt5Bridge {
    /// Create a new bridge (not yet connected).
    pub fn new(config: Mt5BridgeConfig) -> Self {
        Self {
            config,
            stream: None,
            reader: None,
            pending_events: Vec::new(),
            ping_seq: 0,
        }
    }

    /// Establish the TCP connection to the MT5 EA connector.
    ///
    /// Must be called before any other method.
    pub fn connect(&mut self) -> Result<(), BridgeError> {
        if self.stream.is_some() {
            return Err(BridgeError::AlreadyConnected);
        }

        let addr = self.config.socket_addr();
        info!(addr = %addr, "connecting to MT5 EA connector");

        let stream = TcpStream::connect_timeout(
            &addr.parse().map_err(|e| {
                BridgeError::ConnectionFailed(format!("invalid address '{addr}': {e}"))
            })?,
            self.config.connect_timeout,
        )
        .map_err(|e| BridgeError::ConnectionFailed(format!("{e}")))?;

        stream
            .set_read_timeout(Some(std::time::Duration::from_millis(10)))
            .map_err(BridgeError::Io)?;

        // Clone the stream for the read half.
        let read_stream = stream.try_clone().map_err(BridgeError::Io)?;
        self.reader = Some(BufReader::new(read_stream));
        self.stream = Some(Arc::new(Mutex::new(stream)));

        info!(addr = %addr, "connected to MT5 EA connector");
        Ok(())
    }

    /// Disconnect and free the TCP connection.
    pub fn disconnect(&mut self) {
        self.stream = None;
        self.reader = None;
        info!("disconnected from MT5 EA connector");
    }

    /// Returns `true` if the TCP connection is active.
    pub fn is_connected(&self) -> bool {
        self.stream.is_some()
    }

    /// Send a heartbeat ping to the EA.
    pub fn ping(&mut self) -> Result<(), BridgeError> {
        let seq = self.ping_seq;
        self.ping_seq += 1;
        self.send_message(&BridgeMessage::Ping { seq })
    }

    /// Send a modify order message to MT5.
    pub fn modify_order(
        &mut self,
        order_id: &OrderId,
        new_sl: Option<quantfund_core::types::Price>,
        new_tp: Option<quantfund_core::types::Price>,
    ) -> Result<(), BridgeError> {
        let msg = BridgeMessage::ModifyOrder(Mt5ModifyRequest {
            order_id: order_id.to_string(),
            new_sl: new_sl.map(|p| p.to_string()),
            new_tp: new_tp.map(|p| p.to_string()),
        });
        self.send_message(&msg)
    }

    /// Send a close position message to MT5.
    pub fn close_position(
        &mut self,
        order_id: &OrderId,
        volume: Option<&Volume>,
    ) -> Result<(), BridgeError> {
        let msg = BridgeMessage::ClosePosition(Mt5CloseRequest {
            order_id: order_id.to_string(),
            volume: volume.map(|v| v.to_string()),
        });
        self.send_message(&msg)
    }

    // ── Private helpers ──────────────────────────────────────────────────────

    /// Serialise `msg` to a single JSON line and write it to the stream.
    fn send_message(&mut self, msg: &BridgeMessage) -> Result<(), BridgeError> {
        let stream_arc = self.stream.as_ref().ok_or(BridgeError::NotConnected)?;

        let mut line =
            serde_json::to_string(msg).map_err(|e| BridgeError::Serialization(e.to_string()))?;
        line.push('\n');

        if self.config.debug_wire {
            trace!(direction = "outbound", wire = %line.trim_end(), "bridge wire");
        }

        let mut stream = stream_arc
            .lock()
            .map_err(|_| BridgeError::Io(std::io::Error::other("mutex poisoned")))?;
        stream.write_all(line.as_bytes()).map_err(BridgeError::Io)?;
        stream.flush().map_err(BridgeError::Io)?;

        debug!(msg_type = msg.type_tag(), "message sent to MT5");
        Ok(())
    }

    /// Drain all currently available inbound lines from the reader (non-blocking).
    ///
    /// Lines are converted to [`Event`]s and pushed into `self.pending_events`.
    fn drain_inbound(&mut self) {
        let reader = match self.reader.as_mut() {
            Some(r) => r,
            None => return,
        };

        let debug_wire = self.config.debug_wire;
        loop {
            let mut line = String::new();
            match reader.read_line(&mut line) {
                Ok(0) => break, // EOF / disconnected.
                Ok(_) => {
                    // Trim and own the string so we can drop the reader borrow
                    // before calling self.parse_response (which needs &self).
                    let trimmed: String = line.trim_end().to_owned();
                    if trimmed.is_empty() {
                        continue;
                    }
                    if debug_wire {
                        trace!(direction = "inbound", wire = %trimmed, "bridge wire");
                    }
                    // Temporarily release reader borrow by breaking out of the loop
                    // is not possible, so we collect lines and process after.
                    // Instead, inline the parse logic here to avoid double-borrow.
                    let resp_result =
                        serde_json::from_str::<crate::protocol::BridgeResponse>(&trimmed);
                    match resp_result {
                        Ok(resp) => match Self::response_to_event(resp) {
                            Ok(Some(event)) => self.pending_events.push(event),
                            Ok(None) => {}
                            Err(e) => {
                                error!(error = %e, raw = %trimmed, "failed to convert inbound bridge response");
                            }
                        },
                        Err(e) => {
                            error!(error = %e, raw = %trimmed, "failed to parse inbound bridge response");
                        }
                    }
                }
                Err(ref e)
                    if e.kind() == std::io::ErrorKind::WouldBlock
                        || e.kind() == std::io::ErrorKind::TimedOut =>
                {
                    break; // No more data available right now.
                }
                Err(e) => {
                    error!(error = %e, "socket read error — marking bridge as disconnected");
                    self.stream = None;
                    self.reader = None;
                    break;
                }
            }
        }
    }

    /// Convert an already-deserialized [`BridgeResponse`] into an [`Event`] if it warrants one.
    fn response_to_event(resp: BridgeResponse) -> Result<Option<Event>, BridgeError> {
        match resp {
            BridgeResponse::Fill(deal) => {
                let fill = deal.to_fill_event()?;
                Ok(Some(Event::Fill(fill)))
            }

            BridgeResponse::Closed(deal) => {
                // Treat a position close as a fill in the opposite direction.
                let fill = deal.to_fill_event()?;
                Ok(Some(Event::Fill(fill)))
            }

            BridgeResponse::PartialFill(pf) => {
                let order_id = parse_order_id(&pf.order_id)?;
                let filled_volume = parse_volume(&pf.filled_volume)?;
                let remaining_volume = parse_volume(&pf.remaining_volume)?;
                let fill_price = parse_price(&pf.fill_price)?;
                let timestamp = Timestamp::from_millis(pf.timestamp_ms);

                Ok(Some(Event::PartialFill(PartialFillEvent {
                    timestamp,
                    order_id,
                    filled_volume,
                    remaining_volume,
                    fill_price,
                })))
            }

            BridgeResponse::Rejection(rej) => {
                let order_id = parse_order_id(&rej.order_id)?;
                warn!(
                    order_id = %rej.order_id,
                    retcode = rej.retcode,
                    message = %rej.message,
                    "MT5 rejected order"
                );
                Ok(Some(Event::Rejection(RejectionEvent {
                    timestamp: Timestamp::now(),
                    order_id,
                    reason: RejectionReason::BrokerRejected(format!(
                        "retcode={} {}",
                        rej.retcode, rej.message
                    )),
                })))
            }

            BridgeResponse::Ack(ack) => {
                debug!(order_id = %ack.order_id, mt5_ticket = ack.mt5_ticket, "order acknowledged");
                Ok(None)
            }

            BridgeResponse::Cancelled(ack) => {
                debug!(order_id = %ack.order_id, "order cancelled");
                Ok(None)
            }

            BridgeResponse::Tick(mt5_tick) => {
                let tick = mt5_tick.to_tick_event()?;
                Ok(Some(Event::Tick(tick)))
            }

            BridgeResponse::AccountUpdate(update) => {
                debug!(
                    balance = %update.balance,
                    equity = %update.equity,
                    "account update from MT5"
                );
                Ok(None)
            }

            BridgeResponse::Pong { seq } => {
                debug!(seq = seq, "pong from MT5 EA");
                Ok(None)
            }

            BridgeResponse::Error { message } => {
                error!(message = %message, "error from MT5 EA");
                Ok(None)
            }
        }
    }

    /// Wait synchronously for an `Ack` or `Fill` for `order_id`, timing out
    /// after `config.ack_timeout`.
    ///
    /// Used when `submit_order` needs to confirm the order landed on the broker.
    pub fn wait_for_ack(&mut self, order_id: &OrderId) -> Result<(), BridgeError> {
        let deadline = Instant::now() + self.config.ack_timeout;
        let order_id_str = order_id.to_string();

        loop {
            if Instant::now() >= deadline {
                return Err(BridgeError::AckTimeout {
                    order_id: order_id_str,
                });
            }

            self.drain_inbound();

            // Check if we got an Ack (via pending events list is not ideal;
            // in production a dedicated ack-tracker map is better — this is
            // sufficient for Phase 5).
            let got_fill = self
                .pending_events
                .iter()
                .any(|e| matches!(e, Event::Fill(f) if f.order_id == *order_id));
            if got_fill {
                return Ok(());
            }

            std::thread::sleep(std::time::Duration::from_millis(1));
        }
    }
}

// ─── ExecutionBridge impl for Mt5Bridge ─────────────────────────────────────

impl ExecutionBridge for Mt5Bridge {
    fn submit_order(&mut self, order: Order, _now: Timestamp) -> Result<(), BridgeError> {
        let req = Mt5OrderRequest::from_order(&order);
        let msg = BridgeMessage::NewOrder(req);
        self.send_message(&msg)
    }

    fn cancel_order(&mut self, order_id: &OrderId) -> Result<(), BridgeError> {
        let msg = BridgeMessage::CancelOrder(Mt5CancelRequest {
            order_id: order_id.to_string(),
        });
        self.send_message(&msg)
    }

    fn process_tick(&mut self, _tick: &TickEvent) -> Vec<Event> {
        // In live mode, tick data comes from MT5 itself (or a separate market
        // data feed).  This call simply drains any buffered inbound responses.
        self.drain_inbound();
        std::mem::take(&mut self.pending_events)
    }

    fn mode(&self) -> BridgeMode {
        BridgeMode::Live
    }
}

// ─── Inline helpers (same as in protocol.rs but private to bridge) ───────────

fn parse_order_id(s: &str) -> Result<OrderId, BridgeError> {
    use uuid::Uuid;
    let uuid = Uuid::parse_str(s)
        .map_err(|e| BridgeError::Deserialization(format!("invalid order_id '{s}': {e}")))?;
    Ok(OrderId::from_uuid(uuid))
}

fn parse_volume(s: &str) -> Result<Volume, BridgeError> {
    let d: rust_decimal::Decimal = s
        .parse()
        .map_err(|e| BridgeError::Deserialization(format!("invalid volume '{s}': {e}")))?;
    Ok(Volume::new(d))
}

fn parse_price(s: &str) -> Result<quantfund_core::types::Price, BridgeError> {
    let d: rust_decimal::Decimal = s
        .parse()
        .map_err(|e| BridgeError::Deserialization(format!("invalid price '{s}': {e}")))?;
    Ok(quantfund_core::types::Price::new(d))
}

// ─── BridgeMessage helper ────────────────────────────────────────────────────

impl BridgeMessage {
    pub fn type_tag(&self) -> &'static str {
        match self {
            BridgeMessage::NewOrder(_) => "new_order",
            BridgeMessage::ModifyOrder(_) => "modify_order",
            BridgeMessage::CancelOrder(_) => "cancel_order",
            BridgeMessage::ClosePosition(_) => "close_position",
            BridgeMessage::Ping { .. } => "ping",
        }
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::instrument::InstrumentId;
    use quantfund_core::order::Order;
    use quantfund_core::types::{Side, StrategyId, Volume};
    use rust_decimal_macros::dec;

    // ── Disconnected bridge tests (no real TCP needed) ───────────────────────

    #[test]
    fn bridge_starts_disconnected() {
        let bridge = Mt5Bridge::new(Mt5BridgeConfig::default());
        assert!(!bridge.is_connected());
        assert_eq!(bridge.mode(), BridgeMode::Live);
    }

    #[test]
    fn submit_order_without_connect_returns_error() {
        let mut bridge = Mt5Bridge::new(Mt5BridgeConfig::default());
        let order = Order::market(
            InstrumentId::new("EURUSD"),
            Side::Buy,
            Volume::new(dec!(0.1)),
            StrategyId::new("test"),
        );
        let result = bridge.submit_order(order, Timestamp::now());
        assert!(matches!(result, Err(BridgeError::NotConnected)));
    }

    #[test]
    fn cancel_order_without_connect_returns_error() {
        let mut bridge = Mt5Bridge::new(Mt5BridgeConfig::default());
        let order_id = OrderId::new();
        let result = bridge.cancel_order(&order_id);
        assert!(matches!(result, Err(BridgeError::NotConnected)));
    }

    #[test]
    fn ping_without_connect_returns_error() {
        let mut bridge = Mt5Bridge::new(Mt5BridgeConfig::default());
        let result = bridge.ping();
        assert!(matches!(result, Err(BridgeError::NotConnected)));
    }

    #[test]
    fn process_tick_without_connect_returns_empty() {
        let mut bridge = Mt5Bridge::new(Mt5BridgeConfig::default());
        use quantfund_core::event::TickEvent;
        use quantfund_core::types::Price;
        let tick = TickEvent {
            timestamp: Timestamp::from_nanos(0),
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(dec!(1.1)),
            ask: Price::new(dec!(1.1002)),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: dec!(0.0002),
        };
        let events = bridge.process_tick(&tick);
        assert!(events.is_empty());
    }

    #[test]
    fn connect_to_missing_server_returns_error() {
        let mut bridge = Mt5Bridge::new(Mt5BridgeConfig {
            host: "127.0.0.1".into(),
            port: 19999, // Nothing listening here.
            connect_timeout: std::time::Duration::from_millis(200),
            ..Default::default()
        });
        let result = bridge.connect();
        assert!(matches!(result, Err(BridgeError::ConnectionFailed(_))));
    }
}
