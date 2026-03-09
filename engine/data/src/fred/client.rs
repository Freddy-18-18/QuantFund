//! FRED API Client for QuantFund Trading Platform
//!
//! Provides async access to the Federal Reserve Economic Data (FRED) API
//! with rate limiting, retry logic, and comprehensive endpoint coverage.

use super::error::{FredError, FredResult};
use super::models::*;
use async_trait::async_trait;
use reqwest::Client;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::time::{sleep, Duration};

const BASE_URL: &str = "https://api.stlouisfed.org/fred";
const REQUEST_DELAY_MS: u64 = 500;
const MAX_RETRIES: u32 = 3;
const INITIAL_BACKOFF_MS: u64 = 1000;

#[derive(Clone)]
pub struct FredClient {
    client: Client,
    api_key: String,
    rate_limiter: Arc<RateLimiter>,
}

struct RateLimiter {
    last_request: AtomicU64,
}

impl RateLimiter {
    fn new() -> Self {
        Self {
            last_request: AtomicU64::new(0),
        }
    }

    async fn acquire(&self) {
        loop {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_millis() as u64;

            let last = self.last_request.load(Ordering::Acquire);
            let elapsed = now.saturating_sub(last);

            if elapsed < REQUEST_DELAY_MS {
                sleep(Duration::from_millis(REQUEST_DELAY_MS - elapsed)).await;
                continue;
            }

            // Try to update last_request. If someone else did it, loop again.
            if self.last_request
                .compare_exchange(last, now, Ordering::SeqCst, Ordering::Relaxed)
                .is_ok()
            {
                break;
            }
        }
    }
}

impl FredClient {
    pub fn new(api_key: String) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .expect("Failed to create HTTP client");

        Self {
            client,
            api_key,
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
    ) -> FredResult<T> {
        let mut attempt = 0;

        loop {
            self.rate_limit_wait().await;

            let mut url = format!("{}{}", BASE_URL, endpoint);
            let mut query_params = params.clone();
            query_params.insert("api_key".to_string(), self.api_key.clone());
            query_params.insert("file_type".to_string(), "json".to_string());

            if !query_params.is_empty() {
                let query_string: Vec<String> = query_params
                    .iter()
                    .map(|(k, v)| format!("{}={}", k, v))
                    .collect();
                url = format!("{}?{}", url, query_string.join("&"));
            }

            match self.client.get(&url).send().await {
                Ok(response) => {
                    let status = response.status();
                    let body = response.text().await.unwrap_or_default();

                    if status.is_success() {
                        match serde_json::from_str(&body) {
                            Ok(data) => return Ok(data),
                            Err(e) => {
                                return Err(FredError::Parse(format!(
                                    "Failed to parse response: {} - Body: {}",
                                    e, body
                                )));
                            }
                        }
                    } else if status.as_u16() == 429 {
                        if attempt < MAX_RETRIES {
                            let backoff =
                                INITIAL_BACKOFF_MS * 2u64.pow(attempt) + (rand_u64() % 500);
                            sleep(Duration::from_millis(backoff)).await;
                            attempt += 1;
                            continue;
                        } else {
                            return Err(FredError::RateLimited);
                        }
                    } else if status.as_u16() == 401 {
                        return Err(FredError::Authentication);
                    } else if status.as_u16() == 404 {
                        return Err(FredError::NotFound(body));
                    } else if status.is_server_error() {
                        if attempt < MAX_RETRIES {
                            let backoff =
                                INITIAL_BACKOFF_MS * 2u64.pow(attempt) + (rand_u64() % 500);
                            sleep(Duration::from_millis(backoff)).await;
                            attempt += 1;
                            continue;
                        } else {
                            return Err(FredError::ServerError(body));
                        }
                    } else {
                        return Err(FredError::from_response(
                            status.as_u16(),
                            body,
                        ));
                    }
                }
                Err(e) => {
                    if attempt < MAX_RETRIES {
                        let backoff =
                            INITIAL_BACKOFF_MS * 2u64.pow(attempt) + (rand_u64() % 500);
                        sleep(Duration::from_millis(backoff)).await;
                        attempt += 1;
                        continue;
                    } else {
                        return Err(FredError::Request(e));
                    }
                }
            }
        }
    }

    // ==================== CATEGORIES ====================

    pub async fn get_category(&self, category_id: u32) -> FredResult<Category> {
        let mut params = HashMap::new();
        params.insert("category_id".to_string(), category_id.to_string());
        let response: CategoryInfo = self
            .request_with_retry("/category", &params)
            .await?;
        response.first().ok_or_else(|| FredError::NotFound("Category not found".to_string()))
    }

    pub async fn get_category_children(&self, category_id: u32) -> FredResult<Vec<Category>> {
        let mut params = HashMap::new();
        params.insert("category_id".to_string(), category_id.to_string());
        let response: CategoryInfo = self
            .request_with_retry("/category/children", &params)
            .await?;
        Ok(response.categories)
    }

    pub async fn get_category_related(&self, category_id: u32) -> FredResult<Vec<Category>> {
        let mut params = HashMap::new();
        params.insert("category_id".to_string(), category_id.to_string());
        let response: CategoryInfo = self
            .request_with_retry("/category/related", &params)
            .await?;
        Ok(response.categories)
    }

    pub async fn get_category_series(
        &self,
        category_id: u32,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<CategorySeriesResponse> {
        let mut params = HashMap::new();
        params.insert("category_id".to_string(), category_id.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/category/series", &params).await
    }

    pub async fn get_category_tags(
        &self,
        category_id: u32,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<CategoryTagsResponse> {
        let mut params = HashMap::new();
        params.insert("category_id".to_string(), category_id.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/category/tags", &params).await
    }

    pub async fn get_category_related_tags(
        &self,
        category_id: u32,
        tag_names: &str,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<RelatedTagsResponse> {
        let mut params = HashMap::new();
        params.insert("category_id".to_string(), category_id.to_string());
        params.insert("tag_names".to_string(), tag_names.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/category/related_tags", &params).await
    }

    // ==================== RELEASES ====================

    pub async fn get_all_releases(
        &self,
        limit: Option<u32>,
        offset: Option<u32>,
    ) -> FredResult<ReleasesResponse> {
        let mut params = HashMap::new();
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        self.request_with_retry("/releases", &params).await
    }

    pub async fn get_releases_dates(
        &self,
        release_id: Option<u32>,
        realtime_start: Option<&str>,
        realtime_end: Option<&str>,
    ) -> FredResult<ReleaseDatesResponse> {
        let mut params = HashMap::new();
        if let Some(rid) = release_id {
            params.insert("release_id".to_string(), rid.to_string());
        }
        if let Some(rs) = realtime_start {
            params.insert("realtime_start".to_string(), rs.to_string());
        }
        if let Some(re) = realtime_end {
            params.insert("realtime_end".to_string(), re.to_string());
        }
        self.request_with_retry("/releases/dates", &params).await
    }

    pub async fn get_release(&self, release_id: u32) -> FredResult<Release> {
        let mut params = HashMap::new();
        params.insert("release_id".to_string(), release_id.to_string());
        let response: ReleaseInfoResponse = self
            .request_with_retry("/release", &params)
            .await?;
        response.releases.into_iter().next().ok_or_else(|| FredError::NotFound("Release not found".to_string()))
    }

    pub async fn get_release_dates(
        &self,
        release_id: u32,
        realtime_start: Option<&str>,
        realtime_end: Option<&str>,
        limit: Option<u32>,
        offset: Option<u32>,
    ) -> FredResult<ReleaseDatesResponse> {
        let mut params = HashMap::new();
        params.insert("release_id".to_string(), release_id.to_string());
        if let Some(rs) = realtime_start {
            params.insert("realtime_start".to_string(), rs.to_string());
        }
        if let Some(re) = realtime_end {
            params.insert("realtime_end".to_string(), re.to_string());
        }
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        self.request_with_retry("/release/dates", &params).await
    }

    pub async fn get_release_series(
        &self,
        release_id: u32,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<ReleaseSeriesResponse> {
        let mut params = HashMap::new();
        params.insert("release_id".to_string(), release_id.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/release/series", &params).await
    }

    pub async fn get_release_sources(&self, release_id: u32) -> FredResult<SourcesResponse> {
        let mut params = HashMap::new();
        params.insert("release_id".to_string(), release_id.to_string());
        self.request_with_retry("/release/sources", &params).await
    }

    pub async fn get_release_tags(
        &self,
        release_id: u32,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<ReleaseTagsResponse> {
        let mut params = HashMap::new();
        params.insert("release_id".to_string(), release_id.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/release/tags", &params).await
    }

    pub async fn get_release_related_tags(
        &self,
        release_id: u32,
        tag_names: &str,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<RelatedTagsResponse> {
        let mut params = HashMap::new();
        params.insert("release_id".to_string(), release_id.to_string());
        params.insert("tag_names".to_string(), tag_names.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/release/related_tags", &params).await
    }

    pub async fn get_release_tables(&self, release_id: u32) -> FredResult<serde_json::Value> {
        let mut params = HashMap::new();
        params.insert("release_id".to_string(), release_id.to_string());
        self.request_with_retry("/release/tables", &params).await
    }

    // ==================== SERIES ====================

    pub async fn get_series(&self, series_id: &str) -> FredResult<Series> {
        let mut params = HashMap::new();
        params.insert("series_id".to_string(), series_id.to_string());
        let response: SeriesInfoResponse = self
            .request_with_retry("/series", &params)
            .await?;
        response.seriess.into_iter().next().ok_or_else(|| FredError::NotFound("Series not found".to_string()))
    }

    pub async fn get_series_categories(&self, series_id: &str) -> FredResult<Category> {
        let mut params = HashMap::new();
        params.insert("series_id".to_string(), series_id.to_string());
        let response: CategoryInfo = self
            .request_with_retry("/series/categories", &params)
            .await?;
        response.first().ok_or_else(|| FredError::NotFound("Category not found".to_string()))
    }

    pub async fn get_series_observations(
        &self,
        series_id: &str,
        realtime_start: Option<&str>,
        realtime_end: Option<&str>,
        observation_start: Option<&str>,
        observation_end: Option<&str>,
        frequency: Option<&str>,
        aggregation_method: Option<&str>,
        output_type: Option<u32>,
        vintage_dates: Option<&str>,
    ) -> FredResult<SeriesObservationsResponse> {
        let mut params = HashMap::new();
        params.insert("series_id".to_string(), series_id.to_string());
        if let Some(rs) = realtime_start {
            params.insert("realtime_start".to_string(), rs.to_string());
        }
        if let Some(re) = realtime_end {
            params.insert("realtime_end".to_string(), re.to_string());
        }
        if let Some(os) = observation_start {
            params.insert("observation_start".to_string(), os.to_string());
        }
        if let Some(oe) = observation_end {
            params.insert("observation_end".to_string(), oe.to_string());
        }
        if let Some(f) = frequency {
            params.insert("frequency".to_string(), f.to_string());
        }
        if let Some(am) = aggregation_method {
            params.insert("aggregation_method".to_string(), am.to_string());
        }
        if let Some(ot) = output_type {
            params.insert("output_type".to_string(), ot.to_string());
        }
        if let Some(vd) = vintage_dates {
            params.insert("vintage_dates".to_string(), vd.to_string());
        }
        self.request_with_retry("/series/observations", &params).await
    }

    pub async fn get_series_release(&self, series_id: &str) -> FredResult<Release> {
        let mut params = HashMap::new();
        params.insert("series_id".to_string(), series_id.to_string());
        let response: ReleaseInfoResponse = self
            .request_with_retry("/series/release", &params)
            .await?;
        response.releases.into_iter().next().ok_or_else(|| FredError::NotFound("Release not found".to_string()))
    }

    pub async fn search_series(
        &self,
        query: &str,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
        search_type: Option<&str>,
    ) -> FredResult<SeriesSearchResponse> {
        let mut params = HashMap::new();
        params.insert("search_text".to_string(), query.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        if let Some(st) = search_type {
            params.insert("search_type".to_string(), st.to_string());
        }
        self.request_with_retry("/series/search", &params).await
    }

    pub async fn search_series_tags(
        &self,
        query: &str,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<TagsResponse> {
        let mut params = HashMap::new();
        params.insert("series_search_text".to_string(), query.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/series/search/tags", &params).await
    }

    pub async fn search_series_related_tags(
        &self,
        query: &str,
        tag_names: &str,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<RelatedTagsResponse> {
        let mut params = HashMap::new();
        params.insert("series_search_text".to_string(), query.to_string());
        params.insert("tag_names".to_string(), tag_names.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/series/search/related_tags", &params).await
    }

    pub async fn get_series_tags(
        &self,
        series_id: &str,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<TagsResponse> {
        let mut params = HashMap::new();
        params.insert("series_id".to_string(), series_id.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/series/tags", &params).await
    }

    pub async fn get_series_updates(
        &self,
        realtime_start: Option<&str>,
        realtime_end: Option<&str>,
        limit: Option<u32>,
        offset: Option<u32>,
    ) -> FredResult<SeriesUpdatesResponse> {
        let mut params = HashMap::new();
        if let Some(rs) = realtime_start {
            params.insert("realtime_start".to_string(), rs.to_string());
        }
        if let Some(re) = realtime_end {
            params.insert("realtime_end".to_string(), re.to_string());
        }
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        self.request_with_retry("/series/updates", &params).await
    }

    pub async fn get_series_vintagedates(
        &self,
        series_id: &str,
        realtime_start: Option<&str>,
        realtime_end: Option<&str>,
        limit: Option<u32>,
        offset: Option<u32>,
    ) -> FredResult<serde_json::Value> {
        let mut params = HashMap::new();
        params.insert("series_id".to_string(), series_id.to_string());
        if let Some(rs) = realtime_start {
            params.insert("realtime_start".to_string(), rs.to_string());
        }
        if let Some(re) = realtime_end {
            params.insert("realtime_end".to_string(), re.to_string());
        }
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        self.request_with_retry("/series/vintagedates", &params).await
    }

    // ==================== SOURCES ====================

    pub async fn get_all_sources(&self) -> FredResult<SourcesResponse> {
        let params = HashMap::new();
        self.request_with_retry("/sources", &params).await
    }

    pub async fn get_source(&self, source_id: u32) -> FredResult<Source> {
        let mut params = HashMap::new();
        params.insert("source_id".to_string(), source_id.to_string());
        let response: SourceResponse = self
            .request_with_retry("/source", &params)
            .await?;
        response.sources.into_iter().next().ok_or_else(|| FredError::NotFound("Source not found".to_string()))
    }

    pub async fn get_source_releases(&self, source_id: u32) -> FredResult<SourceReleasesResponse> {
        let mut params = HashMap::new();
        params.insert("source_id".to_string(), source_id.to_string());
        self.request_with_retry("/source/releases", &params).await
    }

    // ==================== TAGS ====================

    pub async fn get_all_tags(
        &self,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<TagsResponse> {
        let mut params = HashMap::new();
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/tags", &params).await
    }

    pub async fn get_related_tags(
        &self,
        tag_names: &str,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<RelatedTagsResponse> {
        let mut params = HashMap::new();
        params.insert("tag_names".to_string(), tag_names.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/related_tags", &params).await
    }

    pub async fn get_tags_series(
        &self,
        tag_names: &str,
        limit: Option<u32>,
        offset: Option<u32>,
        order_by: Option<&str>,
        sort_order: Option<&str>,
    ) -> FredResult<TagSeriesResponse> {
        let mut params = HashMap::new();
        params.insert("tag_names".to_string(), tag_names.to_string());
        if let Some(l) = limit {
            params.insert("limit".to_string(), l.to_string());
        }
        if let Some(o) = offset {
            params.insert("offset".to_string(), o.to_string());
        }
        if let Some(ob) = order_by {
            params.insert("order_by".to_string(), ob.to_string());
        }
        if let Some(so) = sort_order {
            params.insert("sort_order".to_string(), so.to_string());
        }
        self.request_with_retry("/tags/series", &params).await
    }

    // ==================== GEOSPATIAL ====================

    pub async fn get_geoseries_data(
        &self,
        series_id: &str,
        date: Option<&str>,
    ) -> FredResult<GeoDataResponse> {
        let mut params = HashMap::new();
        params.insert("series_id".to_string(), series_id.to_string());
        if let Some(d) = date {
            params.insert("date".to_string(), d.to_string());
        }
        self.request_with_retry("/geoseries/data", &params).await
    }
}

#[async_trait]
pub trait FredDataProvider: Send + Sync {
    async fn fetch_series(&self, series_id: &str) -> FredResult<Series>;
    async fn fetch_observations(
        &self,
        series_id: &str,
        observation_start: Option<&str>,
        observation_end: Option<&str>,
    ) -> FredResult<SeriesObservationsResponse>;
    async fn search_series(
        &self,
        query: &str,
        limit: Option<u32>,
    ) -> FredResult<SeriesSearchResponse>;
}

#[async_trait]
impl FredDataProvider for FredClient {
    async fn fetch_series(&self, series_id: &str) -> FredResult<Series> {
        self.get_series(series_id).await
    }

    async fn fetch_observations(
        &self,
        series_id: &str,
        observation_start: Option<&str>,
        observation_end: Option<&str>,
    ) -> FredResult<SeriesObservationsResponse> {
        self.get_series_observations(
            series_id,
            None,
            None,
            observation_start,
            observation_end,
            None,
            None,
            None,
            None,
        )
        .await
    }

    async fn search_series(
        &self,
        query: &str,
        limit: Option<u32>,
    ) -> FredResult<SeriesSearchResponse> {
        self.search_series(query, limit, None, None, None, None)
            .await
    }
}

fn rand_u64() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos() as u64
        % 1000
}
