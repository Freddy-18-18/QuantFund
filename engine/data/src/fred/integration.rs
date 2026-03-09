use super::client::FredClient;
use super::cache::FredCache;
use super::error::FredResult;
use super::models::*;
use std::sync::Arc;

pub struct FredService {
    client: FredClient,
    cache: Arc<FredCache>,
}

impl FredService {
    pub fn new(api_key: String, cache_size: usize) -> Self {
        Self {
            client: FredClient::new(api_key),
            cache: FredCache::new(cache_size),
        }
    }
    
    pub async fn get_series(&self, series_id: &str) -> FredResult<Series> {
        let cache_key = format!("/series/{}", series_id);
        if let Some(cached) = self.cache.get(&cache_key).await {
            return serde_json::from_str(&cached.value)
                .map_err(|e| super::error::FredError::Parse(e.to_string()));
        }
        
        let series = self.client.get_series(series_id).await?;
        
        self.cache.set(cache_key, serde_json::to_string(&series).unwrap(), 
            super::cache::DataType::SeriesMetadata)
            .await;
        
        Ok(series)
    }
    
    pub async fn get_observations(
        &self,
        series_id: &str,
        start: Option<&str>,
        end: Option<&str>,
    ) -> FredResult<Vec<SeriesObservation>> {
        let cache_key = format!(
            "/series/observations/{}?start={:?}&end={:?}",
            series_id, start, end
        );
        
        if let Some(cached) = self.cache.get(&cache_key).await {
            let response: SeriesObservationsResponse = 
                serde_json::from_str(&cached.value)
                    .map_err(|e| super::error::FredError::Parse(e.to_string()))?;
            return Ok(response.observations);
        }
        
        let response = self.client.get_series_observations(
            series_id, None, None, start, end, None, None, None, None
        ).await?;
        
        self.cache.set(cache_key, serde_json::to_string(&response).unwrap(),
            super::cache::DataType::Observations)
            .await;
        
        Ok(response.observations)
    }
    
    pub async fn search(&self, query: &str, limit: Option<u32>) -> FredResult<Vec<SeriesSearchResult>> {
        let response = self.client.search_series(query, limit, None, None, None, None).await?;
        Ok(response.series)
    }
    
    pub async fn get_updated(&self, limit: Option<u32>) -> FredResult<Vec<SeriesUpdate>> {
        let response = self.client.get_series_updates(None, None, limit, None).await?;
        Ok(response.series)
    }
    
    pub async fn get_cache_stats(&self) -> super::cache::CacheMetrics {
        self.cache.get_metrics().await
    }
    
    pub async fn clear_cache(&self) {
        self.cache.clear().await;
    }
}
