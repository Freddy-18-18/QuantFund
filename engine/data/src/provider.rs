use std::collections::HashMap;

use quantfund_core::event::TickEvent;
use quantfund_core::types::Timestamp;
use quantfund_core::InstrumentId;

/// Error types for data operations.
#[derive(Debug, thiserror::Error)]
pub enum DataError {
    #[error("no data available for {instrument} in range")]
    NoData { instrument: String },
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("parse error: {0}")]
    Parse(String),
    #[error("parquet error: {0}")]
    Parquet(String),
}

/// Trait for tick data providers.
/// Abstracts over file-based (Parquet) and live (MT5) data sources.
pub trait TickDataProvider: Send {
    /// Load ticks for an instrument within a time range.
    fn load_ticks(
        &self,
        instrument: &InstrumentId,
        from: Timestamp,
        to: Timestamp,
    ) -> Result<Vec<TickEvent>, DataError>;

    /// Get the available time range for an instrument.
    fn available_range(
        &self,
        instrument: &InstrumentId,
    ) -> Result<(Timestamp, Timestamp), DataError>;

    /// List available instruments.
    fn instruments(&self) -> Result<Vec<InstrumentId>, DataError>;
}

/// In-memory tick data provider for testing and small backtests.
pub struct InMemoryProvider {
    ticks: HashMap<InstrumentId, Vec<TickEvent>>,
}

impl InMemoryProvider {
    pub fn new() -> Self {
        Self {
            ticks: HashMap::new(),
        }
    }

    /// Add ticks for an instrument. Ticks are sorted by timestamp on insertion.
    pub fn add_ticks(&mut self, instrument: InstrumentId, mut ticks: Vec<TickEvent>) {
        ticks.sort_by_key(|t| t.timestamp);
        self.ticks.entry(instrument).or_default().extend(ticks);
    }
}

impl Default for InMemoryProvider {
    fn default() -> Self {
        Self::new()
    }
}

impl TickDataProvider for InMemoryProvider {
    fn load_ticks(
        &self,
        instrument: &InstrumentId,
        from: Timestamp,
        to: Timestamp,
    ) -> Result<Vec<TickEvent>, DataError> {
        let ticks = self
            .ticks
            .get(instrument)
            .ok_or_else(|| DataError::NoData {
                instrument: instrument.to_string(),
            })?;

        let filtered: Vec<TickEvent> = ticks
            .iter()
            .filter(|t| t.timestamp >= from && t.timestamp <= to)
            .cloned()
            .collect();

        if filtered.is_empty() {
            return Err(DataError::NoData {
                instrument: instrument.to_string(),
            });
        }

        Ok(filtered)
    }

    fn available_range(
        &self,
        instrument: &InstrumentId,
    ) -> Result<(Timestamp, Timestamp), DataError> {
        let ticks = self
            .ticks
            .get(instrument)
            .ok_or_else(|| DataError::NoData {
                instrument: instrument.to_string(),
            })?;

        if ticks.is_empty() {
            return Err(DataError::NoData {
                instrument: instrument.to_string(),
            });
        }

        // Ticks are sorted by timestamp on insertion.
        let first = ticks.first().unwrap().timestamp;
        let last = ticks.last().unwrap().timestamp;
        Ok((first, last))
    }

    fn instruments(&self) -> Result<Vec<InstrumentId>, DataError> {
        Ok(self.ticks.keys().cloned().collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::types::{Price, Volume};
    use rust_decimal_macros::dec;

    fn make_tick(instrument: &str, ts_nanos: i64) -> TickEvent {
        TickEvent {
            timestamp: Timestamp::from_nanos(ts_nanos),
            instrument_id: InstrumentId::new(instrument),
            bid: Price::new(dec!(1.1000)),
            ask: Price::new(dec!(1.1002)),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: dec!(0.0002),
        }
    }

    #[test]
    fn load_ticks_filters_by_range() {
        let mut provider = InMemoryProvider::new();
        let instrument = InstrumentId::new("EURUSD");
        let ticks = vec![
            make_tick("EURUSD", 100),
            make_tick("EURUSD", 200),
            make_tick("EURUSD", 300),
            make_tick("EURUSD", 400),
        ];
        provider.add_ticks(instrument.clone(), ticks);

        let result = provider
            .load_ticks(
                &instrument,
                Timestamp::from_nanos(150),
                Timestamp::from_nanos(350),
            )
            .unwrap();
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].timestamp, Timestamp::from_nanos(200));
        assert_eq!(result[1].timestamp, Timestamp::from_nanos(300));
    }

    #[test]
    fn available_range_returns_min_max() {
        let mut provider = InMemoryProvider::new();
        let instrument = InstrumentId::new("EURUSD");
        let ticks = vec![make_tick("EURUSD", 100), make_tick("EURUSD", 500)];
        provider.add_ticks(instrument.clone(), ticks);

        let (from, to) = provider.available_range(&instrument).unwrap();
        assert_eq!(from, Timestamp::from_nanos(100));
        assert_eq!(to, Timestamp::from_nanos(500));
    }

    #[test]
    fn no_data_for_unknown_instrument() {
        let provider = InMemoryProvider::new();
        let instrument = InstrumentId::new("UNKNOWN");
        let result = provider.load_ticks(
            &instrument,
            Timestamp::from_nanos(0),
            Timestamp::from_nanos(1000),
        );
        assert!(result.is_err());
    }
}
