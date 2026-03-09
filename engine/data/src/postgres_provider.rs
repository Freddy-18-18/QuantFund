use std::str::FromStr;
use tokio::runtime::Runtime;
use tokio_postgres::NoTls;
use tracing::{debug, error};

use quantfund_core::event::TickEvent;
use quantfund_core::types::{Price, Timestamp, Volume};
use quantfund_core::InstrumentId;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

use crate::provider::{DataError, TickDataProvider};

/// Provided tick data adapter from OHLCV PostgreSQL tables.
/// Since the historical data in PostgreSQL is stored as OHLCV bars
/// (table `xauusd_ohlcv`), this provider generates 4 pseudo-ticks
/// (Open, High, Low, Close) per bar to simulate tick-level replay.
pub struct PostgresTickProvider {
    config_string: String,
    fixed_spread: Decimal,
}

impl PostgresTickProvider {
    /// Creates a new PostgresTickProvider.
    /// `config_string`: PostgreSQL connection string.
    /// `fixed_spread`: The spread to add to the bid price to generate the ask price.
    pub fn new(config_string: String, fixed_spread: Decimal) -> Self {
        Self {
            config_string,
            fixed_spread,
        }
    }

    /// Helper to block on async code for synchronous trait implementation.
    fn block_on<F: std::future::Future>(&self, f: F) -> F::Output {
        // We create a fresh single-threaded runtime for the query to avoid conflicts.
        let rt = Runtime::new().expect("Failed to create Tokio runtime for Postgres sync");
        rt.block_on(f)
    }
}

impl TickDataProvider for PostgresTickProvider {
    fn load_ticks(
        &self,
        instrument: &InstrumentId,
        from: Timestamp,
        to: Timestamp,
    ) -> Result<Vec<TickEvent>, DataError> {
        self.block_on(async {
            let (client, connection) = tokio_postgres::connect(&self.config_string, NoTls)
                .await
                .map_err(|e| DataError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;

            // Spawn connection handler
            tokio::spawn(async move {
                if let Err(e) = connection.await {
                    error!("PostgreSQL connection error: {}", e);
                }
            });

            // Convert timestamps to chrono::NaiveDateTime for querying
            let from_dt = chrono::DateTime::from_timestamp_millis(from.as_millis() as i64)
                .unwrap_or_default()
                .naive_utc();
            let to_dt = chrono::DateTime::from_timestamp_millis(to.as_millis() as i64)
                .unwrap_or_default()
                .naive_utc();

            let query = "
                SELECT datetime, o::text, h::text, l::text, c::text, v 
                FROM xauusd_ohlcv 
                WHERE symbol = $1 AND datetime >= $2 AND datetime <= $3
                ORDER BY datetime ASC
            ";

            let symbol = instrument.to_string();
            let stmt = client
                .prepare(query)
                .await
                .map_err(|e| DataError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;

            let rows = client
                .query(&stmt, &[&symbol, &from_dt, &to_dt])
                .await
                .map_err(|e| DataError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;

            if rows.is_empty() {
                return Err(DataError::NoData {
                    instrument: symbol,
                });
            }

            let mut ticks = Vec::with_capacity(rows.len() * 4);
            let spread_dec = self.fixed_spread;

            for row in rows {
                let datetime: chrono::NaiveDateTime = row.get(0);
                let o_str: String = row.get(1);
                let h_str: String = row.get(2);
                let l_str: String = row.get(3);
                let c_str: String = row.get(4);
                let v: i64 = row.get(5);

                let open = Decimal::from_str(&o_str).unwrap_or_default();
                let high = Decimal::from_str(&h_str).unwrap_or_default();
                let low = Decimal::from_str(&l_str).unwrap_or_default();
                let close = Decimal::from_str(&c_str).unwrap_or_default();
                let volume_per_tick = Decimal::from(v) / dec!(4.0);

                let base_ts = Timestamp::from_millis(datetime.and_utc().timestamp_millis());
                
                // Helper to create a tick event
                let make_tick = |price: Decimal, offset_ms: u64| TickEvent {
                    timestamp: Timestamp::from_millis(base_ts.as_millis() as i64 + offset_ms as i64),
                    instrument_id: instrument.clone(),
                    bid: Price::new(price),
                    ask: Price::new(price + spread_dec),
                    bid_volume: Volume::new(volume_per_tick),
                    ask_volume: Volume::new(volume_per_tick),
                    spread: spread_dec,
                };

                // Generate OHLC sequence
                ticks.push(make_tick(open, 0));
                
                // Deterministic ordering of High and Low based on bar direction
                if close > open {
                    // Bullish: Low first, then High, then Close
                    ticks.push(make_tick(low, 15000));
                    ticks.push(make_tick(high, 30000));
                } else {
                    // Bearish: High first, then Low, then Close
                    ticks.push(make_tick(high, 15000));
                    ticks.push(make_tick(low, 30000));
                }
                
                ticks.push(make_tick(close, 45000));
            }

            debug!("Loaded {} pseudo-ticks from PostgreSQL", ticks.len());
            Ok(ticks)
        })
    }

    fn available_range(
        &self,
        instrument: &InstrumentId,
    ) -> Result<(Timestamp, Timestamp), DataError> {
        self.block_on(async {
            let (client, connection) = tokio_postgres::connect(&self.config_string, NoTls)
                .await
                .map_err(|e| DataError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;

            tokio::spawn(async move {
                if let Err(e) = connection.await {
                    error!("PostgreSQL connection error: {}", e);
                }
            });

            let query = "
                SELECT MIN(datetime), MAX(datetime)
                FROM xauusd_ohlcv
                WHERE symbol = $1
            ";

            let symbol = instrument.to_string();
            let row = client
                .query_one(query, &[&symbol])
                .await
                .map_err(|e| DataError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;

            let min_dt: Option<chrono::NaiveDateTime> = row.get(0);
            let max_dt: Option<chrono::NaiveDateTime> = row.get(1);

            match (min_dt, max_dt) {
                (Some(min), Some(max)) => {
                    let from = Timestamp::from_millis(min.and_utc().timestamp_millis());
                    let to = Timestamp::from_millis(max.and_utc().timestamp_millis());
                    Ok((from, to))
                }
                _ => Err(DataError::NoData {
                    instrument: symbol,
                }),
            }
        })
    }

    fn instruments(&self) -> Result<Vec<InstrumentId>, DataError> {
        self.block_on(async {
            let (client, connection) = tokio_postgres::connect(&self.config_string, NoTls)
                .await
                .map_err(|e| DataError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;

            tokio::spawn(async move {
                if let Err(e) = connection.await {
                    error!("PostgreSQL connection error: {}", e);
                }
            });

            let query = "SELECT DISTINCT symbol FROM xauusd_ohlcv";

            let rows = client
                .query(query, &[])
                .await
                .map_err(|e| DataError::Io(std::io::Error::new(std::io::ErrorKind::Other, e)))?;

            let instruments = rows
                .into_iter()
                .map(|row| InstrumentId::new(&row.get::<_, String>(0)))
                .collect();

            Ok(instruments)
        })
    }
}
