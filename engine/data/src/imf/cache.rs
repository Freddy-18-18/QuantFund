//! IMF API Cache Implementation
//!
//! LRU cache with TTL support for IMF data

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::RwLock;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone)]
struct CacheEntry {
    data: Vec<u8>,
    expires_at: Instant,
    size_bytes: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheMetrics {
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
    pub size_bytes: usize,
    pub entries_count: usize,
}

pub struct ImfCache {
    entries: Arc<RwLock<HashMap<String, CacheEntry>>>,
    max_entries: usize,
    max_bytes: usize,
    default_ttl: Duration,
    metrics: Arc<RwLock<CacheMetrics>>,
}

impl ImfCache {
    pub fn new(max_entries: usize) -> Self {
        Self {
            entries: Arc::new(RwLock::new(HashMap::new())),
            max_entries,
            max_bytes: 50 * 1024 * 1024, // 50MB default
            default_ttl: Duration::from_secs(24 * 60 * 60), // 24 hours
            metrics: Arc::new(RwLock::new(CacheMetrics {
                hits: 0,
                misses: 0,
                evictions: 0,
                size_bytes: 0,
                entries_count: 0,
            })),
        }
    }

    pub async fn get(&self, key: &str) -> Option<Vec<u8>> {
        let mut entries = self.entries.write().await;
        
        if let Some(entry) = entries.get(key) {
            if Instant::now() < entry.expires_at {
                // Cache hit
                let mut metrics = self.metrics.write().await;
                metrics.hits += 1;
                return Some(entry.data.clone());
            } else {
                // Entry expired, remove it
                entries.remove(key);
            }
        }
        
        // Cache miss
        let mut metrics = self.metrics.write().await;
        metrics.misses += 1;
        None
    }

    pub async fn set(&self, key: String, data: Vec<u8>, ttl: Option<Duration>) {
        let ttl = ttl.unwrap_or(self.default_ttl);
        let size_bytes = data.len();
        
        let mut entries = self.entries.write().await;
        
        // Evict if necessary
        while entries.len() >= self.max_entries || self.current_size(&entries) + size_bytes > self.max_bytes {
            if let Some(oldest_key) = self.find_oldest_key(&entries) {
                if let Some(old_entry) = entries.remove(&oldest_key) {
                    let mut metrics = self.metrics.write().await;
                    metrics.evictions += 1;
                    metrics.size_bytes = metrics.size_bytes.saturating_sub(old_entry.size_bytes);
                    metrics.entries_count = entries.len();
                }
            } else {
                break;
            }
        }
        
        let entry = CacheEntry {
            data: data.clone(),
            expires_at: Instant::now() + ttl,
            size_bytes,
        };
        
        entries.insert(key, entry);
        
        let mut metrics = self.metrics.write().await;
        metrics.size_bytes = self.current_size(&entries);
        metrics.entries_count = entries.len();
    }

    pub async fn invalidate(&self, key: &str) {
        let mut entries = self.entries.write().await;
        if entries.remove(key).is_some() {
            let mut metrics = self.metrics.write().await;
            metrics.entries_count = entries.len();
            metrics.size_bytes = self.current_size(&entries);
        }
    }

    pub async fn clear(&self) {
        let mut entries = self.entries.write().await;
        entries.clear();
        
        let mut metrics = self.metrics.write().await;
        metrics.size_bytes = 0;
        metrics.entries_count = 0;
    }

    pub async fn get_metrics(&self) -> CacheMetrics {
        let entries = self.entries.read().await;
        let mut metrics = self.metrics.read().await.clone();
        metrics.entries_count = entries.len();
        metrics.size_bytes = self.current_size(&entries);
        metrics
    }

    fn current_size(&self, entries: &HashMap<String, CacheEntry>) -> usize {
        entries.values().map(|e| e.size_bytes).sum()
    }

    fn find_oldest_key(&self, entries: &HashMap<String, CacheEntry>) -> Option<String> {
        entries
            .iter()
            .min_by_key(|(_, e)| e.expires_at)
            .map(|(k, _)| k.clone())
    }
}

impl Default for ImfCache {
    fn default() -> Self {
        Self::new(1000)
    }
}

// Thread-safe wrapper for use in async contexts
pub type SharedCache = Arc<ImfCache>;

pub fn create_cache(size: usize) -> SharedCache {
    Arc::new(ImfCache::new(size))
}
