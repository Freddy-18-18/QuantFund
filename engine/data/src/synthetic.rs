//! Synthetic tick data generator for deterministic testing.
//!
//! Produces realistic-looking tick sequences with controllable parameters:
//! - Geometric Brownian Motion (GBM) for price dynamics
//! - Configurable spread, volatility, and tick frequency
//! - Deterministic via seeded xorshift64 PRNG (no external RNG dependency)

use quantfund_core::event::TickEvent;
use quantfund_core::types::{Price, Timestamp, Volume};
use quantfund_core::InstrumentId;
use rust_decimal::prelude::ToPrimitive;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

/// Configuration for generating synthetic tick data.
#[derive(Clone, Debug)]
pub struct SyntheticTickConfig {
    /// Instrument identifier.
    pub instrument_id: InstrumentId,
    /// Starting mid-price.
    pub initial_price: Decimal,
    /// Half-spread in price units (e.g., 0.0001 for 1 pip on EURUSD).
    pub half_spread: Decimal,
    /// Annualized volatility (e.g., 0.10 = 10%).
    pub volatility: f64,
    /// Drift (annualized, e.g., 0.0 for no drift).
    pub drift: f64,
    /// Number of ticks to generate.
    pub num_ticks: usize,
    /// Interval between ticks in nanoseconds.
    pub tick_interval_ns: i64,
    /// Starting timestamp in nanoseconds since epoch.
    pub start_timestamp_ns: i64,
    /// Random seed for determinism.
    pub seed: u64,
    /// Base volume per tick.
    pub base_volume: Decimal,
}

impl Default for SyntheticTickConfig {
    fn default() -> Self {
        Self {
            instrument_id: InstrumentId::new("EURUSD"),
            initial_price: dec!(1.1000),
            half_spread: dec!(0.0001),
            volatility: 0.10,
            drift: 0.0,
            num_ticks: 1000,
            tick_interval_ns: 100_000_000, // 100ms between ticks
            start_timestamp_ns: 1_000_000_000_000_000_000, // ~2001
            seed: 42,
            base_volume: dec!(100),
        }
    }
}

/// Generates a vector of synthetic ticks using geometric Brownian motion.
///
/// Tick prices follow:
///   `log_return = (drift - 0.5 * vol^2) * dt + vol * sqrt(dt) * z`
///
/// where `z` is a standard normal sample from our seeded PRNG.
pub fn generate_synthetic_ticks(config: &SyntheticTickConfig) -> Vec<TickEvent> {
    let mut rng_state = config.seed;
    let mut mid_price = config.initial_price.to_f64().unwrap_or(1.1);

    // dt = tick_interval in years (assuming 252 trading days, 8h/day, 3600s/h)
    let seconds_per_year: f64 = 252.0 * 8.0 * 3600.0;
    let dt = (config.tick_interval_ns as f64 / 1_000_000_000.0) / seconds_per_year;
    let sqrt_dt = dt.sqrt();

    let drift_term = (config.drift - 0.5 * config.volatility * config.volatility) * dt;
    let vol_term = config.volatility * sqrt_dt;

    let mut ticks = Vec::with_capacity(config.num_ticks);

    for i in 0..config.num_ticks {
        let ts = config.start_timestamp_ns + (i as i64) * config.tick_interval_ns;

        // Generate standard normal via Box-Muller transform.
        let z = box_muller_normal(&mut rng_state);

        // GBM step.
        let log_return = drift_term + vol_term * z;
        mid_price *= (1.0 + log_return).max(0.0001); // Floor to avoid negative/zero

        // Clamp to reasonable range.
        mid_price = mid_price.max(0.0001);

        let mid_decimal = Decimal::try_from(mid_price).unwrap_or(config.initial_price);

        let bid = Price::new(mid_decimal - config.half_spread);
        let ask = Price::new(mid_decimal + config.half_spread);
        let spread = config.half_spread * dec!(2);

        // Slight volume variation.
        let vol_noise = xorshift64(&mut rng_state) as f64 / u64::MAX as f64;
        let vol_multiplier = Decimal::try_from(0.5 + vol_noise).unwrap_or(Decimal::ONE);
        let volume = config.base_volume * vol_multiplier;

        ticks.push(TickEvent {
            timestamp: Timestamp::from_nanos(ts),
            instrument_id: config.instrument_id.clone(),
            bid,
            ask,
            bid_volume: Volume::new(volume),
            ask_volume: Volume::new(volume),
            spread,
        });
    }

    ticks
}

/// Configuration for generating trending tick data.
#[derive(Clone, Debug)]
pub struct TrendingTickConfig {
    /// Instrument identifier.
    pub instrument_id: InstrumentId,
    /// Starting mid-price.
    pub initial_price: Decimal,
    /// Half-spread in price units.
    pub half_spread: Decimal,
    /// Number of ticks in each uptrend phase.
    pub trend_up_ticks: usize,
    /// Number of ticks in the downtrend phase.
    pub trend_down_ticks: usize,
    /// Price change per tick (e.g., 0.0001 for 1 pip).
    pub pip_per_tick: Decimal,
    /// Starting timestamp in nanoseconds since epoch.
    pub start_ns: i64,
    /// Interval between ticks in nanoseconds.
    pub tick_interval_ns: i64,
}

/// Generate synthetic ticks with a trend pattern:
/// - First `trend_up_ticks` ticks trend upward
/// - Then `trend_down_ticks` ticks trend downward
/// - Then `trend_up_ticks` ticks trend upward again
///
/// Useful for testing trend-following strategies like SMA crossover.
pub fn generate_trending_ticks(config: &TrendingTickConfig) -> Vec<TickEvent> {
    let mut ticks = Vec::new();
    let mut mid = config.initial_price;
    let mut ts = config.start_ns;

    // Phase 1: Uptrend
    for _ in 0..config.trend_up_ticks {
        mid += config.pip_per_tick;
        ticks.push(make_tick(
            &config.instrument_id,
            mid,
            config.half_spread,
            ts,
        ));
        ts += config.tick_interval_ns;
    }

    // Phase 2: Downtrend
    for _ in 0..config.trend_down_ticks {
        mid -= config.pip_per_tick;
        ticks.push(make_tick(
            &config.instrument_id,
            mid,
            config.half_spread,
            ts,
        ));
        ts += config.tick_interval_ns;
    }

    // Phase 3: Uptrend again
    for _ in 0..config.trend_up_ticks {
        mid += config.pip_per_tick;
        ticks.push(make_tick(
            &config.instrument_id,
            mid,
            config.half_spread,
            ts,
        ));
        ts += config.tick_interval_ns;
    }

    ticks
}

fn make_tick(
    instrument_id: &InstrumentId,
    mid: Decimal,
    half_spread: Decimal,
    ts_nanos: i64,
) -> TickEvent {
    TickEvent {
        timestamp: Timestamp::from_nanos(ts_nanos),
        instrument_id: instrument_id.clone(),
        bid: Price::new(mid - half_spread),
        ask: Price::new(mid + half_spread),
        bid_volume: Volume::new(dec!(100)),
        ask_volume: Volume::new(dec!(100)),
        spread: half_spread * dec!(2),
    }
}

/// Xorshift64 PRNG — fast, deterministic, no allocation.
fn xorshift64(state: &mut u64) -> u64 {
    let mut x = *state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *state = x;
    x
}

/// Box-Muller transform to generate a standard normal sample from uniform
/// samples produced by xorshift64.
fn box_muller_normal(state: &mut u64) -> f64 {
    let u1 = (xorshift64(state) as f64 / u64::MAX as f64).max(1e-15);
    let u2 = xorshift64(state) as f64 / u64::MAX as f64;
    (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generates_correct_number_of_ticks() {
        let config = SyntheticTickConfig {
            num_ticks: 500,
            ..Default::default()
        };
        let ticks = generate_synthetic_ticks(&config);
        assert_eq!(ticks.len(), 500);
    }

    #[test]
    fn deterministic_output() {
        let config = SyntheticTickConfig {
            num_ticks: 100,
            seed: 12345,
            ..Default::default()
        };
        let ticks1 = generate_synthetic_ticks(&config);
        let ticks2 = generate_synthetic_ticks(&config);

        for (t1, t2) in ticks1.iter().zip(ticks2.iter()) {
            assert_eq!(t1.bid, t2.bid);
            assert_eq!(t1.ask, t2.ask);
            assert_eq!(t1.timestamp, t2.timestamp);
        }
    }

    #[test]
    fn bid_less_than_ask() {
        let config = SyntheticTickConfig {
            num_ticks: 1000,
            ..Default::default()
        };
        let ticks = generate_synthetic_ticks(&config);
        for tick in &ticks {
            assert!(
                *tick.bid < *tick.ask,
                "bid {} should be < ask {}",
                tick.bid,
                tick.ask
            );
        }
    }

    #[test]
    fn timestamps_are_monotonically_increasing() {
        let config = SyntheticTickConfig {
            num_ticks: 100,
            ..Default::default()
        };
        let ticks = generate_synthetic_ticks(&config);
        for window in ticks.windows(2) {
            assert!(window[0].timestamp < window[1].timestamp);
        }
    }

    #[test]
    fn trending_ticks_produce_expected_pattern() {
        let ticks = generate_trending_ticks(&TrendingTickConfig {
            instrument_id: InstrumentId::new("EURUSD"),
            initial_price: dec!(1.1000),
            half_spread: dec!(0.0001),
            trend_up_ticks: 50,
            trend_down_ticks: 100,
            pip_per_tick: dec!(0.0001),
            start_ns: 1_000_000_000,
            tick_interval_ns: 100_000_000,
        });
        assert_eq!(ticks.len(), 200); // 50 + 100 + 50

        // After 50 up ticks: price should be around 1.1050
        // After 100 down ticks: price should be around 1.0950
        // After 50 more up ticks: price should be around 1.1000
        let mid_at_50 = (*ticks[49].bid + *ticks[49].ask) / dec!(2);
        let mid_at_150 = (*ticks[149].bid + *ticks[149].ask) / dec!(2);
        let mid_at_200 = (*ticks[199].bid + *ticks[199].ask) / dec!(2);

        assert!(mid_at_50 > dec!(1.1000), "should be trending up");
        assert!(mid_at_150 < mid_at_50, "should be trending down");
        assert!(mid_at_200 > mid_at_150, "should be trending up again");
    }
}
