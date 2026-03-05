use anyhow::Result;
use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

// Verify all crate linkages — importing at least one type from each workspace crate
// proves the workspace compiles and all crates link correctly.
use quantfund_backtest::{BacktestConfig, BacktestResult, BacktestRunner};
use quantfund_core::{Event, OrderId, Price, Side, Timestamp, Volume};
use quantfund_data::{InMemoryProvider, TickReplay};
use quantfund_events::{EventBus, EventBusConfig};
use quantfund_execution::{ExecutionModelConfig, MatchingEngine, OrderManagementSystem};
use quantfund_risk::{RiskConfig, RiskEngine};
use quantfund_strategy::Strategy;

fn main() -> Result<()> {
    init_logging();

    tracing::info!("QuantFund Engine v{}", env!("CARGO_PKG_VERSION"));
    tracing::info!("Initializing institutional trading engine...");

    print_system_info();

    // Prove linkage: instantiate one representative type from each crate.
    // These are zero-cost in release builds (the compiler will optimize them away).
    verify_linkage();

    // TODO: Parse CLI args (run mode: backtest, live, paper)
    // TODO: Load configuration from TOML
    // TODO: Initialize subsystems
    // TODO: Start event loop

    tracing::info!("Engine initialized successfully");
    tracing::info!("Phase 1 skeleton complete - all subsystems ready for integration");

    Ok(())
}

/// Initialize structured logging via `tracing-subscriber`.
///
/// - JSON format for production (`QUANTFUND_LOG_FORMAT=json`).
/// - Pretty (human-readable) format for development (default).
/// - Filter controlled by `RUST_LOG` env var. Default: info globally,
///   debug for all `quantfund_*` crates.
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

/// Log system information useful for debugging and reproducibility.
fn print_system_info() {
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
}

/// Instantiate one type from each workspace crate to prove linkage at compile time.
///
/// In optimized builds the compiler will eliminate all of this as dead code,
/// but it guarantees every crate's public API is reachable from the binary.
fn verify_linkage() {
    // quantfund-core
    let _timestamp = Timestamp::now();
    let _side = Side::Buy;
    let _order_id = OrderId::new();
    let _price = Price::from(1.0);
    let _volume = Volume::from(0.01);
    let _: fn() -> Option<Event> = || None;

    // quantfund-events
    let _bus = EventBus::new(EventBusConfig::default());

    // quantfund-data
    let _provider = InMemoryProvider::new();
    let _replay = TickReplay::from_ticks(vec![]);

    // quantfund-strategy (trait — just reference it)
    let _: Option<&dyn Strategy> = None;

    // quantfund-risk
    let _risk_config = RiskConfig::default();
    let _risk_engine = RiskEngine::new(_risk_config);

    // quantfund-execution
    let _exec_config = ExecutionModelConfig::default();
    let _matching = MatchingEngine::new(_exec_config, 42);
    let _oms = OrderManagementSystem::new();

    // quantfund-backtest
    let _: fn(BacktestConfig, Vec<Box<dyn Strategy>>) -> BacktestRunner = BacktestRunner::new;
    let _: Option<BacktestResult> = None;

    tracing::debug!("all workspace crate linkages verified");
}
