use std::fmt;
use std::ops::Deref;

use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

// ─── Timestamp ───────────────────────────────────────────────────────────────

/// Nanoseconds since Unix epoch. The universal time representation across the engine.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct Timestamp(i64);

impl Timestamp {
    /// Current wall-clock time as nanoseconds since epoch.
    pub fn now() -> Self {
        Self(Utc::now().timestamp_nanos_opt().unwrap_or(0))
    }

    pub fn from_nanos(nanos: i64) -> Self {
        Self(nanos)
    }

    pub fn from_millis(millis: i64) -> Self {
        Self(millis * 1_000_000)
    }

    pub fn as_nanos(self) -> i64 {
        self.0
    }

    pub fn as_millis(self) -> i64 {
        self.0 / 1_000_000
    }
}

impl fmt::Display for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let secs = self.0 / 1_000_000_000;
        let nsecs = (self.0 % 1_000_000_000).unsigned_abs() as u32;
        match DateTime::from_timestamp(secs, nsecs) {
            Some(dt) => write!(f, "{}", dt.format("%Y-%m-%dT%H:%M:%S%.9fZ")),
            None => write!(f, "Timestamp({})", self.0),
        }
    }
}

// ─── Price ───────────────────────────────────────────────────────────────────

/// Exact decimal price — wraps `rust_decimal::Decimal` to avoid floating-point errors.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct Price(Decimal);

impl Price {
    pub fn new(value: Decimal) -> Self {
        Self(value)
    }
}

impl From<f64> for Price {
    fn from(value: f64) -> Self {
        Self(Decimal::try_from(value).expect("f64 -> Decimal conversion failed"))
    }
}

impl From<Decimal> for Price {
    fn from(value: Decimal) -> Self {
        Self(value)
    }
}

impl Deref for Price {
    type Target = Decimal;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl fmt::Display for Price {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

// ─── Volume ──────────────────────────────────────────────────────────────────

/// Exact decimal volume (lots / quantity).
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct Volume(Decimal);

impl Volume {
    pub fn new(value: Decimal) -> Self {
        Self(value)
    }
}

impl From<f64> for Volume {
    fn from(value: f64) -> Self {
        Self(Decimal::try_from(value).expect("f64 -> Decimal conversion failed"))
    }
}

impl From<Decimal> for Volume {
    fn from(value: Decimal) -> Self {
        Self(value)
    }
}

impl Deref for Volume {
    type Target = Decimal;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl fmt::Display for Volume {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

// ─── StrategyId ──────────────────────────────────────────────────────────────

/// Identifies a unique strategy instance within the engine.
#[derive(Clone, Debug, Hash, Eq, PartialEq, Serialize, Deserialize)]
pub struct StrategyId(String);

impl StrategyId {
    pub fn new(id: impl Into<String>) -> Self {
        Self(id.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for StrategyId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl From<&str> for StrategyId {
    fn from(s: &str) -> Self {
        Self(s.to_owned())
    }
}

impl From<String> for StrategyId {
    fn from(s: String) -> Self {
        Self(s)
    }
}

// ─── OrderId ─────────────────────────────────────────────────────────────────

/// Globally unique order identifier backed by UUID v4.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct OrderId(Uuid);

impl OrderId {
    /// Generate a new random order id (UUID v4).
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }

    /// Construct an `OrderId` from an existing [`Uuid`].
    /// Used by the MT5 bridge to reconstruct IDs received over the wire.
    pub fn from_uuid(uuid: Uuid) -> Self {
        Self(uuid)
    }

    pub fn as_uuid(&self) -> &Uuid {
        &self.0
    }
}

impl Default for OrderId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for OrderId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

// ─── Side ────────────────────────────────────────────────────────────────────

/// Trade direction.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Side {
    Buy,
    Sell,
}

impl fmt::Display for Side {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Side::Buy => f.write_str("Buy"),
            Side::Sell => f.write_str("Sell"),
        }
    }
}

// ─── Timeframe ───────────────────────────────────────────────────────────────

/// Bar timeframe / periodicity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Timeframe {
    Tick,
    S1,
    M1,
    M5,
    M15,
    M30,
    H1,
    H4,
    D1,
    W1,
    MN1,
}

impl Timeframe {
    /// Duration in seconds, or `None` for `Tick` (aperiodic) and `MN1` (variable length).
    pub fn as_seconds(&self) -> Option<u64> {
        match self {
            Timeframe::Tick => None,
            Timeframe::S1 => Some(1),
            Timeframe::M1 => Some(60),
            Timeframe::M5 => Some(300),
            Timeframe::M15 => Some(900),
            Timeframe::M30 => Some(1_800),
            Timeframe::H1 => Some(3_600),
            Timeframe::H4 => Some(14_400),
            Timeframe::D1 => Some(86_400),
            Timeframe::W1 => Some(604_800),
            Timeframe::MN1 => None,
        }
    }
}

impl fmt::Display for Timeframe {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            Timeframe::Tick => "Tick",
            Timeframe::S1 => "S1",
            Timeframe::M1 => "M1",
            Timeframe::M5 => "M5",
            Timeframe::M15 => "M15",
            Timeframe::M30 => "M30",
            Timeframe::H1 => "H1",
            Timeframe::H4 => "H4",
            Timeframe::D1 => "D1",
            Timeframe::W1 => "W1",
            Timeframe::MN1 => "MN1",
        };
        f.write_str(label)
    }
}
