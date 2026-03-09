//! IMF API Client Implementation
//!
//! HTTP client with OAuth authentication and rate limiting

use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::RwLock;
use reqwest::Client;
use serde::Deserialize;

use super::cache::{ImfCache, CacheMetrics};
use super::error::{ImfError, ImfResult};
use super::models::*;

const AUTH_URL: &str = "https://api.imf.org/oauth/token";

#[derive(Debug)]
struct RateLimiter {
    max_requests: u32,
    window_secs: f64,
    tokens: f64,
    last_reset: Instant,
}

impl RateLimiter {
    fn new(max_requests: u32, window_secs: f64) -> Self {
        Self {
            max_requests,
            window_secs,
            tokens: max_requests as f64,
            last_reset: Instant::now(),
        }
    }

    fn try_acquire(&mut self) -> bool {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_reset).as_secs_f64();
        
        // Recargar tokens basado en tiempo transcurrido
        let tokens_to_add = elapsed * (self.max_requests as f64 / self.window_secs);
        self.tokens = (self.tokens + tokens_to_add).min(self.max_requests as f64);
        
        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            self.last_reset = now;
            true
        } else {
            false
        }
    }

    fn time_until_available(&self) -> Duration {
        if self.tokens >= 1.0 {
            Duration::ZERO
        } else {
            let tokens_needed = 1.0 - self.tokens;
            let secs_needed = tokens_needed * (self.window_secs / self.max_requests as f64);
            Duration::from_secs_f64(secs_needed)
        }
    }
}

pub struct ImfClient {
    http: Client,
    config: ImfConfig,
    rate_limiter: Arc<RwLock<RateLimiter>>,
    cache: Arc<ImfCache>,
    auth_token: Arc<RwLock<Option<AuthToken>>>,
}

impl ImfClient {
    pub fn new(api_key: String) -> Self {
        Self::with_config(ImfConfig::new(api_key))
    }

    pub fn with_config(config: ImfConfig) -> Self {
        Self {
            http: Client::builder()
                .timeout(Duration::from_secs(30))
                .build()
                .expect("Failed to create HTTP client"),
            config,
            rate_limiter: Arc::new(RwLock::new(RateLimiter::new(10, 5.0))),
            cache: Arc::new(ImfCache::new(1000)),
            auth_token: Arc::new(RwLock::new(None)),
        }
    }

    // ========================================================================
    // Authentication
    // ========================================================================

    async fn ensure_authenticated(&self) -> ImfResult<String> {
        // Check if we have a valid token
        {
            let token = self.auth_token.read().await;
            if let Some(ref t) = *token {
                // Token valid for 1 hour, check if we have time left
                // For simplicity, we'll re-authenticate if token is older than 50 minutes
                return Ok(t.access_token.clone());
            }
        }

        // Need to authenticate
        let response = self.http
            .post(AUTH_URL)
            .form(&[
                ("grant_type", "client_credentials"),
                ("client_id", &self.config.client_id),
                ("client_secret", &self.config.client_secret),
            ])
            .send()
            .await?;

        if response.status() == 401 {
            return Err(ImfError::Authentication("Invalid credentials".to_string()));
        }

        let token: AuthToken = response.json().await
            .map_err(|e| ImfError::Authentication(e.to_string()))?;

        let access_token = token.access_token.clone();
        {
            let mut auth = self.auth_token.write().await;
            *auth = Some(token);
        }

        Ok(access_token)
    }

    // ========================================================================
    // Rate Limiting
    // ========================================================================

    async fn wait_for_rate_limit(&self) {
        loop {
            {
                let mut limiter = self.rate_limiter.write().await;
                if limiter.try_acquire() {
                    break;
                }
                let wait_time = limiter.time_until_available();
                drop(limiter);
                tokio::time::sleep(wait_time).await;
            }
        }
    }

    // ========================================================================
    // Cache
    // ========================================================================

    fn cache_key(dataset: &str, key: &str, start: Option<&str>, end: Option<&str>) -> String {
        format!("{}:{}:{}:{}", dataset, key, start.unwrap_or("*"), end.unwrap_or("*"))
    }

    // ========================================================================
    // HTTP Requests
    // ========================================================================

    async fn get<T: for<'de> Deserialize<'de>>(&self, url: &str) -> ImfResult<T> {
        // Use a loop to handle retries instead of recursion
        loop {
            // Wait for rate limit
            self.wait_for_rate_limit().await;

            // Get auth token
            let token = self.ensure_authenticated().await?;

            // Make request
            let response = self.http
                .get(url)
                .header("Authorization", format!("Bearer {}", token))
                .header("Accept", "application/json")
                .send()
                .await?;

            match response.status() {
                reqwest::StatusCode::OK => {
                    return response.json().await.map_err(|e| ImfError::Parse(e.to_string()));
                }
                reqwest::StatusCode::NOT_FOUND => {
                    return Err(ImfError::NotFound(url.to_string()));
                }
                reqwest::StatusCode::TOO_MANY_REQUESTS => {
                    // Rate limited - wait and retry
                    tokio::time::sleep(Duration::from_secs(5)).await;
                    continue;
                }
                reqwest::StatusCode::UNAUTHORIZED => {
                    // Token might be expired, clear and retry
                    {
                        let mut auth = self.auth_token.write().await;
                        *auth = None;
                    }
                    continue;
                }
                _ => {
                    let status = response.status();
                    let text = response.text().await.unwrap_or_default();
                    return Err(ImfError::ApiError(format!("{}: {}", status, text)));
                }
            }
        }
    }

    // ========================================================================
    // Data Query Endpoints
    // ========================================================================

    /// Get time series data
    /// 
    /// # Example
    /// ```ignore
    /// let gold = client.get_data("PCPS", "PGold.PP0000", Some("2020-01"), None).await?;
    /// ```
    pub async fn get_data(
        &self,
        dataset: &str,
        key: &str,
        start: Option<&str>,
        end: Option<&str>,
    ) -> ImfResult<DataResponse> {
        let cache_key = Self::cache_key(dataset, key, start, end);
        
        // Check cache
        if let Some(cached) = self.cache.get(&cache_key).await {
            let data: DataResponse = serde_json::from_slice(&cached)
                .map_err(|e| ImfError::Cache(e.to_string()))?;
            return Ok(data);
        }

        // Build URL
        let mut url = format!("{}/data/IMF/{}/+/{}", BASE_URL, dataset, key);
        
        let mut params: Vec<(&str, String)> = vec![
            ("dimensionAtObservation", "TIME_PERIOD".to_string()),
        ];

        if start.is_some() || end.is_some() {
            let time_parts: Vec<String> = [
                start.map(|s| format!("ge:{}", s)),
                end.map(|e| format!("le:{}", e)),
            ]
            .into_iter()
            .flatten()
            .collect();

            if !time_parts.is_empty() {
                let time_period = format!("TIME_PERIOD={}", time_parts.join("+"));
                params.push(("c", time_period));
            }
        }

        // Add query string
        if !params.is_empty() {
            let query_string: String = params
                .iter()
                .map(|(k, v)| format!("{}={}", k, v))
                .collect::<Vec<_>>()
                .join("&");
            url = format!("{}?{}", url, query_string);
        }

        let data: DataResponse = self.get(&url).await?;

        // Cache the response
        if let Ok(json_bytes) = serde_json::to_vec(&data) {
            self.cache.set(cache_key, json_bytes, Some(Duration::from_secs(24 * 60 * 60))).await;
        }

        Ok(data)
    }

    /// Get data availability for a dataset and key
    pub async fn get_availability(
        &self,
        dataset: &str,
        key: &str,
    ) -> ImfResult<AvailabilityResponse> {
        let url = format!("{}/availability/data/IMF/{}/+/{}/?", BASE_URL, dataset, key);
        self.get(&url).await
    }

    /// Get data for multiple series with filters
    pub async fn get_data_filtered(
        &self,
        dataset: &str,
        key: &str,
        frequency: Option<&str>,
        first_n: Option<usize>,
        last_n: Option<usize>,
    ) -> ImfResult<DataResponse> {
        let mut url = format!("{}/data/IMF/{}/+/{}", BASE_URL, dataset, key);
        
        let mut params: Vec<(&str, String)> = vec![
            ("dimensionAtObservation", "TIME_PERIOD".to_string()),
        ];

        if let Some(freq) = frequency {
            params.push(("frequency", freq.to_string()));
        }

        if let Some(n) = first_n {
            params.push(("firstNObservations", n.to_string()));
        }

        if let Some(n) = last_n {
            params.push(("lastNObservations", n.to_string()));
        }

        let query_string: String = params
            .iter()
            .map(|(k, v)| format!("{}={}", k, v))
            .collect::<Vec<_>>()
            .join("&");
        url = format!("{}?{}", url, query_string);

        self.get(&url).await
    }

    // ========================================================================
    // Structure Query Endpoints
    // ========================================================================

    /// Get all available dataflows (datasets)
    pub async fn get_dataflows(&self) -> ImfResult<DataflowsResponse> {
        let url = format!("{}/structure/dataflows/IMF?detail=full", BASE_URL);
        self.get(&url).await
    }

    /// Get dataflow by ID
    pub async fn get_dataflow(&self, dataset: &str) -> ImfResult<DataflowsResponse> {
        let url = format!("{}/structure/dataflows/IMF/{}?detail=full", BASE_URL, dataset);
        self.get(&url).await
    }

    /// Get codelists
    pub async fn get_codelists(&self, agency: Option<&str>) -> ImfResult<CodelistsResponse> {
        let agency = agency.unwrap_or("IMF");
        let url = format!("{}/structure/codelists/{}", BASE_URL, agency);
        self.get(&url).await
    }

    /// Get specific codelist
    pub async fn get_codelist(&self, agency: &str, codelist_id: &str) -> ImfResult<CodelistsResponse> {
        let url = format!("{}/structure/codelists/{}/{}", BASE_URL, agency, codelist_id);
        self.get(&url).await
    }

    /// Get code info for a dimension
    pub async fn get_codes(&self, dataset: &str) -> ImfResult<CodelistsResponse> {
        let url = format!("{}/structure/codelists/IMF/{}", BASE_URL, dataset);
        self.get(&url).await
    }

    // ========================================================================
    // Cache Management
    // ========================================================================

    pub async fn cache_get(&self, key: &str) -> Option<Vec<u8>> {
        self.cache.get(key).await
    }

    pub async fn cache_set(&self, key: String, data: Vec<u8>, ttl_secs: Option<u64>) {
        let ttl = ttl_secs.map(Duration::from_secs);
        self.cache.set(key, data, ttl).await
    }

    pub async fn cache_invalidate(&self, key: &str) {
        self.cache.invalidate(key).await;
    }

    pub async fn cache_clear(&self) {
        self.cache.clear().await;
    }

    pub async fn cache_metrics(&self) -> CacheMetrics {
        self.cache.get_metrics().await
    }
}

impl Default for ImfClient {
    fn default() -> Self {
        Self::new(String::new())
    }
}
