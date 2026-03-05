use quantfund_core::{InstrumentId, Timestamp};
use quantfund_execution::ExecutionModelConfig;
use quantfund_risk::RiskConfig;
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

/// Complete configuration for a backtest run.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BacktestConfig {
    /// Instruments to simulate.
    pub instruments: Vec<InstrumentId>,
    /// Simulation start time.
    pub start_time: Timestamp,
    /// Simulation end time.
    pub end_time: Timestamp,
    /// Initial account balance.
    pub initial_balance: Decimal,
    /// Account leverage.
    pub leverage: Decimal,
    /// Risk configuration.
    pub risk_config: RiskConfig,
    /// Execution model configuration.
    pub execution_config: ExecutionModelConfig,
    /// Random seed for deterministic simulation.
    pub seed: u64,
    /// Commission per lot.
    pub commission_per_lot: Decimal,
}
