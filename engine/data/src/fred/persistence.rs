//! PostgreSQL persistence for FRED economic data
//!
//! This module provides database persistence for FRED economic data,
//! integrated with QuantFund's existing PostgreSQL setup.

use super::error::FredResult;
use super::models::*;
use tokio_postgres::Client;
use chrono::NaiveDate;

pub struct FredPersistence {
    client: Client,
}

impl FredPersistence {
    pub fn new(client: Client) -> Self {
        Self { client }
    }

    pub async fn init_tables(&self) -> FredResult<()> {
        self.client.execute(
            "CREATE TABLE IF NOT EXISTS fred_series (
                series_id TEXT PRIMARY KEY,
                title TEXT,
                observation_start DATE,
                observation_end DATE,
                frequency TEXT,
                units TEXT,
                notes TEXT,
                popularity INTEGER,
                last_updated TEXT
            )",
            &[],
        ).await.map_err(|e: tokio_postgres::Error| super::error::FredError::Cache(e.to_string()))?;

        self.client.execute(
            "CREATE TABLE IF NOT EXISTS fred_observations (
                id SERIAL PRIMARY KEY,
                series_id TEXT NOT NULL,
                observation_date DATE NOT NULL,
                value DOUBLE PRECISION,
                realtime_start TEXT,
                realtime_end TEXT,
                UNIQUE(series_id, observation_date)
            )",
            &[],
        ).await.map_err(|e: tokio_postgres::Error| super::error::FredError::Cache(e.to_string()))?;

        self.client.execute(
            "CREATE INDEX IF NOT EXISTS idx_fred_obs_series
             ON fred_observations(series_id, observation_date)",
            &[],
        ).await.map_err(|e: tokio_postgres::Error| super::error::FredError::Cache(e.to_string()))?;

        Ok(())
    }

    fn parse_date(s: &Option<String>) -> Option<NaiveDate> {
        s.as_ref().and_then(|d| NaiveDate::parse_from_str(d, "%Y-%m-%d").ok())
    }

    pub async fn save_series(&self, series: &Series) -> FredResult<()> {
        let obs_start = Self::parse_date(&series.observation_start);
        let obs_end = Self::parse_date(&series.observation_end);

        self.client.execute(
            "INSERT INTO fred_series (series_id, title, observation_start, observation_end,
             frequency, units, notes, popularity, last_updated)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
             ON CONFLICT(series_id) DO UPDATE SET
             title = EXCLUDED.title,
             observation_start = EXCLUDED.observation_start,
             observation_end = EXCLUDED.observation_end,
             frequency = EXCLUDED.frequency,
             units = EXCLUDED.units,
             notes = EXCLUDED.notes,
             popularity = EXCLUDED.popularity,
             last_updated = EXCLUDED.last_updated",
            &[
                &series.id,
                &series.title,
                &obs_start,
                &obs_end,
                &series.frequency,
                &series.units,
                &series.notes,
                &series.popularity,
                &series.realtime_end,
            ],
        ).await.map_err(|e: tokio_postgres::Error| super::error::FredError::Cache(e.to_string()))?;

        Ok(())
    }

    pub async fn save_observations(&self, series_id: &str, observations: &[SeriesObservation]) -> FredResult<()> {
        for obs in observations {
            if obs.is_missing() {
                continue;
            }

            let value: Option<f64> = obs.value.parse().ok();
            let obs_date = NaiveDate::parse_from_str(&obs.date, "%Y-%m-%d").ok();

            self.client.execute(
                "INSERT INTO fred_observations (series_id, observation_date, value, realtime_start, realtime_end)
                 VALUES ($1, $2, $3, $4, $5)
                 ON CONFLICT(series_id, observation_date) DO UPDATE SET
                 value = EXCLUDED.value,
                 realtime_start = EXCLUDED.realtime_start,
                 realtime_end = EXCLUDED.realtime_end",
                &[
                    &series_id,
                    &obs_date,
                    &value,
                    &obs.realtime_start,
                    &obs.realtime_end,
                ],
            ).await.map_err(|e: tokio_postgres::Error| super::error::FredError::Cache(e.to_string()))?;
        }
        Ok(())
    }

    pub async fn get_observations(
        &self,
        series_id: &str,
        start: Option<&str>,
        end: Option<&str>,
    ) -> FredResult<Vec<SeriesObservation>> {
        let query = if start.is_some() && end.is_some() {
            "SELECT observation_date, value, realtime_start, realtime_end
             FROM fred_observations
             WHERE series_id = $1 AND observation_date BETWEEN $2 AND $3
             ORDER BY observation_date"
        } else {
            "SELECT observation_date, value, realtime_start, realtime_end
             FROM fred_observations
             WHERE series_id = $1
             ORDER BY observation_date"
        };

        let rows = if let (Some(s), Some(e)) = (start, end) {
            let s_date = NaiveDate::parse_from_str(s, "%Y-%m-%d").ok();
            let e_date = NaiveDate::parse_from_str(e, "%Y-%m-%d").ok();
            self.client.query(query, &[&series_id, &s_date, &e_date]).await
        } else {
            self.client.query(query, &[&series_id]).await
        }.map_err(|e: tokio_postgres::Error| super::error::FredError::Cache(e.to_string()))?;

        let mut result = Vec::new();
        for row in rows {
            let obs_date: NaiveDate = row.get(0);
            let value: Option<f64> = row.get(1);
            result.push(SeriesObservation {
                date: obs_date.to_string(),
                value: value.map(|v| v.to_string()).unwrap_or_default(),
                realtime_start: row.get(2),
                realtime_end: row.get(3),
            });
        }

        Ok(result)
    }
}
