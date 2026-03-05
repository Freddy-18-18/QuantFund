use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

/// Controls how orders are filled in simulation.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FillModel {
    /// Whether partial fills are enabled.
    pub partial_fill_enabled: bool,
    /// Minimum fill percentage (0.0 - 1.0).
    pub min_fill_pct: Decimal,
}

impl Default for FillModel {
    fn default() -> Self {
        Self {
            partial_fill_enabled: false,
            min_fill_pct: Decimal::ONE,
        }
    }
}

/// Models execution slippage.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SlippageModel {
    /// Fixed base slippage in pips.
    pub base_slippage_pips: Decimal,
    /// Multiplier applied to current ATR.
    pub volatility_factor: Decimal,
    /// Impact factor for position size.
    pub volume_impact: Decimal,
}

impl Default for SlippageModel {
    fn default() -> Self {
        Self {
            // Retail-like: 0.5 pip base slippage
            base_slippage_pips: Decimal::new(5, 1),
            // Moderate volatility sensitivity
            volatility_factor: Decimal::new(1, 1),
            // Small volume impact
            volume_impact: Decimal::new(5, 2),
        }
    }
}

/// Models execution latency.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LatencyModel {
    /// Base latency in milliseconds.
    pub base_latency_ms: u32,
    /// Random jitter range in milliseconds.
    pub jitter_ms: u32,
    /// Probability of a latency spike (0.0 - 1.0).
    pub spike_probability: f64,
    /// Maximum spike latency in milliseconds.
    pub spike_max_ms: u32,
}

impl Default for LatencyModel {
    fn default() -> Self {
        Self {
            // Retail broker: ~50ms base latency
            base_latency_ms: 50,
            // ±20ms jitter
            jitter_ms: 20,
            // 2% chance of spike
            spike_probability: 0.02,
            // Spike up to 500ms
            spike_max_ms: 500,
        }
    }
}

/// Combined execution model configuration.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[derive(Default)]
pub struct ExecutionModelConfig {
    pub fill: FillModel,
    pub slippage: SlippageModel,
    pub latency: LatencyModel,
}

