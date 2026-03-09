/// PostgreSQL database connection and data loading for XAUUSD historical data.
use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use quantfund_core::{Price, Timestamp, Volume};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use tokio_postgres::{Client, NoTls};

pub type DbPool = deadpool_postgres::Pool;

/// OHLCV bar from database
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OhlcvBar {
    pub timestamp: Timestamp,
    pub open: Price,
    pub high: Price,
    pub low: Price,
    pub close: Price,
    pub volume: Volume,
}

/// Database configuration
#[derive(Debug, Clone)]
pub struct DbConfig {
    pub host: String,
    pub port: u16,
    pub user: String,
    pub password: String,
    pub dbname: String,
}

impl Default for DbConfig {
    fn default() -> Self {
        Self {
            host: std::env::var("DB_HOST").unwrap_or_else(|_| "localhost".to_string()),
            port: std::env::var("DB_PORT")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(5432),
            user: std::env::var("DB_USER").unwrap_or_else(|_| "postgres".to_string()),
            password: std::env::var("DB_PASSWORD").unwrap_or_else(|_| "1818".to_string()),
            dbname: std::env::var("DB_NAME").unwrap_or_else(|_| "postgres".to_string()),
        }
    }
}

/// Create a reusable connection pool (connections are lazy — no I/O at construction time).
pub fn create_pool(config: &DbConfig) -> Result<DbPool> {
    let mut cfg = deadpool_postgres::Config::new();
    cfg.host = Some(config.host.clone());
    cfg.port = Some(config.port);
    cfg.user = Some(config.user.clone());
    cfg.password = Some(config.password.clone());
    cfg.dbname = Some(config.dbname.clone());

    cfg.create_pool(Some(deadpool_postgres::Runtime::Tokio1), NoTls)
        .context("Failed to create PostgreSQL connection pool")
}

/// Connect to PostgreSQL database
pub async fn connect(config: &DbConfig) -> Result<Client> {
    let conn_str = format!(
        "host={} port={} user={} password={} dbname={}",
        config.host, config.port, config.user, config.password, config.dbname
    );

    let (client, connection) = tokio_postgres::connect(&conn_str, NoTls)
        .await
        .context("Failed to connect to PostgreSQL")?;

    // Spawn connection handler
    tokio::spawn(async move {
        if let Err(e) = connection.await {
            tracing::error!("PostgreSQL connection error: {}", e);
        }
    });

    Ok(client)
}

/// Load XAUUSD OHLCV data from database
pub async fn load_xauusd_data(
    client: &Client,
    symbol: &str,
    timeframe: &str,
    start_date: Option<DateTime<Utc>>,
    end_date: Option<DateTime<Utc>>,
    limit: Option<i64>,
) -> Result<Vec<OhlcvBar>> {
    let mut query = format!(
        "SELECT datetime, o::text, h::text, l::text, c::text, v \
         FROM xauusd_ohlcv \
         WHERE symbol = $1 AND timeframe = $2"
    );

    let mut param_count = 2;
    let mut params: Vec<Box<dyn tokio_postgres::types::ToSql + Sync + Send>> = vec![
        Box::new(symbol.to_string()),
        Box::new(timeframe.to_string()),
    ];

    if let Some(start) = start_date {
        param_count += 1;
        query.push_str(&format!(" AND datetime >= ${}", param_count));
        params.push(Box::new(start.naive_utc()));
    }

    if let Some(end) = end_date {
        param_count += 1;
        query.push_str(&format!(" AND datetime <= ${}", param_count));
        params.push(Box::new(end.naive_utc()));
    }

    query.push_str(" ORDER BY datetime ASC");

    if let Some(lim) = limit {
        param_count += 1;
        query.push_str(&format!(" LIMIT ${}", param_count));
        params.push(Box::new(lim));
    }

    let stmt = client.prepare(&query).await?;
    
    // Convert params to references
    let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = 
        params.iter().map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync)).collect();
    
    let rows = client.query(&stmt, &param_refs).await?;

    let mut bars = Vec::with_capacity(rows.len());

    for row in rows {
        let datetime: chrono::NaiveDateTime = row.get(0);
        let open: Decimal = row.get::<_, String>(1).parse()?;
        let high: Decimal = row.get::<_, String>(2).parse()?;
        let low: Decimal = row.get::<_, String>(3).parse()?;
        let close: Decimal = row.get::<_, String>(4).parse()?;
        let volume: i64 = row.get(5);

        let timestamp = Timestamp::from_millis(datetime.and_utc().timestamp_millis());

        bars.push(OhlcvBar {
            timestamp,
            open: Price::new(open),
            high: Price::new(high),
            low: Price::new(low),
            close: Price::new(close),
            volume: Volume::new(Decimal::from(volume)),
        });
    }

    Ok(bars)
}

/// Get data statistics
pub async fn get_data_stats(
    client: &Client,
    symbol: &str,
    timeframe: &str,
) -> Result<DataStats> {
    let query = "
        SELECT 
            COUNT(*) as total_bars,
            MIN(datetime) as start_date,
            MAX(datetime) as end_date,
            MIN(l)::text as min_price,
            MAX(h)::text as max_price
        FROM xauusd_ohlcv
        WHERE symbol = $1 AND timeframe = $2
    ";

    let row = client
        .query_one(query, &[&symbol, &timeframe])
        .await
        .context("Failed to get data stats")?;

    let total_bars: i64 = row.get(0);
    let start_date: Option<chrono::NaiveDateTime> = row.get(1);
    let end_date: Option<chrono::NaiveDateTime> = row.get(2);
    let min_price: Option<String> = row.get(3);
    let max_price: Option<String> = row.get(4);

    Ok(DataStats {
        total_bars,
        start_date: start_date.map(|d| d.and_utc()),
        end_date: end_date.map(|d| d.and_utc()),
        min_price: min_price.and_then(|s| s.parse().ok()),
        max_price: max_price.and_then(|s| s.parse().ok()),
    })
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataStats {
    pub total_bars: i64,
    pub start_date: Option<DateTime<Utc>>,
    pub end_date: Option<DateTime<Utc>>,
    pub min_price: Option<Decimal>,
    pub max_price: Option<Decimal>,
}
