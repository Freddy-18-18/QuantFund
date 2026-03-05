use quantfund_core::{Order, Position, Side, TickEvent};
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

use crate::config::RiskConfig;
use crate::limits::{self, RiskViolation};

/// Snapshot of portfolio state used for risk calculations.
pub struct PortfolioState {
    pub equity: Decimal,
    pub balance: Decimal,
    pub daily_pnl: Decimal,
    pub peak_equity: Decimal,
    pub positions: Vec<Position>,
    pub margin_used: Decimal,
}

/// The risk engine. Runs as a dedicated actor receiving orders and returning
/// approval / rejection decisions.
///
/// All checks must complete in < 10 microseconds.
pub struct RiskEngine {
    config: RiskConfig,
    portfolio_state: PortfolioState,
    daily_loss: Decimal,
    peak_equity: Decimal,
    kill_switch_active: bool,
}

impl RiskEngine {
    /// Create a new risk engine with the given configuration.
    pub fn new(config: RiskConfig) -> Self {
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
        }
    }

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

        // Store state before evaluating kill switch so that
        // `current_drawdown()` sees the latest equity.
        self.portfolio_state = state;

        // Check whether the kill switch should now be active.
        self.kill_switch_active = self.check_kill_switch_internal();
    }

    /// Validate an order against all Layer 1–3 risk checks.
    ///
    /// Returns `Ok(())` if every check passes, or `Err(violations)` containing
    /// **all** violations found (not just the first).
    pub fn validate_order(
        &self,
        order: &Order,
        current_tick: &TickEvent,
    ) -> Result<(), Vec<RiskViolation>> {
        let mut violations = Vec::new();

        // ── Kill switch (Layer 4 — checked first, rejects everything) ────────
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

        // Daily loss check (daily_loss is fraction of equity if equity > 0).
        let equity = self.portfolio_state.equity;
        if equity > dec!(0) {
            let daily_loss_fraction = self.daily_loss / equity;
            if let Err(v) =
                limits::check_daily_loss(daily_loss_fraction, self.config.max_daily_loss)
            {
                violations.push(v);
            }

            // Gross exposure: sum of |volume| across all open positions + this order.
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

            // Net exposure: buy volume − sell volume, including the new order.
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
        }

        if violations.is_empty() {
            Ok(())
        } else {
            Err(violations)
        }
    }

    /// Returns `true` if the kill switch should be active.
    pub fn check_kill_switch(&self) -> bool {
        self.check_kill_switch_internal()
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

    /// Returns `false` if the kill switch has been triggered.
    pub fn is_active(&self) -> bool {
        !self.kill_switch_active
    }

    /// Reset daily loss tracking (call at end of day).
    pub fn reset_daily(&mut self) {
        self.daily_loss = dec!(0);
    }

    // ── internal ─────────────────────────────────────────────────────────────

    fn check_kill_switch_internal(&self) -> bool {
        let dd = self.current_drawdown();
        dd >= self.config.kill_switch_drawdown
    }
}

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
        // Set peak so drawdown calcs work correctly.
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
        let tick = default_tick(); // spread = 0.0002
        let err = engine.validate_order(&order, &tick).unwrap_err();
        assert!(err
            .iter()
            .any(|v| matches!(v, RiskViolation::SpreadTooWide { .. })));
    }

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
        // Should have at least position-size and spread violations.
        assert!(err.len() >= 2);
    }
}
