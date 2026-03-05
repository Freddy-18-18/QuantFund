use std::collections::BTreeMap;

use rust_decimal::Decimal;
use tracing::debug;

use quantfund_core::event::{Event, FillEvent, RejectionEvent, RejectionReason, TickEvent};
use quantfund_core::order::OrderType;
use quantfund_core::types::{OrderId, Price, Side};
use quantfund_core::Order;

use crate::models::ExecutionModelConfig;

/// Simulates realistic order matching with price-time priority.
/// Deterministic in backtest mode (uses seeded RNG via xorshift64).
pub struct MatchingEngine {
    /// Pending orders indexed by ID.
    pending_orders: BTreeMap<OrderId, quantfund_core::Order>,
    /// Execution model configuration.
    config: ExecutionModelConfig,
    /// Seed for deterministic simulation (stored for reference).
    seed: u64,
    /// Simple counter-based RNG state for determinism.
    rng_state: u64,
}

impl MatchingEngine {
    pub fn new(config: ExecutionModelConfig, seed: u64) -> Self {
        Self {
            pending_orders: BTreeMap::new(),
            config,
            seed,
            rng_state: seed,
        }
    }

    /// Add an order to the pending book.
    pub fn submit_order(&mut self, order: Order) {
        debug!(order_id = %order.id, order_type = ?order.order_type, "order submitted to matching engine");
        self.pending_orders.insert(order.id, order);
    }

    /// Cancel and remove a pending order.
    pub fn cancel_order(&mut self, order_id: &OrderId) -> Option<Order> {
        let removed = self.pending_orders.remove(order_id);
        if let Some(ref order) = removed {
            debug!(order_id = %order.id, "order cancelled from matching engine");
        }
        removed
    }

    /// Process a tick against all pending orders and return fill/rejection events.
    pub fn process_tick(&mut self, tick: &TickEvent) -> Vec<Event> {
        let mut events = Vec::new();

        // Collect matching order IDs first to avoid borrow conflict.
        let order_ids: Vec<OrderId> = self.pending_orders.keys().copied().collect();

        for order_id in order_ids {
            // Only consider orders for this instrument.
            let instrument_match = self
                .pending_orders
                .get(&order_id)
                .is_some_and(|o| o.instrument_id == tick.instrument_id);

            if !instrument_match {
                continue;
            }

            if let Some(event) = self.try_fill_order(order_id, tick) {
                events.push(event);
            }
        }

        events
    }

    /// Calculate slippage for a given base price and order side.
    /// Uses the slippage model with deterministic pseudo-random noise.
    pub fn calculate_slippage(&mut self, base_price: &Price, side: Side) -> Decimal {
        let random_factor = self.next_random();
        let base_slip = self.config.slippage.base_slippage_pips;
        // Convert pips to a fraction of the price (rough approximation).
        // For forex, 1 pip ≈ 0.0001. We use base_slippage_pips * 0.0001.
        let pip_value = Decimal::new(1, 4);
        let slippage = base_slip * pip_value;

        // Add random component scaled by volatility factor.
        let random_component = Decimal::try_from(random_factor).unwrap_or(Decimal::ZERO)
            * self.config.slippage.volatility_factor
            * pip_value;

        let total_slippage = slippage + random_component;

        // Slippage direction: unfavorable to the trader.
        match side {
            Side::Buy => **base_price * total_slippage,
            Side::Sell => **base_price * total_slippage,
        }
    }

    /// Number of pending orders.
    pub fn pending_count(&self) -> usize {
        self.pending_orders.len()
    }

    /// Iterator over pending orders.
    pub fn pending_orders(&self) -> impl Iterator<Item = &Order> {
        self.pending_orders.values()
    }

    /// Returns the seed used for this engine.
    pub fn seed(&self) -> u64 {
        self.seed
    }

    // ── Private helpers ──────────────────────────────────────────────────────

    /// Deterministic pseudo-random number in [0.0, 1.0) using xorshift64.
    fn next_random(&mut self) -> f64 {
        let mut x = self.rng_state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.rng_state = x;
        // Map to [0.0, 1.0)
        (x as f64) / (u64::MAX as f64)
    }

    /// Attempt to fill a single order against the current tick.
    /// Returns `Some(Event)` if the order was filled or rejected, removing it from pending.
    fn try_fill_order(&mut self, order_id: OrderId, tick: &TickEvent) -> Option<Event> {
        let order = self.pending_orders.get(&order_id)?;
        let order_type = order.order_type;
        let side = order.side;

        match order_type {
            OrderType::Market => {
                let base_price = match side {
                    Side::Buy => tick.ask,
                    Side::Sell => tick.bid,
                };
                let slippage = self.calculate_slippage(&base_price, side);
                let fill_price = match side {
                    Side::Buy => Price::new(*base_price + slippage),
                    Side::Sell => Price::new(*base_price - slippage),
                };
                let order = self.pending_orders.remove(&order_id).unwrap();
                Some(self.create_fill_event(&order, fill_price, slippage, tick))
            }
            OrderType::Limit => {
                let limit_price = order.price?;
                let should_fill = match side {
                    Side::Buy => *tick.ask <= *limit_price,
                    Side::Sell => *tick.bid >= *limit_price,
                };
                if should_fill {
                    let order = self.pending_orders.remove(&order_id).unwrap();
                    Some(self.create_fill_event(&order, limit_price, Decimal::ZERO, tick))
                } else {
                    None
                }
            }
            OrderType::Stop => {
                let stop_price = order.stop_price?;
                let triggered = match side {
                    Side::Buy => *tick.ask >= *stop_price,
                    Side::Sell => *tick.bid <= *stop_price,
                };
                if triggered {
                    let base_price = match side {
                        Side::Buy => tick.ask,
                        Side::Sell => tick.bid,
                    };
                    let slippage = self.calculate_slippage(&base_price, side);
                    let fill_price = match side {
                        Side::Buy => Price::new(*base_price + slippage),
                        Side::Sell => Price::new(*base_price - slippage),
                    };
                    let order = self.pending_orders.remove(&order_id).unwrap();
                    Some(self.create_fill_event(&order, fill_price, slippage, tick))
                } else {
                    None
                }
            }
            OrderType::StopLimit => {
                // StopLimit: once stop is triggered, acts as a limit order.
                // For simplicity in simulation, if the stop triggers and the limit
                // condition is also met on the same tick, fill. Otherwise reject.
                let stop_price = match order.stop_price {
                    Some(p) => p,
                    None => {
                        let order = self.pending_orders.remove(&order_id).unwrap();
                        return Some(self.create_rejection_event(
                            &order,
                            RejectionReason::InvalidPrice,
                            tick,
                        ));
                    }
                };
                let limit_price = match order.price {
                    Some(p) => p,
                    None => {
                        let order = self.pending_orders.remove(&order_id).unwrap();
                        return Some(self.create_rejection_event(
                            &order,
                            RejectionReason::InvalidPrice,
                            tick,
                        ));
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
                    let order = self.pending_orders.remove(&order_id).unwrap();
                    Some(self.create_fill_event(&order, limit_price, Decimal::ZERO, tick))
                } else {
                    None
                }
            }
        }
    }

    fn create_fill_event(
        &self,
        order: &Order,
        fill_price: Price,
        slippage: Decimal,
        tick: &TickEvent,
    ) -> Event {
        debug!(
            order_id = %order.id,
            fill_price = %fill_price,
            slippage = %slippage,
            "order filled"
        );
        Event::Fill(FillEvent {
            timestamp: tick.timestamp,
            order_id: order.id,
            instrument_id: order.instrument_id.clone(),
            side: order.side,
            fill_price,
            volume: order.volume,
            slippage,
            commission: Decimal::ZERO,
        })
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
}

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

    #[test]
    fn market_buy_fills_immediately() {
        let config = ExecutionModelConfig::default();
        let mut engine = MatchingEngine::new(config, 42);
        let order = test_market_buy();
        let order_id = order.id;
        engine.submit_order(order);
        assert_eq!(engine.pending_count(), 1);

        let tick = test_tick(dec!(1.1000), dec!(1.1002));
        let events = engine.process_tick(&tick);

        assert_eq!(events.len(), 1);
        assert_eq!(engine.pending_count(), 0);
        match &events[0] {
            Event::Fill(fill) => {
                assert_eq!(fill.order_id, order_id);
                assert_eq!(fill.side, Side::Buy);
                // Fill price should be >= ask (slippage)
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
        engine.submit_order(order);

        // Ask above limit — no fill
        let tick_above = test_tick(dec!(1.1008), dec!(1.1010));
        let events = engine.process_tick(&tick_above);
        assert!(events.is_empty());
        assert_eq!(engine.pending_count(), 1);

        // Ask at limit — fill
        let tick_at = test_tick(dec!(1.1003), dec!(1.1005));
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
        engine.submit_order(order);
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
        let slip1 = engine1.calculate_slippage(&price, Side::Buy);
        let slip2 = engine2.calculate_slippage(&price, Side::Buy);
        assert_eq!(slip1, slip2);
    }
}
