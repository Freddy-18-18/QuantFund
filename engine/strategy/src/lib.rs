pub mod context;
pub mod sma_crossover;
pub mod traits;

pub use context::StrategyContext;
pub use sma_crossover::{SmaCrossover, SmaCrossoverConfig};
pub use traits::{MarketSnapshot, Strategy};
