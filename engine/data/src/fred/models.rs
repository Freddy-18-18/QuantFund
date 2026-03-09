//! FRED API Data Models
//!
//! Comprehensive data structures for the Federal Reserve Economic Data (FRED) API.
//! Used by the QuantFund trading platform for economic data ingestion and analysis.

use serde::{Deserialize, Serialize};

/// Category information from FRED API
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Category {
    pub id: i32,
    pub name: String,
    #[serde(rename = "parent_id")]
    pub parent_id: Option<i32>,
}

/// Category information response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CategoryInfo {
    pub categories: Vec<Category>,
}

impl CategoryInfo {
    /// Helper to get the first category since API returns a list
    pub fn first(self) -> Option<Category> {
        self.categories.into_iter().next()
    }
}

/// Series within a category
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CategorySeries {
    pub id: String,
    pub title: String,
    pub realtime_start: String,
    pub realtime_end: String,
    pub observation_start: Option<String>,
    pub observation_end: Option<String>,
    pub frequency: Option<String>,
    pub frequency_short: Option<String>,
    pub units: Option<String>,
    pub units_short: Option<String>,
    pub popularity: Option<i32>,
}

/// Category series response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CategorySeriesResponse {
    pub count: i32,
    pub offset: i32,
    pub limit: i32,
    #[serde(rename = "seriess")]
    pub series: Vec<CategorySeries>,
}

/// Tags associated with a category
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CategoryTags {
    pub name: String,
    pub series_count: i32,
    pub popularity: i32,
    pub group_id: Option<String>,
}

/// Category tags response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CategoryTagsResponse {
    pub count: i32,
    pub offset: i32,
    pub limit: i32,
    pub tags: Vec<CategoryTags>,
}

/// Release information from FRED API
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Release {
    pub id: i32,
    pub name: String,
    pub link: Option<String>,
    pub press_release: Option<bool>,
    pub realtime_start: String,
    pub realtime_end: String,
}

/// Release information response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleasesResponse {
    pub count: i32,
    pub offset: Option<i32>,
    pub limit: Option<i32>,
    pub releases: Vec<Release>,
}

/// Single release info
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleaseInfoResponse {
    pub releases: Vec<Release>,
}

/// Release date info
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleaseDate {
    pub release_id: i32,
    pub date: String,
}

/// Release dates response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleaseDatesResponse {
    pub count: i32,
    pub release_dates: Vec<ReleaseDate>,
}

/// Release series response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleaseSeriesResponse {
    pub count: i32,
    pub offset: i32,
    pub limit: i32,
    #[serde(rename = "seriess")]
    pub series: Vec<CategorySeries>,
}

/// Release tags response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleaseTagsResponse {
    pub count: i32,
    pub tags: Vec<CategoryTags>,
}

/// Source information
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Source {
    pub id: i32,
    pub name: String,
    pub link: Option<String>,
}

/// Sources response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourcesResponse {
    pub count: i32,
    pub sources: Vec<Source>,
}

/// Single source response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceResponse {
    pub sources: Vec<Source>,
}

/// Source release info
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceRelease {
    pub id: i32,
    pub name: String,
}

/// Source releases response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceReleasesResponse {
    pub count: i32,
    pub releases: Vec<SourceRelease>,
}

/// Series information
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Series {
    pub id: String,
    pub realtime_start: String,
    pub realtime_end: String,
    pub title: String,
    pub observation_start: Option<String>,
    pub observation_end: Option<String>,
    pub frequency: Option<String>,
    pub frequency_short: Option<String>,
    pub units: Option<String>,
    pub units_short: Option<String>,
    pub seasonal_adjustment: Option<String>,
    pub last_updated: Option<String>,
    pub popularity: Option<i32>,
    pub notes: Option<String>,
}

/// Series information response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SeriesInfoResponse {
    pub seriess: Vec<Series>,
}

/// Series observation
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SeriesObservation {
    pub date: String,
    pub value: String,
    pub realtime_start: String,
    pub realtime_end: String,
}

impl SeriesObservation {
    pub fn is_missing(&self) -> bool {
        self.value == "." || self.value.is_empty()
    }
}

/// Series observations response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SeriesObservationsResponse {
    pub count: i32,
    pub observations: Vec<SeriesObservation>,
    pub realtime_start: String,
    pub realtime_end: String,
}

/// Series search result
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SeriesSearchResult {
    pub id: String,
    pub title: String,
    pub realtime_start: String,
    pub realtime_end: String,
    pub observation_start: Option<String>,
    pub observation_end: Option<String>,
    pub frequency: Option<String>,
    pub units: Option<String>,
}

/// Series search response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SeriesSearchResponse {
    pub count: i32,
    #[serde(rename = "seriess")]
    pub series: Vec<SeriesSearchResult>,
}

/// Tag info
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Tag {
    pub name: String,
    pub series_count: i32,
    pub popularity: i32,
}

/// Tags response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TagsResponse {
    pub count: i32,
    pub tags: Vec<Tag>,
}

/// Related tag info
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RelatedTag {
    pub name: String,
}

/// Related tags response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RelatedTagsResponse {
    pub count: i32,
    pub tags: Vec<RelatedTag>,
}

/// Tag series response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TagSeriesResponse {
    pub count: i32,
    #[serde(rename = "seriess")]
    pub series: Vec<CategorySeries>,
}

/// Series update info
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SeriesUpdate {
    pub series_id: String,
    pub observation_date: String,
    pub value: String,
}

/// Series updates response
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SeriesUpdatesResponse {
    #[serde(rename = "seriess")]
    pub series: Vec<SeriesUpdate>,
}

// ==================== GEOSPATIAL / MAPS ====================

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct GeoSeries {
    pub title: String,
    pub units: String,
    pub frequency: String,
    pub seasonal_adjustment: String,
    pub last_updated: String,
    pub notes: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct GeoData {
    pub region: String,
    pub code: String,
    pub value: String,
    pub series_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct GeoDataResponse {
    pub realtime_start: String,
    pub realtime_end: String,
    pub date: String,
    #[serde(rename = "geoseries_data")]
    pub data: Vec<GeoData>,
}
