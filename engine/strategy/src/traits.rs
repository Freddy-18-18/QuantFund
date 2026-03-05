use quantfund_core::{BarEvent, InstrumentId, SignalEvent, StrategyId, TickEvent};

/// Market snapshot available to strategies. Contains current market state
/// without exposing any execution or risk internals.
pub struct MarketSnapshot<'a> {
    pub tick: &'a TickEvent,
    pub instrument_id: &'a InstrumentId,
}

/// The trait all trading strategies must implement.
///
/// Strategies are stateless signal generators — they receive market data
/// and produce [`SignalEvent`]s. They **never** directly interact with execution.
pub trait Strategy: Send + Sync {
    /// Unique identifier for this strategy instance.
    fn id(&self) -> &StrategyId;

    /// Human-readable name.
    fn name(&self) -> &str;

    /// Which instruments this strategy trades.
    fn instruments(&self) -> &[InstrumentId];

    /// Process a tick and optionally generate a signal.
    ///
    /// Must execute in < 5 microseconds per instrument.
    fn on_tick(&mut self, snapshot: &MarketSnapshot) -> Option<SignalEvent>;

    /// Process a bar event (for multi-timeframe strategies).
    fn on_bar(&mut self, _bar: &BarEvent) -> Option<SignalEvent> {
        None
    }

    /// Called at session open.
    fn on_session_open(&mut self) {}

    /// Called at session close.
    fn on_session_close(&mut self) {}

    /// Reset strategy state (for backtesting between runs).
    fn reset(&mut self);
}
