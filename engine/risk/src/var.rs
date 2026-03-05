//! Fast parametric Value-at-Risk (VaR) approximation.
//!
//! Uses the variance-covariance method with pre-computed EWMA volatilities
//! and correlations. Suitable for the < 10µs risk-check latency budget
//! since all statistical inputs are maintained incrementally.
//!
//! VaR = z_α * σ_portfolio * equity
//!
//! where σ_portfolio = sqrt(Σᵢ Σⱼ wᵢ wⱼ σᵢ σⱼ ρᵢⱼ)

use std::collections::HashMap;

use quantfund_core::InstrumentId;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

use crate::correlation::CorrelationTracker;
use crate::volatility::{decimal_sqrt, VolatilityTracker};

/// Confidence level for VaR computation.
#[derive(Clone, Copy, Debug)]
pub enum VarConfidence {
    /// 95% confidence → z = 1.645
    Pct95,
    /// 99% confidence → z = 2.326
    Pct99,
    /// 99.5% confidence → z = 2.576
    Pct995,
}

impl VarConfidence {
    /// The z-score (quantile of the standard normal) for this confidence level.
    /// Returns as Decimal for exact arithmetic in the hot path.
    pub fn z_score(self) -> Decimal {
        match self {
            VarConfidence::Pct95 => dec!(1.645),
            VarConfidence::Pct99 => dec!(2.326),
            VarConfidence::Pct995 => dec!(2.576),
        }
    }
}

/// Configuration for VaR computation.
#[derive(Clone, Debug)]
pub struct VarConfig {
    /// Confidence level (default: 99%).
    pub confidence: VarConfidence,
    /// Maximum allowed VaR as fraction of equity (e.g. 0.02 = 2%).
    pub max_var: Decimal,
    /// Holding period in days (default: 1 for daily VaR).
    /// VaR scales by sqrt(holding_period).
    pub holding_period_days: u32,
}

impl Default for VarConfig {
    fn default() -> Self {
        Self {
            confidence: VarConfidence::Pct99,
            max_var: dec!(0.02),
            holding_period_days: 1,
        }
    }
}

/// Computes parametric VaR using pre-computed volatilities and correlations.
///
/// This is a pure function — no state. All the "incremental" work is done
/// by `VolatilityTracker` and `CorrelationTracker`. This just assembles the
/// final VaR number from their outputs.
pub fn compute_portfolio_var(
    exposures: &HashMap<InstrumentId, Decimal>,
    equity: Decimal,
    vol_tracker: &VolatilityTracker,
    corr_tracker: &CorrelationTracker,
    config: &VarConfig,
) -> Decimal {
    if equity <= dec!(0) || exposures.is_empty() {
        return dec!(0);
    }

    let instruments: Vec<&InstrumentId> = exposures.keys().collect();
    let n = instruments.len();

    // Compute portfolio variance: Σᵢ Σⱼ wᵢ wⱼ σᵢ σⱼ ρᵢⱼ
    // where wᵢ = exposure_i / equity (weight as fraction of equity)
    let mut portfolio_variance = dec!(0);

    for i in 0..n {
        let w_i = exposures
            .get(instruments[i])
            .copied()
            .unwrap_or(dec!(0))
            .abs()
            / equity;
        let vol_i = vol_tracker.volatility(instruments[i]).unwrap_or(dec!(0));

        // Diagonal term: wᵢ² * σᵢ²
        portfolio_variance += w_i * w_i * vol_i * vol_i;

        for j in (i + 1)..n {
            let w_j = exposures
                .get(instruments[j])
                .copied()
                .unwrap_or(dec!(0))
                .abs()
                / equity;
            let vol_j = vol_tracker.volatility(instruments[j]).unwrap_or(dec!(0));

            let corr = corr_tracker
                .correlation(instruments[i], instruments[j], vol_i, vol_j)
                .unwrap_or(dec!(0));

            // Cross term: 2 * wᵢ * wⱼ * σᵢ * σⱼ * ρᵢⱼ
            portfolio_variance += dec!(2) * w_i * w_j * vol_i * vol_j * corr;
        }
    }

    let portfolio_vol = decimal_sqrt(portfolio_variance);

    // Scale by holding period: VaR_T = VaR_1 * sqrt(T)
    let holding_scale = if config.holding_period_days > 1 {
        decimal_sqrt(Decimal::from(config.holding_period_days))
    } else {
        dec!(1)
    };

    // VaR = z * σ_portfolio * sqrt(T)
    // This is a fraction of equity — multiply by equity for dollar VaR.
    config.confidence.z_score() * portfolio_vol * holding_scale
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use rust_decimal_macros::dec;

    #[test]
    fn empty_portfolio_zero_var() {
        let vol = VolatilityTracker::new(dec!(0.94), 3);
        let corr = CorrelationTracker::new(dec!(0.94), 3);
        let exposures = HashMap::new();

        let var =
            compute_portfolio_var(&exposures, dec!(100000), &vol, &corr, &VarConfig::default());
        assert_eq!(var, dec!(0));
    }

    #[test]
    fn zero_equity_zero_var() {
        let vol = VolatilityTracker::new(dec!(0.94), 3);
        let corr = CorrelationTracker::new(dec!(0.94), 3);
        let mut exposures = HashMap::new();
        exposures.insert(InstrumentId::new("TEST"), dec!(1000));

        let var = compute_portfolio_var(&exposures, dec!(0), &vol, &corr, &VarConfig::default());
        assert_eq!(var, dec!(0));
    }

    #[test]
    fn single_instrument_var() {
        let id = InstrumentId::new("EURUSD");
        let mut vol_tracker = VolatilityTracker::new(dec!(0.94), 3);

        // Feed prices to build up volatility.
        let prices = [
            dec!(1.1000),
            dec!(1.1010),
            dec!(1.0990),
            dec!(1.1020),
            dec!(1.0980),
            dec!(1.1030),
        ];
        for p in &prices {
            vol_tracker.update(&id, *p);
        }

        let corr_tracker = CorrelationTracker::new(dec!(0.94), 3);

        let mut exposures = HashMap::new();
        exposures.insert(id, dec!(50000)); // 50k exposure

        let equity = dec!(100000);
        let var = compute_portfolio_var(
            &exposures,
            equity,
            &vol_tracker,
            &corr_tracker,
            &VarConfig::default(),
        );

        assert!(var > dec!(0), "VaR should be positive for a real position");
        assert!(var < dec!(1), "VaR as fraction should be < 100%");
    }

    #[test]
    fn higher_confidence_higher_var() {
        let id = InstrumentId::new("TEST");
        let mut vol_tracker = VolatilityTracker::new(dec!(0.94), 3);

        for p in &[dec!(100), dec!(101), dec!(99), dec!(102), dec!(98)] {
            vol_tracker.update(&id, *p);
        }

        let corr_tracker = CorrelationTracker::new(dec!(0.94), 3);
        let mut exposures = HashMap::new();
        exposures.insert(id, dec!(50000));

        let config_95 = VarConfig {
            confidence: VarConfidence::Pct95,
            ..Default::default()
        };
        let config_99 = VarConfig {
            confidence: VarConfidence::Pct99,
            ..Default::default()
        };

        let var_95 = compute_portfolio_var(
            &exposures,
            dec!(100000),
            &vol_tracker,
            &corr_tracker,
            &config_95,
        );
        let var_99 = compute_portfolio_var(
            &exposures,
            dec!(100000),
            &vol_tracker,
            &corr_tracker,
            &config_99,
        );

        assert!(var_99 > var_95, "99% VaR should exceed 95% VaR");
    }

    #[test]
    fn z_scores_are_correct() {
        assert_eq!(VarConfidence::Pct95.z_score(), dec!(1.645));
        assert_eq!(VarConfidence::Pct99.z_score(), dec!(2.326));
        assert_eq!(VarConfidence::Pct995.z_score(), dec!(2.576));
    }
}
