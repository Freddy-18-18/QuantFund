use quantfund_core::event::TickEvent;
use quantfund_core::types::Timestamp;
use quantfund_core::InstrumentId;

use crate::provider::{DataError, TickDataProvider};

/// Replays tick data in chronological order.
/// Supports multiple instruments merged by timestamp for deterministic replay.
pub struct TickReplay {
    ticks: Vec<TickEvent>,
    position: usize,
}

impl TickReplay {
    /// Load ticks from a provider for multiple instruments, merged and sorted by timestamp.
    pub fn from_provider(
        provider: &dyn TickDataProvider,
        instruments: &[InstrumentId],
        from: Timestamp,
        to: Timestamp,
    ) -> Result<Self, DataError> {
        let mut all_ticks = Vec::new();

        for instrument in instruments {
            match provider.load_ticks(instrument, from, to) {
                Ok(ticks) => all_ticks.extend(ticks),
                Err(DataError::NoData { .. }) => {
                    // Skip instruments with no data in the range.
                    continue;
                }
                Err(e) => return Err(e),
            }
        }

        if all_ticks.is_empty() {
            return Err(DataError::NoData {
                instrument: "all requested instruments".to_owned(),
            });
        }

        // Sort by timestamp for deterministic chronological replay.
        all_ticks.sort_by_key(|t| t.timestamp);

        Ok(Self {
            ticks: all_ticks,
            position: 0,
        })
    }

    /// Construct directly from a pre-built tick vector.
    pub fn from_ticks(ticks: Vec<TickEvent>) -> Self {
        Self { ticks, position: 0 }
    }

    /// Returns the next tick in sequence, advancing the position.
    pub fn next_tick(&mut self) -> Option<&TickEvent> {
        if self.position < self.ticks.len() {
            let tick = &self.ticks[self.position];
            self.position += 1;
            Some(tick)
        } else {
            None
        }
    }

    /// Peek at the next tick without advancing.
    pub fn peek(&self) -> Option<&TickEvent> {
        self.ticks.get(self.position)
    }

    /// Reset replay to the beginning.
    pub fn reset(&mut self) {
        self.position = 0;
    }

    /// Number of ticks remaining.
    pub fn remaining(&self) -> usize {
        self.ticks.len().saturating_sub(self.position)
    }

    /// Total number of ticks in the replay.
    pub fn total(&self) -> usize {
        self.ticks.len()
    }

    /// Progress as a fraction from 0.0 (start) to 1.0 (complete).
    pub fn progress(&self) -> f64 {
        if self.ticks.is_empty() {
            return 1.0;
        }
        self.position as f64 / self.ticks.len() as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::provider::InMemoryProvider;
    use quantfund_core::types::{Price, Volume};
    use rust_decimal_macros::dec;

    fn make_tick(instrument: &str, ts_nanos: i64, bid: Decimal, ask: Decimal) -> TickEvent {
        TickEvent {
            timestamp: Timestamp::from_nanos(ts_nanos),
            instrument_id: InstrumentId::new(instrument),
            bid: Price::new(bid),
            ask: Price::new(ask),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: ask - bid,
        }
    }

    use rust_decimal::Decimal;

    #[test]
    fn replay_from_provider_merges_instruments() {
        let mut provider = InMemoryProvider::new();
        provider.add_ticks(
            InstrumentId::new("EURUSD"),
            vec![
                make_tick("EURUSD", 100, dec!(1.1000), dec!(1.1002)),
                make_tick("EURUSD", 300, dec!(1.1001), dec!(1.1003)),
            ],
        );
        provider.add_ticks(
            InstrumentId::new("GBPUSD"),
            vec![
                make_tick("GBPUSD", 200, dec!(1.3000), dec!(1.3002)),
                make_tick("GBPUSD", 400, dec!(1.3001), dec!(1.3003)),
            ],
        );

        let instruments = vec![InstrumentId::new("EURUSD"), InstrumentId::new("GBPUSD")];
        let mut replay = TickReplay::from_provider(
            &provider,
            &instruments,
            Timestamp::from_nanos(0),
            Timestamp::from_nanos(500),
        )
        .unwrap();

        assert_eq!(replay.total(), 4);
        assert_eq!(replay.remaining(), 4);
        assert!((replay.progress() - 0.0).abs() < f64::EPSILON);

        // Should replay in timestamp order across instruments.
        let t1 = replay.next_tick().unwrap();
        assert_eq!(t1.instrument_id, InstrumentId::new("EURUSD"));
        assert_eq!(t1.timestamp, Timestamp::from_nanos(100));

        let t2 = replay.next_tick().unwrap();
        assert_eq!(t2.instrument_id, InstrumentId::new("GBPUSD"));
        assert_eq!(t2.timestamp, Timestamp::from_nanos(200));

        let t3 = replay.next_tick().unwrap();
        assert_eq!(t3.instrument_id, InstrumentId::new("EURUSD"));
        assert_eq!(t3.timestamp, Timestamp::from_nanos(300));

        let t4 = replay.next_tick().unwrap();
        assert_eq!(t4.instrument_id, InstrumentId::new("GBPUSD"));
        assert_eq!(t4.timestamp, Timestamp::from_nanos(400));

        assert!(replay.next_tick().is_none());
        assert_eq!(replay.remaining(), 0);
        assert!((replay.progress() - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn peek_does_not_advance() {
        let ticks = vec![
            make_tick("EURUSD", 100, dec!(1.1000), dec!(1.1002)),
            make_tick("EURUSD", 200, dec!(1.1001), dec!(1.1003)),
        ];
        let mut replay = TickReplay::from_ticks(ticks);

        let peeked = replay.peek().unwrap().timestamp;
        let next = replay.next_tick().unwrap().timestamp;
        assert_eq!(peeked, next);
    }

    #[test]
    fn reset_returns_to_start() {
        let ticks = vec![
            make_tick("EURUSD", 100, dec!(1.1000), dec!(1.1002)),
            make_tick("EURUSD", 200, dec!(1.1001), dec!(1.1003)),
        ];
        let mut replay = TickReplay::from_ticks(ticks);

        replay.next_tick();
        replay.next_tick();
        assert_eq!(replay.remaining(), 0);

        replay.reset();
        assert_eq!(replay.remaining(), 2);
        assert!((replay.progress() - 0.0).abs() < f64::EPSILON);
    }
}
