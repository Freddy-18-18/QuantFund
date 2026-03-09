//! FRED API Error types

use thiserror::Error;

/// Result type for FRED operations
pub type FredResult<T> = Result<T, FredError>;

/// FRED API errors
#[derive(Error, Debug)]
pub enum FredError {
    #[error("API request failed: {0}")]
    Request(#[from] reqwest::Error),

    #[error("Rate limit exceeded. Wait before making more requests.")]
    RateLimited,

    #[error("Authentication failed. Check your API key.")]
    Authentication,

    #[error("Resource not found: {0}")]
    NotFound(String),

    #[error("Invalid parameter: {0}")]
    InvalidParameter(String),

    #[error("Server error: {0}")]
    ServerError(String),

    #[error("Parse error: {0}")]
    Parse(String),

    #[error("Cache error: {0}")]
    Cache(String),

    #[error("Configuration error: {0}")]
    Config(String),

    #[error("API error ({code}): {message}")]
    Api { code: u16, message: String },
}

impl FredError {
    /// Create error from FRED API response
    pub fn from_response(code: u16, message: String) -> Self {
        match code {
            401 => FredError::Authentication,
            404 => FredError::NotFound(message),
            429 => FredError::RateLimited,
            400..=499 => FredError::InvalidParameter(message),
            500..=599 => FredError::ServerError(message),
            _ => FredError::Api { code, message },
        }
    }
}
