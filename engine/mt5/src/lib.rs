/// `quantfund-mt5` — MT5 Bridge
///
/// Implements the bidirectional IPC layer between the Rust trading engine and
/// a MetaTrader 5 terminal.  The architecture follows §4 of ARCHITECTURE.md:
///
/// ```text
/// Rust Core Engine
///       |
/// IPC Layer (TCP socket, line-delimited JSON)
///       |
/// MT5 EA Connector (MQL5)
///       |
/// MT5 Terminal
/// ```
///
/// ## Mode duality
/// Both `MatchingEngine` (backtest) and `Mt5Bridge` (live) implement the
/// [`ExecutionBridge`] trait, making them fully swappable in the backtest
/// runner and any future live runner without changing strategy or risk code.
///
/// ## Wire format
/// Each message is a **single-line JSON** object terminated by `\n`.
/// Using JSON instead of Protobuf keeps the MQL5 connector simple (string
/// parsing only) while remaining human-readable for debugging.  The format
/// can be swapped to Protobuf in Phase 6 without changing the public API.
pub mod bridge;
pub mod config;
pub mod error;
pub mod protocol;
pub mod simulation;

pub use bridge::{BridgeMode, ExecutionBridge, Mt5Bridge};
pub use config::Mt5BridgeConfig;
pub use error::BridgeError;
pub use protocol::{BridgeMessage, BridgeResponse, Mt5Deal, Mt5OrderRequest};
pub use simulation::SimulationBridge;
