use std::fmt;

use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

use crate::types::{Price, Volume};

// ─── InstrumentId ────────────────────────────────────────────────────────────

/// Canonical identifier for a tradeable instrument (e.g. `"XAUUSD"`, `"EURUSD"`).
#[derive(Clone, Debug, Hash, Eq, PartialEq, Serialize, Deserialize)]
pub struct InstrumentId(String);

impl InstrumentId {
    pub fn new(id: impl Into<String>) -> Self {
        Self(id.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for InstrumentId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl From<&str> for InstrumentId {
    fn from(s: &str) -> Self {
        Self(s.to_owned())
    }
}

impl From<String> for InstrumentId {
    fn from(s: String) -> Self {
        Self(s)
    }
}

// ─── InstrumentSpec ──────────────────────────────────────────────────────────

/// Full specification of a tradeable instrument — tick size, lot constraints, margin, etc.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InstrumentSpec {
    /// Canonical symbol identifier.
    pub id: InstrumentId,
    /// Minimum price increment (e.g. 0.01 for XAUUSD).
    pub tick_size: Price,
    /// Minimum tradeable quantity step (e.g. 0.01 lots).
    pub lot_size: Volume,
    /// Maximum order volume.
    pub max_volume: Volume,
    /// Minimum order volume.
    pub min_volume: Volume,
    /// Dollar value per one point of price movement per lot.
    pub point_value: Decimal,
    /// Margin requirement as a fraction (e.g. 0.05 = 5 %).
    pub margin_rate: Decimal,
    /// Commission charged per lot (one side).
    pub commission_per_lot: Decimal,
}
