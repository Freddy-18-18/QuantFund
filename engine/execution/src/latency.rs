use std::collections::VecDeque;

use quantfund_core::types::{OrderId, Timestamp};

use crate::models::LatencyModel;

// ─── Delayed Order ───────────────────────────────────────────────────────────

/// An order that has been submitted but is still "in flight" due to simulated
/// network/broker latency.
#[derive(Clone, Debug)]
pub struct DelayedOrder {
    pub order_id: OrderId,
    /// Simulation timestamp when the order was submitted.
    pub submitted_at: Timestamp,
    /// Simulation timestamp when the order becomes visible to the matching engine.
    pub available_at: Timestamp,
    /// Injected latency in microseconds (for telemetry).
    pub latency_us: u64,
}

// ─── Latency Simulator ──────────────────────────────────────────────────────

/// Simulates execution latency by holding orders in a delay queue.
///
/// When an order is submitted, it enters a delay buffer with a calculated
/// arrival time = now + latency. On each tick, orders whose `available_at`
/// timestamp has passed are released to the matching engine.
///
/// Deterministic: uses the same xorshift64 RNG as the matching engine.
pub struct LatencySimulator {
    config: LatencyModel,
    /// FIFO queue of delayed orders, sorted by `available_at`.
    delay_queue: VecDeque<DelayedOrder>,
    /// RNG state for deterministic jitter.
    rng_state: u64,
}

impl LatencySimulator {
    pub fn new(config: LatencyModel, seed: u64) -> Self {
        Self {
            config,
            delay_queue: VecDeque::new(),
            rng_state: seed,
        }
    }

    /// Submit an order with latency injection.
    /// Returns the `DelayedOrder` descriptor (also stored internally).
    pub fn submit(&mut self, order_id: OrderId, now: Timestamp) -> DelayedOrder {
        let latency_us = if self.config.enabled {
            self.calculate_latency()
        } else {
            0
        };

        let available_at = Timestamp::from_nanos(
            now.as_nanos() + (latency_us as i64 * 1_000), // µs -> ns
        );

        let delayed = DelayedOrder {
            order_id,
            submitted_at: now,
            available_at,
            latency_us,
        };

        self.delay_queue.push_back(delayed.clone());
        delayed
    }

    /// Release all orders that have become available at or before `now`.
    /// Returns a list of order IDs that should now be processed by the
    /// matching engine.
    pub fn release(&mut self, now: Timestamp) -> Vec<DelayedOrder> {
        let mut released = Vec::new();

        while let Some(front) = self.delay_queue.front() {
            if front.available_at <= now {
                released.push(self.delay_queue.pop_front().unwrap());
            } else {
                break;
            }
        }

        released
    }

    /// Number of orders currently in the delay queue.
    pub fn pending_count(&self) -> usize {
        self.delay_queue.len()
    }

    /// Whether latency injection is enabled.
    pub fn is_enabled(&self) -> bool {
        self.config.enabled
    }

    // ── Private helpers ──────────────────────────────────────────────────────

    /// Calculate a single latency sample in microseconds.
    fn calculate_latency(&mut self) -> u64 {
        let r = self.next_random();

        // Check for spike.
        if r < self.config.spike_probability {
            // Spike latency: uniform in [base, spike_max].
            let r2 = self.next_random();
            let spike_range = self
                .config
                .spike_max_us
                .saturating_sub(self.config.base_latency_us);
            return self.config.base_latency_us + (r2 * spike_range as f64) as u64;
        }

        // Normal latency: base ± jitter.
        let r3 = self.next_random();
        let jitter = ((r3 * 2.0 - 1.0) * self.config.jitter_us as f64) as i64;
        let latency = self.config.base_latency_us as i64 + jitter;

        // Clamp to non-negative.
        latency.max(0) as u64
    }

    /// Deterministic pseudo-random number in [0.0, 1.0) using xorshift64.
    fn next_random(&mut self) -> f64 {
        let mut x = self.rng_state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.rng_state = x;
        (x as f64) / (u64::MAX as f64)
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn disabled_config() -> LatencyModel {
        LatencyModel {
            enabled: false,
            ..LatencyModel::default()
        }
    }

    fn enabled_config() -> LatencyModel {
        LatencyModel {
            enabled: true,
            base_latency_us: 50_000,
            jitter_us: 10_000,
            spike_probability: 0.0, // No spikes for predictable tests.
            spike_max_us: 500_000,
        }
    }

    #[test]
    fn disabled_latency_zero_delay() {
        let mut sim = LatencySimulator::new(disabled_config(), 42);
        let now = Timestamp::from_nanos(1_000_000_000);
        let delayed = sim.submit(OrderId::new(), now);

        assert_eq!(delayed.latency_us, 0);
        assert_eq!(delayed.available_at, now);
    }

    #[test]
    fn enabled_latency_adds_delay() {
        let mut sim = LatencySimulator::new(enabled_config(), 42);
        let now = Timestamp::from_nanos(1_000_000_000);
        let delayed = sim.submit(OrderId::new(), now);

        assert!(delayed.latency_us > 0);
        assert!(delayed.available_at > now);
    }

    #[test]
    fn release_respects_timing() {
        let mut sim = LatencySimulator::new(enabled_config(), 42);
        let now = Timestamp::from_nanos(1_000_000_000);

        let d1 = sim.submit(OrderId::new(), now);
        let d2 = sim.submit(OrderId::new(), now);

        // Before the earliest available_at -> nothing released.
        let released = sim.release(now);
        assert!(released.is_empty());
        assert_eq!(sim.pending_count(), 2);

        // After both available -> both released.
        let far_future = Timestamp::from_nanos(now.as_nanos() + 1_000_000_000);
        let released = sim.release(far_future);
        assert_eq!(released.len(), 2);
        assert_eq!(released[0].order_id, d1.order_id);
        assert_eq!(released[1].order_id, d2.order_id);
        assert_eq!(sim.pending_count(), 0);
    }

    #[test]
    fn deterministic_same_seed() {
        let mut sim1 = LatencySimulator::new(enabled_config(), 99);
        let mut sim2 = LatencySimulator::new(enabled_config(), 99);
        let now = Timestamp::from_nanos(1_000_000_000);

        // Use the same OrderId is not required — we only care about latency values.
        let d1 = sim1.submit(OrderId::new(), now);
        let d2 = sim2.submit(OrderId::new(), now);

        assert_eq!(d1.latency_us, d2.latency_us);
    }

    #[test]
    fn spike_latency_when_enabled() {
        let config = LatencyModel {
            enabled: true,
            base_latency_us: 50_000,
            jitter_us: 10_000,
            spike_probability: 1.0, // Always spike.
            spike_max_us: 500_000,
        };
        let mut sim = LatencySimulator::new(config, 42);
        let now = Timestamp::from_nanos(1_000_000_000);

        let delayed = sim.submit(OrderId::new(), now);
        // Spike should be >= base_latency.
        assert!(delayed.latency_us >= 50_000);
    }
}
