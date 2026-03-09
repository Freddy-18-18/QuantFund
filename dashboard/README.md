# QuantFund XAUUSD Trading Dashboard

Professional institutional-grade backtesting platform for XAUUSD (Gold) trading strategies.

## Features

### 🎯 Core Capabilities
- **Real-time Data Integration**: Direct PostgreSQL connection to historical XAUUSD M1 data
- **Professional Backtesting**: Tick-level deterministic backtesting with institutional metrics
- **Strategy Management**: Pluggable strategy architecture with configurable parameters
- **Risk Management**: Multi-layer risk controls with position sizing and drawdown limits
- **Performance Analytics**: Comprehensive metrics including Sharpe, Sortino, Calmar ratios

### 📊 Metrics & Analytics
- Total Return & PnL
- Sharpe Ratio & Sortino Ratio
- Maximum Drawdown
- Win Rate & Profit Factor
- Trade Statistics (avg win/loss, largest trades)
- XAUUSD-specific metrics (holding periods, price moves, best/worst hours)

### 🎨 User Interface
- Modern dark theme optimized for trading
- Real-time progress tracking
- Interactive strategy configuration
- Data statistics dashboard
- Export results to JSON

## Technology Stack

### Backend (Rust)
- **Tauri v2**: Desktop application framework
- **tokio-postgres**: Async PostgreSQL client
- **quantfund-engine**: Core trading engine modules
  - `quantfund-core`: Event system and types
  - `quantfund-strategy`: Strategy implementations
  - `quantfund-risk`: Risk management
  - `quantfund-backtest`: Backtesting framework
  - `quantfund-execution`: Order execution simulator

### Frontend (React + TypeScript)
- **React 18**: UI framework
- **TypeScript**: Type-safe development
- **Recharts**: Data visualization
- **Lucide React**: Icon library
- **Vite**: Build tool

## Prerequisites

1. **Rust** (latest stable)
2. **Node.js** (v18+)
3. **PostgreSQL** (v14+) with XAUUSD data loaded
4. **Python 3.11+** (for data pipeline)

## Setup

### 1. Database Setup

Ensure PostgreSQL is running and XAUUSD data is loaded:

```bash
# Run the data download script
python download_histdata.py --start-year 2020 --end-year 2024 --timeframe M1
```

### 2. Install Dependencies

```bash
# Install frontend dependencies
cd dashboard
npm install

# Rust dependencies are managed by Cargo
```

### 3. Development

```bash
# Run in development mode
npm run tauri dev
```

### 4. Build for Production

```bash
# Build optimized production bundle
npm run tauri build
```

## Configuration

### Database Connection

Edit `dashboard/src-tauri/src/database.rs`:

```rust
impl Default for DbConfig {
    fn default() -> Self {
        Self {
            host: "localhost".to_string(),
            port: 5432,
            user: "postgres".to_string(),
            password: "your_password".to_string(),
            dbname: "postgres".to_string(),
        }
    }
}
```

### Strategy Parameters

Strategies can be configured through the UI or programmatically:

```typescript
const config = {
  initial_capital: 100000,
  strategy_type: "sma_crossover",
  strategy_params: {
    fast_period: 20,
    slow_period: 50,
    position_size: 0.1,
  },
  risk_params: {
    max_position_size: 10.0,
    max_leverage: 2.0,
    max_drawdown_pct: 0.2,
  },
};
```

## Available Strategies

### 1. SMA Crossover
Simple Moving Average crossover strategy.

**Parameters:**
- `fast_period`: Fast SMA period (default: 20)
- `slow_period`: Slow SMA period (default: 50)
- `position_size`: Position size as fraction of capital (default: 0.1)

### 2. Mean Reversion (Coming Soon)
Bollinger Bands mean reversion strategy.

**Parameters:**
- `period`: Bollinger Bands period (default: 20)
- `std_dev`: Standard deviation multiplier (default: 2.0)

## Project Structure

```
dashboard/
├── src/                      # Frontend source
│   ├── components/          # React components
│   │   ├── DataManager.tsx  # Database stats viewer
│   │   ├── StrategySelector.tsx
│   │   ├── EquityCurve.tsx
│   │   └── RiskMetrics.tsx
│   ├── XauusdApp.tsx        # Main application
│   ├── XauusdApp.css        # Styles
│   └── main.tsx             # Entry point
├── src-tauri/               # Backend source
│   ├── src/
│   │   ├── main.rs          # Tauri entry point
│   │   ├── commands.rs      # Tauri commands
│   │   ├── database.rs      # PostgreSQL integration
│   │   ├── xauusd_engine.rs # XAUUSD backtesting
│   │   ├── engine.rs        # Legacy engine
│   │   └── state.rs         # Application state
│   ├── Cargo.toml           # Rust dependencies
│   └── tauri.conf.json      # Tauri configuration
└── package.json             # Node dependencies
```

## Performance Targets

- Strategy decision: < 5µs per instrument
- Risk validation: < 10µs
- Event dispatch: < 1µs
- Backtest throughput: > 1M ticks/sec

## Roadmap

- [x] PostgreSQL integration
- [x] XAUUSD data loading
- [x] SMA Crossover strategy
- [x] Professional UI
- [x] Performance metrics
- [ ] Mean Reversion strategy
- [ ] Walk-forward optimization
- [ ] Monte Carlo simulation
- [ ] Live trading integration (MT5)
- [ ] Multi-instrument support
- [ ] Machine learning strategies

## License

UNLICENSED - Proprietary

## Support

For issues or questions, contact the development team.

---

**Built with ❤️ for institutional trading**
