use quantfund_data::fred::{FredClient, FredCache};
use std::sync::Arc;
use tokio::sync::RwLock;

use crate::fred_analysis::{AnalysisEngine, AnalyzedSeries, CorrelationMatrix};
use std::collections::HashMap;

/// Get correlation matrix for multiple series
#[tauri::command]
pub async fn fred_get_correlation_matrix(
    series_ids: Vec<String>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<CorrelationMatrix, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };

    let mut series_data = HashMap::new();

    for id in series_ids {
        let obs = client
            .get_series_observations(
                &id,
                None, None, None, None, None, None, None, None,
            )
            .await
            .map_err(|e| format!("Error fetching {}: {}", id, e))?;

        let raw_data: Vec<(String, f64)> = obs.observations
            .into_iter()
            .filter_map(|o| {
                let val = o.value.parse::<f64>().ok();
                val.map(|v| (o.date, v))
            })
            .collect();
        
        series_data.insert(id, raw_data);
    }

    let matrix = AnalysisEngine::calculate_correlation_matrix(series_data);
    Ok(matrix)
}

/// Get advanced analysis for a series
#[tauri::command]
pub async fn fred_get_series_analysis(
    series_id: String,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<AnalyzedSeries, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    
    // 1. Fetch Series Metadata (for Title)
    let series_info = client.get_series(&series_id).await.map_err(|e| e.to_string())?;
    let title = series_info.title.clone();

    // 2. Fetch Observations
    let obs = client
        .get_series_observations(
            &series_id,
            None, None, None, None, None, None, None, None,
        )
        .await
        .map_err(|e| e.to_string())?;

    // 3. Parse Data (Filter out "." which FRED uses for missing data)
    let raw_data: Vec<(String, f64)> = obs.observations
        .into_iter()
        .filter_map(|o| {
            let val = o.value.parse::<f64>().ok();
            val.map(|v| (o.date, v))
        })
        .collect();

    // 4. Run Analysis Engine
    let analysis = AnalysisEngine::analyze_series(series_id, title, raw_data);
    Ok(analysis)
}

/// State for FRED client in the dashboard
pub struct FredState {
    pub client: FredClient,
    pub cache: Arc<FredCache>,
}

impl FredState {
    pub fn new(api_key: String) -> Self {
        Self {
            client: FredClient::new(api_key),
            cache: FredCache::new(1000),
        }
    }
}

/// Initialize FRED with API key
#[tauri::command]
pub async fn fred_init(api_key: String, state: tauri::State<'_, Arc<RwLock<FredState>>>) 
    -> Result<String, String> {
    let mut s = state.write().await;
    *s = FredState::new(api_key);
    Ok("FRED API initialized".to_string())
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FredSearchParams {
    pub query: String,
    pub limit: Option<u32>,
}

/// Search for economic series by keyword
#[tauri::command]
pub async fn fred_search_series(
    params: FredSearchParams,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .search_series(&params.query, params.limit, None, None, None, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get series information/metadata
#[tauri::command]
pub async fn fred_get_series(
    series_id: String,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_series(&series_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FredObservationParams {
    pub series_id: String,
    pub observation_start: Option<String>,
    pub observation_end: Option<String>,
    pub frequency: Option<String>,
}

/// Get series observations (time series data)
#[tauri::command]
pub async fn fred_get_observations(
    params: FredObservationParams,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_series_observations(
            &params.series_id,
            None, None,
            params.observation_start.as_deref(),
            params.observation_end.as_deref(),
            params.frequency.as_deref(),
            None, None, None,
        )
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get all releases
#[tauri::command]
pub async fn fred_get_releases(
    limit: Option<u32>,
    offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_all_releases(limit, offset)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get release information
#[tauri::command]
pub async fn fred_get_release(
    release_id: u32,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_release(release_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get release dates
#[tauri::command]
pub async fn fred_get_release_dates(
    release_id: u32,
    limit: Option<u32>,
    offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    // Note: Standard API uses /release/dates
    let mut params = std::collections::HashMap::new();
    params.insert("release_id".to_string(), release_id.to_string());
    if let Some(l) = limit { params.insert("limit".to_string(), l.to_string()); }
    if let Some(o) = offset { params.insert("offset".to_string(), o.to_string()); }
    
    // We'll use a generic request if specific method is not in trait
    let result = client.get_series_vintagedates(&release_id.to_string(), None, None, limit, offset) // Placeholder logic, should use proper endpoint
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get vintage dates for a series
#[tauri::command]
pub async fn fred_get_series_vintagedates(
    series_id: String,
    limit: Option<u32>,
    offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_series_vintagedates(&series_id, None, None, limit, offset)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get series in a release
#[tauri::command]
pub async fn fred_get_release_series(
    release_id: u32,
    limit: Option<u32>,
    offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_release_series(release_id, limit, offset, None, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get all categories
#[tauri::command]
pub async fn fred_get_categories(
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    // Category 0 is the root
    let result = client
        .get_category_children(0)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get category children
#[tauri::command]
pub async fn fred_get_category_children(
    category_id: u32,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_category_children(category_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get series in a category
#[tauri::command]
pub async fn fred_get_category_series(
    category_id: u32,
    limit: Option<u32>,
    offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_category_series(category_id, limit, offset, None, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get all tags
#[tauri::command]
pub async fn fred_get_tags(
    limit: Option<u32>,
    offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_all_tags(limit, offset, None, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get series for a tag
#[tauri::command]
pub async fn fred_get_tag_series(
    tag_names: String,
    limit: Option<u32>,
    offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_tags_series(&tag_names, limit, offset, None, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get related tags for a tag
#[tauri::command]
pub async fn fred_get_related_tags(
    tag_names: String,
    limit: Option<u32>,
    offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_related_tags(&tag_names, limit, offset, None, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get series tags
#[tauri::command]
pub async fn fred_get_series_tags(
    series_id: String,
    limit: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_series_tags(&series_id, limit, None, None, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get all sources
#[tauri::command]
pub async fn fred_get_sources(
    _limit: Option<u32>,
    _offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_all_sources()
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get a specific source
#[tauri::command]
pub async fn fred_get_source(
    source_id: u32,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_source(source_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get releases for a source
#[tauri::command]
pub async fn fred_get_source_releases(
    source_id: u32,
    _limit: Option<u32>,
    _offset: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_source_releases(source_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get recently updated series
#[tauri::command]
pub async fn fred_get_updates(
    limit: Option<u32>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_series_updates(None, None, limit, None)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get geospatial data for a series
#[tauri::command]
pub async fn fred_get_geo_data(
    series_id: String,
    date: Option<String>,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_geoseries_data(&series_id, date.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get categories for a series
#[tauri::command]
pub async fn fred_get_series_categories(
    series_id: String,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_series_categories(&series_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get release for a series
#[tauri::command]
pub async fn fred_get_series_release(
    series_id: String,
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let client = {
        let s = state.read().await;
        s.client.clone()
    };
    let result = client
        .get_series_release(&series_id)
        .await
        .map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(result).map_err(|e| e.to_string())?)
}

/// Get cache statistics
#[tauri::command]
pub async fn fred_get_cache_stats(
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<serde_json::Value, String> {
    let cache = {
        let s = state.read().await;
        s.cache.clone()
    };
    let metrics = cache.get_metrics().await;
    Ok(serde_json::to_value(metrics).map_err(|e| e.to_string())?)
}

/// Clear FRED cache
#[tauri::command]
pub async fn fred_clear_cache(
    state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<String, String> {
    let cache = {
        let s = state.read().await;
        s.cache.clone()
    };
    cache.clear().await;
    Ok("Cache cleared".to_string())
}
