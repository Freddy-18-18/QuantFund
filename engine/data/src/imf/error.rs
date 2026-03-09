//! IMF API Error types

use thiserror::Error;

#[derive(Error, Debug)]
pub enum ImfError {
    #[error("HTTP request failed: {0}")]
    Request(#[from] reqwest::Error),

    #[error("Authentication failed: {0}")]
    Authentication(String),

    #[error("Rate limit exceeded: {0}")]
    RateLimit(String),

    #[error("Resource not found: {0}")]
    NotFound(String),

    #[error("Invalid response format: {0}")]
    InvalidResponse(String),

    #[error("API error: {0}")]
    ApiError(String),

    #[error("Parse error: {0}")]
    Parse(String),

    #[error("Cache error: {0}")]
    Cache(String),

    #[error("Configuration error: {0}")]
    Config(String),
}

pub type ImfResult<T> = Result<T, ImfError>;

impl From<serde_json::Error> for ImfError {
    fn from(err: serde_json::Error) -> Self {
        ImfError::Parse(err.to_string())
    }
}
