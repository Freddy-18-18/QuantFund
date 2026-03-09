use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::RwLock;

/// Unified API manager for all external data sources
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ApiManagerState {
    pub fred_enabled: bool,
    pub worldbank_enabled: bool,
    pub fred_api_key: String,
}

impl ApiManagerState {
    pub fn new() -> Self {
        Self {
            fred_enabled: true,
            worldbank_enabled: true,
            fred_api_key: std::env::var("FRED_API_KEY").unwrap_or_default(),
        }
    }
}

pub type ApiManager = Arc<RwLock<ApiManagerState>>;

/// Get status of all APIs
#[tauri::command]
pub async fn api_get_status(
    state: tauri::State<'_, ApiManager>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    Ok(serde_json::json!({
        "fred": {
            "enabled": s.fred_enabled,
            "has_api_key": !s.fred_api_key.is_empty(),
        },
        "worldbank": {
            "enabled": s.worldbank_enabled,
        }
    }))
}

/// Enable or disable FRED API
#[tauri::command]
pub async fn api_set_fred_enabled(
    enabled: bool,
    state: tauri::State<'_, ApiManager>,
) -> Result<String, String> {
    let mut s = state.write().await;
    s.fred_enabled = enabled;
    Ok(format!("FRED API {}", if enabled { "enabled" } else { "disabled" }))
}

/// Enable or disable World Bank API
#[tauri::command]
pub async fn api_set_worldbank_enabled(
    enabled: bool,
    state: tauri::State<'_, ApiManager>,
) -> Result<String, String> {
    let mut s = state.write().await;
    s.worldbank_enabled = enabled;
    Ok(format!("World Bank API {}", if enabled { "enabled" } else { "disabled" }))
}

/// Set FRED API key
#[tauri::command]
pub async fn api_set_fred_key(
    api_key: String,
    state: tauri::State<'_, ApiManager>,
) -> Result<String, String> {
    let mut s = state.write().await;
    s.fred_api_key = api_key;
    Ok("FRED API key updated".to_string())
}

/// Get FRED API key (masked)
#[tauri::command]
pub async fn api_get_fred_key(
    state: tauri::State<'_, ApiManager>,
) -> Result<String, String> {
    let s = state.read().await;
    if s.fred_api_key.is_empty() {
        return Ok("not set".to_string());
    }
    // Return masked key
    let key = &s.fred_api_key;
    if key.len() > 8 {
        Ok(format!("{}...{}", &key[..4], &key[key.len()-4..]))
    } else {
        Ok("***".to_string())
    }
}
