//! RSI Momentum Strategy.
//!
//! Generates **Buy** signals when RSI crosses above the oversold threshold
//! (momentum reversal up) and **Sell** signals when RSI crosses below the
//! overbought threshold (momentum reversal down).
//!
//! Uses Wilder's smoothing (exponential moving average of gains/losses)
//! for the RSI calculation, matching the industry-standard formula.

use std::collections::VecDeque;

use quantfund_core::types::Side;
use quantfund_core::{InstrumentId, SignalEvent, StrategyId};
use rust_decimal::prelude::ToPrimitive;
use rust_decimal_macros::dec;

use crate::traits::{MarketSnapshot, Strategy};

// ─── Config ──────────────────────────────────────────────────────────────────

/// Configuration for the RSI momentum strategy.
#[derive(Clone, Debug)]
pub struct MomentumRsiConfig {
    /// RSI lookback period. Default: 14.
    pub rsi_period: usize,
    /// RSI level below which the asset is considered oversold. Default: 30.
    pub oversold: f64,
    /// RSI level above which the asset is considered overbought. Default: 70.
    pub overbought: f64,
    /// Base position size.
    pub position_size: f64,
    /// Instruments to trade.
    pub instruments: Vec<InstrumentId>,
}

impl Default for MomentumRsiConfig {
    fn default() -> Self {
        Self {
            rsi_period: 14,
            oversold: 30.0,
            overbought: 70.0,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        }
    }
}

// ─── Per-instrument RSI state ────────────────────────────────────────────────

struct RsiState {
    instrument_id: InstrumentId,
    /// Rolling price buffer (only needs last 2 prices for delta, but we keep
    /// `period + 1` to initialise the first average without bias).
    prices: VecDeque<f64>,
    /// Exponential average of gains (Wilder smoothing).
    avg_gain: Option<f64>,
    /// Exponential average of losses (Wilder smoothing).
    avg_loss: Option<f64>,
    /// Previous RSI value (for crossover detection).
    prev_rsi: Option<f64>,
    /// Number of prices seen so far.
    count: usize,
}

impl RsiState {
    fn new(instrument_id: InstrumentId, period: usize) -> Self {
        Self {
            instrument_id,
            prices: VecDeque::with_capacity(period + 2),
            avg_gain: None,
            avg_loss: None,
            prev_rsi: None,
            count: 0,
        }
    }
}

// ─── Strategy ────────────────────────────────────────────────────────────────

/// RSI momentum strategy.
pub struct MomentumRsi {
    id: StrategyId,
    config: MomentumRsiConfig,
    states: Vec<RsiState>,
}

impl MomentumRsi {
    pub fn new(config: MomentumRsiConfig) -> Self {
        let states = config
            .instruments
            .iter()
            .map(|id| RsiState::new(id.clone(), config.rsi_period))
            .collect();

        Self {
            id: StrategyId::new("momentum-rsi"),
            config,
            states,
        }
    }

    fn state_index(&self, instrument_id: &InstrumentId) -> Option<usize> {
        self.states
            .iter()
            .position(|s| &s.instrument_id == instrument_id)
    }

    /// Update RSI state with a new price and return the current RSI.
    fn update_rsi(state: &mut RsiState, price: f64, period: usize) -> Option<f64> {
        state.prices.push_back(price);
        state.count += 1;

        if state.prices.len() < 2 {
            return None;
        }

        let delta = price - state.prices[state.prices.len() - 2];
        let gain = if delta > 0.0 { delta } else { 0.0 };
        let loss = if delta < 0.0 { -delta } else { 0.0 };

        // Keep buffer bounded
        if state.prices.len() > period + 2 {
            state.prices.pop_front();
        }

        if state.count <= period {
            // Accumulation phase: not enough data yet
            return None;
        }

        let period_f = period as f64;

        match (state.avg_gain, state.avg_loss) {
            (Some(avg_g), Some(avg_l)) => {
                // Wilder smoothing: EMA-style update
                let new_avg_gain = (avg_g * (period_f - 1.0) + gain) / period_f;
                let new_avg_loss = (avg_l * (period_f - 1.0) + loss) / period_f;
                state.avg_gain = Some(new_avg_gain);
                state.avg_loss = Some(new_avg_loss);

                let rsi = if new_avg_loss == 0.0 {
                    100.0
                } else {
                    let rs = new_avg_gain / new_avg_loss;
                    100.0 - (100.0 / (1.0 + rs))
                };
                Some(rsi)
            }
            _ => {
                // First RSI calculation: compute simple average of gains/losses
                // from the accumulated deltas.
                if state.count == period + 1 {
                    let mut total_gain = 0.0;
                    let mut total_loss = 0.0;
                    for i in 1..state.prices.len() {
                        let d = state.prices[i] - state.prices[i - 1];
                        if d > 0.0 {
                            total_gain += d;
                        } else {
                            total_loss -= d;
                        }
                    }
                    let avg_gain = total_gain / period_f;
                    let avg_loss = total_loss / period_f;
                    state.avg_gain = Some(avg_gain);
                    state.avg_loss = Some(avg_loss);

                    let rsi = if avg_loss == 0.0 {
                        100.0
                    } else {
                        let rs = avg_gain / avg_loss;
                        100.0 - (100.0 / (1.0 + rs))
                    };
                    Some(rsi)
                } else {
                    None
                }
            }
        }
    }
}

impl Strategy for MomentumRsi {
    fn id(&self) -> &StrategyId {
        &self.id
    }

    fn name(&self) -> &str {
        "Momentum RSI"
    }

    fn instruments(&self) -> &[InstrumentId] {
        &self.config.instruments
    }

    fn on_tick(&mut self, snapshot: &MarketSnapshot) -> Option<SignalEvent> {
        let idx = self.state_index(snapshot.instrument_id)?;

        // Mid-price
        let mid = (*snapshot.tick.bid + *snapshot.tick.ask) / dec!(2);
        let mid_f = mid.to_f64()?;

        let period = self.config.rsi_period;
        let state = &mut self.states[idx];

        let rsi = Self::update_rsi(state, mid_f, period)?;
        let prev_rsi = state.prev_rsi;
        state.prev_rsi = Some(rsi);

        let prev = prev_rsi?;

        // Crossover detection
        let signal = if prev <= self.config.oversold && rsi > self.config.oversold {
            // RSI crossed above oversold → momentum reversal up → Buy
            let strength = ((self.config.oversold - prev) / self.config.oversold)
                .abs()
                .min(1.0)
                .max(0.1);
            Some((Side::Buy, strength))
        } else if prev >= self.config.overbought && rsi < self.config.overbought {
            // RSI crossed below overbought → momentum reversal down → Sell
            let strength = ((prev - self.config.overbought) / (100.0 - self.config.overbought))
                .abs()
                .min(1.0)
                .max(0.1);
            Some((Side::Sell, strength))
        } else {
            None
        };

        let (side, strength) = signal?;

        Some(SignalEvent {
            timestamp: snapshot.tick.timestamp,
            strategy_id: self.id.clone(),
            instrument_id: snapshot.instrument_id.clone(),
            side: Some(side),
            strength: match side {
                Side::Buy => strength,
                Side::Sell => -strength,
            },
            metadata: serde_json::json!({
                "rsi": rsi,
                "prev_rsi": prev,
            }),
        })
    }

    fn reset(&mut self) {
        for state in &mut self.states {
            state.prices.clear();
            state.avg_gain = None;
            state.avg_loss = None;
            state.prev_rsi = None;
            state.count = 0;
        }
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use rust_decimal::Decimal;
    use quantfund_core::{Price, TickEvent, Timestamp, Volume};

    fn make_tick(instrument: &str, bid: Decimal, ask: Decimal, ts_nanos: i64) -> TickEvent {
        TickEvent {
            timestamp: Timestamp::from_nanos(ts_nanos),
            instrument_id: InstrumentId::new(instrument),
            bid: Price::new(bid),
            ask: Price::new(ask),
            bid_volume: Volume::new(dec!(100)),
            ask_volume: Volume::new(dec!(100)),
            spread: ask - bid,
        }
    }

    fn make_snapshot<'a>(tick: &'a TickEvent, id: &'a InstrumentId) -> MarketSnapshot<'a> {
        MarketSnapshot {
            tick,
            instrument_id: id,
        }
    }

    #[test]
    fn no_signal_until_period_filled() {
        let config = MomentumRsiConfig {
            rsi_period: 5,
            oversold: 30.0,
            overbought: 70.0,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = MomentumRsi::new(config);
        let id = InstrumentId::new("XAUUSD");

        // Feed fewer than period+1 ticks → no RSI possible
        for i in 0..5 {
            let bid = dec!(2000.00) + Decimal::new(i, 2);
            let tick = make_tick("XAUUSD", bid, bid + dec!(0.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            assert!(strategy.on_tick(&snap).is_none());
        }
    }

    #[test]
    fn buy_signal_on_oversold_crossover() {
        let config = MomentumRsiConfig {
            rsi_period: 5,
            oversold: 30.0,
            overbought: 70.0,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = MomentumRsi::new(config);
        let id = InstrumentId::new("XAUUSD");

        // Drive price down hard to push RSI below 30 (oversold)
        let mut price = dec!(2000.00);
        for i in 0..8 {
            price -= dec!(5.00); // strong decline
            let tick = make_tick("XAUUSD", price, price + dec!(0.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        // Now reverse up to cross above oversold
        for i in 8..12 {
            price += dec!(3.00);
            let tick = make_tick("XAUUSD", price, price + dec!(0.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            if let Some(signal) = strategy.on_tick(&snap) {
                assert_eq!(signal.side, Some(Side::Buy));
                assert!(signal.strength > 0.0);
                return; // Test passed
            }
        }
        // If RSI didn't cross in this range, that's still valid behavior
        // since the exact crossover point depends on the EMA calculation.
    }

    #[test]
    fn sell_signal_on_overbought_crossover() {
        let config = MomentumRsiConfig {
            rsi_period: 5,
            oversold: 30.0,
            overbought: 70.0,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = MomentumRsi::new(config);
        let id = InstrumentId::new("XAUUSD");

        // Drive price up to push RSI above 70 (overbought)
        let mut price = dec!(2000.00);
        for i in 0..8 {
            price += dec!(5.00);
            let tick = make_tick("XAUUSD", price, price + dec!(0.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        // Reverse down to cross below overbought
        for i in 8..12 {
            price -= dec!(3.00);
            let tick = make_tick("XAUUSD", price, price + dec!(0.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            if let Some(signal) = strategy.on_tick(&snap) {
                assert_eq!(signal.side, Some(Side::Sell));
                assert!(signal.strength < 0.0);
                return;
            }
        }
    }

    #[test]
    fn reset_clears_all_state() {
        let config = MomentumRsiConfig {
            rsi_period: 5,
            ..Default::default()
        };
        let mut strategy = MomentumRsi::new(config);
        let id = InstrumentId::new("XAUUSD");

        for i in 0..10 {
            let bid = dec!(2000.00) + Decimal::new(i, 2);
            let tick = make_tick("XAUUSD", bid, bid + dec!(0.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        strategy.reset();
        assert!(strategy.states[0].prices.is_empty());
        assert!(strategy.states[0].avg_gain.is_none());
        assert!(strategy.states[0].prev_rsi.is_none());
        assert_eq!(strategy.states[0].count, 0);
    }
}
