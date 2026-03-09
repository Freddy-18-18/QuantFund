use quantfund_data::imf::{ImfClient, ImfCache};
use std::sync::Arc;
use tokio::sync::RwLock;

pub struct ImfState {
    pub client: ImfClient,
    #[allow(dead_code)]
    pub cache: Arc<ImfCache>,
}

impl ImfState {
    pub fn new(api_key: String) -> Self {
        Self {
            client: ImfClient::new(api_key),
            cache: Arc::new(ImfCache::new(1000)),
        }
    }
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct ImfConfigInput {
    pub api_key: String,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct DataflowInfo {
    pub id: String,
    pub name: String,
    pub description: String,
    pub version: String,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct AvailabilityInfo {
    pub series_count: u32,
    pub start_date: Option<String>,
    pub end_date: Option<String>,
    pub frequencies: Vec<String>,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct TimeSeriesPoint {
    pub date: String,
    pub value: Option<f64>,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct TimeSeriesData {
    pub series_key: String,
    pub observations: Vec<TimeSeriesPoint>,
}

#[tauri::command]
pub async fn imf_init(
    config: ImfConfigInput,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<String, String> {
    let mut s = state.write().await;
    *s = ImfState::new(config.api_key);
    Ok("IMF API initialized".to_string())
}

#[tauri::command]
pub async fn imf_list_datasets(
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<Vec<DataflowInfo>, String> {
    let s = state.read().await;
    let result = s.client
        .list_datasets()
        .await
        .map_err(|e| e.to_string())?;
    
    let datasets: Vec<DataflowInfo> = result
        .into_iter()
        .map(|df| DataflowInfo {
            id: df.id,
            name: df.name,
            description: df.description.unwrap_or_default(),
            version: df.version,
        })
        .collect();
    
    Ok(datasets)
}

#[tauri::command]
pub async fn imf_get_gold_price(
    start: Option<String>,
    end: Option<String>,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<TimeSeriesData, String> {
    let s = state.read().await;
    let result = s.client
        .get_gold_price(start.as_deref(), end.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    
    parse_time_series(&result, "PGold.PP0000")
}

#[tauri::command]
pub async fn imf_get_silver_price(
    start: Option<String>,
    end: Option<String>,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<TimeSeriesData, String> {
    let s = state.read().await;
    let result = s.client
        .get_silver_price(start.as_deref(), end.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    
    parse_time_series(&result, "PSilver.PP0000")
}

#[tauri::command]
pub async fn imf_get_oil_price(
    start: Option<String>,
    end: Option<String>,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<TimeSeriesData, String> {
    let s = state.read().await;
    let result = s.client
        .get_oil_price(start.as_deref(), end.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    
    parse_time_series(&result, "POilCrude.PP0000")
}

#[tauri::command]
pub async fn imf_get_commodity_prices(
    commodities: Vec<String>,
    start: Option<String>,
    end: Option<String>,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<Vec<TimeSeriesData>, String> {
    let s = state.read().await;
    let refs: Vec<&str> = commodities.iter().map(|s| s.as_str()).collect();
    
    let results = s.client
        .get_commodity_prices(&refs, start.as_deref(), end.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    
    let mut data: Vec<TimeSeriesData> = Vec::new();
    for (i, result) in results.iter().enumerate() {
        let key = commodities.get(i).cloned().unwrap_or_default();
        data.push(parse_time_series(result, &key)?);
    }
    
    Ok(data)
}

#[tauri::command]
pub async fn imf_get_ifs_data(
    indicator: String,
    country: String,
    start: Option<String>,
    end: Option<String>,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<TimeSeriesData, String> {
    let s = state.read().await;
    let result = s.client
        .get_ifs_data(&indicator, &country, start.as_deref(), end.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    
    let key = format!("{}.{}", country, indicator);
    parse_time_series(&result, &key)
}

#[tauri::command]
pub async fn imf_get_inflation(
    country: String,
    start: Option<String>,
    end: Option<String>,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<TimeSeriesData, String> {
    let s = state.read().await;
    let result = s.client
        .get_inflation(&country, start.as_deref(), end.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    
    let key = format!("{}CPI.PCPI_IX", country);
    parse_time_series(&result, &key)
}

#[tauri::command]
pub async fn imf_get_interest_rate(
    country: String,
    start: Option<String>,
    end: Option<String>,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<TimeSeriesData, String> {
    let s = state.read().await;
    let result = s.client
        .get_interest_rate(&country, start.as_deref(), end.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    
    let key = format!("{}.IR.TOTL", country);
    parse_time_series(&result, &key)
}

#[tauri::command]
pub async fn imf_check_availability(
    dataset: String,
    key: String,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<AvailabilityInfo, String> {
    let s = state.read().await;
    let result = s.client
        .check_availability(&dataset, &key)
        .await
        .map_err(|e| e.to_string())?;
    
    Ok(AvailabilityInfo {
        series_count: result.series_count as u32,
        start_date: result.start_date,
        end_date: result.end_date,
        frequencies: result.frequencies,
    })
}

#[tauri::command]
pub async fn imf_get_data(
    dataset: String,
    key: String,
    start: Option<String>,
    end: Option<String>,
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<TimeSeriesData, String> {
    let s = state.read().await;
    let result = s.client
        .get_data(&dataset, &key, start.as_deref(), end.as_deref())
        .await
        .map_err(|e| e.to_string())?;
    
    parse_time_series(&result, &key)
}

#[tauri::command]
pub async fn imf_cache_clear(
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<String, String> {
    let s = state.read().await;
    s.client.cache_clear().await;
    Ok("Cache cleared".to_string())
}

#[tauri::command]
pub async fn imf_cache_metrics(
    state: tauri::State<'_, Arc<RwLock<ImfState>>>,
) -> Result<serde_json::Value, String> {
    let s = state.read().await;
    let metrics = s.client.cache_metrics().await;
    Ok(serde_json::json!({
        "hits": metrics.hits,
        "misses": metrics.misses,
        "size": metrics.size_bytes,
        "max_size": metrics.entries_count,
    }))
}

fn parse_time_series(
    response: &quantfund_data::imf::DataResponse,
    series_key: &str,
) -> Result<TimeSeriesData, String> {
    let mut observations: Vec<TimeSeriesPoint> = Vec::new();
    
    if let Some(data_set) = response.data.data_sets.first() {
        if let Some(series) = &data_set.series {
            if let Some(series_obj) = series.as_object() {
                for (_key, value) in series_obj {
                    if let Some(obs) = value.get("observations") {
                        if let Some(obs_array) = obs.as_array() {
                            for (idx, obs_val) in obs_array.iter().enumerate() {
                                if let Some(obs_list) = obs_val.as_array() {
                                    let date = idx.to_string();
                                    let value = obs_list.first()
                                        .and_then(|v| v.as_str())
                                        .and_then(|s| s.parse::<f64>().ok());
                                    
                                    observations.push(TimeSeriesPoint {
                                        date,
                                        value,
                                    });
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    
    Ok(TimeSeriesData {
        series_key: series_key.to_string(),
        observations,
    })
}
