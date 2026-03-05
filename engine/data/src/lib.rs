pub mod provider;
pub mod replay;
pub mod synthetic;

pub use provider::{DataError, InMemoryProvider, TickDataProvider};
pub use replay::TickReplay;
pub use synthetic::{
    generate_synthetic_ticks, generate_trending_ticks, SyntheticTickConfig, TrendingTickConfig,
};
