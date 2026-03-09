use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use std::sync::Mutex;

#[allow(dead_code)]
static MT5_CONNECTION: Lazy<Mutex<Option<Mt5Connection>>> = Lazy::new(|| Mutex::new(None));

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Mt5AccountInfo {
    pub login: i64,
    pub server: String,
    pub currency: String,
    pub balance: f64,
    pub equity: f64,
    pub margin: f64,
    pub free_margin: f64,
    pub margin_level: f64,
    pub profit: f64,
    pub leverage: i32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Mt5Position {
    pub ticket: i64,
    pub symbol: String,
    pub volume: f64,
    pub open_price: f64,
    pub current_price: f64,
    pub profit: f64,
    pub side: String,
    pub open_time: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Mt5Order {
    pub ticket: i64,
    pub symbol: String,
    pub volume: f64,
    pub price: f64,
    pub order_type: String,
    pub status: String,
    pub open_time: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Mt5Deal {
    pub ticket: i64,
    pub order: i64,
    pub symbol: String,
    pub volume: f64,
    pub price: f64,
    pub profit: f64,
    pub side: String,
    pub entry: String,
    pub time: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Mt5SymbolInfo {
    pub symbol: String,
    pub bid: f64,
    pub ask: f64,
    pub spread: f64,
    pub digits: i32,
    pub volume_min: f64,
    pub volume_max: f64,
    pub volume_step: f64,
}

#[allow(dead_code)]
pub struct Mt5Connection {
    pub connected: bool,
    pub account_info: Option<Mt5AccountInfo>,
    pub last_update: std::time::Instant,
}

impl Mt5Connection {
    #[allow(dead_code)]
    pub fn new() -> Self {
        Self {
            connected: false,
            account_info: None,
            last_update: std::time::Instant::now(),
        }
    }
}

#[allow(dead_code)]
pub fn get_connection() -> std::sync::MutexGuard<'static, Option<Mt5Connection>> {
    MT5_CONNECTION.lock().unwrap()
}

#[allow(dead_code)]
pub fn set_connection(conn: Mt5Connection) {
    let mut guard = MT5_CONNECTION.lock().unwrap();
    *guard = Some(conn);
}

#[allow(dead_code)]
pub fn clear_connection() {
    let mut guard = MT5_CONNECTION.lock().unwrap();
    *guard = None;
}
