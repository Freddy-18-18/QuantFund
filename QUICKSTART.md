# QuantFund XAUUSD - Quick Start Guide

Get up and running with the XAUUSD trading dashboard in 5 minutes.

---

## Prerequisites

Before starting, ensure you have:

- ✅ **Rust** (latest stable) - [Install](https://rustup.rs/)
- ✅ **Node.js** (v18+) - [Install](https://nodejs.org/)
- ✅ **PostgreSQL** (v14+) - [Install](https://www.postgresql.org/download/)
- ✅ **Python 3.11+** - [Install](https://www.python.org/downloads/)

---

## Step 1: Clone & Setup

```bash
# Navigate to project directory
cd QuantFund

# Run setup script
# On Windows:
powershell -ExecutionPolicy Bypass -File setup_dashboard.ps1

# On Linux/Mac:
chmod +x setup_dashboard.sh
./setup_dashboard.sh
```

---

## Step 2: Load XAUUSD Data

### Option A: Download Historical Data (Recommended)

```bash
# Install Python dependencies
pip install pandas psycopg2-binary histdata

# Download XAUUSD M1 data (2020-2024)
python download_histdata.py --start-year 2020 --end-year 2024 --timeframe M1
```

This will:
- Download XAUUSD 1-minute bars from HistData.com
- Verify data quality
- Load into PostgreSQL
- Create necessary indexes

**Expected time:** 10-30 minutes depending on internet speed

### Option B: Use Existing Data

If you already have XAUUSD data in PostgreSQL:

```sql
-- Verify data exists
SELECT COUNT(*), MIN(datetime), MAX(datetime) 
FROM xauusd_ohlcv 
WHERE symbol = 'XAUUSD' AND timeframe = 'M1';
```

---

## Step 3: Configure Database Connection

Edit `dashboard/src-tauri/src/database.rs` if needed:

```rust
impl Default for DbConfig {
    fn default() -> Self {
        Self {
            host: "localhost".to_string(),
            port: 5432,
            user: "postgres".to_string(),
            password: "1818".to_string(),  // Change this!
            dbname: "postgres".to_string(),
        }
    }
}
```

---

## Step 4: Run the Dashboard

```bash
cd dashboard
npm run tauri dev
```

The application will open automatically. You should see:

1. **Data Manager** - Shows XAUUSD data statistics
2. **Strategy Selector** - Configure strategy parameters
3. **Settings Panel** - Adjust risk parameters

---

## Step 5: Run Your First Backtest

1. **Select Strategy**: Choose "SMA Crossover" from dropdown
2. **Configure Parameters**:
   - Fast Period: 20
   - Slow Period: 50
   - Position Size: 0.1
3. **Set Risk Parameters**:
   - Initial Capital: $100,000
   - Max Position Size: 10 lots
   - Max Leverage: 2.0x
   - Max Drawdown: 20%
4. **Click "Run Backtest"**

Watch the progress bar as the backtest runs. Results will display:
- Total Return %
- Sharpe Ratio
- Max Drawdown
- Win Rate
- Profit Factor
- Trade Statistics

---

## Common Issues & Solutions

### Issue: "Database connection failed"

**Solution:**
```bash
# Check PostgreSQL is running
# Windows:
Get-Service postgresql*

# Linux/Mac:
sudo systemctl status postgresql
```

### Issue: "No data available"

**Solution:**
```bash
# Verify data was loaded
psql -U postgres -c "SELECT COUNT(*) FROM xauusd_ohlcv WHERE symbol='XAUUSD';"

# If empty, run data download script again
python download_histdata.py --start-year 2020 --end-year 2024
```

### Issue: "Rust compilation errors"

**Solution:**
```bash
# Update Rust
rustup update

# Clean and rebuild
cd dashboard/src-tauri
cargo clean
cargo build
```

### Issue: "Node modules errors"

**Solution:**
```bash
cd dashboard
rm -rf node_modules package-lock.json
npm install
```

---

## Next Steps

### 1. Explore Strategies

Try different strategy configurations:
- Adjust SMA periods (e.g., 10/30, 50/200)
- Change position sizing
- Test different risk parameters

### 2. Analyze Results

Export results to JSON and analyze:
```typescript
// Click "Export" button in UI
// Results saved as: xauusd_backtest_YYYY-MM-DD.json
```

### 3. Optimize Parameters

Use the research framework for systematic optimization:
```bash
cd research
python -m quantfund.optimization.grid_search
```

### 4. Compare Strategies

Run multiple backtests and compare:
- SMA Crossover vs Mean Reversion
- Different timeframes
- Various risk parameters

---

## Performance Tips

### Speed Up Backtests

1. **Limit Date Range**: Test on smaller periods first
2. **Use Sampling**: Test on every Nth bar for quick validation
3. **Optimize Database**: Ensure indexes are created

### Improve Results

1. **Walk-Forward Testing**: Use out-of-sample validation
2. **Parameter Optimization**: Grid search or genetic algorithms
3. **Risk Management**: Adjust position sizing and stops
4. **Multiple Strategies**: Combine uncorrelated strategies

---

## Development Workflow

### Daily Development

```bash
# 1. Pull latest changes
git pull

# 2. Run dashboard in dev mode
cd dashboard
npm run tauri dev

# 3. Make changes to Rust or TypeScript
# Hot reload will update automatically

# 4. Test changes
cargo test --workspace
```

### Production Build

```bash
cd dashboard
npm run tauri build

# Output: dashboard/src-tauri/target/release/
```

---

## Resources

- **Architecture**: See `ARCHITECTURE.md`
- **Project Status**: See `PROJECT_STATUS.md`
- **Dashboard README**: See `dashboard/README.md`
- **Research Framework**: See `research/README.md`

---

## Support

For issues or questions:

1. Check `PROJECT_STATUS.md` for known issues
2. Review error logs in console
3. Check PostgreSQL logs
4. Verify data integrity

---

## What's Next?

Once you're comfortable with the basics:

1. **Implement Custom Strategies**: Add your own trading logic
2. **Integrate ML Models**: Use Python research framework
3. **Live Trading**: Connect to MT5 for paper trading
4. **Multi-Instrument**: Expand beyond XAUUSD

---

**Happy Trading! 🚀**

*Remember: This is institutional infrastructure, not a retail bot. Trade responsibly.*
