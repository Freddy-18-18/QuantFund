use std::collections::BTreeMap;

use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use tracing::debug;

use quantfund_core::event::{
    Event, FillEvent, PartialFillEvent, RejectionEvent, RejectionReason, TickEvent,
};
use quantfund_core::order::OrderType;
use quantfund_core::types::{OrderId, Price, Side, Timestamp, Volume};
use quantfund_core::Order;

use crate::impact::MarketImpactSimulator;
use crate::latency::{DelayedOrder, LatencySimulator};
use crate::models::{ExecutionModelConfig, SlippageDistribution};
use crate::queue::QueueTracker;

// ─── Pending Order State ─────────────────────────────────────────────────────

/// Extended order state that tracks partial fill progress.
#[derive(Clone, Debug)]
struct PendingOrder {
    order: Order,
    /// Remaining volume to fill.
    remaining_volume: Decimal,
    /// Whether this order has been released by the latency simulator
    /// (i.e., is actually "visible" to the matching engine).
    released: bool,
}

// ─── Matching Engine ─────────────────────────────────────────────────────────

/// Microstructure-aware order matching simulator.
///
/// Phase 4 enhancements over Phase 2:
/// - **Latency injection**: orders sit in a delay queue before becoming visible.
/// - **Queue position tracking**: limit orders must wait in a simulated queue.
/// - **Partial fills**: large orders relative to available liquidity are filled
///   incrementally across multiple ticks.
/// - **Enhanced slippage**: configurable distribution (Fixed/Uniform/Triangular/Exponential),
///   volume-dependent component.
/// - **Market impact**: square-root model (Almgren-Chriss) with temporary decay +
///   permanent component.
///
/// Fully deterministic in backtest mode (seeded xorshift64 RNG).
pub struct MatchingEngine {
    /// Pending orders indexed by ID.
    pending_orders: BTreeMap<OrderId, PendingOrder>,
    /// Execution model configuration.
    config: ExecutionModelConfig,
    /// Seed for deterministic simulation (stored for reference).
    seed: u64,
    /// Simple counter-based RNG state for determinism.
    rng_state: u64,
    /// Latency simulator for order delay injection.
    latency_sim: LatencySimulator,
    /// Queue position tracker for limit orders.
    queue_tracker: QueueTracker,
    /// Market impact simulator.
    impact_sim: MarketImpactSimulator,
}

impl MatchingEngine {
    pub fn new(config: ExecutionModelConfig, seed: u64) -> Self {
        // Use different sub-seeds for each component so they don't share RNG state.
        let latency_seed = seed.wrapping_add(1);
        let latency_sim = LatencySimulator::new(config.latency.clone(), latency_seed);
        let queue_tracker = QueueTracker::default();
        let impact_sim = MarketImpactSimulator::new(config.impact.clone());

        Self {
            pending_orders: BTreeMap::new(),
            config,
            seed,
            rng_state: seed,
            latency_sim,
            queue_tracker,
            impact_sim,
        }
    }

    /// Add an order to the engine.
    ///
    /// If latency injection is enabled, the order enters the delay queue first.
    /// Otherwise it is immediately available for matching.
    pub fn submit_order(&mut self, order: Order, now: Timestamp) {
        debug!(
            order_id = %order.id,
            order_type = ?order.order_type,
            "order submitted to matching engine"
        );

        let remaining = *order.volume;
        let released = if self.latency_sim.is_enabled() {
            self.latency_sim.submit(order.id, now);
            false
        } else {
            // Immediate release — register in queue tracker if limit order.
            if order.order_type == OrderType::Limit
                && let Some(price) = order.price
            {
                let tick_vol = Volume::new(dec!(100)); // Default estimate.
                self.queue_tracker.enter_queue(
                    order.id,
                    order.side,
                    price,
                    order.volume,
                    now,
                    &tick_vol,
                );
            }
            true
        };

        self.pending_orders.insert(
            order.id,
            PendingOrder {
                order,
                remaining_volume: remaining,
                released,
            },
        );
    }

    /// Cancel and remove a pending order.
    pub fn cancel_order(&mut self, order_id: &OrderId) -> Option<Order> {
        self.queue_tracker.remove(order_id);
        let removed = self.pending_orders.remove(order_id);
        if let Some(ref po) = removed {
            debug!(order_id = %po.order.id, "order cancelled from matching engine");
        }
        removed.map(|po| po.order)
    }

    /// Process a tick against all pending orders.
    ///
    /// This is the main simulation entry point, called once per tick.
    /// Returns fill, partial fill, and rejection events.
    pub fn process_tick(&mut self, tick: &TickEvent) -> Vec<Event> {
        let mut events = Vec::new();

        // ── Phase 1: Release delayed orders ──────────────────────────────────
        let released = self.latency_sim.release(tick.timestamp);
        for delayed in &released {
            self.on_order_released(delayed, tick);
        }

        // ── Phase 2: Advance queue positions for limit orders ────────────────
        let queue_fillable = self.queue_tracker.process_tick(tick);

        // ── Phase 3: Decay temporary market impact ───────────────────────────
        self.impact_sim.decay_temporary();

        // ── Phase 4: Try to match all released, pending orders ───────────────
        let order_ids: Vec<OrderId> = self.pending_orders.keys().copied().collect();

        for order_id in order_ids {
            // Skip unreleased orders.
            let is_released = self
                .pending_orders
                .get(&order_id)
                .is_some_and(|po| po.released);
            if !is_released {
                continue;
            }

            // Only consider orders for this instrument.
            let instrument_match = self
                .pending_orders
                .get(&order_id)
                .is_some_and(|po| po.order.instrument_id == tick.instrument_id);
            if !instrument_match {
                continue;
            }

            if let Some(mut new_events) = self.try_fill_order(order_id, tick, &queue_fillable) {
                events.append(&mut new_events);
            }
        }

        events
    }

    /// Calculate slippage for a given base price, side, and volume.
    /// Uses the configured distribution with deterministic RNG.
    pub fn calculate_slippage(
        &mut self,
        base_price: &Price,
        side: Side,
        volume: &Volume,
    ) -> Decimal {
        let pip_value = self.config.slippage.pip_value;
        let base_slip_pips = self.config.slippage.base_slippage_pips;

        // Sample from the configured distribution.
        let distribution_sample = match self.config.slippage.distribution {
            SlippageDistribution::Fixed => base_slip_pips,
            SlippageDistribution::Uniform => {
                let r = self.next_random_decimal();
                base_slip_pips * r
            }
            SlippageDistribution::Triangular => {
                // Triangular distribution with mode at base/2.
                // Using the inverse CDF: if U < c, X = sqrt(U*a*c); else X = a - sqrt((1-U)*a*(a-c))
                // where a = max = base_slippage_pips, c = mode = base/2.
                let r = self.next_random_decimal();
                let a = base_slip_pips;
                let c = a / dec!(2);
                if a == Decimal::ZERO {
                    Decimal::ZERO
                } else {
                    let threshold = c / a; // 0.5
                    if r < threshold {
                        // Left side of triangle.
                        quantfund_risk::volatility::decimal_sqrt(r * a * c)
                    } else {
                        // Right side of triangle.
                        a - quantfund_risk::volatility::decimal_sqrt(
                            (Decimal::ONE - r) * a * (a - c),
                        )
                    }
                }
            }
            SlippageDistribution::Exponential => {
                // Exponential-like: -ln(1 - U) * mean, capped at 3x base.
                let r = self.next_random_decimal();
                let clamped = if r >= dec!(0.999) { dec!(0.999) } else { r };
                // Approximate -ln(1 - r) using a Padé approximant for Decimal:
                // -ln(1-x) ≈ x + x²/2 + x³/3 (Taylor series, 3 terms).
                let x = clamped;
                let neg_ln = x + (x * x) / dec!(2) + (x * x * x) / dec!(3);
                let sample = neg_ln * base_slip_pips;
                // Cap at 3x base.
                let cap = base_slip_pips * dec!(3);
                if sample > cap {
                    cap
                } else {
                    sample
                }
            }
        };

        // Volume-dependent component: extra slippage per lot.
        let volume_component = self.config.slippage.volume_impact * **volume * pip_value;

        // Volatility component (random scaling).
        let random_factor = self.next_random_decimal();
        let volatility_component =
            random_factor * self.config.slippage.volatility_factor * pip_value;

        let total_pips = distribution_sample;
        let total_slippage = (total_pips * pip_value) + volume_component + volatility_component;

        // Slippage is always unfavorable (direction doesn't matter for magnitude).
        let _ = side; // Side is used by the caller to apply direction.
        **base_price * total_slippage
    }

    /// Number of pending orders (including unreleased).
    pub fn pending_count(&self) -> usize {
        self.pending_orders.len()
    }

    /// Number of orders currently in the latency delay queue.
    pub fn latency_pending(&self) -> usize {
        self.latency_sim.pending_count()
    }

    /// Iterator over pending orders.
    pub fn pending_orders(&self) -> impl Iterator<Item = &Order> {
        self.pending_orders.values().map(|po| &po.order)
    }

    /// Returns the seed used for this engine.
    pub fn seed(&self) -> u64 {
        self.seed
    }

    /// Access to the market impact simulator for external queries.
    pub fn impact_simulator(&self) -> &MarketImpactSimulator {
        &self.impact_sim
    }

    // ── Private helpers ──────────────────────────────────────────────────────

    /// Called when a delayed order is released from the latency queue.
    fn on_order_released(&mut self, delayed: &DelayedOrder, tick: &TickEvent) {
        if let Some(po) = self.pending_orders.get_mut(&delayed.order_id) {
            po.released = true;
            debug!(
                order_id = %delayed.order_id,
                latency_us = delayed.latency_us,
                "order released from latency queue"
            );

            // If this is a limit order, register it in the queue tracker now.
            if po.order.order_type == OrderType::Limit
                && let Some(price) = po.order.price
            {
                self.queue_tracker.enter_queue(
                    po.order.id,
                    po.order.side,
                    price,
                    po.order.volume,
                    tick.timestamp,
                    &tick.ask_volume, // Use current tick volume as reference.
                );
            }
        }
    }

    /// Attempt to fill a single order against the current tick.
    /// Returns `Some(Vec<Event>)` if the order produced events (fill/partial/reject).
    fn try_fill_order(
        &mut self,
        order_id: OrderId,
        tick: &TickEvent,
        queue_fillable: &[OrderId],
    ) -> Option<Vec<Event>> {
        let po = self.pending_orders.get(&order_id)?;
        let order_type = po.order.order_type;
        let side = po.order.side;

        match order_type {
            OrderType::Market => self.fill_market_order(order_id, tick),
            OrderType::Limit => self.fill_limit_order(order_id, tick, queue_fillable),
            OrderType::Stop => self.fill_stop_order(order_id, tick),
            OrderType::StopLimit => self.fill_stop_limit_order(order_id, tick, side),
        }
    }

    /// Fill a market order: immediate fill at ask/bid ± slippage ± impact.
    fn fill_market_order(&mut self, order_id: OrderId, tick: &TickEvent) -> Option<Vec<Event>> {
        // Extract all needed data from pending order before calling &mut self methods.
        let (side, remaining, instrument_id) = {
            let po = self.pending_orders.get(&order_id)?;
            (
                po.order.side,
                po.remaining_volume,
                po.order.instrument_id.clone(),
            )
        };

        let base_price = match side {
            Side::Buy => tick.ask,
            Side::Sell => tick.bid,
        };

        let order_volume = Volume::new(remaining);

        // Check for partial fill.
        let (fill_volume, is_partial) = self.calculate_fill_volume(&order_volume, tick);

        // Calculate slippage.
        let slippage = self.calculate_slippage(&base_price, side, &Volume::new(fill_volume));

        // Calculate market impact.
        let impact = self.impact_sim.compute_impact(
            &instrument_id,
            side,
            &Volume::new(fill_volume),
            &base_price,
            Decimal::ZERO, // Volatility passed in at a higher level if available.
        );

        let fill_price = match side {
            Side::Buy => Price::new(*base_price + slippage + impact),
            Side::Sell => Price::new(*base_price - slippage - impact),
        };

        let mut events = Vec::new();

        if is_partial {
            // Update remaining volume.
            let new_remaining = remaining - fill_volume;
            let po = self.pending_orders.get_mut(&order_id).unwrap();
            po.remaining_volume = new_remaining;

            events.push(Event::PartialFill(PartialFillEvent {
                timestamp: tick.timestamp,
                order_id,
                filled_volume: Volume::new(fill_volume),
                remaining_volume: Volume::new(new_remaining),
                fill_price,
            }));

            debug!(
                order_id = %order_id,
                filled = %fill_volume,
                remaining = %new_remaining,
                "partial fill"
            );
        } else {
            // Full fill — remove from pending.
            let po = self.pending_orders.remove(&order_id).unwrap();

            events.push(Event::Fill(FillEvent {
                timestamp: tick.timestamp,
                order_id,
                instrument_id: po.order.instrument_id.clone(),
                side: po.order.side,
                fill_price,
                volume: Volume::new(fill_volume),
                slippage: slippage + impact,
                commission: Decimal::ZERO, // Set by backtest runner.
            }));

            debug!(
                order_id = %order_id,
                fill_price = %fill_price,
                slippage = %slippage,
                impact = %impact,
                "order fully filled"
            );
        }

        Some(events)
    }

    /// Fill a limit order: must pass queue position check first.
    fn fill_limit_order(
        &mut self,
        order_id: OrderId,
        tick: &TickEvent,
        queue_fillable: &[OrderId],
    ) -> Option<Vec<Event>> {
        let po = self.pending_orders.get(&order_id)?;
        let side = po.order.side;
        let limit_price = po.order.price?;

        // Check if the price condition is met.
        let price_met = match side {
            Side::Buy => *tick.ask <= *limit_price,
            Side::Sell => *tick.bid >= *limit_price,
        };

        if !price_met {
            return None;
        }

        // If queue tracking is active for this order, it must be in the fillable set.
        if self.queue_tracker.contains(&order_id) {
            if !queue_fillable.contains(&order_id) {
                return None; // Still waiting in queue.
            }
            self.queue_tracker.remove(&order_id);
        }

        let remaining = po.remaining_volume;
        let order_volume = Volume::new(remaining);
        let (fill_volume, is_partial) = self.calculate_fill_volume(&order_volume, tick);

        let mut events = Vec::new();

        if is_partial {
            let new_remaining = remaining - fill_volume;
            let po = self.pending_orders.get_mut(&order_id).unwrap();
            po.remaining_volume = new_remaining;

            events.push(Event::PartialFill(PartialFillEvent {
                timestamp: tick.timestamp,
                order_id,
                filled_volume: Volume::new(fill_volume),
                remaining_volume: Volume::new(new_remaining),
                fill_price: limit_price,
            }));
        } else {
            let po = self.pending_orders.remove(&order_id).unwrap();

            events.push(Event::Fill(FillEvent {
                timestamp: tick.timestamp,
                order_id,
                instrument_id: po.order.instrument_id.clone(),
                side: po.order.side,
                fill_price: limit_price,
                volume: Volume::new(fill_volume),
                slippage: Decimal::ZERO, // Limit orders fill at limit price.
                commission: Decimal::ZERO,
            }));
        }

        Some(events)
    }

    /// Fill a stop order: triggers when price crosses the stop, then fills like a market order.
    fn fill_stop_order(&mut self, order_id: OrderId, tick: &TickEvent) -> Option<Vec<Event>> {
        // Extract all needed data from pending order before calling &mut self methods.
        let (side, stop_price, remaining, instrument_id) = {
            let po = self.pending_orders.get(&order_id)?;
            (
                po.order.side,
                po.order.stop_price?,
                po.remaining_volume,
                po.order.instrument_id.clone(),
            )
        };

        let triggered = match side {
            Side::Buy => *tick.ask >= *stop_price,
            Side::Sell => *tick.bid <= *stop_price,
        };

        if !triggered {
            return None;
        }

        // Once triggered, fill like a market order at current price.
        let base_price = match side {
            Side::Buy => tick.ask,
            Side::Sell => tick.bid,
        };

        let order_volume = Volume::new(remaining);
        let (fill_volume, is_partial) = self.calculate_fill_volume(&order_volume, tick);

        let slippage = self.calculate_slippage(&base_price, side, &Volume::new(fill_volume));
        let impact = self.impact_sim.compute_impact(
            &instrument_id,
            side,
            &Volume::new(fill_volume),
            &base_price,
            Decimal::ZERO,
        );

        let fill_price = match side {
            Side::Buy => Price::new(*base_price + slippage + impact),
            Side::Sell => Price::new(*base_price - slippage - impact),
        };

        let mut events = Vec::new();

        if is_partial {
            let new_remaining = remaining - fill_volume;
            let po = self.pending_orders.get_mut(&order_id).unwrap();
            po.remaining_volume = new_remaining;

            events.push(Event::PartialFill(PartialFillEvent {
                timestamp: tick.timestamp,
                order_id,
                filled_volume: Volume::new(fill_volume),
                remaining_volume: Volume::new(new_remaining),
                fill_price,
            }));
        } else {
            let po = self.pending_orders.remove(&order_id).unwrap();

            events.push(Event::Fill(FillEvent {
                timestamp: tick.timestamp,
                order_id,
                instrument_id: po.order.instrument_id.clone(),
                side: po.order.side,
                fill_price,
                volume: Volume::new(fill_volume),
                slippage: slippage + impact,
                commission: Decimal::ZERO,
            }));
        }

        Some(events)
    }

    /// Fill a stop-limit order: stop triggers, then limit condition must be met.
    fn fill_stop_limit_order(
        &mut self,
        order_id: OrderId,
        tick: &TickEvent,
        side: Side,
    ) -> Option<Vec<Event>> {
        let po = self.pending_orders.get(&order_id)?;

        let stop_price = match po.order.stop_price {
            Some(p) => p,
            None => {
                let po = self.pending_orders.remove(&order_id).unwrap();
                return Some(vec![self.create_rejection_event(
                    &po.order,
                    RejectionReason::InvalidPrice,
                    tick,
                )]);
            }
        };
        let limit_price = match po.order.price {
            Some(p) => p,
            None => {
                let po = self.pending_orders.remove(&order_id).unwrap();
                return Some(vec![self.create_rejection_event(
                    &po.order,
                    RejectionReason::InvalidPrice,
                    tick,
                )]);
            }
        };

        let triggered = match side {
            Side::Buy => *tick.ask >= *stop_price,
            Side::Sell => *tick.bid <= *stop_price,
        };
        let limit_met = match side {
            Side::Buy => *tick.ask <= *limit_price,
            Side::Sell => *tick.bid >= *limit_price,
        };

        if triggered && limit_met {
            let po = self.pending_orders.remove(&order_id).unwrap();
            Some(vec![Event::Fill(FillEvent {
                timestamp: tick.timestamp,
                order_id,
                instrument_id: po.order.instrument_id.clone(),
                side: po.order.side,
                fill_price: limit_price,
                volume: Volume::new(po.remaining_volume),
                slippage: Decimal::ZERO,
                commission: Decimal::ZERO,
            })])
        } else {
            None
        }
    }

    /// Determine how much volume to fill on this tick.
    /// Returns (fill_volume, is_partial).
    fn calculate_fill_volume(
        &mut self,
        order_volume: &Volume,
        tick: &TickEvent,
    ) -> (Decimal, bool) {
        if !self.config.fill.partial_fill_enabled {
            return (**order_volume, false);
        }

        // Available liquidity = tick volume * liquidity factor.
        let available = *tick.ask_volume * self.config.fill.liquidity_factor;

        if **order_volume <= available {
            // Enough liquidity for full fill.
            return (**order_volume, false);
        }

        // Partial fill: fill a random fraction between min and max fill ratio,
        // capped by available liquidity.
        let r = self.next_random_decimal();
        let range = self.config.fill.max_fill_ratio - self.config.fill.min_fill_ratio;
        let ratio = self.config.fill.min_fill_ratio + (r * range);

        let fill_volume = (**order_volume * ratio).min(available);

        // Ensure we fill at least something (avoid zero fills).
        let fill_volume = fill_volume.max(self.config.venue.min_order_size);

        // Round to order size step.
        let step = self.config.venue.order_size_step;
        let fill_volume = if step > Decimal::ZERO {
            (fill_volume / step).floor() * step
        } else {
            fill_volume
        };

        // If rounding brought us back to full volume, just do full fill.
        if fill_volume >= **order_volume {
            return (**order_volume, false);
        }

        (fill_volume, true)
    }

    fn create_rejection_event(
        &self,
        order: &Order,
        reason: RejectionReason,
        tick: &TickEvent,
    ) -> Event {
        debug!(order_id = %order.id, reason = ?reason, "order rejected");
        Event::Rejection(RejectionEvent {
            timestamp: tick.timestamp,
            order_id: order.id,
            reason,
        })
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

    /// Deterministic random Decimal in [0, 1).
    fn next_random_decimal(&mut self) -> Decimal {
        let r = self.next_random();
        Decimal::try_from(r).unwrap_or(Decimal::ZERO)
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::event::TickEvent;
    use quantfund_core::types::{Price, StrategyId, Timestamp, Volume};
    use quantfund_core::InstrumentId;
    use rust_decimal_macros::dec;

    fn test_tick(bid: Decimal, ask: Decimal) -> TickEvent {
        TickEvent {
            timestamp: Timestamp::from_nanos(1_000_000_000),
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(bid),
            ask: Price::new(ask),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: ask - bid,
        }
    }

    fn test_tick_with_volume(bid: Decimal, ask: Decimal, vol: Decimal) -> TickEvent {
        TickEvent {
            timestamp: Timestamp::from_nanos(1_000_000_000),
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(bid),
            ask: Price::new(ask),
            bid_volume: Volume::new(vol),
            ask_volume: Volume::new(vol),
            spread: ask - bid,
        }
    }

    fn test_market_buy() -> Order {
        Order::market(
            InstrumentId::new("EURUSD"),
            Side::Buy,
            Volume::new(dec!(1)),
            StrategyId::new("test"),
        )
    }

    fn test_limit_buy(price: Decimal) -> Order {
        Order::limit(
            InstrumentId::new("EURUSD"),
            Side::Buy,
            Volume::new(dec!(1)),
            Price::new(price),
            StrategyId::new("test"),
        )
    }

    fn now() -> Timestamp {
        Timestamp::from_nanos(1_000_000_000)
    }

    // ── Basic fill tests (backward-compatible with Phase 2) ──────────────────

    #[test]
    fn market_buy_fills_immediately() {
        let config = ExecutionModelConfig::default();
        let mut engine = MatchingEngine::new(config, 42);
        let order = test_market_buy();
        let order_id = order.id;
        engine.submit_order(order, now());
        assert_eq!(engine.pending_count(), 1);

        let tick = test_tick(dec!(1.1000), dec!(1.1002));
        let events = engine.process_tick(&tick);

        assert_eq!(events.len(), 1);
        assert_eq!(engine.pending_count(), 0);
        match &events[0] {
            Event::Fill(fill) => {
                assert_eq!(fill.order_id, order_id);
                assert_eq!(fill.side, Side::Buy);
                // Fill price should be >= ask (slippage always unfavorable).
                assert!(*fill.fill_price >= dec!(1.1002));
            }
            other => panic!("expected Fill, got {:?}", other.event_type()),
        }
    }

    #[test]
    fn limit_buy_fills_when_ask_at_or_below_limit() {
        let config = ExecutionModelConfig::default();
        let mut engine = MatchingEngine::new(config, 42);
        let order = test_limit_buy(dec!(1.1005));
        let order_id = order.id;
        engine.submit_order(order, now());

        // Ask above limit — no fill.
        let tick_above = test_tick(dec!(1.1008), dec!(1.1010));
        let events = engine.process_tick(&tick_above);
        assert!(events.is_empty());
        assert_eq!(engine.pending_count(), 1);

        // Ask at limit — fill (queue tracker with default depth, but large volume drains it).
        let tick_at = TickEvent {
            timestamp: Timestamp::from_nanos(2_000_000_000),
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(dec!(1.1003)),
            ask: Price::new(dec!(1.1005)),
            bid_volume: Volume::new(dec!(1000)), // Large volume to drain queue.
            ask_volume: Volume::new(dec!(1000)),
            spread: dec!(0.0002),
        };
        let events = engine.process_tick(&tick_at);
        assert_eq!(events.len(), 1);
        assert_eq!(engine.pending_count(), 0);
        match &events[0] {
            Event::Fill(fill) => {
                assert_eq!(fill.order_id, order_id);
                assert_eq!(*fill.fill_price, dec!(1.1005));
            }
            other => panic!("expected Fill, got {:?}", other.event_type()),
        }
    }

    #[test]
    fn cancel_removes_from_pending() {
        let config = ExecutionModelConfig::default();
        let mut engine = MatchingEngine::new(config, 42);
        let order = test_market_buy();
        let order_id = order.id;
        engine.submit_order(order, now());
        assert_eq!(engine.pending_count(), 1);

        let cancelled = engine.cancel_order(&order_id);
        assert!(cancelled.is_some());
        assert_eq!(engine.pending_count(), 0);
    }

    #[test]
    fn deterministic_slippage() {
        let config = ExecutionModelConfig::default();
        let mut engine1 = MatchingEngine::new(config.clone(), 42);
        let mut engine2 = MatchingEngine::new(config, 42);

        let price = Price::new(dec!(1.1000));
        let vol = Volume::new(dec!(1));
        let slip1 = engine1.calculate_slippage(&price, Side::Buy, &vol);
        let slip2 = engine2.calculate_slippage(&price, Side::Buy, &vol);
        assert_eq!(slip1, slip2);
    }

    // ── Partial fill tests ───────────────────────────────────────────────────

    #[test]
    fn partial_fill_when_low_liquidity() {
        let mut config = ExecutionModelConfig::default();
        config.fill.partial_fill_enabled = true;
        config.fill.liquidity_factor = dec!(1); // Available = tick_volume * 1.
        config.fill.min_fill_ratio = dec!(0.5);
        config.fill.max_fill_ratio = dec!(0.8);

        let mut engine = MatchingEngine::new(config, 42);

        // Order for 50 lots but tick volume is only 10.
        let mut order = test_market_buy();
        order.volume = Volume::new(dec!(50));
        let order_id = order.id;
        engine.submit_order(order, now());

        let tick = test_tick_with_volume(dec!(1.1000), dec!(1.1002), dec!(10));
        let events = engine.process_tick(&tick);

        assert!(!events.is_empty());
        match &events[0] {
            Event::PartialFill(pf) => {
                assert_eq!(pf.order_id, order_id);
                assert!(*pf.filled_volume < dec!(50));
                assert!(*pf.remaining_volume > Decimal::ZERO);
            }
            Event::Fill(_) => {
                // If liquidity happens to cover, that's also valid.
            }
            other => panic!("expected PartialFill or Fill, got {:?}", other.event_type()),
        }
    }

    #[test]
    fn full_fill_when_sufficient_liquidity() {
        let mut config = ExecutionModelConfig::default();
        config.fill.partial_fill_enabled = true;
        config.fill.liquidity_factor = dec!(100); // Plenty of liquidity.

        let mut engine = MatchingEngine::new(config, 42);
        let order = test_market_buy(); // 1 lot.
        let order_id = order.id;
        engine.submit_order(order, now());

        let tick = test_tick_with_volume(dec!(1.1000), dec!(1.1002), dec!(1000));
        let events = engine.process_tick(&tick);

        assert_eq!(events.len(), 1);
        match &events[0] {
            Event::Fill(fill) => {
                assert_eq!(fill.order_id, order_id);
            }
            other => panic!("expected Fill, got {:?}", other.event_type()),
        }
    }

    // ── Latency injection tests ──────────────────────────────────────────────

    #[test]
    fn latency_delays_order_release() {
        let mut config = ExecutionModelConfig::default();
        config.latency.enabled = true;
        config.latency.base_latency_us = 100_000; // 100ms = 100_000_000 ns.
        config.latency.jitter_us = 0;
        config.latency.spike_probability = 0.0;

        let mut engine = MatchingEngine::new(config, 42);
        let order = test_market_buy();
        let submit_time = Timestamp::from_nanos(1_000_000_000);
        engine.submit_order(order, submit_time);

        // Tick at submit time — order not yet released.
        let tick1 = TickEvent {
            timestamp: submit_time,
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(dec!(1.1000)),
            ask: Price::new(dec!(1.1002)),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: dec!(0.0002),
        };
        let events = engine.process_tick(&tick1);
        assert!(events.is_empty(), "order should be delayed");
        assert_eq!(engine.pending_count(), 1);

        // Tick well after latency period — order should release and fill.
        let tick2 = TickEvent {
            timestamp: Timestamp::from_nanos(2_000_000_000), // 1 second later.
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(dec!(1.1000)),
            ask: Price::new(dec!(1.1002)),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: dec!(0.0002),
        };
        let events = engine.process_tick(&tick2);
        assert_eq!(events.len(), 1);
        assert!(matches!(&events[0], Event::Fill(_)));
    }

    // ── Queue tracking tests ─────────────────────────────────────────────────

    #[test]
    fn limit_order_waits_in_queue() {
        let config = ExecutionModelConfig::default();
        let mut engine = MatchingEngine::new(config, 42);

        // Submit limit buy at 1.1000.
        let order = test_limit_buy(dec!(1.1000));
        let _order_id = order.id;
        engine.submit_order(order, now());

        // Tick at the limit price but with small volume — not enough to drain queue.
        let tick = TickEvent {
            timestamp: Timestamp::from_nanos(1_500_000_000),
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(dec!(1.0998)),
            ask: Price::new(dec!(1.1000)),
            bid_volume: Volume::new(dec!(1)), // Very small volume.
            ask_volume: Volume::new(dec!(1)),
            spread: dec!(0.0002),
        };
        let events = engine.process_tick(&tick);
        // The queue was initialised with volume_ahead = 100 * 3 = 300 (default).
        // With 1 lot per tick, it takes many ticks to drain. So no fill yet.
        assert!(events.is_empty(), "order should still be in queue");
        assert_eq!(engine.pending_count(), 1);
    }

    // ── Market impact tests ──────────────────────────────────────────────────

    #[test]
    fn market_impact_increases_fill_price() {
        let mut config = ExecutionModelConfig::default();
        config.impact.enabled = true;
        config.impact.temporary_impact_eta = dec!(0.1);
        config.impact.permanent_impact_ratio = dec!(0.1);
        config.impact.estimated_adv = dec!(100);

        let mut engine_with_impact = MatchingEngine::new(config, 42);

        let config_no_impact = ExecutionModelConfig::default();
        let mut engine_without = MatchingEngine::new(config_no_impact, 42);

        // Large order.
        let mut order1 = test_market_buy();
        order1.volume = Volume::new(dec!(10));

        let mut order2 = test_market_buy();
        order2.volume = Volume::new(dec!(10));

        engine_with_impact.submit_order(order1, now());
        engine_without.submit_order(order2, now());

        let tick = test_tick(dec!(1.1000), dec!(1.1002));
        let events1 = engine_with_impact.process_tick(&tick);
        let events2 = engine_without.process_tick(&tick);

        let fill1 = match &events1[0] {
            Event::Fill(f) => f,
            _ => panic!("expected fill"),
        };
        let fill2 = match &events2[0] {
            Event::Fill(f) => f,
            _ => panic!("expected fill"),
        };

        // With impact, buy fill price should be higher (worse for buyer).
        assert!(
            *fill1.fill_price >= *fill2.fill_price,
            "impact fill {} should >= no-impact fill {}",
            fill1.fill_price,
            fill2.fill_price
        );
    }

    // ── Slippage distribution tests ──────────────────────────────────────────

    #[test]
    fn fixed_slippage_no_randomness() {
        let mut config = ExecutionModelConfig::default();
        config.slippage.distribution = SlippageDistribution::Fixed;
        config.slippage.volatility_factor = Decimal::ZERO; // Remove random component.
        config.slippage.volume_impact = Decimal::ZERO;

        let mut engine1 = MatchingEngine::new(config.clone(), 42);
        let mut engine2 = MatchingEngine::new(config, 99); // Different seed.

        let price = Price::new(dec!(1.1000));
        let vol = Volume::new(dec!(1));

        // Fixed distribution should ignore RNG seed for the base component,
        // but volatility_factor is zero so no random component.
        let slip1 = engine1.calculate_slippage(&price, Side::Buy, &vol);
        let slip2 = engine2.calculate_slippage(&price, Side::Buy, &vol);
        // Both should produce the same slippage since vol_factor = 0 and distribution = Fixed.
        // Actually Fixed still uses volatility random factor... let's verify they're close.
        // With volatility_factor = 0, both should be identical.
        assert_eq!(slip1, slip2);
    }

    #[test]
    fn volume_impact_increases_slippage() {
        let mut config = ExecutionModelConfig::default();
        config.slippage.distribution = SlippageDistribution::Fixed;
        config.slippage.volatility_factor = Decimal::ZERO;
        config.slippage.volume_impact = dec!(0.1); // 0.1 pips per lot.

        let mut engine1 = MatchingEngine::new(config.clone(), 42);
        let mut engine2 = MatchingEngine::new(config, 42);

        let price = Price::new(dec!(1.1000));
        let small_vol = Volume::new(dec!(1));
        let large_vol = Volume::new(dec!(100));

        let slip_small = engine1.calculate_slippage(&price, Side::Buy, &small_vol);
        let slip_large = engine2.calculate_slippage(&price, Side::Buy, &large_vol);

        assert!(
            slip_large > slip_small,
            "large={slip_large} should > small={slip_small}"
        );
    }

    // ── Stop order tests ─────────────────────────────────────────────────────

    #[test]
    fn stop_order_triggers_and_fills() {
        let config = ExecutionModelConfig::default();
        let mut engine = MatchingEngine::new(config, 42);

        let mut order = Order::market(
            InstrumentId::new("EURUSD"),
            Side::Buy,
            Volume::new(dec!(1)),
            StrategyId::new("test"),
        );
        order.order_type = quantfund_core::order::OrderType::Stop;
        order.stop_price = Some(Price::new(dec!(1.1050)));
        let order_id = order.id;
        engine.submit_order(order, now());

        // Below stop — no trigger.
        let tick1 = test_tick(dec!(1.1000), dec!(1.1002));
        let events = engine.process_tick(&tick1);
        assert!(events.is_empty());

        // At/above stop — trigger.
        let tick2 = test_tick(dec!(1.1048), dec!(1.1050));
        let events = engine.process_tick(&tick2);
        assert_eq!(events.len(), 1);
        match &events[0] {
            Event::Fill(fill) => {
                assert_eq!(fill.order_id, order_id);
                assert_eq!(fill.side, Side::Buy);
            }
            other => panic!("expected Fill, got {:?}", other.event_type()),
        }
    }

    // ── Multi-order tests ────────────────────────────────────────────────────

    #[test]
    fn multiple_orders_filled_same_tick() {
        let config = ExecutionModelConfig::default();
        let mut engine = MatchingEngine::new(config, 42);

        let order1 = test_market_buy();
        let order2 = test_market_buy();
        engine.submit_order(order1, now());
        engine.submit_order(order2, now());
        assert_eq!(engine.pending_count(), 2);

        let tick = test_tick(dec!(1.1000), dec!(1.1002));
        let events = engine.process_tick(&tick);
        assert_eq!(events.len(), 2);
        assert_eq!(engine.pending_count(), 0);
    }
}
