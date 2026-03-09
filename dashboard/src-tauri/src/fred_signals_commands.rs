use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

use quantfund_data::fred::FredClient;

use crate::fred_analysis::AnalysisEngine;
use crate::fred_commands::FredState;

const XAUUSD_RELEVANT_SERIES: &[&str] = &[
    "DFII10",
    "DFII5",
    "DGS10",
    "DGS2",
    "DGS30",
    "DTIN3M",
    "IC4WSA",
    "MORTGAGE30US",
    "PCEPI",
    "CPALTT01USM657N",
    "UNRATE",
    "GDPC1",
    "BOPGSTB",
    "XRGUSD",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradingSignal {
    pub id: String,
    pub date: String,
    pub symbol: String,
    pub direction: SignalDirection,
    pub strength: f64,
    pub confidence: f64,
    pub source_series: Vec<String>,
    pub metadata: SignalMetadata,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum SignalDirection {
    Buy,
    Sell,
    Neutral,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalMetadata {
    pub indicator_type: String,
    pub z_score: f64,
    pub percentile: f64,
    pub trend: String,
    pub volatility: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompositeSignal {
    pub symbol: String,
    pub date: String,
    pub overall_direction: SignalDirection,
    pub strength: f64,
    pub confidence: f64,
    pub component_signals: Vec<SignalBreakdownItem>,
    pub risk_metrics: RiskMetrics,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalBreakdownItem {
    pub series_id: String,
    pub series_name: String,
    pub contribution: f64,
    pub direction: SignalDirection,
    pub strength: f64,
    pub current_value: f64,
    pub z_score: f64,
    pub percentile: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskMetrics {
    pub volatility_index: f64,
    pub max_series_correlation: f64,
    pub risk_score: f64,
    pub recommended_position_size: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalStrength {
    pub total_signals: usize,
    pub buy_signals: usize,
    pub sell_signals: usize,
    pub neutral_signals: usize,
    pub average_strength: f64,
    pub average_confidence: f64,
    pub dominant_direction: SignalDirection,
    pub consensus_score: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionRecommendation {
    pub symbol: String,
    pub direction: SignalDirection,
    pub position_size: f64,
    pub risk_percentage: f64,
    pub stop_loss_distance: f64,
    pub take_profit_distance: f64,
    pub risk_reward_ratio: f64,
    pub rationale: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorValue {
    pub series_id: String,
    pub name: String,
    pub value: f64,
    pub date: String,
    pub z_score: f64,
    pub percentile: f64,
    pub change_1m: f64,
    pub change_12m: f64,
    pub volatility: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoricalIndicator {
    pub series_id: String,
    pub date: String,
    pub value: f64,
    pub z_score: f64,
    pub percentile: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndicatorCorrelation {
    pub series_a: String,
    pub series_b: String,
    pub correlation: f64,
    pub strength: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilterConfig {
    pub min_confidence: f64,
    pub min_strength: f64,
    pub max_volatility: f64,
    pub exclude_series: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilteredSignal {
    pub original_signal: TradingSignal,
    pub passed_filters: bool,
    pub failed_filters: Vec<String>,
    pub adjusted_strength: f64,
}

pub struct FredSignalsState {
    pub signals_cache: HashMap<String, Vec<TradingSignal>>,
    pub indicators_cache: HashMap<String, IndicatorValue>,
    pub correlation_cache: Option<crate::fred_analysis::CorrelationMatrix>,
    pub config: SignalsConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalsConfig {
    pub xauusd_symbols: Vec<String>,
    pub min_confidence: f64,
    pub min_z_score: f64,
    pub cache_ttl_seconds: u64,
}

impl Default for FredSignalsState {
    fn default() -> Self {
        Self {
            signals_cache: HashMap::new(),
            indicators_cache: HashMap::new(),
            correlation_cache: None,
            config: SignalsConfig {
                xauusd_symbols: XAUUSD_RELEVANT_SERIES.iter().map(|s| s.to_string()).collect(),
                min_confidence: 0.5,
                min_z_score: 0.5,
                cache_ttl_seconds: 3600,
            },
        }
    }
}

impl FredSignalsState {
    pub fn new() -> Self {
        Self::default()
    }
}

#[tauri::command]
pub async fn fred_signals_init(
    _state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
) -> Result<String, String> {
    tracing::info!("FRED Signals module initialized");
    Ok("FRED Signals module initialized".to_string())
}

#[tauri::command]
pub async fn fred_generate_signals(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<Vec<TradingSignal>, String> {
    let config = {
        let s = state.read().await;
        s.config.clone()
    };

    let client = {
        let s = fred_state.read().await;
        s.client.clone()
    };

    let mut signals = Vec::new();

    for series_id in &config.xauusd_symbols {
        match generate_signal_for_series(&client, series_id).await {
            Ok(signal) => signals.push(signal),
            Err(e) => {
                tracing::warn!("Failed to generate signal for {}: {}", series_id, e);
            }
        }
    }

    {
        let mut s = state.write().await;
        let date_key = Utc::now().format("%Y-%m-%d").to_string();
        s.signals_cache.insert(date_key, signals.clone());
    }

    tracing::info!("Generated {} trading signals", signals.len());
    Ok(signals)
}

async fn generate_signal_for_series(
    client: &FredClient,
    series_id: &str,
) -> Result<TradingSignal, String> {
    let obs = client
        .get_series_observations(
            series_id,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;

    let mut data: Vec<(String, f64)> = obs
        .observations
        .into_iter()
        .filter_map(|o| {
            let val = o.value.parse::<f64>().ok();
            val.map(|v| (o.date, v))
        })
        .collect();

    data.sort_by(|a, b| a.0.cmp(&b.0));

    if data.len() < 12 {
        return Err("Insufficient data points".to_string());
    }

    let analysis = AnalysisEngine::analyze_series(
        series_id.to_string(),
        series_id.to_string(),
        data.clone(),
    );

    let _current_value = analysis.stats.current_value;
    let z_score = analysis.stats.z_score_current;
    let percentile = analysis.stats.percentile_current;

    let direction = if z_score > 1.0 {
        SignalDirection::Sell
    } else if z_score < -1.0 {
        SignalDirection::Buy
    } else {
        SignalDirection::Neutral
    };

    let strength = (z_score.abs() / 3.0).min(1.0);
    let confidence = (percentile / 100.0).abs();

    let mom_change = analysis
        .transformations
        .mom_change
        .last()
        .map(|p| p.value)
        .unwrap_or(0.0);

    let trend = if mom_change > 0.0 {
        "Bullish".to_string()
    } else if mom_change < 0.0 {
        "Bearish".to_string()
    } else {
        "Neutral".to_string()
    };

    let date = data.last().map(|(d, _)| d.clone()).unwrap_or_default();

    Ok(TradingSignal {
        id: format!("{}_{}", series_id, date),
        date,
        symbol: "XAUUSD".to_string(),
        direction,
        strength,
        confidence,
        source_series: vec![series_id.to_string()],
        metadata: SignalMetadata {
            indicator_type: get_indicator_type(series_id),
            z_score,
            percentile,
            trend,
            volatility: analysis.stats.max - analysis.stats.min,
        },
    })
}

fn get_indicator_type(series_id: &str) -> String {
    match series_id {
        "DFII10" | "DFII5" => "Inflation Expectation".to_string(),
        "DGS10" | "DGS2" | "DGS30" => "Interest Rate".to_string(),
        "DTIN3M" => "Treasury Yield".to_string(),
        "IC4WSA" => "Credit Conditions".to_string(),
        "MORTGAGE30US" => "Mortgage Rate".to_string(),
        "PCEPI" | "CPALTT01USM657N" => "Inflation".to_string(),
        "UNRATE" => "Unemployment".to_string(),
        "GDPC1" => "GDP Growth".to_string(),
        "BOPGSTB" => "Trade Balance".to_string(),
        "XRGUSD" => "Gold Price".to_string(),
        _ => "Economic Indicator".to_string(),
    }
}

#[tauri::command]
pub async fn fred_get_latest_signals(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
) -> Result<Vec<TradingSignal>, String> {
    let signals_cache = {
        let s = state.read().await;
        s.signals_cache.clone()
    };

    if signals_cache.is_empty() {
        return Ok(Vec::new());
    }

    let latest_key = signals_cache
        .keys()
        .max()
        .cloned()
        .ok_or("No signals available")?;

    signals_cache
        .get(&latest_key)
        .cloned()
        .ok_or("No signals available for latest date".to_string())
}

#[tauri::command]
pub async fn fred_get_signal_history(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    start_date: Option<String>,
    end_date: Option<String>,
    limit: Option<usize>,
) -> Result<Vec<TradingSignal>, String> {
    let signals_cache = {
        let s = state.read().await;
        s.signals_cache.clone()
    };

    let mut all_signals: Vec<TradingSignal> = signals_cache
        .values()
        .flatten()
        .cloned()
        .collect();

    if let Some(start) = start_date {
        all_signals.retain(|s| s.date >= start);
    }
    if let Some(end) = end_date {
        all_signals.retain(|s| s.date <= end);
    }

    all_signals.sort_by(|a, b| b.date.cmp(&a.date));

    if let Some(l) = limit {
        all_signals.truncate(l);
    }

    Ok(all_signals)
}

#[tauri::command]
pub async fn fred_get_signal_by_date(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    date: String,
) -> Result<Vec<TradingSignal>, String> {
    let signals_cache = {
        let s = state.read().await;
        s.signals_cache.clone()
    };

    signals_cache
        .get(&date)
        .cloned()
        .ok_or_else(|| format!("No signals found for date: {}", date))
}

#[tauri::command]
pub async fn fred_get_composite_signal(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<CompositeSignal, String> {
    let signals = fred_generate_signals(state.clone(), fred_state.clone()).await?;

    if signals.is_empty() {
        return Err("No signals available".to_string());
    }

    let mut breakdown_items: Vec<SignalBreakdownItem> = Vec::new();
    let mut buy_count = 0;
    let mut sell_count = 0;
    let mut total_strength = 0.0;
    let mut total_confidence = 0.0;

    for signal in &signals {
        let contribution = match signal.direction {
            SignalDirection::Buy => {
                buy_count += 1;
                signal.strength
            }
            SignalDirection::Sell => {
                sell_count += 1;
                -signal.strength
            }
            SignalDirection::Neutral => 0.0,
        };

        breakdown_items.push(SignalBreakdownItem {
            series_id: signal.source_series.first().cloned().unwrap_or_default(),
            series_name: signal.metadata.indicator_type.clone(),
            contribution,
            direction: signal.direction.clone(),
            strength: signal.strength,
            current_value: signal.metadata.z_score,
            z_score: signal.metadata.z_score,
            percentile: signal.metadata.percentile,
        });

        total_strength += signal.strength;
        total_confidence += signal.confidence;
    }

    let avg_strength = total_strength / signals.len() as f64;
    let avg_confidence = total_confidence / signals.len() as f64;

    let overall_direction = if buy_count > sell_count {
        SignalDirection::Buy
    } else if sell_count > buy_count {
        SignalDirection::Sell
    } else {
        SignalDirection::Neutral
    };

    let volatility_index = signals
        .iter()
        .map(|s| s.metadata.volatility)
        .sum::<f64>()
        / signals.len() as f64;

    let risk_score = (volatility_index / 100.0).min(1.0);
    let recommended_position_size = (1.0 - risk_score * 0.5) * 0.1;

    let date = signals
        .first()
        .map(|s| s.date.clone())
        .unwrap_or_else(|| Utc::now().format("%Y-%m-%d").to_string());

    Ok(CompositeSignal {
        symbol: "XAUUSD".to_string(),
        date,
        overall_direction,
        strength: avg_strength,
        confidence: avg_confidence,
        component_signals: breakdown_items,
        risk_metrics: RiskMetrics {
            volatility_index,
            max_series_correlation: 0.0,
            risk_score,
            recommended_position_size,
        },
    })
}

#[tauri::command]
pub async fn fred_get_signal_breakdown(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<HashMap<String, Vec<SignalBreakdownItem>>, String> {
    let signals = fred_generate_signals(state, fred_state).await?;

    let mut breakdown: HashMap<String, Vec<SignalBreakdownItem>> = HashMap::new();

    for signal in signals {
        let item = SignalBreakdownItem {
            series_id: signal.source_series.first().cloned().unwrap_or_default(),
            series_name: signal.metadata.indicator_type.clone(),
            contribution: match signal.direction {
                SignalDirection::Buy => signal.strength,
                SignalDirection::Sell => -signal.strength,
                SignalDirection::Neutral => 0.0,
            },
            direction: signal.direction,
            strength: signal.strength,
            current_value: signal.metadata.z_score,
            z_score: signal.metadata.z_score,
            percentile: signal.metadata.percentile,
        };

        breakdown
            .entry(signal.metadata.indicator_type.clone())
            .or_insert_with(Vec::new)
            .push(item);
    }

    Ok(breakdown)
}

#[tauri::command]
pub async fn fred_get_signal_strength(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<SignalStrength, String> {
    let signals = fred_generate_signals(state, fred_state).await?;

    if signals.is_empty() {
        return Ok(SignalStrength {
            total_signals: 0,
            buy_signals: 0,
            sell_signals: 0,
            neutral_signals: 0,
            average_strength: 0.0,
            average_confidence: 0.0,
            dominant_direction: SignalDirection::Neutral,
            consensus_score: 0.0,
        });
    }

    let buy_signals = signals.iter().filter(|s| s.direction == SignalDirection::Buy).count();
    let sell_signals = signals.iter().filter(|s| s.direction == SignalDirection::Sell).count();
    let neutral_signals = signals.iter().filter(|s| s.direction == SignalDirection::Neutral).count();

    let total_strength: f64 = signals.iter().map(|s| s.strength).sum();
    let total_confidence: f64 = signals.iter().map(|s| s.confidence).sum();

    let avg_strength = total_strength / signals.len() as f64;
    let avg_confidence = total_confidence / signals.len() as f64;

    let dominant_direction = if buy_signals > sell_signals {
        SignalDirection::Buy
    } else if sell_signals > buy_signals {
        SignalDirection::Sell
    } else {
        SignalDirection::Neutral
    };

    let max_direction_count = buy_signals.max(sell_signals).max(neutral_signals);
    let consensus_score = max_direction_count as f64 / signals.len() as f64;

    Ok(SignalStrength {
        total_signals: signals.len(),
        buy_signals,
        sell_signals,
        neutral_signals,
        average_strength: avg_strength,
        average_confidence: avg_confidence,
        dominant_direction,
        consensus_score,
    })
}

#[tauri::command]
pub async fn fred_get_xauusd_signal(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<CompositeSignal, String> {
    fred_get_composite_signal(state, fred_state).await
}

#[tauri::command]
pub async fn fred_get_position_recommendation(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
    account_balance: Option<f64>,
) -> Result<PositionRecommendation, String> {
    let composite = fred_get_composite_signal(state, fred_state).await?;

    let balance = account_balance.unwrap_or(100000.0);
    let risk_per_trade = 0.02;

    let direction = composite.overall_direction.clone();
    let position_size = composite.risk_metrics.recommended_position_size;

    let actual_position_size = balance * position_size * risk_per_trade;

    let stop_loss_distance = match direction {
        SignalDirection::Buy => 50.0,
        SignalDirection::Sell => 50.0,
        SignalDirection::Neutral => 0.0,
    };

    let take_profit_distance = stop_loss_distance * 2.0;

    let risk_reward_ratio = if stop_loss_distance > 0.0 {
        take_profit_distance / stop_loss_distance
    } else {
        0.0
    };

    let rationale = match direction {
        SignalDirection::Buy => format!(
            "XAUUSD BUY signal based on {} supporting indicators. Risk score: {:.2}",
            composite.component_signals.iter().filter(|s| s.direction == SignalDirection::Buy).count(),
            composite.risk_metrics.risk_score
        ),
        SignalDirection::Sell => format!(
            "XAUUSD SELL signal based on {} supporting indicators. Risk score: {:.2}",
            composite.component_signals.iter().filter(|s| s.direction == SignalDirection::Sell).count(),
            composite.risk_metrics.risk_score
        ),
        SignalDirection::Neutral => "No clear directional signal from FRED indicators. Consider waiting.".to_string(),
    };

    Ok(PositionRecommendation {
        symbol: "XAUUSD".to_string(),
        direction,
        position_size: actual_position_size,
        risk_percentage: risk_per_trade * 100.0,
        stop_loss_distance,
        take_profit_distance,
        risk_reward_ratio,
        rationale,
    })
}

#[tauri::command]
pub async fn fred_apply_filters(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
    filters: FilterConfig,
) -> Result<Vec<FilteredSignal>, String> {
    let signals = fred_generate_signals(state.clone(), fred_state.clone()).await?;

    let mut filtered_signals: Vec<FilteredSignal> = Vec::new();

    for signal in signals {
        let mut failed_filters: Vec<String> = Vec::new();
        let mut passed = true;

        if signal.confidence < filters.min_confidence {
            failed_filters.push(format!(
                "confidence ({:.2} < {:.2})",
                signal.confidence, filters.min_confidence
            ));
            passed = false;
        }

        if signal.strength < filters.min_strength {
            failed_filters.push(format!(
                "strength ({:.2} < {:.2})",
                signal.strength, filters.min_strength
            ));
            passed = false;
        }

        if signal.metadata.volatility > filters.max_volatility {
            failed_filters.push(format!(
                "volatility ({:.2} > {:.2})",
                signal.metadata.volatility, filters.max_volatility
            ));
            passed = false;
        }

        if filters.exclude_series.iter().any(|s| signal.source_series.contains(s)) {
            failed_filters.push("excluded_series".to_string());
            passed = false;
        }

        let adjusted_strength = if passed {
            signal.strength
        } else {
            signal.strength * 0.5
        };

        filtered_signals.push(FilteredSignal {
            original_signal: signal,
            passed_filters: passed,
            failed_filters,
            adjusted_strength,
        });
    }

    Ok(filtered_signals)
}

#[tauri::command]
pub async fn fred_get_indicators(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
) -> Result<Vec<IndicatorValue>, String> {
    let config = {
        let s = state.read().await;
        s.config.clone()
    };

    let client = {
        let s = fred_state.read().await;
        s.client.clone()
    };

    let mut indicators = Vec::new();

    for series_id in &config.xauusd_symbols {
        match fetch_indicator_value(&client, series_id).await {
            Ok(ind) => indicators.push(ind),
            Err(e) => {
                tracing::warn!("Failed to fetch indicator {}: {}", series_id, e);
            }
        }
    }

    {
        let mut s = state.write().await;
        for ind in &indicators {
            s.indicators_cache.insert(ind.series_id.clone(), ind.clone());
        }
    }

    Ok(indicators)
}

async fn fetch_indicator_value(
    client: &FredClient,
    series_id: &str,
) -> Result<IndicatorValue, String> {
    let obs = client
        .get_series_observations(
            series_id,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;

    let mut data: Vec<(String, f64)> = obs
        .observations
        .into_iter()
        .filter_map(|o| {
            let val = o.value.parse::<f64>().ok();
            val.map(|v| (o.date, v))
        })
        .collect();

    data.sort_by(|a, b| a.0.cmp(&b.0));

    if data.len() < 13 {
        return Err("Insufficient data".to_string());
    }

    let analysis = AnalysisEngine::analyze_series(
        series_id.to_string(),
        series_id.to_string(),
        data.clone(),
    );

    let change_1m = analysis
        .transformations
        .mom_change
        .last()
        .map(|p| p.value)
        .unwrap_or(0.0);

    let change_12m = analysis
        .transformations
        .yoy_change
        .last()
        .map(|p| p.value)
        .unwrap_or(0.0);

    let date = data.last().map(|(d, _)| d.clone()).unwrap_or_default();

    Ok(IndicatorValue {
        series_id: series_id.to_string(),
        name: get_indicator_type(series_id),
        value: analysis.stats.current_value,
        date,
        z_score: analysis.stats.z_score_current,
        percentile: analysis.stats.percentile_current,
        change_1m,
        change_12m,
        volatility: analysis.stats.max - analysis.stats.min,
    })
}

#[tauri::command]
pub async fn fred_get_historical_indicators(
    series_id: String,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
    start_date: Option<String>,
    end_date: Option<String>,
) -> Result<Vec<HistoricalIndicator>, String> {
    let client = {
        let s = fred_state.read().await;
        s.client.clone()
    };

    let obs = client
        .get_series_observations(
            &series_id,
            None,
            None,
            start_date.as_deref(),
            end_date.as_deref(),
            None,
            None,
            None,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;

    let mut data: Vec<(String, f64)> = obs
        .observations
        .into_iter()
        .filter_map(|o| {
            let val = o.value.parse::<f64>().ok();
            val.map(|v| (o.date, v))
        })
        .collect();

    data.sort_by(|a, b| a.0.cmp(&b.0));

    if data.len() < 12 {
        return Err("Insufficient data points".to_string());
    }

    let analysis = AnalysisEngine::analyze_series(
        series_id.clone(),
        series_id.clone(),
        data.clone(),
    );

    let stats = &analysis.stats;
    let mean = stats.mean;
    let std_dev = (stats.max - stats.min) / 4.0;

    let mut historical: Vec<HistoricalIndicator> = data
        .iter()
        .map(|(date, value)| {
            let z_score = if std_dev > 0.0 {
                (value - mean) / std_dev
            } else {
                0.0
            };

            let mut sorted_values: Vec<f64> = data.iter().map(|(_, v)| *v).collect();
            sorted_values.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let position = sorted_values.iter().position(|x| (*x - value).abs() < 0.001).unwrap_or(0);
            let percentile = (position as f64 / sorted_values.len() as f64) * 100.0;

            HistoricalIndicator {
                series_id: series_id.clone(),
                date: date.clone(),
                value: *value,
                z_score,
                percentile,
            }
        })
        .collect();

    historical.sort_by(|a, b| a.date.cmp(&b.date));

    Ok(historical)
}

#[tauri::command]
pub async fn fred_get_indicator_correlations(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    fred_state: tauri::State<'_, Arc<RwLock<FredState>>>,
    series_ids: Option<Vec<String>>,
) -> Result<Vec<IndicatorCorrelation>, String> {
    let config = {
        let s = state.read().await;
        s.config.clone()
    };

    let series_list = series_ids.unwrap_or(config.xauusd_symbols);

    if series_list.len() < 2 {
        return Err("At least 2 series required for correlation".to_string());
    }

    let client = {
        let s = fred_state.read().await;
        s.client.clone()
    };

    let mut series_data: HashMap<String, Vec<(String, f64)>> = HashMap::new();

    for series_id in &series_list {
        let obs = client
            .get_series_observations(
                series_id,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            .await
            .map_err(|e| format!("Error fetching {}: {}", series_id, e))?;

        let data: Vec<(String, f64)> = obs
            .observations
            .into_iter()
            .filter_map(|o| {
                let val = o.value.parse::<f64>().ok();
                val.map(|v| (o.date, v))
            })
            .collect();

        series_data.insert(series_id.clone(), data);
    }

    let matrix = AnalysisEngine::calculate_correlation_matrix(series_data);

    let mut correlations: Vec<IndicatorCorrelation> = Vec::new();

    for i in 0..matrix.series_ids.len() {
        for j in (i + 1)..matrix.series_ids.len() {
            let corr_value = matrix.matrix[i][j];
            let strength = if corr_value.abs() > 0.7 {
                "Strong"
            } else if corr_value.abs() > 0.4 {
                "Moderate"
            } else {
                "Weak"
            };

            correlations.push(IndicatorCorrelation {
                series_a: matrix.series_ids[i].clone(),
                series_b: matrix.series_ids[j].clone(),
                correlation: corr_value,
                strength: strength.to_string(),
            });
        }
    }

    correlations.sort_by(|a, b| b.correlation.abs().partial_cmp(&a.correlation.abs()).unwrap());

    Ok(correlations)
}

#[tauri::command]
pub async fn fred_signals_clear_cache(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
) -> Result<String, String> {
    let mut s = state.write().await;
    s.signals_cache.clear();
    s.indicators_cache.clear();
    s.correlation_cache = None;
    tracing::info!("FRED signals cache cleared");
    Ok("Cache cleared".to_string())
}

#[tauri::command]
pub async fn fred_signals_get_config(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
) -> Result<SignalsConfig, String> {
    let s = state.read().await;
    Ok(s.config.clone())
}

#[tauri::command]
pub async fn fred_signals_update_config(
    state: tauri::State<'_, Arc<RwLock<FredSignalsState>>>,
    config: SignalsConfig,
) -> Result<String, String> {
    let mut s = state.write().await;
    s.config = config;
    tracing::info!("FRED signals config updated");
    Ok("Config updated".to_string())
}
