use std::collections::HashMap;

use quantfund_core::{Event, InstrumentId};
use tracing::{debug, trace};

use crate::bus::EventBus;
use crate::handler::EventHandler;

/// Routes events to handlers, optionally partitioned by instrument.
///
/// Global handlers receive every event (subject to their `accepts()` filter).
/// Instrument-specific handlers only receive events whose `instrument_id()`
/// matches the registered instrument.
pub struct EventRouter {
    /// Global handlers that receive all events.
    global_handlers: Vec<Box<dyn EventHandler>>,
    /// Per-instrument handlers.
    instrument_handlers: HashMap<InstrumentId, Vec<Box<dyn EventHandler>>>,
    /// The event bus for draining inbound events and publishing responses.
    bus: EventBus,
}

impl EventRouter {
    /// Create a new router backed by the given event bus.
    pub fn new(bus: EventBus) -> Self {
        Self {
            global_handlers: Vec::new(),
            instrument_handlers: HashMap::new(),
            bus,
        }
    }

    /// Register a handler that receives all events.
    pub fn register_global(&mut self, handler: Box<dyn EventHandler>) {
        debug!(handler = handler.name(), "registered global handler");
        self.global_handlers.push(handler);
    }

    /// Register a handler for a specific instrument.
    pub fn register_for_instrument(
        &mut self,
        instrument: InstrumentId,
        handler: Box<dyn EventHandler>,
    ) {
        debug!(
            handler = handler.name(),
            instrument = %instrument,
            "registered instrument handler",
        );
        self.instrument_handlers
            .entry(instrument)
            .or_default()
            .push(handler);
    }

    /// Route a single event to all applicable handlers and collect responses.
    ///
    /// An event is dispatched to:
    /// 1. Every global handler whose `accepts()` returns `true`.
    /// 2. Every instrument-specific handler registered for the event's
    ///    `instrument_id()`, whose `accepts()` also returns `true`.
    pub fn route(&mut self, event: &Event) -> Vec<Event> {
        let mut responses = Vec::new();

        // Global handlers
        for handler in &mut self.global_handlers {
            if handler.accepts(event) {
                trace!(
                    handler = handler.name(),
                    event_type = event.event_type(),
                    "routing to global handler",
                );
                let produced = handler.handle(event);
                responses.extend(produced);
            }
        }

        // Instrument-specific handlers
        if let Some(instrument_id) = event.instrument_id()
            && let Some(handlers) = self.instrument_handlers.get_mut(instrument_id) {
                for handler in handlers {
                    if handler.accepts(event) {
                        trace!(
                            handler = handler.name(),
                            event_type = event.event_type(),
                            instrument = %instrument_id,
                            "routing to instrument handler",
                        );
                        let produced = handler.handle(event);
                        responses.extend(produced);
                    }
                }
            }

        responses
    }

    /// Run one full processing cycle: drain all events from the bus, route each
    /// one, and publish any response events back onto the bus.
    ///
    /// Returns the number of events processed in this cycle.
    pub fn process_cycle(&mut self) -> usize {
        let events = self.bus.drain();
        let count = events.len();

        if count > 0 {
            debug!(count, "processing event cycle");
        }

        let mut responses = Vec::new();
        for event in &events {
            let produced = self.route(event);
            responses.extend(produced);
        }

        for response in responses {
            // Best-effort publish; if the bus is full the error is logged
            // inside `publish` via tracing.
            let _ = self.bus.publish(response);
        }

        count
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bus::EventBusConfig;
    use quantfund_core::{HeartbeatEvent, InstrumentId, SessionEvent, Timestamp, TradingSession};

    /// A handler that echoes back a heartbeat for every event it receives.
    struct EchoHandler {
        name: &'static str,
        received: usize,
    }

    impl EchoHandler {
        fn new(name: &'static str) -> Self {
            Self { name, received: 0 }
        }
    }

    impl EventHandler for EchoHandler {
        fn handle(&mut self, _event: &Event) -> Vec<Event> {
            self.received += 1;
            vec![Event::Heartbeat(HeartbeatEvent {
                timestamp: Timestamp::now(),
            })]
        }

        fn name(&self) -> &str {
            self.name
        }
    }

    /// A handler that only accepts SessionOpen events.
    struct SessionOnlyHandler {
        received: usize,
    }

    impl EventHandler for SessionOnlyHandler {
        fn handle(&mut self, _event: &Event) -> Vec<Event> {
            self.received += 1;
            Vec::new()
        }

        fn name(&self) -> &str {
            "session_only"
        }

        fn accepts(&self, event: &Event) -> bool {
            matches!(event, Event::SessionOpen(_))
        }
    }

    fn heartbeat() -> Event {
        Event::Heartbeat(HeartbeatEvent {
            timestamp: Timestamp::now(),
        })
    }

    fn tick_event(instrument: &str) -> Event {
        use quantfund_core::{Price, TickEvent, Volume};
        use rust_decimal::Decimal;

        Event::Tick(TickEvent {
            timestamp: Timestamp::now(),
            instrument_id: InstrumentId::new(instrument),
            bid: Price::new(Decimal::new(1000, 1)),
            ask: Price::new(Decimal::new(1001, 1)),
            bid_volume: Volume::new(Decimal::new(1, 0)),
            ask_volume: Volume::new(Decimal::new(1, 0)),
            spread: Decimal::new(1, 1),
        })
    }

    #[test]
    fn global_handler_receives_events() {
        let bus = EventBus::with_default();
        let mut router = EventRouter::new(bus);

        router.register_global(Box::new(EchoHandler::new("echo")));

        let responses = router.route(&heartbeat());
        // EchoHandler produces one heartbeat response per event
        assert_eq!(responses.len(), 1);
    }

    #[test]
    fn accepts_filter_is_respected() {
        let bus = EventBus::with_default();
        let mut router = EventRouter::new(bus);

        router.register_global(Box::new(SessionOnlyHandler { received: 0 }));

        // Heartbeat should be filtered out
        let responses = router.route(&heartbeat());
        assert!(responses.is_empty());

        // SessionOpen should be accepted
        let session = Event::SessionOpen(SessionEvent {
            timestamp: Timestamp::now(),
            session: TradingSession::London,
        });
        let responses = router.route(&session);
        assert!(responses.is_empty()); // SessionOnlyHandler returns empty vec
    }

    #[test]
    fn instrument_handler_receives_matching_events() {
        let bus = EventBus::with_default();
        let mut router = EventRouter::new(bus);

        let instrument = InstrumentId::new("EURUSD");
        router.register_for_instrument(instrument, Box::new(EchoHandler::new("eurusd_handler")));

        // Tick for EURUSD should reach the instrument handler
        let responses = router.route(&tick_event("EURUSD"));
        assert_eq!(responses.len(), 1);

        // Tick for GBPUSD should not reach it
        let responses = router.route(&tick_event("GBPUSD"));
        assert!(responses.is_empty());
    }

    #[test]
    fn process_cycle_drains_and_routes() {
        let config = EventBusConfig {
            channel_capacity: 1024,
            subscriber_capacity: 1024,
        };
        let bus = EventBus::new(config);

        // Publish 3 events onto the bus
        bus.publish(heartbeat()).unwrap();
        bus.publish(heartbeat()).unwrap();
        bus.publish(heartbeat()).unwrap();

        let mut router = EventRouter::new(bus);
        router.register_global(Box::new(EchoHandler::new("echo")));

        let processed = router.process_cycle();
        assert_eq!(processed, 3);
    }

    #[test]
    fn process_cycle_publishes_responses() {
        let config = EventBusConfig {
            channel_capacity: 1024,
            subscriber_capacity: 1024,
        };
        let bus = EventBus::new(config);
        bus.publish(heartbeat()).unwrap();

        let mut router = EventRouter::new(bus);
        router.register_global(Box::new(EchoHandler::new("echo")));

        // First cycle: processes 1 event, EchoHandler produces 1 response
        let processed = router.process_cycle();
        assert_eq!(processed, 1);

        // Second cycle: processes the 1 response event from the first cycle
        let processed = router.process_cycle();
        assert_eq!(processed, 1);
    }

    #[test]
    fn empty_bus_yields_zero_cycle() {
        let bus = EventBus::with_default();
        let mut router = EventRouter::new(bus);

        let processed = router.process_cycle();
        assert_eq!(processed, 0);
    }
}
