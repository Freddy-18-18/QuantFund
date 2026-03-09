use std::sync::Arc;
use std::time::{Duration, Instant};
use std::collections::{HashMap, VecDeque};
use tokio::sync::RwLock;
use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DataType {
    SeriesMetadata,
    Observations,
    Tags,
    Categories,
    Releases,
    Updates,
}

impl DataType {
    pub fn ttl(&self) -> Duration {
        match self {
            DataType::SeriesMetadata => Duration::from_secs(30 * 24 * 60 * 60),
            DataType::Observations => Duration::from_secs(24 * 60 * 60),
            DataType::Tags => Duration::from_secs(7 * 24 * 60 * 60),
            DataType::Categories => Duration::from_secs(7 * 24 * 60 * 60),
            DataType::Releases => Duration::from_secs(24 * 60 * 60),
            DataType::Updates => Duration::from_secs(5 * 60),
        }
    }

    pub fn from_endpoint(endpoint: &str) -> Self {
        if endpoint.contains("/series") && !endpoint.contains("/observations") {
            DataType::SeriesMetadata
        } else if endpoint.contains("/observations") {
            DataType::Observations
        } else if endpoint.contains("/tags") {
            DataType::Tags
        } else if endpoint.contains("/categories") {
            DataType::Categories
        } else if endpoint.contains("/releases") {
            DataType::Releases
        } else if endpoint.contains("/updates") {
            DataType::Updates
        } else {
            DataType::Observations
        }
    }
}

#[derive(Debug, Clone)]
pub struct CachedValue {
    pub value: String,
    pub data_type: DataType,
    pub cached_at: Instant,
    pub expires_at: Instant,
}

impl CachedValue {
    pub fn new(value: String, data_type: DataType) -> Self {
        let now = Instant::now();
        let ttl = data_type.ttl();
        Self {
            value,
            data_type,
            cached_at: now,
            expires_at: now + ttl,
        }
    }

    pub fn is_expired(&self) -> bool {
        Instant::now() > self.expires_at
    }
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct CacheMetrics {
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
    pub inserts: u64,
    pub invalidations: u64,
    pub expirations: u64,
}

impl CacheMetrics {
    pub fn hit_rate(&self) -> f64 {
        let total = self.hits + self.misses;
        if total == 0 {
            0.0
        } else {
            self.hits as f64 / total as f64
        }
    }
}

struct CacheEntry {
    value: CachedValue,
    #[allow(dead_code)]
    key: String,
}

pub struct FredCache {
    entries: RwLock<HashMap<String, CacheEntry>>,
    order: RwLock<VecDeque<String>>,
    max_entries: usize,
    metrics: RwLock<CacheMetrics>,
}

impl FredCache {
    pub fn new(max_entries: usize) -> Arc<Self> {
        Arc::new(Self {
            entries: RwLock::new(HashMap::new()),
            order: RwLock::new(VecDeque::new()),
            max_entries,
            metrics: RwLock::new(CacheMetrics::default()),
        })
    }

    pub async fn get(&self, key: &str) -> Option<CachedValue> {
        let entries = self.entries.read().await;
        
        if let Some(entry) = entries.get(key) {
            if entry.value.is_expired() {
                drop(entries);
                let mut metrics = self.metrics.write().await;
                metrics.expirations += 1;
                drop(metrics);
                self.invalidate(key).await;
                return None;
            }
            
            let value = entry.value.clone();
            
            drop(entries);
            let mut metrics = self.metrics.write().await;
            metrics.hits += 1;
            
            drop(metrics);
            
            self.move_to_front(key).await;
            
            Some(value)
        } else {
            drop(entries);
            let mut metrics = self.metrics.write().await;
            metrics.misses += 1;
            None
        }
    }

    pub async fn set(&self, key: String, value: String, data_type: DataType) {
        let cached = CachedValue::new(value, data_type);
        
        let entries_len = {
            let entries = self.entries.read().await;
            entries.len()
        };
        
        if entries_len >= self.max_entries && !self.entries.read().await.contains_key(&key) {
            self.evict_lru().await;
        }
        
        let mut entries = self.entries.write().await;
        entries.insert(key.clone(), CacheEntry {
            value: cached,
            key: key.clone(),
        });
        
        drop(entries);
        
        let mut order = self.order.write().await;
        order.retain(|k| k != &key);
        order.push_front(key);
        
        let mut metrics = self.metrics.write().await;
        metrics.inserts += 1;
    }

    pub async fn set_with_custom_ttl(&self, key: String, value: String, ttl: Duration) {
        let now = Instant::now();
        let cached = CachedValue {
            value,
            data_type: DataType::Observations,
            cached_at: now,
            expires_at: now + ttl,
        };
        
        let entries_len = {
            let entries = self.entries.read().await;
            entries.len()
        };
        
        if entries_len >= self.max_entries && !self.entries.read().await.contains_key(&key) {
            self.evict_lru().await;
        }
        
        let mut entries = self.entries.write().await;
        entries.insert(key.clone(), CacheEntry {
            value: cached,
            key: key.clone(),
        });
        
        drop(entries);
        
        let mut order = self.order.write().await;
        order.retain(|k| k != &key);
        order.push_front(key);
        
        let mut metrics = self.metrics.write().await;
        metrics.inserts += 1;
    }

    async fn move_to_front(&self, key: &str) {
        let mut order = self.order.write().await;
        order.retain(|k| k != key);
        order.push_front(key.to_string());
    }

    async fn evict_lru(&self) {
        let mut order = self.order.write().await;
        if let Some(lru_key) = order.pop_back() {
            drop(order);
            let mut entries = self.entries.write().await;
            entries.remove(&lru_key);
            
            let mut metrics = self.metrics.write().await;
            metrics.evictions += 1;
        }
    }

    pub async fn invalidate(&self, key: &str) {
        let mut entries = self.entries.write().await;
        entries.remove(key);
        
        drop(entries);
        
        let mut order = self.order.write().await;
        order.retain(|k| k != key);
        
        let mut metrics = self.metrics.write().await;
        metrics.invalidations += 1;
    }

    pub async fn invalidate_by_prefix(&self, prefix: &str) {
        let keys_to_remove: Vec<String> = {
            let entries = self.entries.read().await;
            entries.keys()
                .filter(|k| k.starts_with(prefix))
                .cloned()
                .collect()
        };
        
        for key in &keys_to_remove {
            let mut entries = self.entries.write().await;
            entries.remove(key);
        }
        
        let mut order = self.order.write().await;
        order.retain(|k| !keys_to_remove.contains(k));
        
        let mut metrics = self.metrics.write().await;
        metrics.invalidations += keys_to_remove.len() as u64;
    }

    pub async fn invalidate_by_data_type(&self, data_type: DataType) {
        let keys_to_remove: Vec<String> = {
            let entries = self.entries.read().await;
            entries.iter()
                .filter(|(_, e)| e.value.data_type == data_type)
                .map(|(k, _)| k.clone())
                .collect()
        };
        
        for key in &keys_to_remove {
            let mut entries = self.entries.write().await;
            entries.remove(key);
        }
        
        let mut order = self.order.write().await;
        order.retain(|k| !keys_to_remove.contains(k));
        
        let mut metrics = self.metrics.write().await;
        metrics.invalidations += keys_to_remove.len() as u64;
    }

    pub async fn clear(&self) {
        let mut entries = self.entries.write().await;
        entries.clear();
        
        drop(entries);
        
        let mut order = self.order.write().await;
        order.clear();
        
        let mut metrics = self.metrics.write().await;
        metrics.invalidations += metrics.hits + metrics.misses;
    }

    pub fn metrics(&self) -> CacheMetrics {
        CacheMetrics::default()
    }

    pub async fn get_metrics(&self) -> CacheMetrics {
        let metrics = self.metrics.read().await;
        metrics.clone()
    }

    pub async fn size(&self) -> usize {
        let entries = self.entries.read().await;
        entries.len()
    }

    pub async fn cleanup_expired(&self) {
        let now = Instant::now();
        let keys_to_remove: Vec<String> = {
            let entries = self.entries.read().await;
            entries.iter()
                .filter(|(_, e)| now > e.value.expires_at)
                .map(|(k, _)| k.clone())
                .collect()
        };
        
        for key in &keys_to_remove {
            let mut entries = self.entries.write().await;
            entries.remove(key);
        }
        
        let mut order = self.order.write().await;
        order.retain(|k| !keys_to_remove.contains(k));
        
        let mut metrics = self.metrics.write().await;
        metrics.expirations += keys_to_remove.len() as u64;
    }
}

pub fn build_cache_key(endpoint: &str, params: &[(&str, &str)]) -> String {
    let mut key = endpoint.to_string();
    if !params.is_empty() {
        key.push('?');
        let mut sorted_params: Vec<_> = params.iter().map(|(k, v)| (*k, *v)).collect();
        sorted_params.sort_by(|a, b| a.0.cmp(b.0));
        for (i, (k, v)) in sorted_params.iter().enumerate() {
            if i > 0 {
                key.push('&');
            }
            key.push_str(k);
            key.push('=');
            key.push_str(v);
        }
    }
    key
}

pub fn build_cache_key_from_params(endpoint: &str, params: &HashMap<String, String>) -> String {
    let mut key = endpoint.to_string();
    if !params.is_empty() {
        key.push('?');
        let mut sorted_keys: Vec<_> = params.keys().collect();
        sorted_keys.sort();
        for (i, k) in sorted_keys.iter().enumerate() {
            if i > 0 {
                key.push('&');
            }
            key.push_str(k);
            key.push('=');
            if let Some(v) = params.get(*k) {
                key.push_str(v);
            }
        }
    }
    key
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_cache_basic_operations() {
        let cache = FredCache::new(3);
        
        cache.set(
            "key1".to_string(),
            "value1".to_string(),
            DataType::Observations,
        ).await;
        
        let result = cache.get("key1").await;
        assert!(result.is_some());
        assert_eq!(result.unwrap().value, "value1");
    }

    #[tokio::test]
    async fn test_cache_miss() {
        let cache = FredCache::new(3);
        
        let result = cache.get("nonexistent").await;
        assert!(result.is_none());
        
        let metrics = cache.get_metrics().await;
        assert_eq!(metrics.misses, 1);
        assert_eq!(metrics.hits, 0);
    }

    #[tokio::test]
    async fn test_cache_lru_eviction() {
        let cache = FredCache::new(2);
        
        cache.set("key1".to_string(), "value1".to_string(), DataType::Observations).await;
        cache.set("key2".to_string(), "value2".to_string(), DataType::Observations).await;
        
        cache.get("key1").await;
        
        cache.set("key3".to_string(), "value3".to_string(), DataType::Observations).await;
        
        let result = cache.get("key2").await;
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_cache_invalidate() {
        let cache = FredCache::new(3);
        
        cache.set("key1".to_string(), "value1".to_string(), DataType::Observations).await;
        cache.invalidate("key1").await;
        
        let result = cache.get("key1").await;
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_cache_clear() {
        let cache = FredCache::new(3);
        
        cache.set("key1".to_string(), "value1".to_string(), DataType::Observations).await;
        cache.set("key2".to_string(), "value2".to_string(), DataType::Observations).await;
        
        cache.clear().await;
        
        let size = cache.size().await;
        assert_eq!(size, 0);
    }

    #[tokio::test]
    async fn test_cache_metrics() {
        let cache = FredCache::new(3);
        
        cache.set("key1".to_string(), "value1".to_string(), DataType::Observations).await;
        cache.get("key1").await;
        cache.get("nonexistent").await;
        
        let metrics = cache.get_metrics().await;
        assert_eq!(metrics.hits, 1);
        assert_eq!(metrics.misses, 1);
        assert_eq!(metrics.inserts, 1);
    }

    #[tokio::test]
    async fn test_data_type_ttl() {
        assert_eq!(DataType::SeriesMetadata.ttl(), Duration::from_secs(30 * 24 * 60 * 60));
        assert_eq!(DataType::Observations.ttl(), Duration::from_secs(24 * 60 * 60));
        assert_eq!(DataType::Tags.ttl(), Duration::from_secs(7 * 24 * 60 * 60));
        assert_eq!(DataType::Categories.ttl(), Duration::from_secs(7 * 24 * 60 * 60));
        assert_eq!(DataType::Releases.ttl(), Duration::from_secs(24 * 60 * 60));
        assert_eq!(DataType::Updates.ttl(), Duration::from_secs(5 * 60));
    }

    #[test]
    fn test_build_cache_key() {
        let key = build_cache_key("/series", &[("series_id", "GDP"), ("units", "percent")]);
        assert!(key.contains("series_id=GDP"));
        assert!(key.contains("units=percent"));
    }

    #[tokio::test]
    async fn test_invalidate_by_prefix() {
        let cache = FredCache::new(10);
        
        cache.set("/series/GDP".to_string(), "value1".to_string(), DataType::SeriesMetadata).await;
        cache.set("/series/GNPR".to_string(), "value2".to_string(), DataType::SeriesMetadata).await;
        cache.set("/observations/GDP".to_string(), "value3".to_string(), DataType::Observations).await;
        
        cache.invalidate_by_prefix("/series").await;
        
        assert!(cache.get("/series/GDP").await.is_none());
        assert!(cache.get("/series/GNPR").await.is_none());
        assert!(cache.get("/observations/GDP").await.is_some());
    }
}
