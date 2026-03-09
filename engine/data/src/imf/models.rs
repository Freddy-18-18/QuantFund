//! IMF API Data Models
//!
//! Models for SDMX 3.0 responses

use serde::{Deserialize, Serialize};

pub const BASE_URL: &str = "https://api.imf.org/external/sdmx/3.0";

// ============================================================================
// Auth Models
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthToken {
    pub access_token: String,
    pub token_type: String,
    pub expires_in: u64,
}

// ============================================================================
// Data Query Models
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataResponse {
    pub data: DataContent,
    pub meta: ResponseMeta,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataContent {
    #[serde(rename = "dataSets")]
    pub data_sets: Vec<DataSet>,
    pub structures: Vec<DataStructure>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataSet {
    pub action: Option<String>,
    pub series: Option<serde_json::Value>,
    #[serde(rename = "structure")]
    pub structure_idx: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataStructure {
    pub annotations: Vec<Annotation>,
    pub attributes: Option<StructureAttributes>,
    #[serde(rename = "dataSets")]
    pub data_sets: Vec<usize>,
    pub dimensions: StructureDimensions,
    pub measures: Option<StructureMeasures>,
    pub links: Option<Vec<StructureLink>>,
    #[serde(rename = "urn")]
    pub link_urn: Option<String>,
}

// ============================================================================
// Availability Query Models
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AvailabilityResponse {
    pub data: AvailabilityContent,
    pub meta: ResponseMeta,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AvailabilityContent {
    #[serde(rename = "dataConstraints")]
    pub data_constraints: Vec<DataConstraint>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataConstraint {
    #[serde(rename = "agencyID")]
    pub agency_id: String,
    pub annotations: Vec<Annotation>,
    #[serde(rename = "constraintAttachment")]
    pub constraint_attachment: ConstraintAttachment,
    #[serde(rename = "cubeRegions")]
    pub cube_regions: Vec<CubeRegion>,
    pub description: Option<String>,
    pub descriptions: Option<LocalizedString>,
    pub id: String,
    pub links: Option<Vec<StructureLink>>,
    pub name: Option<String>,
    pub names: Option<LocalizedString>,
    pub role: String,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConstraintAttachment {
    #[serde(rename = "dataStructures")]
    pub data_structures: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CubeRegion {
    pub components: Vec<RegionComponent>,
    pub include: bool,
    #[serde(rename = "keyValues")]
    pub key_values: Vec<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegionComponent {
    pub id: String,
    pub include: bool,
    #[serde(rename = "removePrefix")]
    pub remove_prefix: bool,
    pub values: Vec<ComponentValue>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComponentValue {
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalizedString {
    pub en: String,
}

// ============================================================================
// Structure Query Models (Dataflows)
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataflowsResponse {
    pub data: DataflowsContent,
    pub meta: ResponseMeta,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataflowsContent {
    #[serde(rename = "dataflows")]
    pub data_flows: Vec<Dataflow>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dataflow {
    pub id: String,
    pub name: Option<String>,
    pub description: Option<String>,
    pub annotations: Option<Vec<Annotation>>,
    pub version: Option<String>,
    pub structure: Option<DataflowStructure>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataflowStructure {
    pub id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResponseMeta {
    #[serde(rename = "contentLanguages")]
    pub content_languages: Option<Vec<String>>,
    pub id: Option<String>,
    pub prepared: Option<String>,
    pub schema: Option<String>,
    pub sender: Option<Sender>,
    pub test: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Sender {
    pub id: String,
}

// ============================================================================
// Codelist Models
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CodelistsResponse {
    pub data: CodelistsContent,
    pub meta: ResponseMeta,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CodelistsContent {
    #[serde(rename = "codeLists")]
    pub code_lists: Vec<CodeList>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CodeList {
    #[serde(rename = "agencyID")]
    pub agency_id: String,
    pub annotations: Option<Vec<Annotation>>,
    pub codes: Vec<Code>,
    pub description: Option<String>,
    pub descriptions: Option<LocalizedString>,
    pub id: String,
    #[serde(rename = "isPartial")]
    pub is_partial: Option<bool>,
    pub links: Option<Vec<StructureLink>>,
    pub name: Option<String>,
    pub names: Option<LocalizedString>,
    pub version: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Code {
    pub annotations: Option<Vec<Annotation>>,
    pub description: Option<String>,
    pub descriptions: Option<LocalizedString>,
    pub id: String,
    pub name: Option<String>,
    pub names: Option<LocalizedString>,
}

// ============================================================================
// Parsed Data for Application Use
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeSeries {
    pub id: String,
    pub name: String,
    pub observations: Vec<Observation>,
    pub attributes: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Observation {
    pub date: String,
    pub value: Option<f64>,
    pub status: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataflowInfo {
    pub id: String,
    pub name: String,
    pub description: Option<String>,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CodeInfo {
    pub id: String,
    pub name: String,
    pub description: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AvailabilityInfo {
    pub series_count: usize,
    pub start_date: Option<String>,
    pub end_date: Option<String>,
    pub frequencies: Vec<String>,
}

// ============================================================================
// Configuration
// ============================================================================

#[derive(Debug, Clone)]
pub struct ImfConfig {
    pub api_key: String,
    pub client_id: String,
    pub client_secret: String,
    pub rate_limit_max: u32,
    pub rate_limit_window_secs: f64,
    pub cache_size: usize,
    pub cache_ttl_hours: u32,
}

impl ImfConfig {
    pub fn new(api_key: String) -> Self {
        Self {
            api_key,
            client_id: "8e244147061a4bca897a475f4dacc0a9".to_string(),
            client_secret: "75867736d82f4cb9883fd4e417398a55".to_string(),
            rate_limit_max: 10,
            rate_limit_window_secs: 5.0,
            cache_size: 1000,
            cache_ttl_hours: 24,
        }
    }
}

// ============================================================================
// Additional SDMX Structure Types (previously missing)
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Annotation {
    pub id: Option<String>,
    #[serde(rename = "type")]
    pub annotation_type: Option<String>,
    pub title: Option<String>,
    pub value: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureAttributes {
    pub attributes: Option<Vec<Dimension>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureDimensions {
    pub dimensions: Vec<Dimension>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureMeasures {
    pub measures: Vec<Measure>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureLink {
    pub href: String,
    #[serde(rename = "rel")]
    pub relation: Option<String>,
    #[serde(rename = "type")]
    pub link_type: Option<String>,
    #[serde(rename = "title")]
    pub link_title: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dimension {
    pub id: String,
    pub name: Option<String>,
    pub values: Option<Vec<DimensionValue>>,
    pub role: Option<String>,
    pub annotations: Option<Vec<Annotation>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DimensionValue {
    pub id: String,
    pub name: Option<String>,
    pub description: Option<String>,
    pub annotations: Option<Vec<Annotation>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Measure {
    pub id: String,
    pub name: Option<String>,
    pub annotations: Option<Vec<Annotation>>,
}
