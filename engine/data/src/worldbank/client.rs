//! World Bank API client

use super::error::{WbError, WbResult};
use super::models::*;
use reqwest::Client;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::Semaphore;
use tokio::time::{sleep, Duration};

const BASE_URL: &str = "https://api.worldbank.org/v2";
const MAX_REQUESTS_PER_SECOND: usize = 1;
const REQUEST_DELAY_MS: u64 = 1000;
const MAX_RETRIES: u32 = 3;

pub struct WorldBankClient {
    client: Client,
    rate_limiter: Arc<RateLimiter>,
}

struct RateLimiter {
    semaphore: Semaphore,
    last_request: AtomicU64,
}

impl RateLimiter {
    fn new() -> Self {
        Self {
            semaphore: Semaphore::new(MAX_REQUESTS_PER_SECOND),
            last_request: AtomicU64::new(0),
        }
    }

    async fn acquire(&self) {
        let permit = self.semaphore.acquire().await.expect("Semaphore closed");
        permit.forget();

        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        let last = self.last_request.load(Ordering::Relaxed);
        if now.saturating_sub(last) < REQUEST_DELAY_MS {
            sleep(Duration::from_millis(REQUEST_DELAY_MS - now.saturating_sub(last))).await;
        }

        let current_time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        self.last_request.store(current_time, Ordering::Relaxed);
    }
}

impl WorldBankClient {
    pub fn new() -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .expect("Failed to create HTTP client");

        Self {
            client,
            rate_limiter: Arc::new(RateLimiter::new()),
        }
    }

    async fn rate_limit_wait(&self) {
        self.rate_limiter.acquire().await;
    }

    async fn request_with_retry<T: serde::de::DeserializeOwned>(
        &self,
        endpoint: &str,
        params: &HashMap<String, String>,
    ) -> WbResult<T> {
        let mut attempt = 0;

        loop {
            self.rate_limit_wait().await;

            let url = format!("{}{}", BASE_URL, endpoint);
            let query_params = params.clone();

            if !query_params.is_empty() {
                let query_string: Vec<String> = query_params
                    .iter()
                    .map(|(k, v)| format!("{}={}", k, v))
                    .collect();
                let full_url = format!("{}?{}", url, query_string.join("&"));

                match self.client.get(&full_url).send().await {
                    Ok(resp) if resp.status() == 429 => {
                        attempt += 1;
                        if attempt > MAX_RETRIES {
                            return Err(WbError::RateLimited);
                        }
                        sleep(Duration::from_millis(2u64.pow(attempt) * 500)).await;
                        continue;
                    }
                    Ok(resp) => {
                        if resp.status().is_success() {
                            return resp.json().await.map_err(WbError::from);
                        } else {
                            let status = resp.status().as_u16();
                            let msg = resp.text().await.unwrap_or_default();
                            return Err(WbError::from_response(status, msg));
                        }
                    }
                    Err(e) => return Err(WbError::from(e)),
                }
            } else {
                match self.client.get(&url).send().await {
                    Ok(resp) if resp.status() == 429 => {
                        attempt += 1;
                        if attempt > MAX_RETRIES {
                            return Err(WbError::RateLimited);
                        }
                        sleep(Duration::from_millis(2u64.pow(attempt) * 500)).await;
                        continue;
                    }
                    Ok(resp) => {
                        if resp.status().is_success() {
                            return resp.json().await.map_err(WbError::from);
                        } else {
                            let status = resp.status().as_u16();
                            let msg = resp.text().await.unwrap_or_default();
                            return Err(WbError::from_response(status, msg));
                        }
                    }
                    Err(e) => return Err(WbError::from(e)),
                }
            }
        }
    }

    // ==================== Countries ====================

    /// Get all countries
    pub async fn get_countries(
        &self,
        page: Option<u32>,
        per_page: Option<u32>,
        format: Option<&str>,
    ) -> WbResult<CountriesResponse> {
        let mut params = HashMap::new();
        if let Some(p) = page {
            params.insert("page".to_string(), p.to_string());
        }
        if let Some(p) = per_page {
            params.insert("per_page".to_string(), p.to_string());
        }
        if let Some(f) = format {
            params.insert("format".to_string(), f.to_string());
        }

        self.request_with_retry("/country", &params).await
    }

    /// Get country by ISO code
    pub async fn get_country(&self, country_code: &str) -> WbResult<CountriesResponse> {
        let params = HashMap::new();
        self.request_with_retry(&format!("/country/{}", country_code), &params).await
    }

    // ==================== Indicators ====================

    /// Get all indicators
    pub async fn get_indicators(
        &self,
        page: Option<u32>,
        per_page: Option<u32>,
        source: Option<u32>,
    ) -> WbResult<IndicatorsResponse> {
        let mut params = HashMap::new();
        if let Some(p) = page {
            params.insert("page".to_string(), p.to_string());
        }
        if let Some(p) = per_page {
            params.insert("per_page".to_string(), p.to_string());
        }
        if let Some(s) = source {
            params.insert("source".to_string(), s.to_string());
        }

        self.request_with_retry("/indicator", &params).await
    }

    /// Search indicators by name
    pub async fn search_indicators(&self, query: &str) -> WbResult<IndicatorsResponse> {
        let params = HashMap::new();
        self.request_with_retry(&format!("/indicator?search={}", query), &params).await
    }

    /// Get indicator metadata
    pub async fn get_indicator(&self, indicator_id: &str) -> WbResult<IndicatorsResponse> {
        let params = HashMap::new();
        self.request_with_retry(&format!("/indicator/{}", indicator_id), &params).await
    }

    // ==================== Indicator Data ====================

    /// Get indicator data for a country
    pub async fn get_indicator_data(
        &self,
        indicator: &str,
        country: &str,
        date_start: Option<&str>,
        date_end: Option<&str>,
        per_page: Option<u32>,
        page: Option<u32>,
    ) -> WbResult<IndicatorDataResponse> {
        let mut params = HashMap::new();
        if let Some(d) = date_start {
            params.insert(
                "date".to_string(),
                format!("{}:{}", d, date_end.unwrap_or(d)),
            );
        }
        if let Some(p) = per_page {
            params.insert("per_page".to_string(), p.to_string());
        }
        if let Some(p) = page {
            params.insert("page".to_string(), p.to_string());
        }

        self.request_with_retry(
            &format!("/country/{}/indicator/{}", country, indicator),
            &params,
        )
        .await
    }

    /// Get indicator data for all countries
    pub async fn get_indicator_all_countries(
        &self,
        indicator: &str,
        date_start: Option<&str>,
        date_end: Option<&str>,
        per_page: Option<u32>,
        page: Option<u32>,
    ) -> WbResult<IndicatorDataResponse> {
        let mut params = HashMap::new();
        if let Some(d) = date_start {
            params.insert(
                "date".to_string(),
                format!("{}:{}", d, date_end.unwrap_or(d)),
            );
        }
        if let Some(p) = per_page {
            params.insert("per_page".to_string(), p.to_string());
        }
        if let Some(p) = page {
            params.insert("page".to_string(), p.to_string());
        }

        self.request_with_retry(&format!("/country/all/indicator/{}", indicator), &params).await
    }

    // ==================== Topics ====================

    /// Get all topics
    pub async fn get_topics(&self) -> WbResult<TopicsResponse> {
        let params = HashMap::new();
        self.request_with_retry("/topic", &params).await
    }

    /// Get indicators by topic
    pub async fn get_topic_indicators(&self, topic_id: &str) -> WbResult<IndicatorsResponse> {
        let params = HashMap::new();
        self.request_with_retry(&format!("/topic/{}/indicator", topic_id), &params).await
    }

    // ==================== Sources ====================

    /// Get all data sources
    pub async fn get_sources(&self) -> WbResult<serde_json::Value> {
        let params = HashMap::new();
        self.request_with_retry("/source", &params).await
    }
}

impl Default for WorldBankClient {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_client_creation() {
        let _client = WorldBankClient::new();
    }
}
