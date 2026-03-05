use rust_decimal::Decimal;

/// A risk-limit violation.
///
/// Each variant captures the requested / current value and the configured limit
/// so that rejection messages are self-describing.
#[derive(Clone, Debug, thiserror::Error)]
pub enum RiskViolation {
    #[error("position size {requested} exceeds max {max}")]
    MaxPositionSize { requested: Decimal, max: Decimal },

    #[error("spread {current} exceeds max {max} pips")]
    SpreadTooWide { current: Decimal, max: Decimal },

    #[error("max positions reached: {current}/{max}")]
    MaxPositionsReached { current: usize, max: usize },

    #[error("daily loss limit reached: {current_loss} >= {max_loss}")]
    DailyLossLimit {
        current_loss: Decimal,
        max_loss: Decimal,
    },

    #[error("gross exposure {current} exceeds max {max}")]
    GrossExposureExceeded { current: Decimal, max: Decimal },

    #[error("net exposure {current} exceeds max {max}")]
    NetExposureExceeded { current: Decimal, max: Decimal },

    #[error("portfolio heat {current} exceeds max {max}")]
    PortfolioHeatExceeded { current: Decimal, max: Decimal },

    #[error("drawdown {current} exceeds kill switch threshold {threshold}")]
    KillSwitchTriggered {
        current: Decimal,
        threshold: Decimal,
    },

    #[error("margin level {current} below minimum {min}")]
    InsufficientMargin { current: Decimal, min: Decimal },

    #[error("strategy drawdown {current} exceeds max {max}")]
    StrategyDrawdownExceeded { current: Decimal, max: Decimal },
}

// ─── Standalone check functions ──────────────────────────────────────────────

/// Reject if the requested volume exceeds the configured maximum.
pub fn check_position_size(volume: Decimal, max: Decimal) -> Result<(), RiskViolation> {
    if volume > max {
        return Err(RiskViolation::MaxPositionSize {
            requested: volume,
            max,
        });
    }
    Ok(())
}

/// Reject if the current spread exceeds the configured maximum.
pub fn check_spread(current_spread: Decimal, max_spread: Decimal) -> Result<(), RiskViolation> {
    if current_spread > max_spread {
        return Err(RiskViolation::SpreadTooWide {
            current: current_spread,
            max: max_spread,
        });
    }
    Ok(())
}

/// Reject if the current position count has reached the configured maximum.
pub fn check_max_positions(current: usize, max: usize) -> Result<(), RiskViolation> {
    if current >= max {
        return Err(RiskViolation::MaxPositionsReached { current, max });
    }
    Ok(())
}

/// Reject if today's cumulative loss has reached the configured limit.
pub fn check_daily_loss(current_loss: Decimal, max_loss: Decimal) -> Result<(), RiskViolation> {
    if current_loss >= max_loss {
        return Err(RiskViolation::DailyLossLimit {
            current_loss,
            max_loss,
        });
    }
    Ok(())
}

/// Reject if gross exposure (sum of absolute position values) exceeds the limit.
pub fn check_gross_exposure(current: Decimal, max: Decimal) -> Result<(), RiskViolation> {
    if current > max {
        return Err(RiskViolation::GrossExposureExceeded { current, max });
    }
    Ok(())
}

/// Reject if net exposure (directional imbalance) exceeds the limit.
pub fn check_net_exposure(current: Decimal, max: Decimal) -> Result<(), RiskViolation> {
    if current.abs() > max {
        return Err(RiskViolation::NetExposureExceeded {
            current: current.abs(),
            max,
        });
    }
    Ok(())
}

/// Reject if current drawdown from peak equity exceeds the kill-switch threshold.
pub fn check_kill_switch(current_dd: Decimal, threshold: Decimal) -> Result<(), RiskViolation> {
    if current_dd >= threshold {
        return Err(RiskViolation::KillSwitchTriggered {
            current: current_dd,
            threshold,
        });
    }
    Ok(())
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use rust_decimal_macros::dec;

    #[test]
    fn position_size_within_limit() {
        assert!(check_position_size(dec!(0.5), dec!(1.0)).is_ok());
    }

    #[test]
    fn position_size_at_limit() {
        assert!(check_position_size(dec!(1.0), dec!(1.0)).is_ok());
    }

    #[test]
    fn position_size_exceeds_limit() {
        let err = check_position_size(dec!(1.5), dec!(1.0)).unwrap_err();
        match err {
            RiskViolation::MaxPositionSize { requested, max } => {
                assert_eq!(requested, dec!(1.5));
                assert_eq!(max, dec!(1.0));
            }
            other => panic!("unexpected variant: {other}"),
        }
    }

    #[test]
    fn spread_within_limit() {
        assert!(check_spread(dec!(2.0), dec!(5.0)).is_ok());
    }

    #[test]
    fn spread_exceeds_limit() {
        let err = check_spread(dec!(6.0), dec!(5.0)).unwrap_err();
        match err {
            RiskViolation::SpreadTooWide { current, max } => {
                assert_eq!(current, dec!(6.0));
                assert_eq!(max, dec!(5.0));
            }
            other => panic!("unexpected variant: {other}"),
        }
    }

    #[test]
    fn positions_below_limit() {
        assert!(check_max_positions(2, 5).is_ok());
    }

    #[test]
    fn positions_at_limit() {
        let err = check_max_positions(5, 5).unwrap_err();
        match err {
            RiskViolation::MaxPositionsReached { current, max } => {
                assert_eq!(current, 5);
                assert_eq!(max, 5);
            }
            other => panic!("unexpected variant: {other}"),
        }
    }

    #[test]
    fn daily_loss_within_limit() {
        assert!(check_daily_loss(dec!(0.01), dec!(0.02)).is_ok());
    }

    #[test]
    fn daily_loss_at_limit() {
        let err = check_daily_loss(dec!(0.02), dec!(0.02)).unwrap_err();
        match err {
            RiskViolation::DailyLossLimit {
                current_loss,
                max_loss,
            } => {
                assert_eq!(current_loss, dec!(0.02));
                assert_eq!(max_loss, dec!(0.02));
            }
            other => panic!("unexpected variant: {other}"),
        }
    }

    #[test]
    fn gross_exposure_within_limit() {
        assert!(check_gross_exposure(dec!(1.5), dec!(2.0)).is_ok());
    }

    #[test]
    fn gross_exposure_exceeds_limit() {
        let err = check_gross_exposure(dec!(2.5), dec!(2.0)).unwrap_err();
        match err {
            RiskViolation::GrossExposureExceeded { current, max } => {
                assert_eq!(current, dec!(2.5));
                assert_eq!(max, dec!(2.0));
            }
            other => panic!("unexpected variant: {other}"),
        }
    }

    #[test]
    fn net_exposure_within_limit() {
        assert!(check_net_exposure(dec!(-0.5), dec!(1.0)).is_ok());
    }

    #[test]
    fn net_exposure_exceeds_limit() {
        let err = check_net_exposure(dec!(-1.5), dec!(1.0)).unwrap_err();
        match err {
            RiskViolation::NetExposureExceeded { current, max } => {
                assert_eq!(current, dec!(1.5));
                assert_eq!(max, dec!(1.0));
            }
            other => panic!("unexpected variant: {other}"),
        }
    }

    #[test]
    fn kill_switch_below_threshold() {
        assert!(check_kill_switch(dec!(0.05), dec!(0.10)).is_ok());
    }

    #[test]
    fn kill_switch_at_threshold() {
        let err = check_kill_switch(dec!(0.10), dec!(0.10)).unwrap_err();
        match err {
            RiskViolation::KillSwitchTriggered { current, threshold } => {
                assert_eq!(current, dec!(0.10));
                assert_eq!(threshold, dec!(0.10));
            }
            other => panic!("unexpected variant: {other}"),
        }
    }
}
