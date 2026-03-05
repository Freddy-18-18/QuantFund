use serde::{Deserialize, Serialize};
use thiserror::Error;

// ─── Bridge Errors ───────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum BridgeError {
    /// TCP connection to the MT5 connector could not be established.
    #[error("connection failed: {0}")]
    ConnectionFailed(String),

    /// The bridge is not connected when an operation was attempted.
    #[error("bridge is not connected")]
    NotConnected,

    /// A message could not be serialized to the wire format.
    #[error("serialization error: {0}")]
    Serialization(String),

    /// A response from MT5 could not be deserialized.
    #[error("deserialization error: {0}")]
    Deserialization(String),

    /// MT5 rejected the order with a broker-side error code.
    #[error("broker rejection: code={retcode}, reason={message}")]
    BrokerRejection { retcode: i32, message: String },

    /// A timeout occurred waiting for an acknowledgement from MT5.
    #[error("timeout waiting for acknowledgement (order_id={order_id})")]
    AckTimeout { order_id: String },

    /// I/O error on the underlying socket.
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    /// The bridge was already connected when `connect()` was called.
    #[error("bridge is already connected")]
    AlreadyConnected,

    /// An invalid message type was received from the MT5 side.
    #[error("unexpected message type: {0}")]
    UnexpectedMessage(String),
}

// ─── Serializable error summary (for logging) ────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BridgeErrorInfo {
    pub kind: String,
    pub message: String,
}

impl From<&BridgeError> for BridgeErrorInfo {
    fn from(e: &BridgeError) -> Self {
        Self {
            kind: error_kind(e).to_owned(),
            message: e.to_string(),
        }
    }
}

fn error_kind(e: &BridgeError) -> &'static str {
    match e {
        BridgeError::ConnectionFailed(_) => "ConnectionFailed",
        BridgeError::NotConnected => "NotConnected",
        BridgeError::Serialization(_) => "Serialization",
        BridgeError::Deserialization(_) => "Deserialization",
        BridgeError::BrokerRejection { .. } => "BrokerRejection",
        BridgeError::AckTimeout { .. } => "AckTimeout",
        BridgeError::Io(_) => "Io",
        BridgeError::AlreadyConnected => "AlreadyConnected",
        BridgeError::UnexpectedMessage(_) => "UnexpectedMessage",
    }
}
