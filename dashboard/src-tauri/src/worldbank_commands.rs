use quantfund_data::worldbank::WorldBankClient;
use std::sync::Arc;
use tokio::sync::RwLock;

/// State for World Bank client in the dashboard
pub struct WbState {
    pub client: WorldBankClient,
    pub enabled: bool,
}

impl WbState {
    pub fn new() -> Self {
        Self {
            client: WorldBankClient::new(),
            enabled: true,
        }
    }
}

impl Default for WbState {
    fn default() -> Self {
        Self::new()
    }
}

/// Enable or disable World Bank API
#[tauri::command]
pub async fn wb_set_enabled(
    enabled: bool,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<String, String> {
    let mut s = state.write().await;
    s.enabled = enabled;
    Ok(format!("World Bank API {}", if enabled { "enabled" } else { "disabled" }))
}

/// Get World Bank API status
#[tauri::command]
pub async fn wb_get_status(
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    Ok(serde_json::json!({
        "enabled": s.enabled,
    }))
}

/// Get all countries
#[tauri::command]
pub async fn wb_get_countries(
    page: Option<u32>,
    per_page: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_countries(page, per_page, Some("json"))
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get country by code
#[tauri::command]
pub async fn wb_get_country(
    country_code: String,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_country(&country_code)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get all indicators
#[tauri::command]
pub async fn wb_get_indicators(
    page: Option<u32>,
    per_page: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_indicators(page, per_page, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Search indicators
#[tauri::command]
pub async fn wb_search_indicators(
    query: String,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .search_indicators(&query)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get indicator info
#[tauri::command]
pub async fn wb_get_indicator(
    indicator_id: String,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_indicator(&indicator_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WbIndicatorParams {
    pub indicator_id: String,
    pub country_code: String,
    pub date_start: Option<String>,
    pub date_end: Option<String>,
    pub per_page: Option<u32>,
}

/// Get indicator data for a country
#[tauri::command]
pub async fn wb_get_indicator_data(
    params: WbIndicatorParams,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_indicator_data(
            &params.indicator_id,
            &params.country_code,
            params.date_start.as_deref(),
            params.date_end.as_deref(),
            params.per_page,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get indicator data for all countries
#[tauri::command]
pub async fn wb_get_indicator_all_countries(
    indicator_id: String,
    date_start: Option<String>,
    date_end: Option<String>,
    per_page: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_indicator_all_countries(
            &indicator_id,
            date_start.as_deref(),
            date_end.as_deref(),
            per_page,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get all topics
#[tauri::command]
pub async fn wb_get_topics(
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_topics()
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get indicators by topic
#[tauri::command]
pub async fn wb_get_topic_indicators(
    topic_id: String,
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_topic_indicators(&topic_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get data sources
#[tauri::command]
pub async fn wb_get_sources(
    state: tauri::State<'_, Arc<RwLock<WbState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    if !s.enabled {
        return Err("World Bank API is disabled".to_string());
    }
    let result = s.client
        .get_sources()
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}
