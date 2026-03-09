//! Bollinger Bands Mean Reversion Strategy.
//!
//! Enters **long** when price drops below the lower Bollinger Band (oversold),
//! enters **short** when price rises above the upper Bollinger Band (overbought),
//! and flattens when price returns to the SMA (middle band).
//!
//! Well-suited for range-bound markets / XAUUSD consolidation phases.

use std::collections::VecDeque;

use quantfund_core::types::Side;
use quantfund_core::{InstrumentId, SignalEvent, StrategyId};
use rust_decimal::prelude::ToPrimitive;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

use crate::traits::{MarketSnapshot, Strategy};

// ─── Config ──────────────────────────────────────────────────────────────────

/// Configuration for the Bollinger Bands mean reversion strategy.
#[derive(Clone, Debug)]
pub struct MeanReversionConfig {
    /// Lookback period for the SMA and standard deviation.
    pub period: usize,
    /// Number of standard deviations for the upper/lower bands.
    pub std_dev: f64,
    /// Base position size as fraction of account equity.
    pub position_size: f64,
    /// Instruments to trade.
    pub instruments: Vec<InstrumentId>,
}

impl Default for MeanReversionConfig {
    fn default() -> Self {
        Self {
            period: 20,
            std_dev: 2.0,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        }
    }
}

// ─── Strategy ────────────────────────────────────────────────────────────────

/// Bollinger Bands mean reversion strategy.
pub struct MeanReversion {
    id: StrategyId,
    config: MeanReversionConfig,
    /// Rolling price buffer per instrument.
    price_buffers: Vec<(InstrumentId, VecDeque<Decimal>)>,
    /// Current position state per instrument (None = flat, Some(side) = in position).
    position_state: Vec<Option<Side>>,
}

impl MeanReversion {
    pub fn new(config: MeanReversionConfig) -> Self {
        let n = config.instruments.len();
        let price_buffers = config
            .instruments
            .iter()
            .map(|id| (id.clone(), VecDeque::with_capacity(config.period + 1)))
            .collect();

        Self {
            id: StrategyId::new("mean-reversion"),
            config,
            price_buffers,
            position_state: vec![None; n],
        }
    }

    /// Compute SMA of the buffer.
    fn sma(buffer: &VecDeque<Decimal>, period: usize) -> Option<Decimal> {
        if buffer.len() < period {
            return None;
        }
        let sum: Decimal = buffer.iter().rev().take(period).sum();
        Some(sum / Decimal::from(period))
    }

    /// Compute standard deviation of the last `period` values.
    fn std_dev(buffer: &VecDeque<Decimal>, period: usize, mean: Decimal) -> Option<f64> {
        if buffer.len() < period {
            return None;
        }
        let mean_f = mean.to_f64()?;
        let variance: f64 = buffer
            .iter()
            .rev()
            .take(period)
            .filter_map(|v| v.to_f64())
            .map(|v| (v - mean_f).powi(2))
            .sum::<f64>()
            / period as f64;
        Some(variance.sqrt())
    }

    fn instrument_index(&self, instrument_id: &InstrumentId) -> Option<usize> {
        self.price_buffers
            .iter()
            .position(|(id, _)| id == instrument_id)
    }
}

impl Strategy for MeanReversion {
    fn id(&self) -> &StrategyId {
        &self.id
    }

    fn name(&self) -> &str {
        "Mean Reversion (Bollinger Bands)"
    }

    fn instruments(&self) -> &[InstrumentId] {
        &self.config.instruments
    }

    fn on_tick(&mut self, snapshot: &MarketSnapshot) -> Option<SignalEvent> {
        let idx = self.instrument_index(snapshot.instrument_id)?;
        let (_, buffer) = &mut self.price_buffers[idx];

        // Mid-price
        let mid = (*snapshot.tick.bid + *snapshot.tick.ask) / dec!(2);

        // Maintain rolling buffer
        let max_len = self.config.period + 1;
        if buffer.len() >= max_len {
            buffer.pop_front();
        }
        buffer.push_back(mid);

        // Compute Bollinger Bands
        let sma = Self::sma(buffer, self.config.period)?;
        let std = Self::std_dev(buffer, self.config.period, sma)?;

        let std_dec = Decimal::try_from(std * self.config.std_dev).unwrap_or(dec!(0));
        let upper_band = sma + std_dec;
        let lower_band = sma - std_dec;

        let mid_f = mid.to_f64().unwrap_or(0.0);
        let upper_f = upper_band.to_f64().unwrap_or(0.0);
        let lower_f = lower_band.to_f64().unwrap_or(0.0);
        let sma_f = sma.to_f64().unwrap_or(0.0);

        let current_pos = self.position_state[idx];

        // Signal logic
        let (side, strength) = if mid < lower_band && current_pos != Some(Side::Buy) {
            // Price below lower band → oversold → Buy
            let dist = if lower_f != 0.0 {
                ((lower_f - mid_f) / lower_f).abs().min(1.0)
            } else {
                0.5
            };
            self.position_state[idx] = Some(Side::Buy);
            (Some(Side::Buy), dist.max(0.1))
        } else if mid > upper_band && current_pos != Some(Side::Sell) {
            // Price above upper band → overbought → Sell
            let dist = if upper_f != 0.0 {
                ((mid_f - upper_f) / upper_f).abs().min(1.0)
            } else {
                0.5
            };
            self.position_state[idx] = Some(Side::Sell);
            (Some(Side::Sell), dist.max(0.1))
        } else if current_pos.is_some() {
            // Check if price returned to SMA → flatten
            let near_sma = if sma_f != 0.0 {
                ((mid_f - sma_f) / sma_f).abs() < 0.001 // within 0.1% of SMA
            } else {
                false
            };
            if near_sma {
                self.position_state[idx] = None;
                // Signal opposite direction to close the position
                let exit_side = match current_pos.unwrap() {
                    Side::Buy => Side::Sell,
                    Side::Sell => Side::Buy,
                };
                (Some(exit_side), 0.01) // minimal strength for exit
            } else {
                return None; // hold current position
            }
        } else {
            return None; // price within bands, no position
        };

        let side = side?;

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
                "sma": sma_f,
                "upper_band": upper_f,
                "lower_band": lower_f,
                "std_dev": std,
            }),
        })
    }

    fn reset(&mut self) {
        for (_, buffer) in &mut self.price_buffers {
            buffer.clear();
        }
        self.position_state.fill(None);
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
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
        let config = MeanReversionConfig {
            period: 5,
            std_dev: 2.0,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = MeanReversion::new(config);
        let id = InstrumentId::new("XAUUSD");

        for i in 0..4 {
            let bid = dec!(1950.00) + Decimal::new(i, 2);
            let ask = bid + dec!(0.30);
            let tick = make_tick("XAUUSD", bid, ask, i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            assert!(strategy.on_tick(&snap).is_none());
        }
    }

    #[test]
    fn buy_signal_below_lower_band() {
        let config = MeanReversionConfig {
            period: 5,
            std_dev: 1.0, // Reduced from 2.0 to allow mathematical breach for N=5
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = MeanReversion::new(config);
        let id = InstrumentId::new("XAUUSD");

        // Feed stable prices to establish bands
        let stable = dec!(2000.00);
        for i in 0..6 {
            let bid = stable;
            let ask = bid + dec!(0.30);
            let tick = make_tick("XAUUSD", bid, ask, i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        // Drop price far below lower band
        let crash = dec!(1800.00);
        let tick = make_tick("XAUUSD", crash, crash + dec!(0.30), 10_000_000_000);
        let snap = make_snapshot(&tick, &id);
        let signal = strategy.on_tick(&snap);

        assert!(signal.is_some());
        let s = signal.unwrap();
        assert_eq!(s.side, Some(Side::Buy));
        assert!(s.strength > 0.0);
    }

    #[test]
    fn sell_signal_above_upper_band() {
        let config = MeanReversionConfig {
            period: 5,
            std_dev: 1.0, // Reduced from 2.0 to allow mathematical breach for N=5
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = MeanReversion::new(config);
        let id = InstrumentId::new("XAUUSD");

        // Stable prices
        let stable = dec!(2000.00);
        for i in 0..6 {
            let tick = make_tick("XAUUSD", stable, stable + dec!(0.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        // Spike price far above upper band
        let spike = dec!(2200.00);
        let tick = make_tick("XAUUSD", spike, spike + dec!(0.30), 10_000_000_000);
        let snap = make_snapshot(&tick, &id);
        let signal = strategy.on_tick(&snap);

        assert!(signal.is_some());
        let s = signal.unwrap();
        assert_eq!(s.side, Some(Side::Sell));
        assert!(s.strength < 0.0);
    }

    #[test]
    fn reset_clears_state() {
        let config = MeanReversionConfig {
            period: 5,
            std_dev: 2.0,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = MeanReversion::new(config);
        let id = InstrumentId::new("XAUUSD");

        for i in 0..6 {
            let bid = dec!(2000.00);
            let tick = make_tick("XAUUSD", bid, bid + dec!(0.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        strategy.reset();
        assert!(strategy.price_buffers[0].1.is_empty());
        assert!(strategy.position_state[0].is_none());
    }
}
