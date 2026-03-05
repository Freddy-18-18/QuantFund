use std::time::Duration;

// ─── Mt5BridgeConfig ─────────────────────────────────────────────────────────

/// Configuration for the TCP connection to the MT5 EA connector.
#[derive(Debug, Clone)]
pub struct Mt5BridgeConfig {
    /// Host / IP of the machine running the MT5 terminal.
    /// Defaults to `127.0.0.1` (same machine).
    pub host: String,

    /// TCP port the MQL5 EA connector is listening on.
    /// Defaults to `9090`.
    pub port: u16,

    /// Timeout waiting for an order acknowledgement from MT5.
    /// Defaults to 5 seconds.
    pub ack_timeout: Duration,

    /// Timeout for the TCP connection attempt.
    /// Defaults to 3 seconds.
    pub connect_timeout: Duration,

    /// If `true`, every outbound message and inbound response is logged at
    /// TRACE level.  Useful for debugging but very noisy in production.
    pub debug_wire: bool,
}

impl Default for Mt5BridgeConfig {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_owned(),
            port: 9090,
            ack_timeout: Duration::from_secs(5),
            connect_timeout: Duration::from_secs(3),
            debug_wire: false,
        }
    }
}

impl Mt5BridgeConfig {
    /// Build the socket address string, e.g. `"127.0.0.1:9090"`.
    pub fn socket_addr(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}
