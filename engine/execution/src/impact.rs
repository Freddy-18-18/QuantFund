use std::collections::HashMap;

use rust_decimal::Decimal;
use rust_decimal_macros::dec;

use quantfund_core::instrument::InstrumentId;
use quantfund_core::types::{Price, Side, Volume};

use crate::models::MarketImpactModel;

// Re-export `decimal_sqrt` from the risk crate to avoid duplicating Newton's method.
use quantfund_risk::volatility::decimal_sqrt;

// ─── Impact State ────────────────────────────────────────────────────────────

/// Tracks accumulated temporary impact per instrument.
/// Temporary impact decays over time (per tick) while permanent impact persists.
#[derive(Clone, Debug)]
struct ImpactState {
    /// Current accumulated temporary impact as a fraction of price.
    /// Positive = price pushed up, negative = price pushed down.
    temporary: Decimal,
    /// Accumulated permanent impact as a fraction of price.
    permanent: Decimal,
}

// ─── Market Impact Simulator ─────────────────────────────────────────────────

/// Simulates market impact using a square-root model.
///
/// Standard model from Almgren & Chriss (2000):
///   temporary_impact = eta * sigma * sqrt(V / ADV)
///   permanent_impact = gamma * temporary_impact
///
/// Where:
///   eta   = temporary impact coefficient
///   sigma = estimated volatility (passed in per-trade)
///   V     = order volume
///   ADV   = average daily volume
///   gamma = permanent impact ratio
///
/// The temporary component decays exponentially per tick.
/// The permanent component persists until manually reset.
pub struct MarketImpactSimulator {
    config: MarketImpactModel,
    /// Per-instrument impact state.
    states: HashMap<InstrumentId, ImpactState>,
}

impl MarketImpactSimulator {
    pub fn new(config: MarketImpactModel) -> Self {
        Self {
            config,
            states: HashMap::new(),
        }
    }

    /// Calculate the market impact for a trade and update the impact state.
    ///
    /// Returns the total impact as a price adjustment (in price units, not pips).
    /// The sign is always unfavorable to the trader: positive for buys, negative for sells.
    ///
    /// `volatility_estimate` should be the current realized volatility for the instrument
    /// (e.g., from the EWMA volatility tracker). Pass `Decimal::ZERO` if unavailable.
    pub fn compute_impact(
        &mut self,
        instrument_id: &InstrumentId,
        side: Side,
        volume: &Volume,
        base_price: &Price,
        volatility_estimate: Decimal,
    ) -> Decimal {
        if !self.config.enabled {
            return Decimal::ZERO;
        }

        // Participation rate: V / ADV.
        let participation = if self.config.estimated_adv > Decimal::ZERO {
            **volume / self.config.estimated_adv
        } else {
            Decimal::ZERO
        };

        // sqrt(participation rate).
        let sqrt_participation = decimal_sqrt(participation);

        // Temporary impact = eta * sigma * sqrt(V/ADV).
        let sigma = if volatility_estimate > Decimal::ZERO {
            volatility_estimate
        } else {
            dec!(0.001) // Fallback: 0.1% daily vol if unknown.
        };

        let temp_impact_frac = self.config.temporary_impact_eta * sigma * sqrt_participation;

        // Permanent impact = gamma * temporary.
        let perm_impact_frac = self.config.permanent_impact_ratio * temp_impact_frac;

        // Update state.
        let state = self
            .states
            .entry(instrument_id.clone())
            .or_insert(ImpactState {
                temporary: Decimal::ZERO,
                permanent: Decimal::ZERO,
            });

        // Direction multiplier: buys push price up, sells push it down.
        let direction = match side {
            Side::Buy => Decimal::ONE,
            Side::Sell => -Decimal::ONE,
        };

        state.temporary += direction * temp_impact_frac;
        state.permanent += direction * perm_impact_frac;

        // Total impact in price units (always unfavorable to trader).
        let total_frac = temp_impact_frac + perm_impact_frac;
        total_frac * **base_price
    }

    /// Decay the temporary impact for all instruments.
    /// Should be called once per tick.
    pub fn decay_temporary(&mut self) {
        if !self.config.enabled {
            return;
        }

        for state in self.states.values_mut() {
            state.temporary *= self.config.temporary_decay_rate;
            // Zero out negligible values to prevent accumulation of dust.
            if state.temporary.abs() < dec!(0.0000001) {
                state.temporary = Decimal::ZERO;
            }
        }
    }

    /// Get the current total impact (temporary + permanent) for an instrument
    /// as a fraction of price. Can be used for spread dynamics simulation.
    pub fn current_impact(&self, instrument_id: &InstrumentId) -> Decimal {
        self.states
            .get(instrument_id)
            .map(|s| s.temporary + s.permanent)
            .unwrap_or(Decimal::ZERO)
    }

    /// Get the current temporary impact for an instrument (as a fraction).
    pub fn temporary_impact(&self, instrument_id: &InstrumentId) -> Decimal {
        self.states
            .get(instrument_id)
            .map(|s| s.temporary)
            .unwrap_or(Decimal::ZERO)
    }

    /// Get the accumulated permanent impact for an instrument (as a fraction).
    pub fn permanent_impact(&self, instrument_id: &InstrumentId) -> Decimal {
        self.states
            .get(instrument_id)
            .map(|s| s.permanent)
            .unwrap_or(Decimal::ZERO)
    }

    /// Reset all impact state (e.g., at session boundary or for a new backtest).
    pub fn reset(&mut self) {
        self.states.clear();
    }

    /// Whether market impact simulation is enabled.
    pub fn is_enabled(&self) -> bool {
        self.config.enabled
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn enabled_config() -> MarketImpactModel {
        MarketImpactModel {
            enabled: true,
            temporary_impact_eta: dec!(0.05),
            permanent_impact_ratio: dec!(0.1),
            estimated_adv: dec!(10000),
            temporary_decay_rate: dec!(0.95),
        }
    }

    fn disabled_config() -> MarketImpactModel {
        MarketImpactModel {
            enabled: false,
            ..enabled_config()
        }
    }

    #[test]
    fn disabled_returns_zero() {
        let mut sim = MarketImpactSimulator::new(disabled_config());
        let impact = sim.compute_impact(
            &InstrumentId::new("EURUSD"),
            Side::Buy,
            &Volume::new(dec!(100)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );
        assert_eq!(impact, Decimal::ZERO);
    }

    #[test]
    fn larger_volume_more_impact() {
        let mut sim1 = MarketImpactSimulator::new(enabled_config());
        let mut sim2 = MarketImpactSimulator::new(enabled_config());

        let small = sim1.compute_impact(
            &InstrumentId::new("EURUSD"),
            Side::Buy,
            &Volume::new(dec!(1)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );
        let large = sim2.compute_impact(
            &InstrumentId::new("EURUSD"),
            Side::Buy,
            &Volume::new(dec!(100)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );

        assert!(large > small, "large={large} should > small={small}");
    }

    #[test]
    fn impact_is_always_positive() {
        let mut sim = MarketImpactSimulator::new(enabled_config());

        let buy_impact = sim.compute_impact(
            &InstrumentId::new("EURUSD"),
            Side::Buy,
            &Volume::new(dec!(10)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );
        assert!(buy_impact > Decimal::ZERO);

        // Reset for independent sell test.
        sim.reset();
        let sell_impact = sim.compute_impact(
            &InstrumentId::new("EURUSD"),
            Side::Sell,
            &Volume::new(dec!(10)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );
        assert!(sell_impact > Decimal::ZERO);
    }

    #[test]
    fn temporary_impact_decays() {
        let mut sim = MarketImpactSimulator::new(enabled_config());
        let inst = InstrumentId::new("EURUSD");

        sim.compute_impact(
            &inst,
            Side::Buy,
            &Volume::new(dec!(100)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );

        let before = sim.temporary_impact(&inst);
        assert!(before > Decimal::ZERO);

        // Decay 10 times.
        for _ in 0..10 {
            sim.decay_temporary();
        }

        let after = sim.temporary_impact(&inst);
        assert!(after < before, "after={after} should < before={before}");
    }

    #[test]
    fn permanent_impact_persists() {
        let mut sim = MarketImpactSimulator::new(enabled_config());
        let inst = InstrumentId::new("EURUSD");

        sim.compute_impact(
            &inst,
            Side::Buy,
            &Volume::new(dec!(100)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );

        let perm = sim.permanent_impact(&inst);
        assert!(perm > Decimal::ZERO);

        // Decay many times — permanent should not change.
        for _ in 0..100 {
            sim.decay_temporary();
        }

        assert_eq!(sim.permanent_impact(&inst), perm);
    }

    #[test]
    fn reset_clears_all() {
        let mut sim = MarketImpactSimulator::new(enabled_config());
        let inst = InstrumentId::new("EURUSD");

        sim.compute_impact(
            &inst,
            Side::Buy,
            &Volume::new(dec!(100)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );

        assert!(sim.current_impact(&inst) != Decimal::ZERO);
        sim.reset();
        assert_eq!(sim.current_impact(&inst), Decimal::ZERO);
    }

    #[test]
    fn zero_adv_no_panic() {
        let config = MarketImpactModel {
            enabled: true,
            estimated_adv: Decimal::ZERO,
            ..enabled_config()
        };
        let mut sim = MarketImpactSimulator::new(config);

        let impact = sim.compute_impact(
            &InstrumentId::new("EURUSD"),
            Side::Buy,
            &Volume::new(dec!(100)),
            &Price::new(dec!(1.1000)),
            dec!(0.01),
        );
        assert_eq!(impact, Decimal::ZERO);
    }
}
