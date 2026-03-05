use std::collections::{HashMap, VecDeque};

use quantfund_core::{InstrumentId, Position, TickEvent};
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

/// Read-only context providing historical data to strategies.
///
/// Strategies use this to access price history without managing their own buffers.
/// The engine updates this context before each strategy tick.
pub struct StrategyContext {
    /// Rolling window of recent ticks per instrument.
    tick_buffers: HashMap<InstrumentId, VecDeque<TickEvent>>,
    /// Maximum ticks to retain per instrument.
    max_buffer_size: usize,
    /// Current positions (read-only view).
    positions: Vec<Position>,
    /// Account equity.
    equity: Decimal,
    /// Account balance.
    balance: Decimal,
}

impl StrategyContext {
    /// Create a new context with the given maximum tick buffer size per instrument.
    pub fn new(max_buffer_size: usize) -> Self {
        Self {
            tick_buffers: HashMap::new(),
            max_buffer_size,
            positions: Vec::new(),
            equity: dec!(0),
            balance: dec!(0),
        }
    }

    /// Add a tick to the appropriate instrument buffer, evicting the oldest if full.
    pub fn update_tick(&mut self, tick: &TickEvent) {
        let buffer = self
            .tick_buffers
            .entry(tick.instrument_id.clone())
            .or_insert_with(|| VecDeque::with_capacity(self.max_buffer_size));

        if buffer.len() >= self.max_buffer_size {
            buffer.pop_front();
        }
        buffer.push_back(tick.clone());
    }

    /// Replace the current position snapshot.
    pub fn update_positions(&mut self, positions: Vec<Position>) {
        self.positions = positions;
    }

    /// Update account equity and balance.
    pub fn update_account(&mut self, equity: Decimal, balance: Decimal) {
        self.equity = equity;
        self.balance = balance;
    }

    /// Return up to `count` most-recent ticks for the given instrument as a
    /// contiguous slice.
    ///
    /// Calls [`VecDeque::make_contiguous`] internally so the returned slice is
    /// guaranteed to be a single contiguous memory region.  Returns an empty
    /// slice when no data is available.
    pub fn recent_ticks(&mut self, instrument: &InstrumentId, count: usize) -> &[TickEvent] {
        let Some(buffer) = self.tick_buffers.get_mut(instrument) else {
            return &[];
        };

        let slice = buffer.make_contiguous();
        let len = slice.len();
        if count >= len {
            slice
        } else {
            &slice[len - count..]
        }
    }

    /// Return the most-recent tick for the given instrument, if any.
    pub fn last_tick(&self, instrument: &InstrumentId) -> Option<&TickEvent> {
        self.tick_buffers.get(instrument)?.back()
    }

    /// Return the current open position for the given instrument, if any.
    pub fn position_for(&self, instrument: &InstrumentId) -> Option<&Position> {
        self.positions
            .iter()
            .find(|p| p.instrument_id == *instrument && p.is_open())
    }

    /// Check whether there is an open position for the given instrument.
    pub fn has_open_position(&self, instrument: &InstrumentId) -> bool {
        self.position_for(instrument).is_some()
    }

    /// Current account equity.
    pub fn equity(&self) -> Decimal {
        self.equity
    }

    /// Current account balance.
    pub fn balance(&self) -> Decimal {
        self.balance
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::{Price, Timestamp, Volume};
    use rust_decimal_macros::dec;

    fn make_tick(instrument: &str, bid: Decimal, ask: Decimal) -> TickEvent {
        TickEvent {
            timestamp: Timestamp::now(),
            instrument_id: InstrumentId::new(instrument),
            bid: Price::new(bid),
            ask: Price::new(ask),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: ask - bid,
        }
    }

    #[test]
    fn test_update_and_last_tick() {
        let mut ctx = StrategyContext::new(10);
        let tick = make_tick("EURUSD", dec!(1.1000), dec!(1.1002));
        ctx.update_tick(&tick);

        let last = ctx.last_tick(&InstrumentId::new("EURUSD")).unwrap();
        assert_eq!(*last.bid, dec!(1.1000));
    }

    #[test]
    fn test_buffer_eviction() {
        let mut ctx = StrategyContext::new(3);
        let id = InstrumentId::new("XAUUSD");

        for i in 0..5 {
            let bid = Decimal::from(1900 + i);
            let ask = bid + dec!(1);
            ctx.update_tick(&make_tick("XAUUSD", bid, ask));
        }

        let ticks = ctx.recent_ticks(&id, 10);
        assert_eq!(ticks.len(), 3);
        // Oldest surviving tick should be the one with bid=1902
        assert_eq!(*ticks[0].bid, dec!(1902));
    }

    #[test]
    fn test_recent_ticks_count() {
        let mut ctx = StrategyContext::new(100);
        let id = InstrumentId::new("GBPUSD");

        for i in 0..10 {
            let bid = Decimal::from(i);
            ctx.update_tick(&make_tick("GBPUSD", bid, bid + dec!(1)));
        }

        let ticks = ctx.recent_ticks(&id, 3);
        assert_eq!(ticks.len(), 3);
        assert_eq!(*ticks[0].bid, dec!(7));
    }

    #[test]
    fn test_recent_ticks_empty() {
        let mut ctx = StrategyContext::new(10);
        let id = InstrumentId::new("UNKNOWN");
        let ticks = ctx.recent_ticks(&id, 5);
        assert!(ticks.is_empty());
    }

    #[test]
    fn test_account_update() {
        let mut ctx = StrategyContext::new(10);
        ctx.update_account(dec!(50000), dec!(48000));
        assert_eq!(ctx.equity(), dec!(50000));
        assert_eq!(ctx.balance(), dec!(48000));
    }
}
