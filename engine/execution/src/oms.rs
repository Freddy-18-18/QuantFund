use std::collections::HashMap;

use tracing::debug;

use quantfund_core::order::OrderStatus;
use quantfund_core::types::{OrderId, Timestamp};
use quantfund_core::Order;

/// Records a single order state transition.
pub struct OrderTransition {
    pub order_id: OrderId,
    pub from_status: OrderStatus,
    pub to_status: OrderStatus,
    pub timestamp: Timestamp,
    pub details: String,
}

/// Tracks the full lifecycle of all orders.
/// Every state transition is recorded in an append-only audit log.
pub struct OrderManagementSystem {
    /// All orders by ID.
    orders: HashMap<OrderId, Order>,
    /// Order state transition log.
    audit_log: Vec<OrderTransition>,
}

impl OrderManagementSystem {
    pub fn new() -> Self {
        Self {
            orders: HashMap::new(),
            audit_log: Vec::new(),
        }
    }

    /// Register a new order with `Created` status.
    pub fn register_order(&mut self, mut order: Order) {
        let id = order.id;
        order.status = OrderStatus::Created;
        debug!(order_id = %id, "order registered in OMS");
        self.orders.insert(id, order);
    }

    /// Update order status and record the transition in the audit log.
    /// Returns `Some(())` if the order exists, `None` otherwise.
    pub fn update_status(
        &mut self,
        order_id: &OrderId,
        new_status: OrderStatus,
        timestamp: Timestamp,
        details: &str,
    ) -> Option<()> {
        let order = self.orders.get_mut(order_id)?;
        let old_status = order.status;
        order.status = new_status;

        debug!(
            order_id = %order_id,
            from = ?old_status,
            to = ?new_status,
            "order status updated"
        );

        self.audit_log.push(OrderTransition {
            order_id: *order_id,
            from_status: old_status,
            to_status: new_status,
            timestamp,
            details: details.to_owned(),
        });

        Some(())
    }

    /// Look up an order by ID.
    pub fn get_order(&self, order_id: &OrderId) -> Option<&Order> {
        self.orders.get(order_id)
    }

    /// Returns all orders that are not in a terminal state
    /// (i.e., not `Filled`, `Rejected`, or `Cancelled`).
    pub fn open_orders(&self) -> Vec<&Order> {
        self.orders
            .values()
            .filter(|o| !is_terminal(o.status))
            .collect()
    }

    /// Returns all audit transitions for a given order.
    pub fn audit_trail(&self, order_id: &OrderId) -> Vec<&OrderTransition> {
        self.audit_log
            .iter()
            .filter(|t| t.order_id == *order_id)
            .collect()
    }

    /// Total number of orders tracked (all states).
    pub fn order_count(&self) -> usize {
        self.orders.len()
    }
}

impl Default for OrderManagementSystem {
    fn default() -> Self {
        Self::new()
    }
}

/// Whether an order status is terminal (no further transitions expected).
fn is_terminal(status: OrderStatus) -> bool {
    matches!(
        status,
        OrderStatus::Filled | OrderStatus::Rejected | OrderStatus::Cancelled
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::types::{Side, StrategyId, Volume};
    use quantfund_core::InstrumentId;
    use rust_decimal_macros::dec;

    fn sample_order() -> Order {
        Order::market(
            InstrumentId::new("EURUSD"),
            Side::Buy,
            Volume::new(dec!(1)),
            StrategyId::new("test"),
        )
    }

    #[test]
    fn register_and_retrieve() {
        let mut oms = OrderManagementSystem::new();
        let order = sample_order();
        let id = order.id;
        oms.register_order(order);

        assert_eq!(oms.order_count(), 1);
        let retrieved = oms.get_order(&id).unwrap();
        assert_eq!(retrieved.status, OrderStatus::Created);
    }

    #[test]
    fn status_transitions_recorded() {
        let mut oms = OrderManagementSystem::new();
        let order = sample_order();
        let id = order.id;
        let ts = Timestamp::from_nanos(1_000_000_000);
        oms.register_order(order);

        oms.update_status(&id, OrderStatus::Sent, ts, "sent to exchange")
            .unwrap();
        oms.update_status(&id, OrderStatus::Filled, ts, "fully filled")
            .unwrap();

        let trail = oms.audit_trail(&id);
        assert_eq!(trail.len(), 2);
        assert_eq!(trail[0].from_status, OrderStatus::Created);
        assert_eq!(trail[0].to_status, OrderStatus::Sent);
        assert_eq!(trail[1].from_status, OrderStatus::Sent);
        assert_eq!(trail[1].to_status, OrderStatus::Filled);
    }

    #[test]
    fn open_orders_excludes_terminal() {
        let mut oms = OrderManagementSystem::new();
        let ts = Timestamp::from_nanos(1_000_000_000);

        let order1 = sample_order();
        let id1 = order1.id;
        oms.register_order(order1);

        let order2 = sample_order();
        oms.register_order(order2);

        // Fill the first order
        oms.update_status(&id1, OrderStatus::Filled, ts, "filled")
            .unwrap();

        let open = oms.open_orders();
        assert_eq!(open.len(), 1);
        assert_eq!(oms.order_count(), 2);
    }

    #[test]
    fn update_nonexistent_returns_none() {
        let mut oms = OrderManagementSystem::new();
        let ts = Timestamp::from_nanos(1_000_000_000);
        let fake_id = OrderId::new();
        assert!(oms
            .update_status(&fake_id, OrderStatus::Filled, ts, "nope")
            .is_none());
    }
}
