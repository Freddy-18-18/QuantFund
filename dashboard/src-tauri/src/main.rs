// Prevents an additional console window on Windows in release mode.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod api_manager;
mod commands;
mod database;
mod engine;
mod finnhub;
mod fred_analysis;
mod fred_commands;
mod fred_persistence;
mod fred_signals_commands;
mod imf_commands;
mod mt5_connection;
mod state;
mod worldbank_commands;
mod xauusd_engine;

use std::sync::{Arc, Mutex};
use tokio::sync::RwLock;

use api_manager::ApiManagerState;
use fred_commands::FredState;
use fred_signals_commands::FredSignalsState;
use imf_commands::ImfState;
use state::AppState;
use tracing_subscriber::EnvFilter;
use worldbank_commands::WbState;

fn main() {
    // Load environment variables from .env file
    dotenv::dotenv().ok();

    // Initialise logging (RUST_LOG=info by default).
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let app_state = Arc::new(Mutex::new(AppState::default()));

    // Build the DB pool eagerly so commands can use it immediately.
    // create_pool() is synchronous and connections are lazy, so this is safe
    // to call before the Tokio runtime starts.
    let db_config = database::DbConfig::default();
    let pool: Option<database::DbPool> = match database::create_pool(&db_config) {
        Ok(p) => Some(p),
        Err(e) => {
            tracing::warn!("Failed to create PostgreSQL connection pool: {}. Database features will be disabled.", e);
            None
        }
    };

    // Initialize FRED state with API key from environment
    let fred_api_key = std::env::var("FRED_API_KEY").unwrap_or_default();
    let fred_state = Arc::new(RwLock::new(FredState::new(fred_api_key)));

    // Initialize World Bank state (enabled by default)
    let wb_state = Arc::new(RwLock::new(WbState::new()));

    // Initialize API manager state
    let api_manager = Arc::new(RwLock::new(ApiManagerState::new()));

    // Initialize IMF state (empty API key initially)
    let imf_state = Arc::new(RwLock::new(ImfState::new(String::new())));

    // Initialize FRED Signals state
    let fred_signals_state = Arc::new(RwLock::new(FredSignalsState::new()));

    tauri::Builder::default()
        .manage(app_state)
        .manage(pool)
        .manage(fred_state)
        .manage(fred_signals_state)
        .manage(wb_state)
        .manage(api_manager)
        .manage(imf_state)
        .manage(db_config)
        .invoke_handler(tauri::generate_handler![
            // API Manager
            api_manager::api_get_status,
            api_manager::api_set_fred_enabled,
            api_manager::api_set_worldbank_enabled,
            api_manager::api_set_fred_key,
            api_manager::api_get_fred_key,
            commands::get_snapshot,
            commands::start_backtest,
            commands::stop_engine,
            commands::fetch_data_stats,
            commands::start_xauusd_backtest,
            commands::cancel_backtest,
            commands::load_strategies,
            commands::save_strategy_config,
            commands::load_strategy_config,
            commands::mt5_initialize,
            commands::mt5_get_account_info,
            commands::mt5_get_positions,
            commands::mt5_get_orders,
            commands::mt5_get_deals,
            commands::mt5_get_symbols,
            commands::mt5_shutdown,
            commands::mt5_is_initialized,
            commands::mt5_place_order,
            commands::mt5_close_position,
            commands::mt5_modify_position,
            commands::mt5_cancel_order,
            commands::fetch_financial_news,
            commands::analyze_news_with_ai,
            commands::get_market_sentiment,
            commands::get_broker_connections,
            commands::connect_broker,
            commands::disconnect_broker,
            commands::remove_broker,
            commands::sync_broker,
            commands::get_all_positions,
            commands::get_portfolio_summary,
            // Finnhub commands
            commands::finnhub_get_market_news,
            commands::finnhub_get_company_news,
            commands::finnhub_get_economic_calendar,
            commands::finnhub_get_technical_indicator,
            commands::finnhub_get_company_profile,
            commands::finnhub_get_recommendations,
            commands::finnhub_get_social_sentiment,
            commands::finnhub_get_market_status,
            commands::finnhub_get_earnings_calendar,
            commands::finnhub_get_covid_data,
            // FRED commands
            fred_commands::fred_init,
            fred_commands::fred_search_series,
            fred_commands::fred_get_correlation_matrix,
            fred_commands::fred_get_series_analysis,
            fred_commands::fred_get_series,
            fred_commands::fred_get_observations,
            fred_commands::fred_get_releases,
            fred_commands::fred_get_release,
            fred_commands::fred_get_release_series,
            fred_commands::fred_get_categories,
            fred_commands::fred_get_category_children,
            fred_commands::fred_get_category_series,
            fred_commands::fred_get_tags,
            fred_commands::fred_get_tag_series,
            fred_commands::fred_get_related_tags,
            fred_commands::fred_get_series_tags,
            fred_commands::fred_get_sources,
            fred_commands::fred_get_source,
            fred_commands::fred_get_source_releases,
            fred_commands::fred_get_updates,
            fred_commands::fred_get_geo_data,
            fred_commands::fred_get_series_categories,
            fred_commands::fred_get_series_release,
            fred_commands::fred_get_release_dates,
            fred_commands::fred_get_series_vintagedates,
            fred_commands::fred_get_cache_stats,
            fred_commands::fred_clear_cache,
            // FRED Persistence commands
            fred_persistence::fred_persistence_init,
            fred_persistence::fred_save_series,
            fred_persistence::fred_save_observations,
            fred_persistence::fred_get_cached_observations,
            fred_persistence::fred_check_for_updates,
            fred_persistence::fred_sync_series,
            // FRED Signals commands
            fred_signals_commands::fred_signals_init,
            fred_signals_commands::fred_generate_signals,
            fred_signals_commands::fred_get_latest_signals,
            fred_signals_commands::fred_get_signal_history,
            fred_signals_commands::fred_get_signal_by_date,
            fred_signals_commands::fred_get_composite_signal,
            fred_signals_commands::fred_get_signal_breakdown,
            fred_signals_commands::fred_get_signal_strength,
            fred_signals_commands::fred_get_xauusd_signal,
            fred_signals_commands::fred_get_position_recommendation,
            fred_signals_commands::fred_apply_filters,
            fred_signals_commands::fred_get_indicators,
            fred_signals_commands::fred_get_historical_indicators,
            fred_signals_commands::fred_get_indicator_correlations,
            fred_signals_commands::fred_signals_clear_cache,
            fred_signals_commands::fred_signals_get_config,
            fred_signals_commands::fred_signals_update_config,
            // World Bank commands
            worldbank_commands::wb_set_enabled,
            worldbank_commands::wb_get_status,
            worldbank_commands::wb_get_countries,
            worldbank_commands::wb_get_country,
            worldbank_commands::wb_get_indicators,
            worldbank_commands::wb_search_indicators,
            worldbank_commands::wb_get_indicator,
            worldbank_commands::wb_get_indicator_data,
            worldbank_commands::wb_get_indicator_all_countries,
            worldbank_commands::wb_get_topics,
            worldbank_commands::wb_get_topic_indicators,
            worldbank_commands::wb_get_sources,
            // IMF commands
            imf_commands::imf_init,
            imf_commands::imf_list_datasets,
            imf_commands::imf_get_gold_price,
            imf_commands::imf_get_silver_price,
            imf_commands::imf_get_oil_price,
            imf_commands::imf_get_commodity_prices,
            imf_commands::imf_get_ifs_data,
            imf_commands::imf_get_inflation,
            imf_commands::imf_get_interest_rate,
            imf_commands::imf_check_availability,
            imf_commands::imf_get_data,
            imf_commands::imf_cache_clear,
            imf_commands::imf_cache_metrics,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Tauri application");
}
