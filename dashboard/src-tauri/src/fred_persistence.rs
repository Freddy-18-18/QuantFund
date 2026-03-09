use anyhow::Result;
use chrono::NaiveDate;
use quantfund_data::fred::{FredClient, FredPersistence, Series, SeriesObservation, SeriesObservationsResponse};
use serde::{Deserialize, Serialize};
use tokio_postgres::Client;

use crate::database::{connect, DbConfig};

pub struct FredPersistenceState {
    pub persistence: FredPersistence,
    pub client: Client,
}

impl FredPersistenceState {
    pub fn new(persistence: FredPersistence, client: Client) -> Self {
        Self { persistence, client }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncStatus {
    pub series_id: String,
    pub has_local_data: bool,
    pub local_last_date: Option<String>,
    pub remote_last_date: Option<String>,
    pub needs_update: bool,
    pub new_observations: i32,
}

#[tauri::command]
pub async fn fred_persistence_init(
    config: tauri::State<'_, DbConfig>,
) -> Result<String, String> {
    let db_config = DbConfig {
        host: config.host.clone(),
        port: config.port,
        user: config.user.clone(),
        password: config.password.clone(),
        dbname: config.dbname.clone(),
    };

    let client = connect(&db_config)
        .await
        .map_err(|e| format!("Failed to connect to database: {}", e))?;

    let persistence = FredPersistence::new(client);
    persistence
        .init_tables()
        .await
        .map_err(|e| format!("Failed to initialize tables: {}", e))?;

    tracing::info!("FRED persistence tables initialized successfully");
    Ok("FRED persistence tables initialized successfully".to_string())
}

#[tauri::command]
pub async fn fred_save_series(
    series_id: String,
    series_data: serde_json::Value,
    config: tauri::State<'_, DbConfig>,
) -> Result<String, String> {
    let db_config = DbConfig {
        host: config.host.clone(),
        port: config.port,
        user: config.user.clone(),
        password: config.password.clone(),
        dbname: config.dbname.clone(),
    };

    let client = connect(&db_config)
        .await
        .map_err(|e| format!("Failed to connect to database: {}", e))?;

    let persistence = FredPersistence::new(client);

    let series: Series = serde_json::from_value(series_data)
        .map_err(|e| format!("Failed to parse series data: {}", e))?;

    persistence
        .save_series(&series)
        .await
        .map_err(|e| format!("Failed to save series: {}", e))?;

    tracing::info!("Saved series {} to PostgreSQL", series_id);
    Ok(format!("Series {} saved successfully", series_id))
}

#[tauri::command]
pub async fn fred_save_observations(
    series_id: String,
    observations: Vec<SeriesObservation>,
    config: tauri::State<'_, DbConfig>,
) -> Result<String, String> {
    let db_config = DbConfig {
        host: config.host.clone(),
        port: config.port,
        user: config.user.clone(),
        password: config.password.clone(),
        dbname: config.dbname.clone(),
    };

    let client = connect(&db_config)
        .await
        .map_err(|e| format!("Failed to connect to database: {}", e))?;

    let persistence = FredPersistence::new(client);

    persistence
        .save_observations(&series_id, &observations)
        .await
        .map_err(|e| format!("Failed to save observations: {}", e))?;

    tracing::info!(
        "Saved {} observations for series {} to PostgreSQL",
        observations.len(),
        series_id
    );
    Ok(format!(
        "Saved {} observations for series {}",
        observations.len(),
        series_id
    ))
}

#[tauri::command]
pub async fn fred_get_cached_observations(
    series_id: String,
    start_date: Option<String>,
    end_date: Option<String>,
    config: tauri::State<'_, DbConfig>,
) -> Result<serde_json::Value, String> {
    let db_config = DbConfig {
        host: config.host.clone(),
        port: config.port,
        user: config.user.clone(),
        password: config.password.clone(),
        dbname: config.dbname.clone(),
    };

    let client = connect(&db_config)
        .await
        .map_err(|e| format!("Failed to connect to database: {}", e))?;

    let persistence = FredPersistence::new(client);

    let start = start_date.as_deref();
    let end = end_date.as_deref();

    let observations = persistence
        .get_observations(&series_id, start, end)
        .await
        .map_err(|e| format!("Failed to get cached observations: {}", e))?;

    let response = SeriesObservationsResponse {
        count: observations.len() as i32,
        observations,
        realtime_start: String::new(),
        realtime_end: String::new(),
    };

    Ok(serde_json::to_value(response).map_err(|e| e.to_string())?)
}

#[tauri::command]
pub async fn fred_check_for_updates(
    series_id: String,
    api_key: String,
    config: tauri::State<'_, DbConfig>,
) -> Result<SyncStatus, String> {
    let db_config = DbConfig {
        host: config.host.clone(),
        port: config.port,
        user: config.user.clone(),
        password: config.password.clone(),
        dbname: config.dbname.clone(),
    };

    let client = connect(&db_config)
        .await
        .map_err(|e| format!("Failed to connect to database: {}", e))?;

    let persistence = FredPersistence::new(client);

    let local_observations = persistence
        .get_observations(&series_id, None, None)
        .await
        .map_err(|e| format!("Failed to get local observations: {}", e))?;

    let has_local_data = !local_observations.is_empty();
    let local_last_date = local_observations.last().map(|o| o.date.clone());

    let fred_client = FredClient::new(api_key);
    let series_info = fred_client
        .get_series(&series_id)
        .await
        .map_err(|e| format!("Failed to fetch series info: {}", e))?;

    let remote_last_date = series_info.observation_end.clone();

    let needs_update = if let (Some(local), Some(remote)) = (&local_last_date, &remote_last_date) {
        local < remote
    } else {
        !has_local_data
    };

    let new_observations = if needs_update {
        if let (Some(start), Some(end)) = (&local_last_date, &remote_last_date) {
            if start < end {
                let observations = fred_client
                    .get_series_observations(&series_id, None, None, Some(start), Some(end), None, None, None, None)
                    .await
                    .map_err(|e| format!("Failed to fetch new observations: {}", e))?;
                observations.observations.len() as i32
            } else {
                0
            }
        } else {
            0
        }
    } else {
        0
    };

    Ok(SyncStatus {
        series_id,
        has_local_data,
        local_last_date,
        remote_last_date,
        needs_update,
        new_observations,
    })
}

#[tauri::command]
pub async fn fred_sync_series(
    series_id: String,
    api_key: String,
    config: tauri::State<'_, DbConfig>,
) -> Result<serde_json::Value, String> {
    let db_config = DbConfig {
        host: config.host.clone(),
        port: config.port,
        user: config.user.clone(),
        password: config.password.clone(),
        dbname: config.dbname.clone(),
    };

    let client = connect(&db_config)
        .await
        .map_err(|e| format!("Failed to connect to database: {}", e))?;

    let persistence = FredPersistence::new(client);

    let local_observations = persistence
        .get_observations(&series_id, None, None)
        .await
        .map_err(|e| format!("Failed to get local observations: {}", e))?;

    let has_local_data = !local_observations.is_empty();
    let local_last_date = local_observations.last().map(|o| o.date.clone());

    let fred_client = FredClient::new(api_key.clone());
    
    let series_info = fred_client
        .get_series(&series_id)
        .await
        .map_err(|e| format!("Failed to fetch series info: {}", e))?;

    persistence
        .save_series(&series_info)
        .await
        .map_err(|e| format!("Failed to save series metadata: {}", e))?;

    let observations_to_fetch = if has_local_data {
        if let Some(start_date) = &local_last_date {
            let next_day = NaiveDate::parse_from_str(start_date, "%Y-%m-%d")
                .map_err(|e| format!("Failed to parse date: {}", e))?
                .succ_opt()
                .map(|d| d.to_string());

            if let Some(start) = next_day {
                Some((start, "latest".to_string()))
            } else {
                None
            }
        } else {
            None
        }
    } else {
        None
    };

    let new_observations: Vec<SeriesObservation> = if let Some((start, end)) = observations_to_fetch {
        let response = fred_client
            .get_series_observations(&series_id, None, None, Some(&start), Some(&end), None, None, None, None)
            .await
            .map_err(|e| format!("Failed to fetch observations: {}", e))?;
        response.observations
    } else {
        let response = fred_client
            .get_series_observations(&series_id, None, None, None, None, None, None, None, None)
            .await
            .map_err(|e| format!("Failed to fetch all observations: {}", e))?;
        response.observations
    };

    let valid_observations: Vec<SeriesObservation> = new_observations
        .into_iter()
        .filter(|o| !o.is_missing())
        .collect();

    if !valid_observations.is_empty() {
        persistence
            .save_observations(&series_id, &valid_observations)
            .await
            .map_err(|e| format!("Failed to save new observations: {}", e))?;

        tracing::info!(
            "Synced {} new observations for series {}",
            valid_observations.len(),
            series_id
        );
    }

    let final_observations = persistence
        .get_observations(&series_id, None, None)
        .await
        .map_err(|e| format!("Failed to get final observations: {}", e))?;

    let response = SeriesObservationsResponse {
        count: final_observations.len() as i32,
        observations: final_observations,
        realtime_start: series_info.realtime_start,
        realtime_end: series_info.realtime_end,
    };

    Ok(serde_json::json!({
        "status": "synced",
        "series_id": series_id,
        "total_observations": response.count,
        "new_observations_saved": valid_observations.len(),
        "data": response
    }))
}
