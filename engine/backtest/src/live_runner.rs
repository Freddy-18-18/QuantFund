use std::collections::HashMap;
use std::thread;
use std::time::Duration;

use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use tracing::{error, info, warn};

use quantfund_core::{
    Event, FillEvent, InstrumentId, Order, OrderId, OrderStatus, Price, StrategyId, TickEvent, Volume,
};
use quantfund_execution::OrderManagementSystem;
use quantfund_mt5::{BridgeError, ExecutionBridge, Mt5Bridge, Mt5BridgeConfig};
use quantfund_risk::{PortfolioState, RiskEngine};
use quantfund_strategy::{MarketSnapshot, Strategy};

use crate::config::BacktestConfig;
use crate::portfolio::Portfolio;

/// Live trading runner connecting to MetaTrader 5 via `Mt5Bridge`.
pub struct LiveRunner {
    config: BacktestConfig,
    bridge: Mt5Bridge,
    strategies: Vec<Box<dyn Strategy>>,
    risk_engine: RiskEngine,
    oms: OrderManagementSystem,
    portfolio: Portfolio,
    running: bool,
}

impl LiveRunner {
    /// Create a new LiveRunner.
    pub fn new(
        config: BacktestConfig,
        bridge_config: Mt5BridgeConfig,
        strategies: Vec<Box<dyn Strategy>>,
    ) -> Self {
        let risk_engine = RiskEngine::new(config.risk_config.clone());
        let bridge = Mt5Bridge::new(bridge_config);
        let oms = OrderManagementSystem::new();
        let portfolio = Portfolio::new(config.initial_balance);

        Self {
            config,
            bridge,
            strategies,
            risk_engine,
            oms,
            portfolio,
            running: false,
        }
    }

    /// Run the live trading loop.
    pub fn run(&mut self) -> Result<(), BridgeError> {
        info!("Starting LiveRunner...");
        self.bridge.connect()?;
        self.running = true;

        // Map from OrderId to (strategy_id, sl, tp) so we can attribute fills
        // back to the originating strategy.
        let mut order_metadata: HashMap<OrderId, (StrategyId, Option<Price>, Option<Price>)> =
            HashMap::new();

        // Map from InstrumentId to current open Position ID (simplified tracking)
        let mut instrument_positions: HashMap<InstrumentId, u64> = HashMap::new();

        info!("Connected to MT5. Waiting for market data...");

        while self.running {
            // 1. Poll for events
            let events = self.bridge.poll_events();

            for event in events {
                match event {
                    Event::Tick(tick) => {
                        self.handle_tick(tick, &mut order_metadata)?;
                    }
                    Event::Fill(fill) => {
                        self.handle_fill(fill, &mut instrument_positions, &mut order_metadata);
                    }
                    Event::PartialFill(pf) => {
                        info!("Partial fill: {:?}", pf);
                        // TODO: Update portfolio state for partial fills
                    }
                    Event::Rejection(rej) => {
                        self.oms.update_status(
                            &rej.order_id,
                            OrderStatus::Rejected,
                            rej.timestamp,
                            &format!("Rejected: {:?}", rej.reason),
                        );
                        warn!("Order rejected: {:?}", rej);
                    }
                    _ => {}
                }
            }

            // Small sleep to prevent busy loop if no events
            thread::sleep(Duration::from_millis(1));
        }

        Ok(())
    }

    fn handle_tick(
        &mut self,
        tick: TickEvent,
        order_metadata: &mut HashMap<OrderId, (StrategyId, Option<Price>, Option<Price>)>,
    ) -> Result<(), BridgeError> {
        // Update Risk Engine with current portfolio state
        let open_positions: Vec<quantfund_core::Position> =
            self.portfolio.open_positions().values().cloned().collect();

        self.risk_engine.update_portfolio(PortfolioState {
            equity: self.portfolio.equity(),
            balance: self.portfolio.balance(),
            daily_pnl: self.portfolio.daily_pnl(),
            peak_equity: self.portfolio.equity(),
            positions: open_positions,
            margin_used: dec!(0),
        });

        // Run strategies
        let snapshot = MarketSnapshot {
            tick: &tick,
            instrument_id: &tick.instrument_id,
        };

        // Collect signals first
        let mut signals = Vec::new();
        for strategy in &mut self.strategies {
            if let Some(signal) = strategy.on_tick(&snapshot) {
                signals.push(signal);
            }
        }

        for signal in signals {
            let Some(side) = signal.side else {
                continue;
            };

            // Volume calculation (simplified)
            let base_volume = dec!(0.01);
            let strength_abs = Decimal::try_from(signal.strength.abs()).unwrap_or(dec!(1));
            let volume = base_volume * strength_abs;
            if volume <= dec!(0) {
                continue;
            }

            let order = Order::market(
                signal.instrument_id.clone(),
                side,
                Volume::new(volume),
                signal.strategy_id.clone(),
            );

            // Risk Check
            match self.risk_engine.validate_order(&order, &tick) {
                Ok(()) => {
                    info!("Order approved: {:?}", order);
                    
                    self.oms.register_order(order.clone());
                    match self.bridge.submit_order(order.clone(), tick.timestamp) {
                        Ok(_) => {
                            order_metadata.insert(order.id, (signal.strategy_id.clone(), None, None));
                        }
                        Err(e) => {
                            error!("Failed to submit order: {:?}", e);
                        }
                    }
                }
                Err(violations) => {
                    warn!("Order rejected by risk engine: {:?} - Violations: {:?}", order, violations);
                }
            }
        }

        Ok(())
    }

    fn handle_fill(
        &mut self,
        fill: FillEvent,
        instrument_positions: &mut HashMap<InstrumentId, u64>,
        order_metadata: &mut HashMap<OrderId, (StrategyId, Option<Price>, Option<Price>)>,
    ) {
        info!("Order filled: {:?}", fill);
        
        self.oms.update_status(
            &fill.order_id, 
            OrderStatus::Filled, 
            fill.timestamp, 
            "Filled by broker"
        );

        // Update Portfolio (Open/Close logic)
        let (strategy_id, sl, tp) = order_metadata
            .get(&fill.order_id)
            .cloned()
            .unwrap_or_else(|| (quantfund_core::StrategyId::new("unknown"), None, None));

        // Check if there is an existing open position for this instrument.
        if let Some(&existing_id) = instrument_positions.get(&fill.instrument_id) {
            // Check if the fill is in the opposite direction -> close.
            if let Some(pos) = self.portfolio.open_positions().get(&existing_id) {
                let should_close = pos.side != fill.side;
                if should_close {
                    self.portfolio.close_position(existing_id, &fill);
                    instrument_positions.remove(&fill.instrument_id);
                    return;
                }
            }
        }

        // No opposing position found -> open new position.
        let mut fill_with_commission = fill.clone();
        fill_with_commission.commission = *fill.volume * self.config.commission_per_lot;

        let pos_id = self
            .portfolio
            .open_position(&fill_with_commission, strategy_id, sl, tp);
        instrument_positions.insert(fill.instrument_id.clone(), pos_id);
    }
}
