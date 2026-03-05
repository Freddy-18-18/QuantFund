use quantfund_core::Event;

/// Trait for any component that processes events.
///
/// Each subsystem (strategy, risk, execution) implements this to receive
/// events from the [`EventRouter`](crate::router::EventRouter) and optionally
/// produce response events that get published back to the bus.
pub trait EventHandler: Send + Sync {
    /// Process an incoming event. May produce zero or more response events.
    fn handle(&mut self, event: &Event) -> Vec<Event>;

    /// The name of this handler (for logging and metrics).
    fn name(&self) -> &str;

    /// Whether this handler is interested in the given event.
    ///
    /// The default implementation accepts all events. Override this to filter
    /// by event type, instrument, strategy, etc.
    fn accepts(&self, _event: &Event) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::{HeartbeatEvent, Timestamp};

    /// A minimal handler for testing the trait.
    struct CountingHandler {
        count: usize,
    }

    impl EventHandler for CountingHandler {
        fn handle(&mut self, _event: &Event) -> Vec<Event> {
            self.count += 1;
            Vec::new()
        }

        fn name(&self) -> &str {
            "counting_handler"
        }
    }

    /// A handler that only accepts Heartbeat events.
    struct HeartbeatOnlyHandler;

    impl EventHandler for HeartbeatOnlyHandler {
        fn handle(&mut self, _event: &Event) -> Vec<Event> {
            Vec::new()
        }

        fn name(&self) -> &str {
            "heartbeat_only"
        }

        fn accepts(&self, event: &Event) -> bool {
            matches!(event, Event::Heartbeat(_))
        }
    }

    fn heartbeat() -> Event {
        Event::Heartbeat(HeartbeatEvent {
            timestamp: Timestamp::now(),
        })
    }

    #[test]
    fn handler_processes_events() {
        let mut handler = CountingHandler { count: 0 };
        handler.handle(&heartbeat());
        handler.handle(&heartbeat());
        assert_eq!(handler.count, 2);
    }

    #[test]
    fn handler_name_returns_expected() {
        let handler = CountingHandler { count: 0 };
        assert_eq!(handler.name(), "counting_handler");
    }

    #[test]
    fn default_accepts_returns_true() {
        let handler = CountingHandler { count: 0 };
        assert!(handler.accepts(&heartbeat()));
    }

    #[test]
    fn custom_accepts_filters_events() {
        let handler = HeartbeatOnlyHandler;
        assert!(handler.accepts(&heartbeat()));

        let session_event = Event::SessionOpen(quantfund_core::SessionEvent {
            timestamp: Timestamp::now(),
            session: quantfund_core::TradingSession::London,
        });
        assert!(!handler.accepts(&session_event));
    }
}
