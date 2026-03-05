//! Enhanced risk engine with full Level 1–4 hierarchical risk control.
//!
//! Integrates:
//! - Level 1: Pre-trade validation (size, spread, slippage)
//! - Level 2: Strategy-level risk (drawdown, volatility, correlation clustering)
//! - Level 3: Portfolio-level risk (exposure, heat, daily loss, VaR, margin)
//! - Level 4: Kill switch (drawdown, latency anomaly, slippage anomaly)
//!
//! All checks target < 10µs per `validate_order` call.

use std::collections::HashMap;

use quantfund_core::{InstrumentId, Order, Position, Side, StrategyId, TickEvent};
use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use tracing::warn;

use crate::config::RiskConfig;
use crate::correlation::CorrelationTracker;
use crate::limits::{self, RiskViolation};
use crate::var::{compute_portfolio_var, VarConfidence, VarConfig};
use crate::volatility::VolatilityTracker;

/// Snapshot of portfolio state used for risk calculations.
#[derive(Debug)]
pub struct PortfolioState {
    pub equity: Decimal,
    pub balance: Decimal,
    pub daily_pnl: Decimal,
    pub peak_equity: Decimal,
    pub positions: Vec<Position>,
    pub margin_used: Decimal,
}

/// Per-strategy equity tracking for strategy-level drawdown monitoring.
#[derive(Clone, Debug)]
struct StrategyState {
    /// Peak P&L attributed to this strategy.
    peak_pnl: Decimal,
    /// Current P&L attributed to this strategy.
    current_pnl: Decimal,
}

impl StrategyState {
    fn new() -> Self {
        Self {
            peak_pnl: dec!(0),
            current_pnl: dec!(0),
        }
    }

    /// Current drawdown as a fraction. Returns 0 if peak is non-positive.
    fn drawdown(&self, equity: Decimal) -> Decimal {
        if equity <= dec!(0) || self.peak_pnl <= dec!(0) {
            // Use absolute drawdown relative to equity instead.
            let loss = self.peak_pnl - self.current_pnl;
            if loss <= dec!(0) || equity <= dec!(0) {
                return dec!(0);
            }
            return loss / equity;
        }
        let dd = self.peak_pnl - self.current_pnl;
        if dd <= dec!(0) {
            dec!(0)
        } else {
            dd / self.peak_pnl
        }
    }
}

/// Kill switch reason tracking.
#[derive(Clone, Debug)]
pub enum KillSwitchReason {
    /// Drawdown from peak equity exceeded threshold.
    Drawdown {
        current: Decimal,
        threshold: Decimal,
    },
    /// Execution latency anomaly detected.
    LatencyAnomaly { observed_us: u64, threshold_us: u64 },
    /// Slippage anomaly detected.
    SlippageAnomaly {
        mean_slippage: Decimal,
        threshold: Decimal,
    },
    /// Margin level dropped below minimum.
    InsufficientMargin { level: Decimal, min: Decimal },
    /// Manually triggered by operator.
    Manual,
}

/// The enhanced risk engine. Runs as a dedicated actor receiving orders and
/// returning approval / rejection decisions.
///
/// All checks must complete in < 10 microseconds.
pub struct RiskEngine {
    config: RiskConfig,
    portfolio_state: PortfolioState,
    daily_loss: Decimal,
    peak_equity: Decimal,
    kill_switch_active: bool,
    kill_switch_reason: Option<KillSwitchReason>,

    // ── Per-strategy tracking ────────────────────────────────────────────────
    strategy_states: HashMap<StrategyId, StrategyState>,

    // ── Analytics engines ────────────────────────────────────────────────────
    vol_tracker: VolatilityTracker,
    corr_tracker: CorrelationTracker,
    var_config: VarConfig,

    // ── Kill switch anomaly tracking ─────────────────────────────────────────
    /// Last observed execution latency in microseconds.
    last_execution_latency_us: u64,
    /// EWMA of recent slippage (pips).
    ewma_slippage: Decimal,
}

impl RiskEngine {
    /// Create a new risk engine with the given configuration.
    pub fn new(config: RiskConfig) -> Self {
        let vol_tracker =
            VolatilityTracker::new(config.ewma_lambda, config.analytics_warmup_period);
        let corr_tracker =
            CorrelationTracker::new(config.ewma_lambda, config.analytics_warmup_period);
        let var_config = VarConfig {
            confidence: VarConfidence::Pct99,
            max_var: config.max_var,
            holding_period_days: 1,
        };

        Self {
            config,
            portfolio_state: PortfolioState {
                equity: dec!(0),
                balance: dec!(0),
                daily_pnl: dec!(0),
                peak_equity: dec!(0),
                positions: Vec::new(),
                margin_used: dec!(0),
            },
            daily_loss: dec!(0),
            peak_equity: dec!(0),
            kill_switch_active: false,
            kill_switch_reason: None,
            strategy_states: HashMap::new(),
            vol_tracker,
            corr_tracker,
            var_config,
            last_execution_latency_us: 0,
            ewma_slippage: dec!(0),
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // State updates
    // ═══════════════════════════════════════════════════════════════════════════

    /// Update the engine with a fresh portfolio-state snapshot.
    pub fn update_portfolio(&mut self, state: PortfolioState) {
        // Track peak equity for drawdown calculation.
        if state.equity > self.peak_equity {
            self.peak_equity = state.equity;
        }

        // Track daily loss (negative P&L = loss).
        if state.daily_pnl < dec!(0) {
            self.daily_loss = state.daily_pnl.abs();
        } else {
            self.daily_loss = dec!(0);
        }

        // Update per-strategy P&L from positions.
        self.update_strategy_pnl(&state.positions);

        // Store state before evaluating kill switch so that
        // `current_drawdown()` sees the latest equity.
        self.portfolio_state = state;

        // Check whether the kill switch should now be active.
        self.evaluate_kill_switch();
    }

    /// Feed a new tick to update volatility and correlation trackers.
    /// Call this on every tick, before `validate_order`.
    pub fn update_tick(&mut self, tick: &TickEvent) {
        let mid = (*tick.bid + *tick.ask) / dec!(2);
        self.vol_tracker.update(&tick.instrument_id, mid);
        self.corr_tracker.update(&tick.instrument_id, mid);
    }

    /// Record an execution event for anomaly tracking.
    /// `latency_us`: order-to-fill latency in microseconds.
    /// `slippage_pips`: observed slippage for this fill.
    pub fn record_execution(&mut self, latency_us: u64, slippage_pips: Decimal) {
        self.last_execution_latency_us = latency_us;

        // EWMA of slippage: s_t = λ * s_{t-1} + (1-λ) * |slippage|
        let lambda = self.config.ewma_lambda;
        let one_minus_lambda = dec!(1) - lambda;
        self.ewma_slippage = lambda * self.ewma_slippage + one_minus_lambda * slippage_pips.abs();

        // Re-evaluate kill switch after each execution.
        self.evaluate_kill_switch();
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Order validation
    // ═══════════════════════════════════════════════════════════════════════════

    /// Validate an order against all Layer 1–4 risk checks.
    ///
    /// Returns `Ok(())` if every check passes, or `Err(violations)` containing
    /// **all** violations found (not just the first).
    pub fn validate_order(
        &self,
        order: &Order,
        current_tick: &TickEvent,
    ) -> Result<(), Vec<RiskViolation>> {
        let mut violations = Vec::new();

        // ── Layer 4: Kill switch (checked first, rejects everything) ─────────
        if self.kill_switch_active {
            let dd = self.current_drawdown();
            violations.push(RiskViolation::KillSwitchTriggered {
                current: dd,
                threshold: self.config.kill_switch_drawdown,
            });
            return Err(violations);
        }

        // ── Layer 1: Trade-level ─────────────────────────────────────────────
        if let Err(v) = limits::check_position_size(*order.volume, self.config.max_order_size) {
            violations.push(v);
        }

        if let Err(v) = limits::check_spread(current_tick.spread, self.config.max_spread_pips) {
            violations.push(v);
        }

        // ── Layer 2: Strategy-level ──────────────────────────────────────────
        let strategy_position_count = self
            .portfolio_state
            .positions
            .iter()
            .filter(|p| p.strategy_id == order.strategy_id && p.is_open())
            .count();

        if let Err(v) = limits::check_max_positions(
            strategy_position_count,
            self.config.max_positions_per_strategy,
        ) {
            violations.push(v);
        }

        // Per-strategy drawdown check.
        if let Some(ss) = self.strategy_states.get(&order.strategy_id) {
            let strategy_dd = ss.drawdown(self.portfolio_state.equity);
            if let Err(v) =
                limits::check_strategy_drawdown(strategy_dd, self.config.max_drawdown_per_strategy)
            {
                violations.push(v);
            }
        }

        // Rolling volatility check (for the instrument being traded).
        if let Some(vol) = self.vol_tracker.volatility(&order.instrument_id)
            && let Err(v) = limits::check_volatility(vol, self.config.rolling_volatility_cap)
        {
            violations.push(v);
        }

        // Correlation cluster exposure check.
        self.check_correlation_clusters(order, &mut violations);

        // ── Layer 3: Portfolio-level ─────────────────────────────────────────
        let total_open = self
            .portfolio_state
            .positions
            .iter()
            .filter(|p| p.is_open())
            .count();

        if let Err(v) = limits::check_max_positions(total_open, self.config.max_total_positions) {
            violations.push(v);
        }

        let equity = self.portfolio_state.equity;
        if equity > dec!(0) {
            // Daily loss check.
            let daily_loss_fraction = self.daily_loss / equity;
            if let Err(v) =
                limits::check_daily_loss(daily_loss_fraction, self.config.max_daily_loss)
            {
                violations.push(v);
            }

            // Gross exposure.
            let gross_volume: Decimal = self
                .portfolio_state
                .positions
                .iter()
                .filter(|p| p.is_open())
                .map(|p| (*p.volume).abs())
                .sum();
            let gross_with_order = gross_volume + (*order.volume).abs();
            let gross_exposure = gross_with_order / equity;

            if let Err(v) =
                limits::check_gross_exposure(gross_exposure, self.config.max_gross_exposure)
            {
                violations.push(v);
            }

            // Net exposure.
            let signed_volume = |p: &Position| -> Decimal {
                match p.side {
                    Side::Buy => *p.volume,
                    Side::Sell => -(*p.volume),
                }
            };
            let net_volume: Decimal = self
                .portfolio_state
                .positions
                .iter()
                .filter(|p| p.is_open())
                .map(signed_volume)
                .sum();
            let order_signed = match order.side {
                Side::Buy => *order.volume,
                Side::Sell => -(*order.volume),
            };
            let net_with_order = net_volume + order_signed;
            let net_exposure = net_with_order / equity;

            if let Err(v) = limits::check_net_exposure(net_exposure, self.config.max_net_exposure) {
                violations.push(v);
            }

            // Portfolio heat: sum of (volume * |entry_price - sl_price|) / equity
            // for all open positions. Positions without SL contribute their full notional.
            let heat = self.calculate_portfolio_heat(equity);
            if let Err(v) = limits::check_portfolio_heat(heat, self.config.max_portfolio_heat) {
                violations.push(v);
            }

            // Margin level check.
            let margin_used = self.portfolio_state.margin_used;
            if margin_used > dec!(0) {
                let margin_level = equity / margin_used;
                if let Err(v) =
                    limits::check_margin_level(margin_level, self.config.min_margin_level)
                {
                    violations.push(v);
                }
            }

            // VaR check.
            let var = self.compute_var(equity);
            if var > dec!(0)
                && let Err(v) = limits::check_var(var, self.config.max_var)
            {
                violations.push(v);
            }
        }

        if violations.is_empty() {
            Ok(())
        } else {
            Err(violations)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Public queries
    // ═══════════════════════════════════════════════════════════════════════════

    /// Returns `true` if the kill switch should be active.
    pub fn check_kill_switch(&self) -> bool {
        self.kill_switch_active
    }

    /// Current drawdown from peak equity as a fraction (0.0 = no drawdown).
    pub fn current_drawdown(&self) -> Decimal {
        if self.peak_equity <= dec!(0) {
            return dec!(0);
        }
        let dd = self.peak_equity - self.portfolio_state.equity;
        if dd <= dec!(0) {
            dec!(0)
        } else {
            dd / self.peak_equity
        }
    }

    /// Returns `true` if the engine is accepting orders (kill switch NOT active).
    pub fn is_active(&self) -> bool {
        !self.kill_switch_active
    }

    /// Get the reason the kill switch was triggered.
    pub fn kill_switch_reason(&self) -> Option<&KillSwitchReason> {
        self.kill_switch_reason.as_ref()
    }

    /// Reset daily loss tracking (call at end of day).
    pub fn reset_daily(&mut self) {
        self.daily_loss = dec!(0);
    }

    /// Manually trigger the kill switch. Use for operator-initiated halts.
    pub fn trigger_kill_switch_manual(&mut self) {
        warn!("kill switch manually triggered");
        self.kill_switch_active = true;
        self.kill_switch_reason = Some(KillSwitchReason::Manual);
    }

    /// Reset the kill switch. Requires explicit operator action.
    /// Returns `false` if the underlying condition still exists (drawdown etc).
    pub fn reset_kill_switch(&mut self) -> bool {
        // Check if the drawdown condition has recovered.
        let dd = self.current_drawdown();
        if dd >= self.config.kill_switch_drawdown {
            warn!(
                drawdown = %dd,
                threshold = %self.config.kill_switch_drawdown,
                "cannot reset kill switch: drawdown condition persists"
            );
            return false;
        }

        // Check latency anomaly.
        if self.last_execution_latency_us > self.config.latency_anomaly_threshold_us {
            warn!(
                latency_us = self.last_execution_latency_us,
                threshold_us = self.config.latency_anomaly_threshold_us,
                "cannot reset kill switch: latency anomaly persists"
            );
            return false;
        }

        // Check slippage anomaly.
        if self.ewma_slippage > self.config.slippage_anomaly_threshold {
            warn!(
                slippage = %self.ewma_slippage,
                threshold = %self.config.slippage_anomaly_threshold,
                "cannot reset kill switch: slippage anomaly persists"
            );
            return false;
        }

        self.kill_switch_active = false;
        self.kill_switch_reason = None;
        true
    }

    /// Get read-only access to the volatility tracker.
    pub fn volatility_tracker(&self) -> &VolatilityTracker {
        &self.vol_tracker
    }

    /// Get read-only access to the correlation tracker.
    pub fn correlation_tracker(&self) -> &CorrelationTracker {
        &self.corr_tracker
    }

    /// Get the current VaR as a fraction of equity.
    pub fn current_var(&self) -> Decimal {
        let equity = self.portfolio_state.equity;
        if equity <= dec!(0) {
            return dec!(0);
        }
        self.compute_var(equity)
    }

    /// Get per-strategy drawdown for a specific strategy.
    pub fn strategy_drawdown(&self, strategy_id: &StrategyId) -> Decimal {
        self.strategy_states
            .get(strategy_id)
            .map(|ss| ss.drawdown(self.portfolio_state.equity))
            .unwrap_or(dec!(0))
    }

    /// Get the current portfolio heat.
    pub fn current_portfolio_heat(&self) -> Decimal {
        let equity = self.portfolio_state.equity;
        if equity <= dec!(0) {
            return dec!(0);
        }
        self.calculate_portfolio_heat(equity)
    }

    /// Reset analytics state (volatility, correlation trackers).
    /// Useful when switching instruments or after large regime changes.
    pub fn reset_analytics(&mut self) {
        self.vol_tracker.reset();
        self.corr_tracker.reset();
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Internal helpers
    // ═══════════════════════════════════════════════════════════════════════════

    /// Update per-strategy P&L from the current positions.
    fn update_strategy_pnl(&mut self, positions: &[Position]) {
        // Accumulate P&L per strategy from all positions (open + closed during this update).
        let mut strategy_pnl: HashMap<StrategyId, Decimal> = HashMap::new();

        for pos in positions {
            *strategy_pnl.entry(pos.strategy_id.clone()).or_default() += pos.pnl_net;
        }

        for (sid, pnl) in strategy_pnl {
            let state = self
                .strategy_states
                .entry(sid)
                .or_insert_with(StrategyState::new);
            state.current_pnl = pnl;
            if pnl > state.peak_pnl {
                state.peak_pnl = pnl;
            }
        }
    }

    /// Evaluate all kill switch conditions and set the flag if any trigger.
    fn evaluate_kill_switch(&mut self) {
        // Already active — don't override the reason.
        if self.kill_switch_active {
            return;
        }

        // 1. Drawdown threshold.
        let dd = self.current_drawdown();
        if dd >= self.config.kill_switch_drawdown {
            warn!(
                drawdown = %dd,
                threshold = %self.config.kill_switch_drawdown,
                "KILL SWITCH: drawdown threshold exceeded"
            );
            self.kill_switch_active = true;
            self.kill_switch_reason = Some(KillSwitchReason::Drawdown {
                current: dd,
                threshold: self.config.kill_switch_drawdown,
            });
            return;
        }

        // 2. Latency anomaly.
        if self.last_execution_latency_us > self.config.latency_anomaly_threshold_us {
            warn!(
                latency_us = self.last_execution_latency_us,
                threshold_us = self.config.latency_anomaly_threshold_us,
                "KILL SWITCH: execution latency anomaly"
            );
            self.kill_switch_active = true;
            self.kill_switch_reason = Some(KillSwitchReason::LatencyAnomaly {
                observed_us: self.last_execution_latency_us,
                threshold_us: self.config.latency_anomaly_threshold_us,
            });
            return;
        }

        // 3. Slippage anomaly.
        if self.ewma_slippage > self.config.slippage_anomaly_threshold {
            warn!(
                slippage = %self.ewma_slippage,
                threshold = %self.config.slippage_anomaly_threshold,
                "KILL SWITCH: slippage anomaly"
            );
            self.kill_switch_active = true;
            self.kill_switch_reason = Some(KillSwitchReason::SlippageAnomaly {
                mean_slippage: self.ewma_slippage,
                threshold: self.config.slippage_anomaly_threshold,
            });
            return;
        }

        // 4. Margin level (checked during portfolio update).
        let margin_used = self.portfolio_state.margin_used;
        if margin_used > dec!(0) {
            let margin_level = self.portfolio_state.equity / margin_used;
            if margin_level < self.config.min_margin_level {
                warn!(
                    margin_level = %margin_level,
                    min = %self.config.min_margin_level,
                    "KILL SWITCH: margin level below minimum"
                );
                self.kill_switch_active = true;
                self.kill_switch_reason = Some(KillSwitchReason::InsufficientMargin {
                    level: margin_level,
                    min: self.config.min_margin_level,
                });
            }
        }
    }

    /// Calculate portfolio heat: sum of position risk as fraction of equity.
    /// Heat = Σ (volume * |entry_price - stop_loss|) / equity
    /// Positions without SL use entry_price * 0.02 (2% assumed risk).
    fn calculate_portfolio_heat(&self, equity: Decimal) -> Decimal {
        if equity <= dec!(0) {
            return dec!(0);
        }

        let heat: Decimal = self
            .portfolio_state
            .positions
            .iter()
            .filter(|p| p.is_open())
            .map(|p| {
                let risk_per_unit = match p.sl {
                    Some(sl) => (*p.open_price - *sl).abs(),
                    // No SL set: assume 2% risk from entry.
                    None => *p.open_price * dec!(0.02),
                };
                *p.volume * risk_per_unit
            })
            .sum();

        heat / equity
    }

    /// Compute current portfolio VaR using the volatility and correlation trackers.
    fn compute_var(&self, equity: Decimal) -> Decimal {
        // Build exposure map from open positions.
        let mut exposures: HashMap<InstrumentId, Decimal> = HashMap::new();
        for pos in &self.portfolio_state.positions {
            if pos.is_open() {
                let notional = *pos.volume * *pos.open_price;
                let signed = match pos.side {
                    Side::Buy => notional,
                    Side::Sell => -notional,
                };
                *exposures.entry(pos.instrument_id.clone()).or_default() += signed;
            }
        }

        compute_portfolio_var(
            &exposures,
            equity,
            &self.vol_tracker,
            &self.corr_tracker,
            &self.var_config,
        )
    }

    /// Check correlation cluster exposure limits.
    fn check_correlation_clusters(&self, order: &Order, violations: &mut Vec<RiskViolation>) {
        let equity = self.portfolio_state.equity;
        if equity <= dec!(0) {
            return;
        }

        let volatilities = self.vol_tracker.all_volatilities();
        if volatilities.len() < 2 {
            return; // Need at least 2 instruments for clustering.
        }

        let clusters = self
            .corr_tracker
            .find_clusters(&volatilities, self.config.correlation_cluster_threshold);

        // Build exposure map.
        let mut exposures: HashMap<InstrumentId, Decimal> = HashMap::new();
        for pos in &self.portfolio_state.positions {
            if pos.is_open() {
                let signed = match pos.side {
                    Side::Buy => *pos.volume,
                    Side::Sell => -(*pos.volume),
                };
                *exposures.entry(pos.instrument_id.clone()).or_default() += signed;
            }
        }
        // Include the pending order.
        let order_signed = match order.side {
            Side::Buy => *order.volume,
            Side::Sell => -(*order.volume),
        };
        *exposures.entry(order.instrument_id.clone()).or_default() += order_signed;

        for cluster in &clusters {
            // Only check clusters that include the instrument being traded.
            if !cluster.contains(&order.instrument_id) {
                continue;
            }

            let cluster_exp =
                self.corr_tracker
                    .cluster_exposure(cluster, &exposures, &volatilities);
            let cluster_exp_fraction = cluster_exp / equity;

            if cluster_exp_fraction > self.config.max_cluster_exposure {
                violations.push(RiskViolation::CorrelationClusterExceeded {
                    current: cluster_exp_fraction,
                    max: self.config.max_cluster_exposure,
                });
                break; // One violation per order is sufficient.
            }
        }
    }
}

// ═════════════════════════════════════════════════════════════════════════════
// Actor interface
// ═════════════════════════════════════════════════════════════════════════════

/// Message types for the risk engine actor.
#[derive(Debug)]
pub enum RiskRequest {
    /// Validate an order against all risk checks.
    ValidateOrder { order: Box<Order>, tick: TickEvent },
    /// Update portfolio state snapshot.
    UpdatePortfolio(PortfolioState),
    /// Feed a tick for analytics.
    UpdateTick(TickEvent),
    /// Record an execution for anomaly tracking.
    RecordExecution {
        latency_us: u64,
        slippage_pips: Decimal,
    },
    /// Reset daily counters.
    ResetDaily,
    /// Manually trigger kill switch.
    TriggerKillSwitch,
    /// Attempt to reset the kill switch.
    ResetKillSwitch,
}

/// Response from the risk engine actor.
#[derive(Debug)]
pub enum RiskResponse {
    /// Order approved.
    Approved { order: Order },
    /// Order rejected with violations.
    Rejected {
        order: Order,
        violations: Vec<RiskViolation>,
    },
    /// Acknowledgement for state-update messages.
    Ack,
    /// Kill switch reset result.
    KillSwitchResetResult { success: bool },
}

/// A risk engine actor that processes requests through a crossbeam channel.
///
/// Call `spawn()` to create a sender/receiver pair, then communicate via
/// `RiskRequest`/`RiskResponse` messages.
pub struct RiskActor;

impl RiskActor {
    /// Spawn the risk engine as a dedicated thread with bounded channels.
    ///
    /// Returns (request_sender, response_receiver).
    /// The actor owns the `RiskEngine` and processes messages sequentially.
    pub fn spawn(
        config: RiskConfig,
        channel_capacity: usize,
    ) -> (
        crossbeam_channel::Sender<RiskRequest>,
        crossbeam_channel::Receiver<RiskResponse>,
    ) {
        let (req_tx, req_rx) = crossbeam_channel::bounded::<RiskRequest>(channel_capacity);
        let (resp_tx, resp_rx) = crossbeam_channel::bounded::<RiskResponse>(channel_capacity);

        std::thread::Builder::new()
            .name("risk-engine".into())
            .spawn(move || {
                let mut engine = RiskEngine::new(config);
                Self::run_loop(&mut engine, &req_rx, &resp_tx);
            })
            .expect("failed to spawn risk engine thread");

        (req_tx, resp_rx)
    }

    fn run_loop(
        engine: &mut RiskEngine,
        rx: &crossbeam_channel::Receiver<RiskRequest>,
        tx: &crossbeam_channel::Sender<RiskResponse>,
    ) {
        while let Ok(request) = rx.recv() {
            let response = match request {
                RiskRequest::ValidateOrder { order, tick } => {
                    match engine.validate_order(&order, &tick) {
                        Ok(()) => RiskResponse::Approved { order: *order },
                        Err(violations) => RiskResponse::Rejected { order: *order, violations },
                    }
                }
                RiskRequest::UpdatePortfolio(state) => {
                    engine.update_portfolio(state);
                    RiskResponse::Ack
                }
                RiskRequest::UpdateTick(tick) => {
                    engine.update_tick(&tick);
                    RiskResponse::Ack
                }
                RiskRequest::RecordExecution {
                    latency_us,
                    slippage_pips,
                } => {
                    engine.record_execution(latency_us, slippage_pips);
                    RiskResponse::Ack
                }
                RiskRequest::ResetDaily => {
                    engine.reset_daily();
                    RiskResponse::Ack
                }
                RiskRequest::TriggerKillSwitch => {
                    engine.trigger_kill_switch_manual();
                    RiskResponse::Ack
                }
                RiskRequest::ResetKillSwitch => {
                    let success = engine.reset_kill_switch();
                    RiskResponse::KillSwitchResetResult { success }
                }
            };

            if tx.send(response).is_err() {
                break; // Response receiver dropped, shut down.
            }
        }
    }
}

// ═════════════════════════════════════════════════════════════════════════════
// Tests
// ═════════════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::*;
    use rust_decimal_macros::dec;

    fn default_tick() -> TickEvent {
        TickEvent {
            timestamp: Timestamp::now(),
            instrument_id: InstrumentId::new("EURUSD"),
            bid: Price::new(dec!(1.1000)),
            ask: Price::new(dec!(1.1002)),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: dec!(0.0002),
        }
    }

    fn make_engine(config: RiskConfig) -> RiskEngine {
        let mut engine = RiskEngine::new(config);
        engine.update_portfolio(PortfolioState {
            equity: dec!(100000),
            balance: dec!(100000),
            daily_pnl: dec!(0),
            peak_equity: dec!(100000),
            positions: Vec::new(),
            margin_used: dec!(0),
        });
        engine.peak_equity = dec!(100000);
        engine
    }

    fn market_order(volume: Decimal) -> Order {
        Order::market(
            InstrumentId::new("EURUSD"),
            Side::Buy,
            Volume::new(volume),
            StrategyId::new("test-strategy"),
        )
    }

    fn market_order_for(instrument: &str, side: Side, volume: Decimal, strategy: &str) -> Order {
        Order::market(
            InstrumentId::new(instrument),
            side,
            Volume::new(volume),
            StrategyId::new(strategy),
        )
    }

    fn make_position(
        instrument: &str,
        side: Side,
        volume: Decimal,
        open_price: Decimal,
        strategy: &str,
        sl: Option<Decimal>,
    ) -> Position {
        Position {
            id: 1,
            instrument_id: InstrumentId::new(instrument),
            strategy_id: StrategyId::new(strategy),
            side,
            volume: Volume::new(volume),
            open_price: Price::new(open_price),
            close_price: None,
            sl: sl.map(Price::new),
            tp: None,
            open_time: Timestamp::now(),
            close_time: None,
            pnl_gross: dec!(0),
            pnl_net: dec!(0),
            commission: dec!(0),
            slippage_entry: dec!(0),
            slippage_exit: dec!(0),
            max_favorable_excursion: dec!(0),
            max_adverse_excursion: dec!(0),
            status: PositionStatus::Open,
        }
    }

    // ── Layer 1 tests ────────────────────────────────────────────────────────

    #[test]
    fn valid_order_passes_all_checks() {
        let engine = make_engine(RiskConfig::default());
        let order = market_order(dec!(0.1));
        let tick = default_tick();
        assert!(engine.validate_order(&order, &tick).is_ok());
    }

    #[test]
    fn oversized_order_rejected() {
        let engine = make_engine(RiskConfig::default());
        let order = market_order(dec!(5.0));
        let tick = default_tick();
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err
            .iter()
            .any(|v| matches!(v, RiskViolation::MaxPositionSize { .. })));
    }

    #[test]
    fn wide_spread_rejected() {
        let config = RiskConfig {
            max_spread_pips: dec!(0.0001),
            ..RiskConfig::default()
        };
        let engine = make_engine(config);
        let order = market_order(dec!(0.1));
        let tick = default_tick();
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err
            .iter()
            .any(|v| matches!(v, RiskViolation::SpreadTooWide { .. })));
    }

    // ── Layer 2 tests ────────────────────────────────────────────────────────

    #[test]
    fn strategy_drawdown_blocks_order() {
        let config = RiskConfig {
            max_drawdown_per_strategy: dec!(0.03),
            ..RiskConfig::default()
        };
        let mut engine = RiskEngine::new(config);

        // Create a position with negative P&L for the strategy.
        let pos = Position {
            pnl_net: dec!(-5000),
            ..make_position(
                "EURUSD",
                Side::Buy,
                dec!(0.1),
                dec!(1.1000),
                "strat-a",
                None,
            )
        };

        engine.update_portfolio(PortfolioState {
            equity: dec!(100000),
            balance: dec!(100000),
            daily_pnl: dec!(0),
            peak_equity: dec!(100000),
            positions: vec![pos],
            margin_used: dec!(0),
        });
        engine.peak_equity = dec!(100000);

        // The strategy state should now show drawdown.
        // Force peak_pnl > 0 to get a meaningful ratio.
        engine
            .strategy_states
            .entry(StrategyId::new("strat-a"))
            .and_modify(|s| {
                s.peak_pnl = dec!(1000);
                s.current_pnl = dec!(-5000);
            });

        let order = market_order_for("EURUSD", Side::Buy, dec!(0.1), "strat-a");
        let tick = default_tick();
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err
            .iter()
            .any(|v| matches!(v, RiskViolation::StrategyDrawdownExceeded { .. })));
    }

    #[test]
    fn volatility_cap_blocks_order() {
        let config = RiskConfig {
            rolling_volatility_cap: dec!(0.001),
            analytics_warmup_period: 3,
            ..RiskConfig::default()
        };
        let mut engine = RiskEngine::new(config);
        engine.update_portfolio(PortfolioState {
            equity: dec!(100000),
            balance: dec!(100000),
            daily_pnl: dec!(0),
            peak_equity: dec!(100000),
            positions: Vec::new(),
            margin_used: dec!(0),
        });
        engine.peak_equity = dec!(100000);

        // Feed volatile ticks to generate high volatility.
        let prices = [
            dec!(1.1000),
            dec!(1.1200),
            dec!(1.0800),
            dec!(1.1300),
            dec!(1.0700),
        ];
        for price in &prices {
            let tick = TickEvent {
                timestamp: Timestamp::now(),
                instrument_id: InstrumentId::new("EURUSD"),
                bid: Price::new(*price),
                ask: Price::new(*price + dec!(0.0002)),
                bid_volume: Volume::new(dec!(100)),
                ask_volume: Volume::new(dec!(100)),
                spread: dec!(0.0002),
            };
            engine.update_tick(&tick);
        }

        let order = market_order(dec!(0.1));
        let tick = default_tick();
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err
            .iter()
            .any(|v| matches!(v, RiskViolation::VolatilityCapExceeded { .. })));
    }

    // ── Layer 3 tests ────────────────────────────────────────────────────────

    #[test]
    fn portfolio_heat_check() {
        // Heat = volume * |entry - sl| / equity.
        // 10.0 * |1.1000 - 1.0000| / 100 = 10.0 * 0.1 / 100 = 0.01 > 0.005.
        let config = RiskConfig {
            max_portfolio_heat: dec!(0.005),
            kill_switch_drawdown: dec!(1.0), // disable kill switch
            max_gross_exposure: dec!(1000),  // disable gross exposure check
            max_net_exposure: dec!(1000),    // disable net exposure check
            max_position_size: dec!(100),
            max_order_size: dec!(100),
            ..RiskConfig::default()
        };
        let mut engine = RiskEngine::new(config);

        // Position with SL far from entry creates high heat relative to small equity.
        let pos = make_position(
            "EURUSD",
            Side::Buy,
            dec!(10.0),
            dec!(1.1000),
            "test",
            Some(dec!(1.0000)), // SL 1000 pips away → risk/unit = 0.1
        );

        engine.update_portfolio(PortfolioState {
            equity: dec!(100),
            balance: dec!(100),
            daily_pnl: dec!(0),
            peak_equity: dec!(100),
            positions: vec![pos],
            margin_used: dec!(0),
        });
        engine.peak_equity = dec!(100);

        let order = market_order(dec!(0.01));
        let tick = default_tick();
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err
            .iter()
            .any(|v| matches!(v, RiskViolation::PortfolioHeatExceeded { .. })));
    }

    #[test]
    fn margin_level_check() {
        let config = RiskConfig {
            min_margin_level: dec!(1.5),
            kill_switch_drawdown: dec!(1.0), // disable drawdown kill switch
            ..RiskConfig::default()
        };
        let mut engine = RiskEngine::new(config);

        // Set up low margin level: equity/margin = 10000/8000 = 1.25 < 1.5.
        // This should trigger the kill switch via margin level during update_portfolio.
        engine.update_portfolio(PortfolioState {
            equity: dec!(10000),
            balance: dec!(10000),
            daily_pnl: dec!(0),
            peak_equity: dec!(10000),
            positions: Vec::new(),
            margin_used: dec!(8000),
        });
        engine.peak_equity = dec!(10000);

        // Kill switch should be active with InsufficientMargin reason.
        assert!(engine.check_kill_switch());
        assert!(matches!(
            engine.kill_switch_reason(),
            Some(KillSwitchReason::InsufficientMargin { .. })
        ));

        // Orders should be rejected (kill switch active).
        let order = market_order(dec!(0.01));
        let tick = default_tick();
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err
            .iter()
            .any(|v| matches!(v, RiskViolation::KillSwitchTriggered { .. })));
    }

    // ── Layer 4 tests ────────────────────────────────────────────────────────

    #[test]
    fn kill_switch_blocks_all_orders() {
        let config = RiskConfig {
            kill_switch_drawdown: dec!(0.05),
            ..RiskConfig::default()
        };
        let mut engine = RiskEngine::new(config);
        engine.peak_equity = dec!(100000);
        engine.update_portfolio(PortfolioState {
            equity: dec!(90000), // 10% drawdown > 5% threshold
            balance: dec!(90000),
            daily_pnl: dec!(-10000),
            peak_equity: dec!(100000),
            positions: Vec::new(),
            margin_used: dec!(0),
        });

        let order = market_order(dec!(0.01));
        let tick = default_tick();
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err
            .iter()
            .any(|v| matches!(v, RiskViolation::KillSwitchTriggered { .. })));
        assert!(!engine.is_active());
    }

    #[test]
    fn latency_anomaly_triggers_kill_switch() {
        let config = RiskConfig {
            latency_anomaly_threshold_us: 50_000,
            ..RiskConfig::default()
        };
        let mut engine = make_engine(config);

        // Record anomalous latency.
        engine.record_execution(100_000, dec!(0.5));

        assert!(!engine.is_active());
        assert!(matches!(
            engine.kill_switch_reason(),
            Some(KillSwitchReason::LatencyAnomaly { .. })
        ));
    }

    #[test]
    fn slippage_anomaly_triggers_kill_switch() {
        let config = RiskConfig {
            slippage_anomaly_threshold: dec!(5.0),
            ewma_lambda: dec!(0.0), // λ=0 means only current value matters
            ..RiskConfig::default()
        };
        let mut engine = make_engine(config);

        // Record anomalous slippage.
        engine.record_execution(100, dec!(10.0));

        assert!(!engine.is_active());
        assert!(matches!(
            engine.kill_switch_reason(),
            Some(KillSwitchReason::SlippageAnomaly { .. })
        ));
    }

    #[test]
    fn manual_kill_switch() {
        let mut engine = make_engine(RiskConfig::default());
        assert!(engine.is_active());

        engine.trigger_kill_switch_manual();
        assert!(!engine.is_active());
        assert!(matches!(
            engine.kill_switch_reason(),
            Some(KillSwitchReason::Manual)
        ));
    }

    #[test]
    fn kill_switch_reset_when_condition_clears() {
        let config = RiskConfig {
            latency_anomaly_threshold_us: 50_000,
            ..RiskConfig::default()
        };
        let mut engine = make_engine(config);

        // Trigger via latency.
        engine.record_execution(100_000, dec!(0.5));
        assert!(!engine.is_active());

        // Clear the latency (simulate next execution being fast).
        engine.last_execution_latency_us = 100;
        assert!(engine.reset_kill_switch());
        assert!(engine.is_active());
    }

    #[test]
    fn kill_switch_reset_fails_when_condition_persists() {
        let config = RiskConfig {
            kill_switch_drawdown: dec!(0.05),
            ..RiskConfig::default()
        };
        let mut engine = RiskEngine::new(config);
        engine.peak_equity = dec!(100000);
        engine.update_portfolio(PortfolioState {
            equity: dec!(90000),
            balance: dec!(90000),
            daily_pnl: dec!(-10000),
            peak_equity: dec!(100000),
            positions: Vec::new(),
            margin_used: dec!(0),
        });

        assert!(!engine.is_active());
        assert!(!engine.reset_kill_switch());
    }

    // ── General tests ────────────────────────────────────────────────────────

    #[test]
    fn drawdown_calculation() {
        let mut engine = RiskEngine::new(RiskConfig::default());
        engine.peak_equity = dec!(100000);
        engine.update_portfolio(PortfolioState {
            equity: dec!(95000),
            balance: dec!(95000),
            daily_pnl: dec!(-5000),
            peak_equity: dec!(100000),
            positions: Vec::new(),
            margin_used: dec!(0),
        });
        assert_eq!(engine.current_drawdown(), dec!(0.05));
    }

    #[test]
    fn reset_daily_clears_loss() {
        let mut engine = RiskEngine::new(RiskConfig::default());
        engine.daily_loss = dec!(500);
        engine.reset_daily();
        assert_eq!(engine.daily_loss, dec!(0));
    }

    #[test]
    fn multiple_violations_collected() {
        let config = RiskConfig {
            max_order_size: dec!(0.01),
            max_spread_pips: dec!(0.00001),
            ..RiskConfig::default()
        };
        let engine = make_engine(config);
        let order = market_order(dec!(5.0));
        let tick = default_tick();
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err.len() >= 2);
    }

    #[test]
    fn portfolio_heat_with_no_sl_uses_default_risk() {
        let config = RiskConfig::default();
        let mut engine = RiskEngine::new(config);

        let pos = make_position(
            "EURUSD",
            Side::Buy,
            dec!(1.0),
            dec!(1.1000),
            "test",
            None, // No SL
        );

        engine.update_portfolio(PortfolioState {
            equity: dec!(100000),
            balance: dec!(100000),
            daily_pnl: dec!(0),
            peak_equity: dec!(100000),
            positions: vec![pos],
            margin_used: dec!(0),
        });

        // Heat = 1.0 * (1.1000 * 0.02) / 100000 = 0.022 / 100000 = 0.00022
        let heat = engine.current_portfolio_heat();
        assert!(heat > dec!(0));
        assert!(heat < dec!(0.001));
    }

    // ── Actor tests ──────────────────────────────────────────────────────────

    #[test]
    fn actor_validate_order_approved() {
        let (tx, rx) = RiskActor::spawn(RiskConfig::default(), 16);

        // First set up portfolio state.
        tx.send(RiskRequest::UpdatePortfolio(PortfolioState {
            equity: dec!(100000),
            balance: dec!(100000),
            daily_pnl: dec!(0),
            peak_equity: dec!(100000),
            positions: Vec::new(),
            margin_used: dec!(0),
        }))
        .unwrap();
        let _ = rx.recv().unwrap(); // Ack

        // Validate a small order.
        let order = market_order(dec!(0.1));
        let tick = default_tick();
        tx.send(RiskRequest::ValidateOrder { order: Box::new(order), tick }).unwrap();

        match rx.recv().unwrap() {
            RiskResponse::Approved { order } => {
                assert_eq!(*order.volume, dec!(0.1));
            }
            other => panic!("expected Approved, got: {other:?}"),
        }
    }

    #[test]
    fn actor_validate_order_rejected() {
        let (tx, rx) = RiskActor::spawn(
            RiskConfig {
                max_order_size: dec!(0.01),
                ..RiskConfig::default()
            },
            16,
        );

        tx.send(RiskRequest::UpdatePortfolio(PortfolioState {
            equity: dec!(100000),
            balance: dec!(100000),
            daily_pnl: dec!(0),
            peak_equity: dec!(100000),
            positions: Vec::new(),
            margin_used: dec!(0),
        }))
        .unwrap();
        let _ = rx.recv().unwrap();

        let order = market_order(dec!(5.0));
        let tick = default_tick();
        tx.send(RiskRequest::ValidateOrder { order: Box::new(order), tick }).unwrap();

        match rx.recv().unwrap() {
            RiskResponse::Rejected { violations, .. } => {
                assert!(!violations.is_empty());
            }
            other => panic!("expected Rejected, got: {other:?}"),
        }
    }

    #[test]
    fn actor_kill_switch_and_reset() {
        let (tx, rx) = RiskActor::spawn(RiskConfig::default(), 16);

        tx.send(RiskRequest::UpdatePortfolio(PortfolioState {
            equity: dec!(100000),
            balance: dec!(100000),
            daily_pnl: dec!(0),
            peak_equity: dec!(100000),
            positions: Vec::new(),
            margin_used: dec!(0),
        }))
        .unwrap();
        let _ = rx.recv().unwrap();

        tx.send(RiskRequest::TriggerKillSwitch).unwrap();
        let _ = rx.recv().unwrap();

        // Order should be rejected.
        let order = market_order(dec!(0.01));
        let tick = default_tick();
        tx.send(RiskRequest::ValidateOrder { order: Box::new(order), tick }).unwrap();
        match rx.recv().unwrap() {
            RiskResponse::Rejected { .. } => {}
            other => panic!("expected Rejected, got: {other:?}"),
        }

        // Reset should succeed (manual trigger has no persistent condition).
        tx.send(RiskRequest::ResetKillSwitch).unwrap();
        match rx.recv().unwrap() {
            RiskResponse::KillSwitchResetResult { success } => {
                assert!(success);
            }
            other => panic!("expected KillSwitchResetResult, got: {other:?}"),
        }
    }
}
