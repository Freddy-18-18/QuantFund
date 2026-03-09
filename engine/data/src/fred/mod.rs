//! FRED API Client for QuantFund
//! 
//! Federal Reserve Economic Data (FRED) API client with rate limiting,
//! caching, and support for all FRED endpoints.
//!
//! # Usage
//!
//! ```rust
//! use quantfund_fred::{FredClient, FredCache};
//!
//! let client = FredClient::new("your-api-key".to_string());
//! let series = client.get_series("UNRATE").await?;
//! ```

pub mod cache;
pub mod client;
pub mod error;
pub mod integration;
pub mod models;
pub mod persistence;

pub use cache::{FredCache, CacheMetrics};
pub use client::{FredClient, FredDataProvider};
pub use error::{FredError, FredResult};
pub use integration::FredService;
pub use models::*;
pub use persistence::FredPersistence;
