//! FRED Macro Signal Strategy.
//!
//! Consumes pre-generated FRED economic signals (from `fred_signals_commands.rs`
//! or the Python research layer) and emits them as [`SignalEvent`]s during
//! backtesting or live trading.
//!
//! Unlike `PythonSignalRelay` (which polls a JSON file on disk), this strategy
//! loads signals **in-memory** at construction time — ideal for deterministic
//! backtesting where all macro events are known in advance.
//!
//! ## Usage
//! 1. Generate FRED signals using the dashboard's FRED analysis commands
//! 2. Serialize them to `Vec<FredSignalEntry>`
//! 3. Pass to `FredSignalStrategy::new(config, signals)`
//! 4. Drop into the backtest runner as any other `Strategy`

use quantfund_core::types::Side;
use quantfund_core::{InstrumentId, SignalEvent, StrategyId};

use crate::traits::{MarketSnapshot, Strategy};

// ─── Signal entry ────────────────────────────────────────────────────────────

/// A single macro signal event from FRED analysis.
#[derive(Clone, Debug)]
pub struct FredSignalEntry {
    /// When this signal was generated (nanoseconds since epoch).
    pub timestamp_ns: i64,
    /// Trading direction.
    pub side: Option<Side>,
    /// Signal strength in [-1.0, 1.0].
    pub strength: f64,
    /// Human-readable label (e.g. "CPI up → gold bullish").
    pub label: String,
}

// ─── Config ──────────────────────────────────────────────────────────────────

/// Configuration for the FRED signal strategy.
#[derive(Clone, Debug)]
pub struct FredSignalStrategyConfig {
    /// Instruments this strategy applies to.
    pub instruments: Vec<InstrumentId>,
    /// Strategy identifier.
    pub strategy_id: String,
    /// How long a signal stays active (nanoseconds). Default: 24 hours.
    pub signal_ttl_ns: i64,
}

impl Default for FredSignalStrategyConfig {
    fn default() -> Self {
        Self {
            instruments: vec![InstrumentId::new("XAUUSD")],
            strategy_id: "fred-macro".to_string(),
            signal_ttl_ns: 24 * 3600 * 1_000_000_000, // 24 hours
        }
    }
}

// ─── Strategy ────────────────────────────────────────────────────────────────

/// Strategy that replays pre-generated FRED macro signals.
pub struct FredSignalStrategy {
    id: StrategyId,
    config: FredSignalStrategyConfig,
    /// Sorted by timestamp (ascending).
    signals: Vec<FredSignalEntry>,
    /// Current index into the signals vector.
    cursor: usize,
    /// The most recently emitted signal (for TTL-based repetition).
    active_signal: Option<FredSignalEntry>,
}

impl FredSignalStrategy {
    /// Create a new strategy with pre-loaded signals.
    ///
    /// Signals will be sorted by timestamp if not already sorted.
    pub fn new(config: FredSignalStrategyConfig, mut signals: Vec<FredSignalEntry>) -> Self {
        // Sort ascending by timestamp
        signals.sort_by_key(|s| s.timestamp_ns);

        Self {
            id: StrategyId::new(config.strategy_id.clone()),
            config,
            signals,
            cursor: 0,
            active_signal: None,
        }
    }

    /// Advance the cursor to find signals that are now active.
    fn advance_to(&mut self, now_ns: i64) {
        while self.cursor < self.signals.len()
            && self.signals[self.cursor].timestamp_ns <= now_ns
        {
            self.active_signal = Some(self.signals[self.cursor].clone());
            self.cursor += 1;
        }
    }
}

impl Strategy for FredSignalStrategy {
    fn id(&self) -> &StrategyId {
        &self.id
    }

    fn name(&self) -> &str {
        "FRED Macro Signals"
    }

    fn instruments(&self) -> &[InstrumentId] {
        &self.config.instruments
    }

    fn on_tick(&mut self, snapshot: &MarketSnapshot) -> Option<SignalEvent> {
        // Check if this instrument is managed
        if !self.config.instruments.contains(snapshot.instrument_id) {
            return None;
        }

        let now_ns = snapshot.tick.timestamp.as_nanos();

        // Advance cursor to pickup any new signals
        self.advance_to(now_ns);

        // Check if we have an active signal within TTL
        let signal = self.active_signal.as_ref()?;
        let age_ns = now_ns - signal.timestamp_ns;
        if age_ns > self.config.signal_ttl_ns {
            return None; // Signal expired
        }

        // Only emit if signal has a direction
        let side = signal.side?;
        let strength = signal.strength.clamp(-1.0, 1.0);

        // Don't emit flat signals
        if strength.abs() < 1e-9 {
            return None;
        }

        Some(SignalEvent {
            timestamp: snapshot.tick.timestamp,
            strategy_id: self.id.clone(),
            instrument_id: snapshot.instrument_id.clone(),
            side: Some(side),
            strength,
            metadata: serde_json::json!({
                "source": "fred",
                "label": signal.label,
                "signal_age_secs": age_ns / 1_000_000_000,
            }),
        })
    }

    fn reset(&mut self) {
        self.cursor = 0;
        self.active_signal = None;
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::{Price, TickEvent, Timestamp, Volume};
    use rust_decimal_macros::dec;

    fn make_tick(instrument: &str, ts_nanos: i64) -> TickEvent {
        TickEvent {
            timestamp: Timestamp::from_nanos(ts_nanos),
            instrument_id: InstrumentId::new(instrument),
            bid: Price::new(dec!(2000.00)),
            ask: Price::new(dec!(2000.30)),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: dec!(0.30),
        }
    }

    fn make_snapshot<'a>(tick: &'a TickEvent, id: &'a InstrumentId) -> MarketSnapshot<'a> {
        MarketSnapshot {
            tick,
            instrument_id: id,
        }
    }

    fn sample_signals() -> Vec<FredSignalEntry> {
        vec![
            FredSignalEntry {
                timestamp_ns: 100_000_000_000, // 100s
                side: Some(Side::Buy),
                strength: 0.75,
                label: "CPI surprise up → gold bullish".to_string(),
            },
            FredSignalEntry {
                timestamp_ns: 200_000_000_000, // 200s
                side: Some(Side::Sell),
                strength: -0.6,
                label: "Strong NFP → gold bearish".to_string(),
            },
        ]
    }

    #[test]
    fn no_signal_before_first_entry() {
        let config = FredSignalStrategyConfig::default();
        let mut strategy = FredSignalStrategy::new(config, sample_signals());
        let id = InstrumentId::new("XAUUSD");

        let tick = make_tick("XAUUSD", 50_000_000_000); // 50s, before first signal
        let snap = make_snapshot(&tick, &id);
        assert!(strategy.on_tick(&snap).is_none());
    }

    #[test]
    fn emits_correct_signal_for_timestamp() {
        let config = FredSignalStrategyConfig::default();
        let mut strategy = FredSignalStrategy::new(config, sample_signals());
        let id = InstrumentId::new("XAUUSD");

        // Tick at 150s → should pick up the 100s Buy signal
        let tick = make_tick("XAUUSD", 150_000_000_000);
        let snap = make_snapshot(&tick, &id);
        let signal = strategy.on_tick(&snap).expect("should have signal");
        assert_eq!(signal.side, Some(Side::Buy));
        assert!((signal.strength - 0.75).abs() < 1e-9);
    }

    #[test]
    fn second_signal_overrides_first() {
        let config = FredSignalStrategyConfig::default();
        let mut strategy = FredSignalStrategy::new(config, sample_signals());
        let id = InstrumentId::new("XAUUSD");

        // Tick at 250s → should pick up the 200s Sell signal
        let tick = make_tick("XAUUSD", 250_000_000_000);
        let snap = make_snapshot(&tick, &id);
        let signal = strategy.on_tick(&snap).expect("should have signal");
        assert_eq!(signal.side, Some(Side::Sell));
        assert!((signal.strength - (-0.6)).abs() < 1e-9);
    }

    #[test]
    fn expired_signal_returns_none() {
        let config = FredSignalStrategyConfig {
            signal_ttl_ns: 10_000_000_000, // 10 seconds TTL
            ..Default::default()
        };
        let mut strategy = FredSignalStrategy::new(config, sample_signals());
        let id = InstrumentId::new("XAUUSD");

        // Tick at 200s, but TTL is 10s → signal at 100s is expired
        // and 200s signal hasn't been picked up yet relative to TTL check
        let tick = make_tick("XAUUSD", 115_000_000_000); // 115s, 15s after 100s signal
        let snap = make_snapshot(&tick, &id);
        assert!(strategy.on_tick(&snap).is_none());
    }

    #[test]
    fn reset_returns_to_beginning() {
        let config = FredSignalStrategyConfig::default();
        let mut strategy = FredSignalStrategy::new(config, sample_signals());
        let id = InstrumentId::new("XAUUSD");

        // Advance past all signals
        let tick = make_tick("XAUUSD", 300_000_000_000);
        let snap = make_snapshot(&tick, &id);
        strategy.on_tick(&snap);
        assert_eq!(strategy.cursor, 2);

        // Reset
        strategy.reset();
        assert_eq!(strategy.cursor, 0);
        assert!(strategy.active_signal.is_none());

        // Should be able to replay
        let tick = make_tick("XAUUSD", 150_000_000_000);
        let snap = make_snapshot(&tick, &id);
        let signal = strategy.on_tick(&snap).expect("should replay signal");
        assert_eq!(signal.side, Some(Side::Buy));
    }
}
