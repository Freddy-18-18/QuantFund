//! Data Ingestion and Management for QuantFund
//!
//! Provides connectors for various data sources, including FRED, IMF, and World Bank.

pub mod fred;
pub mod imf;
pub mod worldbank;
pub mod provider;
pub mod replay;
pub mod synthetic;
pub mod postgres_provider;

// Re-export common types
pub use fred::models::{
    Category, Release, Series, SeriesObservation, Tag, Source,
    CategorySeries, CategorySeriesResponse, SeriesObservationsResponse,
    SeriesSearchResponse,
};
pub use imf::models::{
    TimeSeries, Observation, DataflowInfo,
};
pub use worldbank::models::{
    Indicator, Country, IndicatorData,
};
pub use replay::TickReplay;
pub use provider::TickDataProvider;
pub use synthetic::{SyntheticTickConfig, generate_synthetic_ticks};
pub use postgres_provider::PostgresTickProvider;
