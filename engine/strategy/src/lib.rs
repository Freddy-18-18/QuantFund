pub mod channel_breakout;
pub mod context;
pub mod fred_signal_strategy;
pub mod mean_reversion;
pub mod momentum_rsi;
pub mod python_signal_relay;
pub mod sma_crossover;
pub mod traits;

pub use channel_breakout::{ChannelBreakout, ChannelBreakoutConfig};
pub use context::StrategyContext;
pub use fred_signal_strategy::{FredSignalStrategy, FredSignalStrategyConfig};
pub use mean_reversion::{MeanReversion, MeanReversionConfig};
pub use momentum_rsi::{MomentumRsi, MomentumRsiConfig};
pub use python_signal_relay::{PythonSignalRelay, PythonSignalRelayConfig};
pub use sma_crossover::{SmaCrossover, SmaCrossoverConfig};
pub use traits::{MarketSnapshot, Strategy};
