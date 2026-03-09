use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Country {
    pub id: String,
    #[serde(rename = "iso2Code")]
    pub iso2_code: String,
    pub name: String,
    pub region: Option<Region>,
    #[serde(rename = "incomeLevel")]
    pub income_level: Option<IncomeLevel>,
    #[serde(rename = "lendingType")]
    pub lending_type: Option<LendingType>,
    #[serde(rename = "capitalCity")]
    pub capital_city: Option<String>,
    pub longitude: Option<String>,
    pub latitude: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Region {
    pub id: String,
    #[serde(rename = "iso2code")]
    pub iso2code: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IncomeLevel {
    pub id: String,
    #[serde(rename = "iso2code")]
    pub iso2code: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LendingType {
    pub id: String,
    #[serde(rename = "iso2code")]
    pub iso2code: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Indicator {
    pub id: String,
    pub name: String,
    pub description: Option<String>,
    pub source: Option<Source>,
    pub topics: Vec<Topic>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Source {
    pub id: u32,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Topic {
    pub id: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorData {
    pub indicator: IndicatorRef,
    pub country: CountryRef,
    #[serde(rename = "countryiso3code")]
    pub countryiso3code: Option<String>,
    pub date: String,
    pub value: Option<f64>,
    pub unit: Option<String>,
    #[serde(rename = "obsStatus")]
    pub obs_status: Option<String>,
    pub decimal: Option<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorRef {
    pub id: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CountryRef {
    pub id: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CountriesResponse {
    pub page: u32,
    pub pages: u32,
    #[serde(rename = "per_page")]
    pub per_page: u32,
    pub total: u32,
    #[serde(default)]
    pub countries: Vec<Country>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorsResponse {
    pub page: u32,
    pub pages: u32,
    #[serde(rename = "per_page")]
    pub per_page: u32,
    pub total: u32,
    #[serde(default)]
    pub indicators: Vec<Indicator>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorDataResponse {
    pub page: u32,
    pub pages: u32,
    #[serde(rename = "per_page")]
    pub per_page: u32,
    pub total: u32,
    #[serde(default)]
    pub data: Vec<IndicatorData>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TopicsResponse {
    pub page: u32,
    pub pages: u32,
    #[serde(rename = "per_page")]
    pub per_page: u32,
    pub total: u32,
    #[serde(default)]
    pub topics: Vec<Topic>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CountryDataQuery {
    pub format: Option<String>,
    pub per_page: Option<u32>,
    pub page: Option<u32>,
    pub source: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorDataQuery {
    pub format: Option<String>,
    pub per_page: Option<u32>,
    pub page: Option<u32>,
    pub date: Option<String>,
    #[serde(rename = "startDate")]
    pub start_date: Option<String>,
    #[serde(rename = "endDate")]
    pub end_date: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorQuery {
    pub format: Option<String>,
    pub per_page: Option<u32>,
    pub page: Option<u32>,
    pub source: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TopicQuery {
    pub format: Option<String>,
    pub per_page: Option<u32>,
    pub page: Option<u32>,
}

impl Default for CountryDataQuery {
    fn default() -> Self {
        Self {
            format: Some("json".to_string()),
            per_page: Some(100),
            page: Some(1),
            source: None,
        }
    }
}

impl Default for IndicatorDataQuery {
    fn default() -> Self {
        Self {
            format: Some("json".to_string()),
            per_page: Some(100),
            page: Some(1),
            date: None,
            start_date: None,
            end_date: None,
        }
    }
}

impl Default for IndicatorQuery {
    fn default() -> Self {
        Self {
            format: Some("json".to_string()),
            per_page: Some(100),
            page: Some(1),
            source: None,
        }
    }
}

impl Default for TopicQuery {
    fn default() -> Self {
        Self {
            format: Some("json".to_string()),
            per_page: Some(100),
            page: Some(1),
        }
    }
}
