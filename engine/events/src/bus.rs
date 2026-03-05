use crossbeam_channel::{bounded, Receiver, Sender, TrySendError};
use quantfund_core::Event;
use tracing::{debug, warn};

/// Error type for event bus operations.
#[derive(Debug, thiserror::Error)]
pub enum EventBusError {
    #[error("channel full: backpressure limit reached")]
    ChannelFull,
    #[error("channel disconnected")]
    Disconnected,
}

/// Configuration for the event bus.
pub struct EventBusConfig {
    /// Capacity of the main event channel (bounded for backpressure).
    pub channel_capacity: usize,
    /// Capacity of each subscriber channel.
    pub subscriber_capacity: usize,
}

impl Default for EventBusConfig {
    fn default() -> Self {
        Self {
            channel_capacity: 65_536,
            subscriber_capacity: 65_536,
        }
    }
}

/// The central event bus. All subsystems communicate through this.
///
/// Uses crossbeam bounded channels for lock-free, backpressure-aware messaging.
/// The bus has one main channel for publishing events and zero or more subscriber
/// channels that receive clones of every published event.
pub struct EventBus {
    sender: Sender<Event>,
    receiver: Receiver<Event>,
    subscribers: Vec<Sender<Event>>,
    subscriber_capacity: usize,
}

impl EventBus {
    /// Create a new event bus with the given configuration.
    pub fn new(config: EventBusConfig) -> Self {
        let (sender, receiver) = bounded(config.channel_capacity);
        Self {
            sender,
            receiver,
            subscribers: Vec::new(),
            subscriber_capacity: config.subscriber_capacity,
        }
    }

    /// Create a new event bus with default configuration.
    pub fn with_default() -> Self {
        Self::new(EventBusConfig::default())
    }

    /// Publish an event to the main channel.
    ///
    /// Also fans out a clone to every subscriber. If a subscriber's channel is
    /// full the event is dropped for that subscriber (with a warning) rather
    /// than blocking the publisher.
    pub fn publish(&self, event: Event) -> Result<(), EventBusError> {
        self.sender.try_send(event.clone()).map_err(|e| match e {
            TrySendError::Full(_) => {
                warn!("event bus main channel full, dropping event");
                EventBusError::ChannelFull
            }
            TrySendError::Disconnected(_) => EventBusError::Disconnected,
        })?;

        self.fan_out(&event);

        debug!(event_type = event.event_type(), "event published");
        Ok(())
    }

    /// Create a new subscriber channel and return its receiver.
    ///
    /// Every event published after this call will be cloned into the returned
    /// receiver. The subscriber channel is bounded with the same capacity
    /// configured on the bus.
    pub fn subscribe(&mut self) -> Receiver<Event> {
        let (tx, rx) = bounded(self.subscriber_capacity);
        self.subscribers.push(tx);
        rx
    }

    /// Return a clone of the main sender so other threads can publish events.
    pub fn sender(&self) -> Sender<Event> {
        self.sender.clone()
    }

    /// Drain all pending events from the main channel.
    ///
    /// Useful for testing and backtest tick-by-tick processing.
    pub fn drain(&self) -> Vec<Event> {
        let mut events = Vec::new();
        while let Ok(event) = self.receiver.try_recv() {
            events.push(event);
        }
        events
    }

    /// Number of pending events in the main channel.
    pub fn len(&self) -> usize {
        self.receiver.len()
    }

    /// Returns `true` if the main channel has no pending events.
    pub fn is_empty(&self) -> bool {
        self.receiver.is_empty()
    }

    /// Fan out an event clone to every subscriber, dropping events for full channels.
    fn fan_out(&self, event: &Event) {
        for subscriber in &self.subscribers {
            if let Err(TrySendError::Full(_)) = subscriber.try_send(event.clone()) {
                warn!("subscriber channel full, dropping event");
            }
            // Disconnected subscribers are silently ignored; they will be
            // effectively dead once their receiver is dropped.
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::{HeartbeatEvent, Timestamp};

    fn heartbeat() -> Event {
        Event::Heartbeat(HeartbeatEvent {
            timestamp: Timestamp::now(),
        })
    }

    #[test]
    fn new_bus_is_empty() {
        let bus = EventBus::with_default();
        assert!(bus.is_empty());
        assert_eq!(bus.len(), 0);
    }

    #[test]
    fn publish_and_drain() {
        let bus = EventBus::with_default();
        bus.publish(heartbeat()).unwrap();
        bus.publish(heartbeat()).unwrap();

        assert_eq!(bus.len(), 2);

        let events = bus.drain();
        assert_eq!(events.len(), 2);
        assert!(bus.is_empty());
    }

    #[test]
    fn subscribe_receives_events() {
        let mut bus = EventBus::with_default();
        let rx = bus.subscribe();

        bus.publish(heartbeat()).unwrap();

        // Subscriber should have the event
        let event = rx.try_recv().expect("subscriber should receive event");
        assert_eq!(event.event_type(), "Heartbeat");
    }

    #[test]
    fn multiple_subscribers() {
        let mut bus = EventBus::with_default();
        let rx1 = bus.subscribe();
        let rx2 = bus.subscribe();

        bus.publish(heartbeat()).unwrap();

        assert!(rx1.try_recv().is_ok());
        assert!(rx2.try_recv().is_ok());
    }

    #[test]
    fn sender_clone_can_publish() {
        let bus = EventBus::with_default();
        let sender = bus.sender();

        sender.try_send(heartbeat()).unwrap();
        assert_eq!(bus.len(), 1);
    }

    #[test]
    fn backpressure_returns_channel_full() {
        let config = EventBusConfig {
            channel_capacity: 2,
            subscriber_capacity: 2,
        };
        let bus = EventBus::new(config);

        bus.publish(heartbeat()).unwrap();
        bus.publish(heartbeat()).unwrap();
        let err = bus.publish(heartbeat()).unwrap_err();

        assert!(matches!(err, EventBusError::ChannelFull));
    }

    #[test]
    fn drain_returns_empty_vec_when_no_events() {
        let bus = EventBus::with_default();
        let events = bus.drain();
        assert!(events.is_empty());
    }
}
