use std::collections::HashMap;
use std::time::Instant;

use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use tracing::{debug, info};

use quantfund_core::{
    Event, FillEvent, InstrumentId, Order, OrderId, OrderStatus, Price, StrategyId, Volume,
};
use quantfund_data::TickReplay;
use quantfund_execution::{MatchingEngine, OrderManagementSystem};
use quantfund_risk::{PortfolioState, RiskEngine};
use quantfund_strategy::{MarketSnapshot, Strategy};

use crate::config::BacktestConfig;
use crate::metrics::calculate_metrics;
use crate::portfolio::Portfolio;
use crate::result::BacktestResult;

/// The deterministic backtest runner.
/// Processes ticks sequentially, maintaining strict event ordering.
pub struct BacktestRunner {
    config: BacktestConfig,
    strategies: Vec<Box<dyn Strategy>>,
    risk_engine: RiskEngine,
    matching_engine: MatchingEngine,
    oms: OrderManagementSystem,
    portfolio: Portfolio,
}

impl BacktestRunner {
    /// Initialise all subsystems from the provided config.
    pub fn new(config: BacktestConfig, strategies: Vec<Box<dyn Strategy>>) -> Self {
        let risk_engine = RiskEngine::new(config.risk_config.clone());
        let matching_engine = MatchingEngine::new(config.execution_config.clone(), config.seed);
        let oms = OrderManagementSystem::new();
        let portfolio = Portfolio::new(config.initial_balance);

        Self {
            config,
            strategies,
            risk_engine,
            matching_engine,
            oms,
            portfolio,
        }
    }

    /// Run the backtest over the full tick replay and return a complete result.
    ///
    /// This is a purely sequential, deterministic loop:
    ///   tick -> matching -> portfolio -> strategies -> risk -> submit
    pub fn run(&mut self, replay: &mut TickReplay) -> BacktestResult {
        let wall_start = Instant::now();
        let total_ticks_expected = replay.total() as u64;
        let mut tick_counter: u64 = 0;

        // Map from instrument to the currently-open position ID.
        let mut instrument_positions: HashMap<InstrumentId, u64> = HashMap::new();

        // Map from OrderId to (strategy_id, sl, tp) so we can attribute fills
        // back to the originating strategy.
        let mut order_metadata: HashMap<OrderId, (StrategyId, Option<Price>, Option<Price>)> =
            HashMap::new();

        info!(
            instruments = ?self.config.instruments,
            start = %self.config.start_time,
            end = %self.config.end_time,
            total_ticks = total_ticks_expected,
            "backtest started"
        );

        while let Some(tick) = replay.next_tick() {
            // Clone the tick so we own it for the remainder of this iteration.
            let tick = tick.clone();

            // ── Step A: Process tick through matching engine -> collect fills ─
            let events = self.matching_engine.process_tick(&tick);

            for event in &events {
                if let Event::Fill(fill) = event {
                    self.handle_fill(fill, &mut instrument_positions, &order_metadata);

                    // Update OMS status to Filled.
                    self.oms.update_status(
                        &fill.order_id,
                        OrderStatus::Filled,
                        fill.timestamp,
                        "filled by matching engine",
                    );

                    // Feed execution data to risk engine for anomaly tracking.
                    // In backtest, latency is deterministic (0µs).
                    self.risk_engine.record_execution(0, fill.slippage);
                }
            }

            // ── Step B: Feed tick to risk analytics (volatility, correlation) ─
            self.risk_engine.update_tick(&tick);

            // ── Step C: Update portfolio equity with current prices ───────────
            let mut current_prices: HashMap<InstrumentId, (Price, Price)> = HashMap::new();
            current_prices.insert(tick.instrument_id.clone(), (tick.bid, tick.ask));
            self.portfolio
                .update_equity(tick.timestamp, &current_prices);

            // ── Step D: Update risk engine with portfolio state ────────────────
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

            // ── Step E: For each strategy, call on_tick and collect signals ────
            let snapshot = MarketSnapshot {
                tick: &tick,
                instrument_id: &tick.instrument_id,
            };

            let mut signals = Vec::new();
            for strategy in &mut self.strategies {
                if strategy
                    .instruments().contains(&tick.instrument_id)
                    && let Some(signal) = strategy.on_tick(&snapshot) {
                        signals.push(signal);
                    }
            }

            // ── Step F: For each signal, create Order and validate via risk ───
            for signal in signals {
                let Some(side) = signal.side else {
                    continue; // No directional bias -> skip.
                };

                // Determine volume from signal strength (simple mapping).
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

                // Extract SL/TP from signal metadata if present.
                let sl = signal
                    .metadata
                    .get("sl")
                    .and_then(|v| v.as_f64())
                    .map(Price::from);
                let tp = signal
                    .metadata
                    .get("tp")
                    .and_then(|v| v.as_f64())
                    .map(Price::from);

                // ── Step G: Risk validation ──────────────────────────────────
                match self.risk_engine.validate_order(&order, &tick) {
                    Ok(()) => {
                        debug!(
                            order_id = %order.id,
                            instrument = %order.instrument_id,
                            side = %order.side,
                            volume = %order.volume,
                            "order approved by risk engine"
                        );

                        let order_id = order.id;

                        // Store metadata for fill attribution.
                        order_metadata.insert(order_id, (signal.strategy_id.clone(), sl, tp));

                        // Register in OMS and submit to matching engine.
                        self.oms.register_order(order.clone());
                        self.matching_engine.submit_order(order);
                    }
                    Err(violations) => {
                        debug!(
                            order_id = %order.id,
                            violations = ?violations,
                            "order rejected by risk engine"
                        );
                    }
                }
            }

            tick_counter += 1;

            // Log progress every 100_000 ticks.
            if tick_counter.is_multiple_of(100_000) {
                let pct = if total_ticks_expected > 0 {
                    (tick_counter as f64 / total_ticks_expected as f64) * 100.0
                } else {
                    0.0
                };
                info!(
                    ticks = tick_counter,
                    progress = format!("{pct:.1}%"),
                    equity = %self.portfolio.equity(),
                    open_positions = self.portfolio.open_positions().len(),
                    "backtest progress"
                );
            }
        }

        // ── Finalise ─────────────────────────────────────────────────────────

        let elapsed = wall_start.elapsed();
        let elapsed_ms = elapsed.as_millis() as u64;
        let ticks_per_second = if elapsed_ms > 0 {
            tick_counter as f64 / (elapsed_ms as f64 / 1000.0)
        } else {
            tick_counter as f64
        };

        let metrics = calculate_metrics(
            self.portfolio.closed_positions(),
            self.portfolio.equity_curve(),
            self.config.initial_balance,
        );

        info!(
            total_ticks = tick_counter,
            total_trades = metrics.total_trades,
            total_pnl = %metrics.total_pnl,
            sharpe = metrics.sharpe_ratio,
            max_drawdown = %metrics.max_drawdown,
            elapsed_ms = elapsed_ms,
            tps = ticks_per_second as u64,
            "backtest completed"
        );

        BacktestResult {
            config: self.config.clone(),
            metrics,
            equity_curve: self.portfolio.equity_curve().to_vec(),
            closed_positions: self.portfolio.closed_positions().to_vec(),
            total_ticks_processed: tick_counter,
            elapsed_time_ms: elapsed_ms,
            ticks_per_second,
        }
    }

    /// Handle a fill event: either close an existing position (opposite side)
    /// or open a new one.
    fn handle_fill(
        &mut self,
        fill: &FillEvent,
        instrument_positions: &mut HashMap<InstrumentId, u64>,
        order_metadata: &HashMap<OrderId, (StrategyId, Option<Price>, Option<Price>)>,
    ) {
        let (strategy_id, sl, tp) = order_metadata
            .get(&fill.order_id)
            .cloned()
            .unwrap_or_else(|| (StrategyId::new("unknown"), None, None));

        // Check if there is an existing open position for this instrument.
        if let Some(&existing_id) = instrument_positions.get(&fill.instrument_id) {
            // Check if the fill is in the opposite direction -> close.
            if let Some(pos) = self.portfolio.open_positions().get(&existing_id) {
                let should_close = pos.side != fill.side;
                if should_close {
                    self.portfolio.close_position(existing_id, fill);
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
