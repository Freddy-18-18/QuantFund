//! IMF API Client for QuantFund
//! 
//! International Monetary Fund (IMF) SDMX 3.0 API client with rate limiting,
//! caching, and support for economic data retrieval.
//!
//! # Datasets Available
//!
//! - PCPS: Primary Commodity Prices (includes Gold)
//! - IFS: International Financial Statistics
//! - DOT: Direction of Trade
//! - WEO: World Economic Outlook
//! - BOP: Balance of Payments
//! - CPI: Consumer Price Index
//! - IR: Interest Rates
//!
//! # Usage
//!
//! ```rust
//! use quantfund_imf::{ImfClient, ImfCache};
//!
//! let client = ImfClient::new("your-api-key".to_string());
//! let gold_prices = client.get_data("PCPS", "PGold.PP0000", None, None).await?;
//! ```

pub mod cache;
pub mod client;
pub mod endpoints;
pub mod error;
pub mod models;

pub use cache::{ImfCache, CacheMetrics};
pub use client::ImfClient;
pub use error::{ImfError, ImfResult};
pub use models::*;
