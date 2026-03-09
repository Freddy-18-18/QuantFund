use reqwest::Client;
use serde::{Deserialize, Serialize};
use thiserror::Error;

const FINNHUB_BASE_URL: &str = "https://finnhub.io/api/v1";
const FINNHUB_API_KEY: &str = "d6mdsu9r01qi0ajlsb20d6mdsu9r01qi0ajlsb2g";

#[derive(Error, Debug)]
pub enum FinnhubError {
    #[error("HTTP request failed: {0}")]
    RequestError(#[from] reqwest::Error),
    #[error("API returned error: {0}")]
    ApiError(String),
    #[error("Failed to parse response: {0}")]
    ParseError(#[from] serde_json::Error),
}

pub struct FinnhubClient {
    client: Client,
    api_key: String,
}

impl FinnhubClient {
    pub fn new() -> Self {
        Self {
            client: Client::new(),
            api_key: FINNHUB_API_KEY.to_string(),
        }
    }

    pub async fn get_market_news(&self, category: &str) -> Result<Vec<FinnhubNews>, FinnhubError> {
        let url = format!(
            "{}/news?category={}&token={}",
            FINNHUB_BASE_URL, category, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let news: Vec<FinnhubNews> = response.json().await?;
        Ok(news)
    }

    pub async fn get_company_news(&self, symbol: &str, from: &str, to: &str) -> Result<Vec<CompanyNews>, FinnhubError> {
        let url = format!(
            "{}/news?symbol={}&from={}&to={}&token={}",
            FINNHUB_BASE_URL, symbol, from, to, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let news: Vec<CompanyNews> = response.json().await?;
        Ok(news)
    }

    pub async fn get_economic_calendar(
        &self, 
        from: &str, 
        to: &str,
    ) -> Result<Vec<EconomicEvent>, FinnhubError> {
        let url = format!(
            "{}/economic/calendar?from={}&to={}&token={}",
            FINNHUB_BASE_URL, from, to, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let calendar: EconomicCalendarResponse = response.json().await?;
        Ok(calendar.events)
    }

    #[allow(dead_code)]
    pub async fn get_stock_candles(
        &self,
        symbol: &str,
        resolution: &str,
        from: i64,
        to: i64,
    ) -> Result<StockCandles, FinnhubError> {
        let url = format!(
            "{}/stock/candle?symbol={}&resolution={}&from={}&to={}&token={}",
            FINNHUB_BASE_URL, symbol, resolution, from, to, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let candles: StockCandles = response.json().await?;
        Ok(candles)
    }

    pub async fn get_aggregate_indicator(
        &self,
        symbol: &str,
        resolution: &str,
    ) -> Result<AggregateIndicator, FinnhubError> {
        let url = format!(
            "{}/indicator?symbol={}&resolution={}&token={}",
            FINNHUB_BASE_URL, symbol, resolution, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let indicator: AggregateIndicator = response.json().await?;
        Ok(indicator)
    }

    pub async fn get_company_profile(&self, symbol: &str) -> Result<CompanyProfile, FinnhubError> {
        let url = format!(
            "{}/stock/profile2?symbol={}&token={}",
            FINNHUB_BASE_URL, symbol, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let profile: CompanyProfile = response.json().await?;
        Ok(profile)
    }

    pub async fn get_stock_recommendations(&self, symbol: &str) -> Result<StockRecommendations, FinnhubError> {
        let url = format!(
            "{}/stock/recommendation?symbol={}&token={}",
            FINNHUB_BASE_URL, symbol, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let recommendations: Vec<RecommendationTrend> = response.json().await?;
        Ok(StockRecommendations { trends: recommendations })
    }

    pub async fn get_social_sentiment(
        &self,
        symbol: &str,
    ) -> Result<SocialSentiment, FinnhubError> {
        let url = format!(
            "{}/social-sentiment?symbol={}&token={}",
            FINNHUB_BASE_URL, symbol, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let sentiment: SocialSentiment = response.json().await?;
        Ok(sentiment)
    }

    pub async fn get_earnings_calendar(
        &self,
        from: &str,
        to: &str,
    ) -> Result<EarningsCalendar, FinnhubError> {
        let url = format!(
            "{}/earnings-calendar?from={}&to={}&token={}",
            FINNHUB_BASE_URL, from, to, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let calendar: EarningsCalendar = response.json().await?;
        Ok(calendar)
    }

    pub async fn get_covid_data(&self) -> Result<Vec<CovidData>, FinnhubError> {
        let url = format!(
            "{}/covid?token={}",
            FINNHUB_BASE_URL, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let data: Vec<CovidData> = response.json().await?;
        Ok(data)
    }

    pub async fn get_market_status(&self) -> Result<MarketStatus, FinnhubError> {
        let url = format!(
            "{}/market/status?token={}",
            FINNHUB_BASE_URL, self.api_key
        );
        
        let response = self.client.get(&url).send().await?;
        
        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(FinnhubError::ApiError(error_text));
        }
        
        let status: MarketStatus = response.json().await?;
        Ok(status)
    }
}

impl Default for FinnhubClient {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FinnhubNews {
    pub id: i64,
    pub headline: String,
    pub summary: String,
    pub source: String,
    pub url: String,
    pub datetime: i64,
    pub image: String,
    pub related: String,
    pub category: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CompanyNews {
    pub id: i64,
    pub headline: String,
    pub summary: String,
    pub source: String,
    pub url: String,
    pub datetime: i64,
    pub image: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EconomicCalendarResponse {
    pub events: Vec<EconomicEvent>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EconomicEvent {
    pub event_id: String,
    pub date: String,
    pub time: Option<String>,
    pub event: String,
    pub country: String,
    pub currency: String,
    pub importance: i32,
    pub actual: Option<String>,
    pub previous: Option<String>,
    pub consensus: Option<String>,
    pub revised: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[allow(dead_code)]
pub struct StockCandles {
    pub s: String,
    pub t: Vec<i64>,
    pub c: Vec<f64>,
    pub o: Vec<f64>,
    pub h: Vec<f64>,
    pub l: Vec<f64>,
    pub v: Vec<i64>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AggregateIndicator {
    pub s: String,
    pub technical: TechnicalIndicator,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TechnicalIndicator {
    pub count: i32,
    pub sell: i32,
    pub neutral: i32,
    pub buy: i32,
    pub indicator: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CompanyProfile {
    pub country: Option<String>,
    pub currency: Option<String>,
    pub exchange: Option<String>,
    pub ipo: Option<String>,
    pub market_capitalization: Option<f64>,
    pub name: Option<String>,
    pub phone: Option<String>,
    pub share_outstanding: Option<f64>,
    pub ticker: Option<String>,
    pub weburl: Option<String>,
    pub logo: Option<String>,
    pub finnhub_industry: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct StockRecommendations {
    pub trends: Vec<RecommendationTrend>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RecommendationTrend {
    pub period: String,
    pub strong_buy: i32,
    pub buy: i32,
    pub hold: i32,
    pub sell: i32,
    pub strong_sell: i32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SocialSentiment {
    pub symbol: String,
    pub sentiment: Vec<SentimentData>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SentimentData {
    pub date: String,
    pub at_time: i64,
    pub reddit_comment_sentiment: Option<f64>,
    pub reddit_post_sentiment: Option<f64>,
    pub reddit_posts: Option<i32>,
    pub reddit_comments: Option<i32>,
    pub twitter_followers: Option<i32>,
    pub twitter_following: Option<i32>,
    pub twitter_lists: Option<i32>,
    pub twitter_sentiment: Option<f64>,
    pub twitter_posts: Option<i32>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EarningsCalendar {
    pub earnings_calendar: Vec<EarningsEvent>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EarningsEvent {
    pub date: String,
    pub symbol: String,
    pub name: Option<String>,
    pub eps: Option<f64>,
    pub eps_estimate: Option<f64>,
    pub revenue: Option<f64>,
    pub revenue_estimate: Option<f64>,
    pub hour: Option<String>,
    pub market_cap: Option<f64>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CovidData {
    pub country: String,
    pub case: i64,
    pub death: i64,
    pub recovered: i64,
    pub date: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct MarketStatus {
    pub is_open: bool,
    pub session: String,
    pub market_type: String,
    pub local_market: String,
    pub exchanges: Vec<ExchangeStatus>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ExchangeStatus {
    pub name: String,
    pub status: String,
    pub delay: i32,
}
