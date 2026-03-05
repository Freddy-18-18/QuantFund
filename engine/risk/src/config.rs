use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use serde::{Deserialize, Serialize};

/// Multi-layer risk configuration.
///
/// Limits are organised into four escalating layers:
///
/// 1. **Trade-level** — per-order sanity checks (size, spread, slippage).
/// 2. **Strategy-level** — per-strategy drawdown and position caps.
/// 3. **Portfolio-level** — aggregate exposure, heat, and daily loss.
/// 4. **Kill switch** — hard circuit breakers that halt all trading.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RiskConfig {
    // Layer 1: Trade-level
    /// Maximum lots per single position.
    pub max_position_size: Decimal,
    /// Maximum lots per single order.
    pub max_order_size: Decimal,
    /// Reject order if spread exceeds this many pips.
    pub max_spread_pips: Decimal,
    /// Maximum acceptable slippage in pips.
    pub max_slippage_pips: Decimal,

    // Layer 2: Strategy-level
    /// Maximum drawdown per strategy as a fraction of equity (e.g. 0.05 = 5%).
    pub max_drawdown_per_strategy: Decimal,
    /// Maximum concurrent positions per strategy.
    pub max_positions_per_strategy: usize,
    /// Cap on rolling realised volatility.
    pub rolling_volatility_cap: Decimal,

    // Layer 3: Portfolio-level
    /// Maximum gross exposure as a fraction of equity.
    pub max_gross_exposure: Decimal,
    /// Maximum net (directional) exposure as a fraction of equity.
    pub max_net_exposure: Decimal,
    /// Maximum total open positions across all strategies.
    pub max_total_positions: usize,
    /// Maximum portfolio heat (sum of all position risk, as fraction of equity).
    pub max_portfolio_heat: Decimal,
    /// Maximum daily loss as a fraction of equity (e.g. 0.02 = 2%).
    pub max_daily_loss: Decimal,

    // Layer 4: Kill switch
    /// Drawdown from peak equity that triggers a full halt (e.g. 0.10 = 10%).
    pub kill_switch_drawdown: Decimal,
    /// Minimum margin level (e.g. 1.5 = 150%). Below this, halt trading.
    pub min_margin_level: Decimal,
}

impl Default for RiskConfig {
    /// Conservative defaults suitable for a newly deployed strategy.
    fn default() -> Self {
        Self {
            // Layer 1
            max_position_size: dec!(1.0),
            max_order_size: dec!(1.0),
            max_spread_pips: dec!(5.0),
            max_slippage_pips: dec!(3.0),

            // Layer 2
            max_drawdown_per_strategy: dec!(0.05),
            max_positions_per_strategy: 3,
            rolling_volatility_cap: dec!(0.02),

            // Layer 3
            max_gross_exposure: dec!(2.0),
            max_net_exposure: dec!(1.0),
            max_total_positions: 10,
            max_portfolio_heat: dec!(0.06),
            max_daily_loss: dec!(0.02),

            // Layer 4
            kill_switch_drawdown: dec!(0.10),
            min_margin_level: dec!(1.5),
        }
    }
}
