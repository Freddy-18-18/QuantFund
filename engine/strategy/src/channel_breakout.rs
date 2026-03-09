//! Donchian Channel Breakout Strategy.
//!
//! Generates a **Buy** signal when price breaks above the highest high of the
//! lookback period (new channel high) and a **Sell** signal when price breaks
//! below the lowest low (new channel low).
//!
//! Classic trend-following strategy — performs well in strong directional markets
//! like XAUUSD during risk-off events or central bank pivots.

use std::collections::VecDeque;

use quantfund_core::types::Side;
use quantfund_core::{InstrumentId, SignalEvent, StrategyId};
use rust_decimal::prelude::ToPrimitive;
use rust_decimal::Decimal;

use crate::traits::{MarketSnapshot, Strategy};

// ─── Config ──────────────────────────────────────────────────────────────────

/// Configuration for the channel breakout strategy.
#[derive(Clone, Debug)]
pub struct ChannelBreakoutConfig {
    /// Number of ticks to look back for the channel high/low.
    pub lookback: usize,
    /// Base position size.
    pub position_size: f64,
    /// Instruments to trade.
    pub instruments: Vec<InstrumentId>,
}

impl Default for ChannelBreakoutConfig {
    fn default() -> Self {
        Self {
            lookback: 20,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        }
    }
}

// ─── Strategy ────────────────────────────────────────────────────────────────

/// Donchian Channel breakout strategy.
pub struct ChannelBreakout {
    id: StrategyId,
    config: ChannelBreakoutConfig,
    /// Rolling high prices per instrument.
    highs: Vec<(InstrumentId, VecDeque<Decimal>)>,
    /// Rolling low prices per instrument.
    lows: Vec<(InstrumentId, VecDeque<Decimal>)>,
    /// Last breakout direction to avoid duplicate signals.
    last_breakout: Vec<Option<Side>>,
}

impl ChannelBreakout {
    pub fn new(config: ChannelBreakoutConfig) -> Self {
        let n = config.instruments.len();
        let cap = config.lookback + 1;

        let highs = config
            .instruments
            .iter()
            .map(|id| (id.clone(), VecDeque::with_capacity(cap)))
            .collect();
        let lows = config
            .instruments
            .iter()
            .map(|id| (id.clone(), VecDeque::with_capacity(cap)))
            .collect();

        Self {
            id: StrategyId::new("channel-breakout"),
            config,
            highs,
            lows,
            last_breakout: vec![None; n],
        }
    }

    fn instrument_index(&self, instrument_id: &InstrumentId) -> Option<usize> {
        self.highs
            .iter()
            .position(|(id, _)| id == instrument_id)
    }
}

impl Strategy for ChannelBreakout {
    fn id(&self) -> &StrategyId {
        &self.id
    }

    fn name(&self) -> &str {
        "Channel Breakout (Donchian)"
    }

    fn instruments(&self) -> &[InstrumentId] {
        &self.config.instruments
    }

    fn on_tick(&mut self, snapshot: &MarketSnapshot) -> Option<SignalEvent> {
        let idx = self.instrument_index(snapshot.instrument_id)?;
        let lookback = self.config.lookback;

        // Use ask as high proxy, bid as low proxy (more realistic than mid)
        let high = *snapshot.tick.ask;
        let low = *snapshot.tick.bid;

        let (_, highs) = &mut self.highs[idx];
        let (_, lows) = &mut self.lows[idx];

        // Compute channel boundaries BEFORE adding current tick
        let channel_high = highs.iter().max().copied();
        let channel_low = lows.iter().min().copied();

        // Maintain rolling buffers
        if highs.len() >= lookback {
            highs.pop_front();
        }
        highs.push_back(high);

        if lows.len() >= lookback {
            lows.pop_front();
        }
        lows.push_back(low);

        // Need full lookback period
        if highs.len() < lookback {
            return None;
        }

        let ch = channel_high?;
        let cl = channel_low?;

        // Breakout detection
        let signal = if high > ch && self.last_breakout[idx] != Some(Side::Buy) {
            // New high → upside breakout → Buy
            self.last_breakout[idx] = Some(Side::Buy);
            let strength = if ch > Decimal::ZERO {
                ((high - ch) / ch).to_f64().unwrap_or(0.1).min(1.0).max(0.05)
            } else {
                0.5
            };
            Some((Side::Buy, strength))
        } else if low < cl && self.last_breakout[idx] != Some(Side::Sell) {
            // New low → downside breakout → Sell
            self.last_breakout[idx] = Some(Side::Sell);
            let strength = if cl > Decimal::ZERO {
                ((cl - low) / cl).to_f64().unwrap_or(0.1).min(1.0).max(0.05)
            } else {
                0.5
            };
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
                "channel_high": ch.to_f64().unwrap_or(0.0),
                "channel_low": cl.to_f64().unwrap_or(0.0),
                "breakout_price": match side {
                    Side::Buy => high.to_f64().unwrap_or(0.0),
                    Side::Sell => low.to_f64().unwrap_or(0.0),
                },
            }),
        })
    }

    fn reset(&mut self) {
        for (_, buf) in &mut self.highs {
            buf.clear();
        }
        for (_, buf) in &mut self.lows {
            buf.clear();
        }
        self.last_breakout.fill(None);
    }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use quantfund_core::{Price, TickEvent, Timestamp, Volume};
    use rust_decimal_macros::dec;

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
    fn no_signal_until_lookback_filled() {
        let config = ChannelBreakoutConfig {
            lookback: 5,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = ChannelBreakout::new(config);
        let id = InstrumentId::new("XAUUSD");

        for i in 0..4 {
            let bid = dec!(2000.00);
            let ask = bid + dec!(0.30);
            let tick = make_tick("XAUUSD", bid, ask, i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            assert!(strategy.on_tick(&snap).is_none());
        }
    }

    #[test]
    fn buy_signal_on_upside_breakout() {
        let config = ChannelBreakoutConfig {
            lookback: 5,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = ChannelBreakout::new(config);
        let id = InstrumentId::new("XAUUSD");

        // Fill channel with stable prices
        for i in 0..6 {
            let bid = dec!(2000.00);
            let ask = bid + dec!(0.30);
            let tick = make_tick("XAUUSD", bid, ask, i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        // Break above channel
        let spike_bid = dec!(2010.00);
        let spike_ask = spike_bid + dec!(0.30);
        let tick = make_tick("XAUUSD", spike_bid, spike_ask, 10_000_000_000);
        let snap = make_snapshot(&tick, &id);
        let signal = strategy.on_tick(&snap);

        assert!(signal.is_some());
        let s = signal.unwrap();
        assert_eq!(s.side, Some(Side::Buy));
        assert!(s.strength > 0.0);
    }

    #[test]
    fn sell_signal_on_downside_breakout() {
        let config = ChannelBreakoutConfig {
            lookback: 5,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = ChannelBreakout::new(config);
        let id = InstrumentId::new("XAUUSD");

        // Fill channel
        for i in 0..6 {
            let bid = dec!(2000.00);
            let ask = bid + dec!(0.30);
            let tick = make_tick("XAUUSD", bid, ask, i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        // Break below channel
        let drop_bid = dec!(1990.00);
        let drop_ask = drop_bid + dec!(0.30);
        let tick = make_tick("XAUUSD", drop_bid, drop_ask, 10_000_000_000);
        let snap = make_snapshot(&tick, &id);
        let signal = strategy.on_tick(&snap);

        assert!(signal.is_some());
        let s = signal.unwrap();
        assert_eq!(s.side, Some(Side::Sell));
        assert!(s.strength < 0.0);
    }

    #[test]
    fn no_duplicate_signals_same_direction() {
        let config = ChannelBreakoutConfig {
            lookback: 5,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = ChannelBreakout::new(config);
        let id = InstrumentId::new("XAUUSD");

        // Fill channel
        for i in 0..6 {
            let bid = dec!(2000.00);
            let ask = bid + dec!(0.30);
            let tick = make_tick("XAUUSD", bid, ask, i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        // First breakout → signal
        let tick = make_tick("XAUUSD", dec!(2010.00), dec!(2010.30), 10_000_000_000);
        let snap = make_snapshot(&tick, &id);
        assert!(strategy.on_tick(&snap).is_some());

        // Second breakout same direction → no duplicate
        let tick = make_tick("XAUUSD", dec!(2015.00), dec!(2015.30), 11_000_000_000);
        let snap = make_snapshot(&tick, &id);
        assert!(strategy.on_tick(&snap).is_none());
    }

    #[test]
    fn reset_clears_state() {
        let config = ChannelBreakoutConfig {
            lookback: 5,
            position_size: 0.1,
            instruments: vec![InstrumentId::new("XAUUSD")],
        };
        let mut strategy = ChannelBreakout::new(config);
        let id = InstrumentId::new("XAUUSD");

        for i in 0..6 {
            let tick = make_tick("XAUUSD", dec!(2000.00), dec!(2000.30), i * 1_000_000_000);
            let snap = make_snapshot(&tick, &id);
            strategy.on_tick(&snap);
        }

        strategy.reset();
        assert!(strategy.highs[0].1.is_empty());
        assert!(strategy.lows[0].1.is_empty());
        assert!(strategy.last_breakout[0].is_none());
    }
}
