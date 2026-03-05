//! Incremental correlation tracker and cluster detection.
//!
//! Uses Welford's online algorithm extended to covariance for O(1)
//! per-update pairwise correlation tracking. Suitable for the < 10µs
//! risk-check latency budget.

use std::collections::HashMap;

use quantfund_core::InstrumentId;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

/// Tracks a single pairwise correlation incrementally.
///
/// Uses an exponentially weighted version of the Welford online algorithm
/// for covariance: cov_t = λ * cov_{t-1} + (1-λ) * r_x * r_y
#[derive(Clone, Debug)]
struct PairState {
    /// EWMA of covariance(r_x, r_y).
    covariance: Decimal,
    /// Number of joint observations.
    count: u64,
}

impl PairState {
    fn new() -> Self {
        Self {
            covariance: dec!(0),
            count: 0,
        }
    }
}

/// Per-instrument return state for correlation computation.
#[derive(Clone, Debug)]
struct ReturnState {
    last_price: Option<Decimal>,
    last_return: Option<Decimal>,
}

impl ReturnState {
    fn new() -> Self {
        Self {
            last_price: None,
            last_return: None,
        }
    }
}

/// A pair key that is order-independent (A,B == B,A).
#[derive(Clone, Debug, Hash, PartialEq, Eq)]
struct PairKey(InstrumentId, InstrumentId);

impl PairKey {
    fn new(a: &InstrumentId, b: &InstrumentId) -> Self {
        if a.as_str() <= b.as_str() {
            PairKey(a.clone(), b.clone())
        } else {
            PairKey(b.clone(), a.clone())
        }
    }
}

/// Tracks rolling pairwise correlations across instruments using EWMA.
///
/// For N instruments, maintains N*(N-1)/2 pair trackers. Each update is O(N)
/// since a tick for instrument X updates all pairs involving X.
///
/// Correlation = cov(X,Y) / (vol(X) * vol(Y))
/// where vol comes from the companion `VolatilityTracker`.
#[derive(Clone, Debug)]
pub struct CorrelationTracker {
    lambda: Decimal,
    returns: HashMap<InstrumentId, ReturnState>,
    pairs: HashMap<PairKey, PairState>,
    warmup_period: u64,
}

impl CorrelationTracker {
    /// Create a new tracker with the given EWMA decay factor.
    pub fn new(lambda: Decimal, warmup_period: u64) -> Self {
        Self {
            lambda,
            returns: HashMap::new(),
            pairs: HashMap::new(),
            warmup_period,
        }
    }

    /// Feed a new mid-price for an instrument. This updates the return for
    /// this instrument and all pairwise covariances involving it.
    pub fn update(&mut self, instrument_id: &InstrumentId, mid_price: Decimal) {
        // Compute return for this instrument.
        let state = self
            .returns
            .entry(instrument_id.clone())
            .or_insert_with(ReturnState::new);

        let current_return = if let Some(prev) = state.last_price {
            if prev > dec!(0) {
                Some((mid_price - prev) / prev)
            } else {
                None
            }
        } else {
            None
        };

        state.last_price = Some(mid_price);
        state.last_return = current_return;

        // If we have a return, update all pair covariances.
        if let Some(ret_x) = current_return {
            let one_minus_lambda = dec!(1) - self.lambda;

            // Collect other instruments' returns to avoid borrow conflicts.
            let other_returns: Vec<(InstrumentId, Decimal)> = self
                .returns
                .iter()
                .filter(|(id, _)| *id != instrument_id)
                .filter_map(|(id, s)| s.last_return.map(|r| (id.clone(), r)))
                .collect();

            for (other_id, ret_y) in other_returns {
                let key = PairKey::new(instrument_id, &other_id);
                let pair = self.pairs.entry(key).or_insert_with(PairState::new);

                pair.covariance = self.lambda * pair.covariance + one_minus_lambda * ret_x * ret_y;
                pair.count += 1;
            }
        }
    }

    /// Get the correlation between two instruments.
    /// Returns `None` if either instrument hasn't been observed enough times.
    pub fn correlation(
        &self,
        a: &InstrumentId,
        b: &InstrumentId,
        vol_a: Decimal,
        vol_b: Decimal,
    ) -> Option<Decimal> {
        if a == b {
            return Some(dec!(1));
        }

        let key = PairKey::new(a, b);
        let pair = self.pairs.get(&key)?;

        if pair.count < self.warmup_period {
            return None;
        }

        let denominator = vol_a * vol_b;
        if denominator <= dec!(0) {
            return None;
        }

        let corr = pair.covariance / denominator;
        // Clamp to [-1, 1] to handle numerical imprecision.
        Some(corr.clamp(dec!(-1), dec!(1)))
    }

    /// Detect correlation clusters: groups of instruments where the average
    /// pairwise correlation exceeds `threshold`.
    ///
    /// Returns a list of clusters, where each cluster is a vec of instrument IDs.
    /// A single instrument can appear in multiple overlapping clusters.
    ///
    /// This uses a simple greedy approach: for each instrument, find all others
    /// correlated above the threshold. This is O(N²) but N is typically < 50.
    pub fn find_clusters(
        &self,
        volatilities: &HashMap<InstrumentId, Decimal>,
        threshold: Decimal,
    ) -> Vec<Vec<InstrumentId>> {
        let instruments: Vec<InstrumentId> = volatilities.keys().cloned().collect();
        let n = instruments.len();
        if n < 2 {
            return Vec::new();
        }

        let mut clusters = Vec::new();

        for i in 0..n {
            let mut cluster = vec![instruments[i].clone()];

            for j in (i + 1)..n {
                let vol_i = volatilities
                    .get(&instruments[i])
                    .copied()
                    .unwrap_or(dec!(0));
                let vol_j = volatilities
                    .get(&instruments[j])
                    .copied()
                    .unwrap_or(dec!(0));

                if let Some(corr) = self.correlation(&instruments[i], &instruments[j], vol_i, vol_j)
                    && corr.abs() >= threshold
                {
                    cluster.push(instruments[j].clone());
                }
            }

            // Only emit clusters with 2+ members.
            if cluster.len() >= 2 {
                clusters.push(cluster);
            }
        }

        clusters
    }

    /// Compute the aggregate exposure of a correlation cluster.
    ///
    /// This sums the absolute net exposures of all instruments in the cluster,
    /// weighted by their pairwise correlations. For highly correlated instruments,
    /// their exposures effectively add up (diversification benefit is nil).
    ///
    /// `exposures` maps instrument_id → signed net exposure (in equity fraction).
    pub fn cluster_exposure(
        &self,
        cluster: &[InstrumentId],
        exposures: &HashMap<InstrumentId, Decimal>,
        volatilities: &HashMap<InstrumentId, Decimal>,
    ) -> Decimal {
        let mut total = dec!(0);

        for i in 0..cluster.len() {
            let exp_i = exposures.get(&cluster[i]).copied().unwrap_or(dec!(0)).abs();
            total += exp_i;

            for j in (i + 1)..cluster.len() {
                let exp_j = exposures.get(&cluster[j]).copied().unwrap_or(dec!(0)).abs();
                let vol_i = volatilities.get(&cluster[i]).copied().unwrap_or(dec!(0));
                let vol_j = volatilities.get(&cluster[j]).copied().unwrap_or(dec!(0));

                let corr = self
                    .correlation(&cluster[i], &cluster[j], vol_i, vol_j)
                    .unwrap_or(dec!(0));

                // Cross-term: 2 * corr * exp_i * exp_j
                total += dec!(2) * corr * exp_i * exp_j;
            }
        }

        total
    }

    /// Reset all state.
    pub fn reset(&mut self) {
        self.returns.clear();
        self.pairs.clear();
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use rust_decimal_macros::dec;

    #[test]
    fn self_correlation_is_one() {
        let id = InstrumentId::new("A");
        let tracker = CorrelationTracker::new(dec!(0.94), 3);
        assert_eq!(
            tracker.correlation(&id, &id, dec!(0.01), dec!(0.01)),
            Some(dec!(1))
        );
    }

    #[test]
    fn no_data_returns_none() {
        let a = InstrumentId::new("A");
        let b = InstrumentId::new("B");
        let tracker = CorrelationTracker::new(dec!(0.94), 3);
        assert!(tracker
            .correlation(&a, &b, dec!(0.01), dec!(0.01))
            .is_none());
    }

    #[test]
    fn positively_correlated_instruments() {
        let a = InstrumentId::new("A");
        let b = InstrumentId::new("B");
        let mut tracker = CorrelationTracker::new(dec!(0.94), 3);

        // Both instruments move in the same direction.
        let prices_a = [
            dec!(100),
            dec!(101),
            dec!(102),
            dec!(103),
            dec!(104),
            dec!(105),
        ];
        let prices_b = [
            dec!(50),
            dec!(50.5),
            dec!(51),
            dec!(51.5),
            dec!(52),
            dec!(52.5),
        ];

        for i in 0..prices_a.len() {
            tracker.update(&a, prices_a[i]);
            tracker.update(&b, prices_b[i]);
        }

        let vol_a = dec!(0.01); // Approximate
        let vol_b = dec!(0.01);
        let corr = tracker.correlation(&a, &b, vol_a, vol_b);
        assert!(corr.is_some());
        let c = corr.unwrap();
        assert!(c > dec!(0), "expected positive correlation, got {c}");
    }

    #[test]
    fn find_clusters_basic() {
        let a = InstrumentId::new("A");
        let b = InstrumentId::new("B");
        let c = InstrumentId::new("C");
        let mut tracker = CorrelationTracker::new(dec!(0.94), 3);

        // A and B move together, C moves independently.
        for i in 0..10 {
            let base = dec!(100) + Decimal::from(i);
            tracker.update(&a, base);
            tracker.update(&b, base * dec!(0.5));
            // C oscillates independently
            if i % 2 == 0 {
                tracker.update(&c, dec!(80) + Decimal::from(i));
            } else {
                tracker.update(&c, dec!(80) - Decimal::from(i));
            }
        }

        let mut vols = HashMap::new();
        vols.insert(a.clone(), dec!(0.01));
        vols.insert(b.clone(), dec!(0.01));
        vols.insert(c.clone(), dec!(0.01));

        let clusters = tracker.find_clusters(&vols, dec!(0.5));
        // Should find at least one cluster containing A and B.
        let has_ab_cluster = clusters.iter().any(|cl| cl.contains(&a) && cl.contains(&b));
        assert!(has_ab_cluster, "expected A-B cluster, got: {clusters:?}");
    }

    #[test]
    fn reset_clears_all() {
        let a = InstrumentId::new("A");
        let b = InstrumentId::new("B");
        let mut tracker = CorrelationTracker::new(dec!(0.94), 2);

        for _ in 0..5 {
            tracker.update(&a, dec!(100));
            tracker.update(&b, dec!(50));
        }

        tracker.reset();
        assert!(tracker
            .correlation(&a, &b, dec!(0.01), dec!(0.01))
            .is_none());
    }

    #[test]
    fn pair_key_order_independent() {
        let a = InstrumentId::new("A");
        let b = InstrumentId::new("B");
        let k1 = PairKey::new(&a, &b);
        let k2 = PairKey::new(&b, &a);
        assert_eq!(k1, k2);
    }
}
