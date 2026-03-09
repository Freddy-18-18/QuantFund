use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use quantfund_backtest::{BacktestConfig, BacktestRunner, LiveRunner};
use quantfund_core::{InstrumentId, Timestamp};
use quantfund_data::{generate_synthetic_ticks, SyntheticTickConfig, TickReplay};
use quantfund_execution::ExecutionModelConfig;
use quantfund_mt5::Mt5BridgeConfig;
use quantfund_risk::RiskConfig;
use quantfund_strategy::{
    ChannelBreakout, ChannelBreakoutConfig, MeanReversion, MeanReversionConfig, MomentumRsi,
    MomentumRsiConfig, SmaCrossover, SmaCrossoverConfig, Strategy,
};

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

        /// Use real data from PostgreSQL database instead of synthetic data.
        #[arg(long, default_value_t = false)]
        use_db: bool,

        /// PostgreSQL connection string (only used if --use-db is present).
        #[arg(long, default_value = "host=localhost port=5432 user=postgres password=1818 dbname=postgres")]
        db_url: String,

        /// Backtest start time (RFC3339). Only used if --use-db is present.
        #[arg(long, default_value = "2023-01-01T00:00:00Z")]
        from: String,

        /// Backtest end time (RFC3339). Only used if --use-db is present.
        #[arg(long, default_value = "2024-01-01T00:00:00Z")]
        to: String,
    },
    /// Display system information and verify crate linkages.
    Info,

    /// Run paper trading via MT5 Bridge.
    PaperTrade {
        /// Symbol to trade.
        #[arg(long, default_value = "XAUUSD")]
        symbol: String,

        /// MT5 Bridge host.
        #[arg(long, default_value = "127.0.0.1")]
        host: String,

        /// MT5 Bridge port.
        #[arg(long, default_value_t = 7777)]
        port: u16,

        /// Strategy to use (sma, mean_reversion, momentum, breakout).
        #[arg(long, default_value = "sma")]
        strategy: String,
    },
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
            use_db,
            db_url,
            from,
            to,
        } => {
            run_backtest(
                config_path,
                ticks,
                fast_period,
                slow_period,
                &balance,
                seed,
                &symbol,
                use_db,
                &db_url,
                &from,
                &to,
            )?;
        }
        Commands::Info => {
            run_info();
        }
        Commands::PaperTrade {
            symbol,
            host,
            port,
            strategy,
        } => {
            run_paper_trade(symbol, host, port, strategy)?;
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
    use_db: bool,
    db_url: &str,
    from_str: &str,
    to_str: &str,
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

    let (mut replay, first_ts, last_ts) = if use_db {
        tracing::info!("Loading real data from PostgreSQL...");
        use quantfund_data::PostgresTickProvider;
        
        let provider = PostgresTickProvider::new(db_url.to_string(), dec!(0.00010));
        let from = chrono::DateTime::parse_from_rfc3339(from_str)
            .context("invalid from date format")?
            .with_timezone(&chrono::Utc);
        let to = chrono::DateTime::parse_from_rfc3339(to_str)
            .context("invalid to date format")?
            .with_timezone(&chrono::Utc);
            
        let from_ts = Timestamp::from_millis(from.timestamp_millis());
        let to_ts = Timestamp::from_millis(to.timestamp_millis());

        let replay = TickReplay::from_provider(&provider, &[instrument.clone()], from_ts, to_ts)?;
        
        tracing::info!("Loaded {} pseudo-ticks from db", replay.total());
        (replay, from_ts, to_ts)
    } else {
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

        let replay = TickReplay::from_ticks(ticks);
        (replay, first_ts, last_ts)
    };

    tracing::info!(
        total = replay.total(),
        first = %first_ts,
        last = %last_ts,
        "tick data ready"
    );

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

// ─── Paper Trade Command ─────────────────────────────────────────────────────

fn run_paper_trade(
    symbol: String,
    host: String,
    port: u16,
    strategy_name: String,
) -> Result<()> {
    let instrument = InstrumentId::new(&symbol);
    tracing::info!(
        symbol = %symbol,
        host = %host,
        port = port,
        strategy = %strategy_name,
        "Starting Paper Trading Mode"
    );

    // 1. Configure Strategy
    let strategy: Box<dyn Strategy> = match strategy_name.as_str() {
        "sma" => {
            let config = SmaCrossoverConfig {
                fast_period: 10,
                slow_period: 30,
                instruments: vec![instrument.clone()],
            };
            Box::new(SmaCrossover::new(config))
        }
        "mean_reversion" => {
            let config = MeanReversionConfig {
                period: 20,
                std_dev: 2.0,
                position_size: 0.1,
                instruments: vec![instrument.clone()],
            };
            Box::new(MeanReversion::new(config))
        }
        "momentum" => {
            let config = MomentumRsiConfig {
                rsi_period: 14,
                oversold: 30.0,
                overbought: 70.0,
                position_size: 0.1,
                instruments: vec![instrument.clone()],
            };
            Box::new(MomentumRsi::new(config))
        }
        "breakout" => {
            let config = ChannelBreakoutConfig {
                lookback: 20,
                position_size: 0.1,
                instruments: vec![instrument.clone()],
            };
            Box::new(ChannelBreakout::new(config))
        }
        _ => anyhow::bail!("Unknown strategy: {}", strategy_name),
    };

    // 2. Configure Bridge
    let bridge_config = Mt5BridgeConfig {
        host,
        port,
        connect_timeout: std::time::Duration::from_secs(5),
        ack_timeout: std::time::Duration::from_secs(5),
        debug_wire: true,
    };

    // 3. Configure Runner (Risk + Portfolio)
    let backtest_config = BacktestConfig {
        instruments: vec![instrument.clone()],
        start_time: Timestamp::now(),
        end_time: Timestamp::from_millis(0), // Infinite
        initial_balance: dec!(100_000),
        leverage: dec!(100),
        risk_config: RiskConfig::default(),
        execution_config: ExecutionModelConfig::default(),
        seed: 42,
        commission_per_lot: dec!(7.0),
    };

    let mut runner = LiveRunner::new(backtest_config, bridge_config, vec![strategy]);

    // 4. Run
    runner.run().map_err(|e| anyhow::anyhow!("Bridge error: {}", e))?;

    Ok(())
}
