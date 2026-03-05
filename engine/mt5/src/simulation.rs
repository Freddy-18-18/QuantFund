/// [`SimulationBridge`] — wraps [`MatchingEngine`] to implement [`ExecutionBridge`].
///
/// This adapter makes `MatchingEngine` and `Mt5Bridge` fully swappable behind
/// the same trait interface.  The backtest runner holds a
/// `Box<dyn ExecutionBridge>` and never needs to know which backend is active.
use quantfund_core::event::{Event, TickEvent};
use quantfund_core::order::Order;
use quantfund_core::types::{OrderId, Timestamp};
use quantfund_execution::MatchingEngine;

use crate::bridge::{BridgeMode, ExecutionBridge};
use crate::error::BridgeError;

/// Wraps a [`MatchingEngine`] and presents it as an [`ExecutionBridge`].
pub struct SimulationBridge {
    engine: MatchingEngine,
}

impl SimulationBridge {
    pub fn new(engine: MatchingEngine) -> Self {
        Self { engine }
    }

    /// Borrow the inner [`MatchingEngine`] (e.g., for metrics or config queries).
    pub fn inner(&self) -> &MatchingEngine {
        &self.engine
    }

    /// Mutably borrow the inner engine.
    pub fn inner_mut(&mut self) -> &mut MatchingEngine {
        &mut self.engine
    }
}

impl ExecutionBridge for SimulationBridge {
    fn submit_order(&mut self, order: Order, now: Timestamp) -> Result<(), BridgeError> {
        self.engine.submit_order(order, now);
        Ok(())
    }

    fn cancel_order(&mut self, order_id: &OrderId) -> Result<(), BridgeError> {
        self.engine.cancel_order(order_id);
        Ok(())
    }

    fn process_tick(&mut self, tick: &TickEvent) -> Vec<Event> {
        self.engine.process_tick(tick)
    }

    fn mode(&self) -> BridgeMode {
        BridgeMode::Simulation
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::event::TickEvent;
    use quantfund_core::instrument::InstrumentId;
    use quantfund_core::types::{Price, Side, StrategyId, Timestamp, Volume};
    use quantfund_execution::{ExecutionModelConfig, MatchingEngine};
    use rust_decimal_macros::dec;

    fn make_bridge() -> SimulationBridge {
        SimulationBridge::new(MatchingEngine::new(ExecutionModelConfig::default(), 42))
    }

    fn test_tick() -> TickEvent {
        TickEvent {
            timestamp: Timestamp::from_nanos(1_000_000_000),
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(dec!(1.1000)),
            ask: Price::new(dec!(1.1002)),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: dec!(0.0002),
        }
    }

    #[test]
    fn simulation_bridge_mode_is_simulation() {
        let bridge = make_bridge();
        assert_eq!(bridge.mode(), BridgeMode::Simulation);
    }

    #[test]
    fn simulation_bridge_submit_and_fill() {
        let mut bridge = make_bridge();
        let order = Order::market(
            InstrumentId::new("EURUSD"),
            Side::Buy,
            Volume::new(dec!(1)),
            StrategyId::new("test"),
        );
        let ts = Timestamp::from_nanos(1_000_000_000);
        bridge
            .submit_order(order, ts)
            .expect("submit should not fail");

        let tick = test_tick();
        let events = bridge.process_tick(&tick);
        assert_eq!(events.len(), 1);
        assert!(matches!(&events[0], quantfund_core::event::Event::Fill(_)));
    }

    #[test]
    fn simulation_bridge_cancel_order() {
        let mut bridge = make_bridge();
        let order = Order::limit(
            InstrumentId::new("EURUSD"),
            Side::Buy,
            Volume::new(dec!(1)),
            Price::new(dec!(1.0900)),
            StrategyId::new("test"),
        );
        let order_id = order.id;
        let ts = Timestamp::from_nanos(1_000_000_000);
        bridge.submit_order(order, ts).unwrap();
        assert_eq!(bridge.inner().pending_count(), 1);

        bridge.cancel_order(&order_id).unwrap();
        assert_eq!(bridge.inner().pending_count(), 0);
    }

    #[test]
    fn simulation_bridge_process_tick_no_orders_returns_empty() {
        let mut bridge = make_bridge();
        let tick = test_tick();
        let events = bridge.process_tick(&tick);
        assert!(events.is_empty());
    }
}
