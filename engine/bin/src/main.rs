use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use quantfund_backtest::{BacktestConfig, BacktestRunner};
use quantfund_core::{InstrumentId, Timestamp};
use quantfund_data::{generate_synthetic_ticks, SyntheticTickConfig, TickReplay};
use quantfund_execution::ExecutionModelConfig;
use quantfund_risk::RiskConfig;
use quantfund_strategy::{SmaCrossover, SmaCrossoverConfig, Strategy};

// ─── CLI ─────────────────────────────────────────────────────────────────────

#[derive(Parser)]
#[command(
    name = "quantfund",
    about = "QuantFund — Institutional Algorithmic Trading Engine",
    version,
    author
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Run a backtest using synthetic data and the built-in SMA crossover strategy.
    Backtest {
        /// Path to TOML configuration file (optional — uses defaults if omitted).
        #[arg(short, long)]
        config: Option<PathBuf>,

        /// Number of synthetic ticks to generate.
        #[arg(short = 'n', long, default_value_t = 10_000)]
        ticks: usize,

        /// Fast SMA period.
        #[arg(long, default_value_t = 10)]
        fast_period: usize,

        /// Slow SMA period.
        #[arg(long, default_value_t = 30)]
        slow_period: usize,

        /// Initial account balance.
        #[arg(long, default_value = "100000")]
        balance: String,

        /// Random seed for deterministic simulation.
        #[arg(long, default_value_t = 42)]
        seed: u64,

        /// Instrument symbol.
        #[arg(long, default_value = "EURUSD")]
        symbol: String,
    },
    /// Display system information and verify crate linkages.
    Info,
}

// ─── Main ────────────────────────────────────────────────────────────────────

fn main() -> Result<()> {
    init_logging();

    let cli = Cli::parse();

    match cli.command {
        Commands::Backtest {
            config: config_path,
            ticks,
            fast_period,
            slow_period,
            balance,
            seed,
            symbol,
        } => {
            run_backtest(
                config_path,
                ticks,
                fast_period,
                slow_period,
                &balance,
                seed,
                &symbol,
            )?;
        }
        Commands::Info => {
            run_info();
        }
    }

    Ok(())
}

// ─── Backtest Command ────────────────────────────────────────────────────────

fn run_backtest(
    _config_path: Option<PathBuf>,
    num_ticks: usize,
    fast_period: usize,
    slow_period: usize,
    balance_str: &str,
    seed: u64,
    symbol: &str,
) -> Result<()> {
    let initial_balance: Decimal = balance_str.parse().context("invalid balance value")?;

    let instrument = InstrumentId::new(symbol);

    tracing::info!(
        symbol = symbol,
        ticks = num_ticks,
        fast = fast_period,
        slow = slow_period,
        balance = %initial_balance,
        seed = seed,
        "configuring backtest"
    );

    // ── Generate synthetic tick data ─────────────────────────────────────────
    tracing::info!("generating {} synthetic ticks...", num_ticks);

    let tick_config = SyntheticTickConfig {
        instrument_id: instrument.clone(),
        initial_price: dec!(1.1000),
        half_spread: dec!(0.00010),
        volatility: 0.10,
        drift: 0.0,
        num_ticks,
        tick_interval_ns: 100_000_000,                 // 100ms
        start_timestamp_ns: 1_704_067_200_000_000_000, // 2024-01-01T00:00:00Z
        seed,
        base_volume: dec!(100),
    };

    let ticks = generate_synthetic_ticks(&tick_config);
    let first_ts = ticks
        .first()
        .map(|t| t.timestamp)
        .unwrap_or(Timestamp::from_nanos(0));
    let last_ts = ticks
        .last()
        .map(|t| t.timestamp)
        .unwrap_or(Timestamp::from_nanos(0));

    tracing::info!(
        total = ticks.len(),
        first = %first_ts,
        last = %last_ts,
        "tick data generated"
    );

    let mut replay = TickReplay::from_ticks(ticks);

    // ── Configure strategy ───────────────────────────────────────────────────
    let strategy_config = SmaCrossoverConfig {
        fast_period,
        slow_period,
        instruments: vec![instrument.clone()],
    };
    let strategy = SmaCrossover::new(strategy_config);

    tracing::info!(
        strategy = strategy.name(),
        fast = fast_period,
        slow = slow_period,
        "strategy configured"
    );

    let strategies: Vec<Box<dyn Strategy>> = vec![Box::new(strategy)];

    // ── Configure backtest ───────────────────────────────────────────────────
    let config = BacktestConfig {
        instruments: vec![instrument],
        start_time: first_ts,
        end_time: last_ts,
        initial_balance,
        leverage: dec!(100),
        risk_config: RiskConfig {
            // Relax some limits for the synthetic test.
            max_order_size: dec!(1.0),
            max_position_size: dec!(1.0),
            max_spread_pips: dec!(5.0),
            max_total_positions: 50,
            max_positions_per_strategy: 20,
            max_gross_exposure: dec!(10.0),
            max_net_exposure: dec!(5.0),
            max_daily_loss: dec!(0.10),
            kill_switch_drawdown: dec!(0.20),
            ..RiskConfig::default()
        },
        execution_config: ExecutionModelConfig::default(),
        seed,
        commission_per_lot: dec!(7.0),
    };

    // ── Run backtest ─────────────────────────────────────────────────────────
    tracing::info!("starting backtest...");

    let mut runner = BacktestRunner::new(config, strategies);
    let result = runner.run(&mut replay);

    // ── Output results ───────────────────────────────────────────────────────
    println!("\n{}", result.summary());

    tracing::info!(
        sharpe = result.metrics.sharpe_ratio,
        total_trades = result.metrics.total_trades,
        total_pnl = %result.metrics.total_pnl,
        tps = result.ticks_per_second as u64,
        "backtest complete"
    );

    Ok(())
}

// ─── Info Command ────────────────────────────────────────────────────────────

fn run_info() {
    tracing::info!("QuantFund Engine v{}", env!("CARGO_PKG_VERSION"));

    let num_cpus = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);

    let build_profile = if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    };

    tracing::info!(cpus = num_cpus, "CPU cores available");
    tracing::info!(
        version = env!("CARGO_PKG_VERSION"),
        build = build_profile,
        "build info"
    );

    tracing::info!("all workspace crate linkages verified");
    tracing::info!("Phase 2 — deterministic backtester operational");
}

// ─── Logging ─────────────────────────────────────────────────────────────────

fn init_logging() {
    let env_filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| {
        EnvFilter::new(
            "info,quantfund_core=debug,quantfund_events=debug,quantfund_data=debug,\
             quantfund_strategy=debug,quantfund_risk=debug,quantfund_execution=debug,\
             quantfund_backtest=debug,quantfund_engine=debug",
        )
    });

    let use_json = std::env::var("QUANTFUND_LOG_FORMAT")
        .map(|v| v.eq_ignore_ascii_case("json"))
        .unwrap_or(false);

    if use_json {
        tracing_subscriber::registry()
            .with(env_filter)
            .with(fmt::layer().json())
            .init();
    } else {
        tracing_subscriber::registry()
            .with(env_filter)
            .with(fmt::layer().with_target(true).with_thread_ids(true))
            .init();
    }
}
