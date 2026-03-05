use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

// ─── Fill Model ──────────────────────────────────────────────────────────────

/// Controls how orders are filled in simulation.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FillModel {
    /// Whether partial fills are enabled.
    pub partial_fill_enabled: bool,
    /// Minimum fill ratio per tick (0.0 - 1.0) when partial fills are active.
    pub min_fill_ratio: Decimal,
    /// Maximum fill ratio per tick (0.0 - 1.0) when partial fills are active.
    pub max_fill_ratio: Decimal,
    /// Available liquidity as a multiple of average tick volume.
    /// Orders larger than `tick_volume * liquidity_factor` will be partially filled.
    pub liquidity_factor: Decimal,
}

impl Default for FillModel {
    fn default() -> Self {
        Self {
            partial_fill_enabled: false,
            min_fill_ratio: Decimal::new(2, 1),   // 0.2 = 20%
            max_fill_ratio: Decimal::ONE,         // 1.0 = 100%
            liquidity_factor: Decimal::new(5, 0), // 5x tick volume
        }
    }
}

// ─── Slippage Distribution ───────────────────────────────────────────────────

/// The probability distribution used for slippage sampling.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub enum SlippageDistribution {
    /// Fixed slippage (deterministic, no randomness).
    Fixed,
    /// Uniform distribution between 0 and base_slippage_pips.
    #[default]
    Uniform,
    /// Triangular distribution peaking at base_slippage_pips / 2.
    /// Models "most fills near half the max slippage" — a realistic retail shape.
    Triangular,
    /// Exponential-like: heavy skew toward small slippage, rare large slippage.
    /// The `lambda` field in SlippageModel controls the decay rate.
    Exponential,
}

// ─── Slippage Model ──────────────────────────────────────────────────────────

/// Models execution slippage.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SlippageModel {
    /// Fixed base slippage in pips.
    pub base_slippage_pips: Decimal,
    /// Multiplier applied to current volatility estimate.
    pub volatility_factor: Decimal,
    /// Impact factor: additional slippage per lot of order volume.
    pub volume_impact: Decimal,
    /// Distribution used for slippage sampling.
    pub distribution: SlippageDistribution,
    /// Pip value as a fraction of price. For forex, 0.0001 (4-digit).
    pub pip_value: Decimal,
}

impl Default for SlippageModel {
    fn default() -> Self {
        Self {
            // Retail-like: 0.5 pip base slippage.
            base_slippage_pips: Decimal::new(5, 1),
            // Moderate volatility sensitivity.
            volatility_factor: Decimal::new(1, 1),
            // Small volume impact (pips per lot).
            volume_impact: Decimal::new(5, 2),
            distribution: SlippageDistribution::default(),
            // Default: 4-digit forex pip.
            pip_value: Decimal::new(1, 4),
        }
    }
}

// ─── Latency Model ───────────────────────────────────────────────────────────

/// Models execution latency (delay between order submission and fill).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LatencyModel {
    /// Whether latency injection is enabled.
    pub enabled: bool,
    /// Base latency in microseconds (not milliseconds — we operate at µs precision).
    pub base_latency_us: u64,
    /// Random jitter range in microseconds.
    pub jitter_us: u64,
    /// Probability of a latency spike (0.0 - 1.0).
    pub spike_probability: f64,
    /// Maximum spike latency in microseconds.
    pub spike_max_us: u64,
}

impl Default for LatencyModel {
    fn default() -> Self {
        Self {
            enabled: false,
            // Retail broker: ~50ms = 50_000µs base latency.
            base_latency_us: 50_000,
            // ±20ms = 20_000µs jitter.
            jitter_us: 20_000,
            // 2% chance of spike.
            spike_probability: 0.02,
            // Spike up to 500ms = 500_000µs.
            spike_max_us: 500_000,
        }
    }
}

// ─── Market Impact Model ─────────────────────────────────────────────────────

/// Models market impact for large orders.
/// Uses a square-root impact model: impact = eta * sigma * sqrt(V/ADV)
///   where V = order volume, ADV = average daily volume, sigma = volatility.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MarketImpactModel {
    /// Whether market impact simulation is enabled.
    pub enabled: bool,
    /// Temporary impact coefficient (eta). Higher = more temporary slippage.
    /// Temporary impact decays after the trade.
    pub temporary_impact_eta: Decimal,
    /// Permanent impact coefficient (gamma). Fraction of temporary impact that persists.
    /// In [0, 1]. 0 = fully temporary, 1 = fully permanent.
    pub permanent_impact_ratio: Decimal,
    /// Estimated average daily volume (ADV) for the instrument in lots.
    /// Used as normalisation denominator in the impact formula.
    pub estimated_adv: Decimal,
    /// Decay factor for temporary impact per tick (0..1). Lower = faster decay.
    pub temporary_decay_rate: Decimal,
}

impl Default for MarketImpactModel {
    fn default() -> Self {
        Self {
            enabled: false,
            // Moderate temporary impact.
            temporary_impact_eta: Decimal::new(5, 2), // 0.05
            // 10% of temporary impact becomes permanent.
            permanent_impact_ratio: Decimal::new(1, 1), // 0.1
            // Default ADV = 10_000 lots.
            estimated_adv: Decimal::new(10_000, 0),
            // 95% of temporary impact remains per tick.
            temporary_decay_rate: Decimal::new(95, 2), // 0.95
        }
    }
}

// ─── Venue Configuration ─────────────────────────────────────────────────────

/// Per-venue execution characteristics.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VenueConfig {
    /// Human-readable venue name (e.g., "MT5-Demo", "Binance-Spot").
    pub name: String,
    /// Latency model specific to this venue.
    pub latency: LatencyModel,
    /// Whether the venue supports partial fills.
    pub supports_partial_fills: bool,
    /// Minimum order size (lots).
    pub min_order_size: Decimal,
    /// Order size step (lots). Orders are rounded to this granularity.
    pub order_size_step: Decimal,
}

impl Default for VenueConfig {
    fn default() -> Self {
        Self {
            name: "default".to_owned(),
            latency: LatencyModel::default(),
            supports_partial_fills: true,
            min_order_size: Decimal::new(1, 2),  // 0.01 lots
            order_size_step: Decimal::new(1, 2), // 0.01 lots
        }
    }
}

// ─── Combined Configuration ──────────────────────────────────────────────────

/// Combined execution model configuration.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ExecutionModelConfig {
    pub fill: FillModel,
    pub slippage: SlippageModel,
    pub latency: LatencyModel,
    pub impact: MarketImpactModel,
    pub venue: VenueConfig,
}
