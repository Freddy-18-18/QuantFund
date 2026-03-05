//! EWMA (Exponentially Weighted Moving Average) volatility tracker.
//!
//! Provides O(1) per-update rolling volatility estimation suitable for the
//! < 10µs risk-check latency budget. No heap allocation after construction.

use std::collections::HashMap;

use quantfund_core::InstrumentId;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

/// Per-instrument EWMA volatility state.
#[derive(Clone, Debug)]
struct EwmaState {
    /// Last observed mid-price for computing log returns.
    last_price: Option<Decimal>,
    /// EWMA of squared returns (i.e. variance estimate).
    variance: Decimal,
    /// Number of observations processed.
    count: u64,
}

impl EwmaState {
    fn new() -> Self {
        Self {
            last_price: None,
            variance: dec!(0),
            count: 0,
        }
    }

    /// Current volatility (standard deviation) estimate.
    fn volatility(&self) -> Decimal {
        if self.variance <= dec!(0) {
            return dec!(0);
        }
        // Use Newton's method for Decimal square root (3 iterations is plenty).
        decimal_sqrt(self.variance)
    }
}

/// Tracks rolling realised volatility for multiple instruments using EWMA.
///
/// The decay factor `lambda` controls the half-life of the exponential
/// weighting. Typical values: 0.94 (RiskMetrics daily) or 0.97 (slower decay).
///
/// Update cost: O(1) per tick per instrument.
#[derive(Clone, Debug)]
pub struct VolatilityTracker {
    /// EWMA decay factor (0 < lambda < 1). Higher = slower decay = smoother.
    lambda: Decimal,
    /// Per-instrument state.
    instruments: HashMap<InstrumentId, EwmaState>,
    /// Minimum observations before the estimate is considered valid.
    warmup_period: u64,
}

impl VolatilityTracker {
    /// Create a new tracker with the given decay factor.
    ///
    /// `lambda` = 0.94 is the classic RiskMetrics daily decay.
    /// `warmup_period` = number of ticks before the estimate is trusted.
    pub fn new(lambda: Decimal, warmup_period: u64) -> Self {
        Self {
            lambda,
            instruments: HashMap::new(),
            warmup_period,
        }
    }

    /// Feed a new mid-price observation for an instrument.
    /// Returns the updated volatility estimate.
    pub fn update(&mut self, instrument_id: &InstrumentId, mid_price: Decimal) -> Decimal {
        let state = self
            .instruments
            .entry(instrument_id.clone())
            .or_insert_with(EwmaState::new);

        if let Some(prev) = state.last_price
            && prev > dec!(0)
        {
            // Log return ≈ (price - prev) / prev for small changes.
            // Using simple return as Decimal has no ln() — this is standard
            // for high-frequency vol estimation.
            let ret = (mid_price - prev) / prev;
            let ret_sq = ret * ret;

            // EWMA update: variance_t = λ * variance_{t-1} + (1-λ) * r²
            let one_minus_lambda = dec!(1) - self.lambda;
            state.variance = self.lambda * state.variance + one_minus_lambda * ret_sq;
        }

        state.last_price = Some(mid_price);
        state.count += 1;

        state.volatility()
    }

    /// Get the current volatility estimate for an instrument.
    /// Returns `None` if the instrument hasn't been seen or isn't warmed up.
    pub fn volatility(&self, instrument_id: &InstrumentId) -> Option<Decimal> {
        self.instruments.get(instrument_id).and_then(|s| {
            if s.count >= self.warmup_period {
                Some(s.volatility())
            } else {
                None
            }
        })
    }

    /// Get volatilities for all tracked instruments that have completed warmup.
    pub fn all_volatilities(&self) -> HashMap<InstrumentId, Decimal> {
        self.instruments
            .iter()
            .filter(|(_, s)| s.count >= self.warmup_period)
            .map(|(id, s)| (id.clone(), s.volatility()))
            .collect()
    }

    /// Reset all state.
    pub fn reset(&mut self) {
        self.instruments.clear();
    }

    /// Returns true if the given instrument has enough data.
    pub fn is_warmed_up(&self, instrument_id: &InstrumentId) -> bool {
        self.instruments
            .get(instrument_id)
            .is_some_and(|s| s.count >= self.warmup_period)
    }
}

/// Newton's method square root for `Decimal`.
/// Converges in ~5 iterations for typical financial values.
pub fn decimal_sqrt(value: Decimal) -> Decimal {
    if value <= dec!(0) {
        return dec!(0);
    }

    // Initial guess: value / 2 (or 1 if value < 1).
    let mut guess = if value >= dec!(1) {
        value / dec!(2)
    } else {
        dec!(1)
    };

    // 8 iterations of Newton's method: x_{n+1} = (x_n + value/x_n) / 2
    for _ in 0..8 {
        if guess <= dec!(0) {
            return dec!(0);
        }
        guess = (guess + value / guess) / dec!(2);
    }

    guess
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use rust_decimal_macros::dec;

    #[test]
    fn decimal_sqrt_basic() {
        let result = decimal_sqrt(dec!(4));
        // Should be very close to 2.0
        assert!((result - dec!(2)).abs() < dec!(0.0001));
    }

    #[test]
    fn decimal_sqrt_small() {
        let result = decimal_sqrt(dec!(0.0004));
        // Should be close to 0.02
        assert!((result - dec!(0.02)).abs() < dec!(0.001));
    }

    #[test]
    fn decimal_sqrt_zero() {
        assert_eq!(decimal_sqrt(dec!(0)), dec!(0));
    }

    #[test]
    fn tracker_warmup_period() {
        let id = InstrumentId::new("TEST");
        let mut tracker = VolatilityTracker::new(dec!(0.94), 5);

        // Before warmup, should return None.
        for i in 0..4 {
            tracker.update(&id, dec!(100) + Decimal::from(i));
            assert!(tracker.volatility(&id).is_none());
        }

        // After warmup, should return Some.
        tracker.update(&id, dec!(104));
        assert!(tracker.volatility(&id).is_some());
    }

    #[test]
    fn tracker_constant_price_zero_vol() {
        let id = InstrumentId::new("TEST");
        let mut tracker = VolatilityTracker::new(dec!(0.94), 3);

        for _ in 0..10 {
            tracker.update(&id, dec!(100));
        }

        let vol = tracker.volatility(&id).unwrap();
        assert_eq!(vol, dec!(0));
    }

    #[test]
    fn tracker_volatile_prices_nonzero_vol() {
        let id = InstrumentId::new("TEST");
        let mut tracker = VolatilityTracker::new(dec!(0.94), 3);

        // Alternating prices to create volatility.
        let prices = [
            dec!(100),
            dec!(102),
            dec!(98),
            dec!(103),
            dec!(97),
            dec!(104),
            dec!(96),
        ];
        for price in &prices {
            tracker.update(&id, *price);
        }

        let vol = tracker.volatility(&id).unwrap();
        assert!(vol > dec!(0), "volatility should be > 0 for varying prices");
    }

    #[test]
    fn tracker_multiple_instruments() {
        let a = InstrumentId::new("A");
        let b = InstrumentId::new("B");
        let mut tracker = VolatilityTracker::new(dec!(0.94), 3);

        // Feed different price patterns.
        for i in 0..5 {
            tracker.update(&a, dec!(100) + Decimal::from(i));
            tracker.update(&b, dec!(50));
        }

        let vol_a = tracker.volatility(&a).unwrap();
        let vol_b = tracker.volatility(&b).unwrap();

        assert!(vol_a > dec!(0));
        assert_eq!(vol_b, dec!(0));
    }

    #[test]
    fn tracker_reset_clears_all() {
        let id = InstrumentId::new("TEST");
        let mut tracker = VolatilityTracker::new(dec!(0.94), 2);

        for _ in 0..5 {
            tracker.update(&id, dec!(100));
        }
        assert!(tracker.volatility(&id).is_some());

        tracker.reset();
        assert!(tracker.volatility(&id).is_none());
    }

    #[test]
    fn all_volatilities_only_warmed_up() {
        let a = InstrumentId::new("A");
        let b = InstrumentId::new("B");
        let mut tracker = VolatilityTracker::new(dec!(0.94), 5);

        // A gets enough data, B doesn't.
        for i in 0..6 {
            tracker.update(&a, dec!(100) + Decimal::from(i));
        }
        for i in 0..3 {
            tracker.update(&b, dec!(50) + Decimal::from(i));
        }

        let all = tracker.all_volatilities();
        assert!(all.contains_key(&a));
        assert!(!all.contains_key(&b));
    }
}
