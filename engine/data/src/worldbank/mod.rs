//! World Bank API Client for QuantFund
//! 
//! Provides async access to the World Bank API (Indicators)
//! with rate limiting and comprehensive endpoint coverage.
//!
//! # Usage
//!
//! ```rust
//! use quantfund_data::worldbank::WorldBankClient;
//!
//! let client = WorldBankClient::new();
//! let countries = client.get_countries(None, Some(50), None).await?;
//! let gdp_data = client.get_indicator_data("NY.GDP.MKTP.CD", "US", Some("2020"), Some("2024"), None, None, None).await?;
//! ```

pub mod client;
pub mod error;
pub mod models;

pub use client::WorldBankClient;
pub use error::{WbError, WbResult};
pub use models::*;
