use std::collections::HashMap;

use rust_decimal::Decimal;
use rust_decimal_macros::dec;

use quantfund_core::event::TickEvent;
use quantfund_core::types::{OrderId, Price, Side, Timestamp, Volume};

// ─── Queue Entry ─────────────────────────────────────────────────────────────

/// Represents a single order's position in the simulated order book queue.
#[derive(Clone, Debug)]
pub struct QueueEntry {
    pub order_id: OrderId,
    pub side: Side,
    pub price: Price,
    pub volume: Volume,
    /// Timestamp when the order entered the queue (for price-time priority).
    pub entry_time: Timestamp,
    /// Estimated queue position ahead of this order (in volume terms).
    /// This is the total volume of orders at this price level that arrived before us.
    pub volume_ahead: Decimal,
}

// ─── Queue Position Tracker ──────────────────────────────────────────────────

/// Tracks simulated queue positions for limit orders using price-time priority.
///
/// In real markets, limit orders sit in an order book queue. When the market
/// trades at a limit price, orders are filled in FIFO order. This tracker
/// simulates that by estimating how much volume sits ahead of each order
/// and draining the queue as volume trades at the limit price.
///
/// The model:
/// - When a limit order is placed, it enters the queue with an estimated
///   `volume_ahead` based on `queue_depth_factor * tick_volume`.
/// - Each tick at or beyond the limit price drains the queue by the tick's
///   traded volume.
/// - When `volume_ahead` reaches zero, the order is eligible for fill.
pub struct QueueTracker {
    /// Active queue entries indexed by order ID.
    entries: HashMap<OrderId, QueueEntry>,
    /// Factor to estimate initial queue depth from tick volume.
    /// Higher = more conservative (orders sit longer in queue).
    queue_depth_factor: Decimal,
}

impl QueueTracker {
    pub fn new(queue_depth_factor: Decimal) -> Self {
        Self {
            entries: HashMap::new(),
            queue_depth_factor,
        }
    }

    /// Register a limit order in the queue tracker.
    /// The initial `volume_ahead` is estimated from the available tick volume
    /// at the price level.
    pub fn enter_queue(
        &mut self,
        order_id: OrderId,
        side: Side,
        price: Price,
        volume: Volume,
        entry_time: Timestamp,
        current_tick_volume: &Volume,
    ) {
        let volume_ahead = **current_tick_volume * self.queue_depth_factor;
        let entry = QueueEntry {
            order_id,
            side,
            price,
            volume,
            entry_time,
            volume_ahead,
        };
        self.entries.insert(order_id, entry);
    }

    /// Process a tick: drain queue positions for orders whose limit price
    /// has been reached or crossed. Returns a list of order IDs that have
    /// cleared the queue and are now eligible for fill.
    pub fn process_tick(&mut self, tick: &TickEvent) -> Vec<OrderId> {
        let mut fillable = Vec::new();

        for entry in self.entries.values_mut() {
            let at_price = match entry.side {
                // Buy limit: fillable when ask <= limit price.
                Side::Buy => *tick.ask <= *entry.price,
                // Sell limit: fillable when bid >= limit price.
                Side::Sell => *tick.bid >= *entry.price,
            };

            if !at_price {
                continue;
            }

            // Drain the queue by the volume traded at this tick.
            // Use the side-appropriate volume from the tick.
            let traded_volume = match entry.side {
                Side::Buy => *tick.ask_volume,
                Side::Sell => *tick.bid_volume,
            };

            entry.volume_ahead -= traded_volume;
            if entry.volume_ahead < Decimal::ZERO {
                entry.volume_ahead = Decimal::ZERO;
            }

            // If no volume remains ahead, this order is at the front of the queue.
            if entry.volume_ahead <= Decimal::ZERO {
                fillable.push(entry.order_id);
            }
        }

        fillable
    }

    /// Remove an order from the queue (after fill or cancel).
    pub fn remove(&mut self, order_id: &OrderId) -> Option<QueueEntry> {
        self.entries.remove(order_id)
    }

    /// Check whether an order is being tracked in the queue.
    pub fn contains(&self, order_id: &OrderId) -> bool {
        self.entries.contains_key(order_id)
    }

    /// Get the queue entry for an order.
    pub fn get(&self, order_id: &OrderId) -> Option<&QueueEntry> {
        self.entries.get(order_id)
    }

    /// Number of orders currently in the queue.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether the queue is empty.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

impl Default for QueueTracker {
    fn default() -> Self {
        Self::new(dec!(3)) // 3x tick volume as default queue depth
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::InstrumentId;
    use rust_decimal_macros::dec;

    fn test_tick(bid: Decimal, ask: Decimal, vol: Decimal) -> TickEvent {
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

    #[test]
    fn enter_and_drain_queue() {
        // queue_depth_factor = 2, tick volume = 10 -> volume_ahead = 20
        let mut tracker = QueueTracker::new(dec!(2));
        let order_id = OrderId::new();

        tracker.enter_queue(
            order_id,
            Side::Buy,
            Price::new(dec!(1.1000)),
            Volume::new(dec!(1)),
            Timestamp::from_nanos(100),
            &Volume::new(dec!(10)),
        );

        assert_eq!(tracker.len(), 1);
        let entry = tracker.get(&order_id).unwrap();
        assert_eq!(entry.volume_ahead, dec!(20));

        // Tick at the limit price with volume 8 -> 20 - 8 = 12 ahead.
        let tick = test_tick(dec!(1.0998), dec!(1.1000), dec!(8));
        let fillable = tracker.process_tick(&tick);
        assert!(fillable.is_empty());
        assert_eq!(tracker.get(&order_id).unwrap().volume_ahead, dec!(12));

        // Tick with volume 15 -> 12 - 15 = 0 (clamped). Now fillable.
        let tick2 = test_tick(dec!(1.0998), dec!(1.0999), dec!(15));
        let fillable = tracker.process_tick(&tick2);
        assert_eq!(fillable.len(), 1);
        assert_eq!(fillable[0], order_id);
    }

    #[test]
    fn no_drain_when_price_not_at_limit() {
        let mut tracker = QueueTracker::new(dec!(2));
        let order_id = OrderId::new();

        tracker.enter_queue(
            order_id,
            Side::Buy,
            Price::new(dec!(1.1000)),
            Volume::new(dec!(1)),
            Timestamp::from_nanos(100),
            &Volume::new(dec!(10)),
        );

        // Ask above limit -> no drain.
        let tick = test_tick(dec!(1.1005), dec!(1.1010), dec!(100));
        let fillable = tracker.process_tick(&tick);
        assert!(fillable.is_empty());
        assert_eq!(tracker.get(&order_id).unwrap().volume_ahead, dec!(20));
    }

    #[test]
    fn sell_limit_queue_tracking() {
        let mut tracker = QueueTracker::new(dec!(1));
        let order_id = OrderId::new();

        tracker.enter_queue(
            order_id,
            Side::Sell,
            Price::new(dec!(1.1050)),
            Volume::new(dec!(1)),
            Timestamp::from_nanos(100),
            &Volume::new(dec!(5)),
        );

        let entry = tracker.get(&order_id).unwrap();
        assert_eq!(entry.volume_ahead, dec!(5));

        // Bid at or above limit -> drain.
        let tick = test_tick(dec!(1.1050), dec!(1.1052), dec!(6));
        let fillable = tracker.process_tick(&tick);
        assert_eq!(fillable.len(), 1);
    }

    #[test]
    fn remove_clears_entry() {
        let mut tracker = QueueTracker::default();
        let order_id = OrderId::new();

        tracker.enter_queue(
            order_id,
            Side::Buy,
            Price::new(dec!(1.1000)),
            Volume::new(dec!(1)),
            Timestamp::from_nanos(100),
            &Volume::new(dec!(10)),
        );

        assert!(tracker.contains(&order_id));
        tracker.remove(&order_id);
        assert!(!tracker.contains(&order_id));
        assert!(tracker.is_empty());
    }

    #[test]
    fn multiple_orders_independent() {
        let mut tracker = QueueTracker::new(dec!(1));
        let id1 = OrderId::new();
        let id2 = OrderId::new();

        // Buy limit at 1.1000 and 1.0990 (different prices).
        tracker.enter_queue(
            id1,
            Side::Buy,
            Price::new(dec!(1.1000)),
            Volume::new(dec!(1)),
            Timestamp::from_nanos(100),
            &Volume::new(dec!(5)), // volume_ahead = 5
        );
        tracker.enter_queue(
            id2,
            Side::Buy,
            Price::new(dec!(1.0990)),
            Volume::new(dec!(1)),
            Timestamp::from_nanos(200),
            &Volume::new(dec!(5)), // volume_ahead = 5
        );

        // Tick at 1.1000 -> only id1 drains.
        let tick = test_tick(dec!(1.0998), dec!(1.1000), dec!(10));
        let fillable = tracker.process_tick(&tick);
        assert_eq!(fillable.len(), 1);
        assert_eq!(fillable[0], id1);

        // id2 still has full queue.
        assert_eq!(tracker.get(&id2).unwrap().volume_ahead, dec!(5));
    }
}
