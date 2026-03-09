//! World Bank API Error types

use thiserror::Error;

/// Result type for World Bank operations
pub type WbResult<T> = Result<T, WbError>;

/// World Bank API errors
#[derive(Error, Debug)]
pub enum WbError {
    #[error("API request failed: {0}")]
    Request(#[from] reqwest::Error),

    #[error("Rate limit exceeded. Wait before making more requests.")]
    RateLimited,

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

impl WbError {
    pub fn from_response(code: u16, message: String) -> Self {
        match code {
            404 => WbError::NotFound(message),
            429 => WbError::RateLimited,
            400..=499 => WbError::InvalidParameter(message),
            500..=599 => WbError::ServerError(message),
            _ => WbError::Api { code, message },
        }
    }
}
