# FRED Data Pipeline

A comprehensive ETL pipeline for downloading, storing, and updating Federal Reserve Economic Data (FRED) into a PostgreSQL/TimescaleDB database. Built for quantitative analysis and trading strategy development.

## Overview

This pipeline provides automated ingestion and maintenance of FRED economic indicators, which are essential for XAUUSD (gold) and broader financial market analysis. The system includes:

- **Database Schema**: TimescaleDB-powered hypertable for efficient time-series storage
- **Initial Ingestion**: Bulk download of historical data for priority series
- **Incremental Updates**: Daily job to fetch only new observations
- **Connection Testing**: Validation tools for API and database connectivity
- **Rate Limiting**: Respects FRED API limits (120 requests/minute)

## Prerequisites

### Software Requirements

| Requirement | Version | Purpose |
|------------|---------|---------|
| Python | 3.8+ | Runtime environment |
| PostgreSQL | 14+ | Database engine |
| TimescaleDB | 2.10+ | Time-series extension |

### Python Dependencies

```bash
pip install psycopg2-binary requests python-dotenv
```

### FRED API Key

1. Register at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html)
2. Activate your API key (may take up to 30 minutes)

## Quick Start

### 1. Set Environment Variables

```bash
# Database configuration
export FRED_DB_HOST=localhost
export FRED_DB_PORT=5432
export FRED_DB_NAME=freddata
export FRED_DB_USER=postgres
export FRED_DB_PASSWORD=your_password

# FRED API
export FRED_API_KEY=your_api_key_here
```

Or create a `.env` file in the project root:

```bash
FRED_DB_HOST=localhost
FRED_DB_PORT=5432
FRED_DB_NAME=freddata
FRED_DB_USER=postgres
FRED_DB_PASSWORD=your_password
FRED_API_KEY=your_api_key_here
```

### 2. Create Database Schema

```bash
cd research/scripts
python fred_schema.py
```

This creates:
- `fred_series` - Series metadata
- `fred_observations` - Time-series data (TimescaleDB hypertable)
- `fred_tags`, `fred_categories` - Classification system
- `fred_releases` - Data release information
- `fred_anomalies` - Anomaly detection results
- `fred_features` - Derived features

### 3. Test Connections

```bash
python test_fred_connection.py
```

### 4. Initial Data Load

Download historical data for all priority series:

```bash
python ingest_fred_data.py
```

### 5. Schedule Daily Updates

Add to crontab:

```bash
0 6 * * * cd /path/to/QuantFund && python research/scripts/update_fred_data.py >> /var/log/fred_update.log 2>&1
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FRED_DB_HOST` | localhost | PostgreSQL host |
| `FRED_DB_PORT` | 5432 | PostgreSQL port |
| `FRED_DB_NAME` | freddata | Database name |
| `FRED_DB_USER` | postgres | Database user |
| `FRED_DB_PASSWORD` | (empty) | Database password |
| `FRED_API_KEY` | (required) | FRED API key |

### Database Configuration

The database uses TimescaleDB for optimized time-series operations:
- Automatic partitioning by time
- Compression after 2 years
- Retention policy for old data

## Scripts

### fred_schema.py

Creates and manages the database schema using PostgreSQL/TimescaleDB.

**Usage:**
```bash
# Create schema (synchronous)
python fred_schema.py

# Create schema (async)
python fred_schema.py --async
```

**Functions:**
- `FredSchemaManager` - Sync operations using psycopg2
- `FredSchemaManagerAsync` - Async operations using asyncpg
- `create_schema_sync()` - Convenience function for sync mode

### ingest_fred_data.py

Performs initial bulk download of FRED data series.

**Usage:**
```bash
# Download all priority series
python ingest_fred_data.py

# Download specific date range
python ingest_fred_data.py --start-date 2020-01-01 --end-date 2024-12-31

# Download specific series
python ingest_fred_data.py --series GDP,UNRATE,FEDFUNDS

# Dry run (show what would be downloaded)
python ingest_fred_data.py --dry-run

# List available series
python ingest_fred_data.py --list-series

# Override rate limit
python ingest_fred_data.py --rate-limit 60
```

**Features:**
- Resume capability (skips existing data)
- Batch inserts for performance
- Retry logic with exponential backoff
- Progress tracking

### update_fred_data.py

Daily/weekly incremental update script.

**Usage:**
```bash
# Update all series in database
python update_fred_data.py

# Parallel execution (faster)
python update_fred_data.py --parallel

# Specific series
python update_fred_data.py --series GDP,UNRATE

# Verbose logging
python update_fred_data.py --verbose

# Dry run
python update_fred_data.py --dry-run
```

**Features:**
- Only fetches new data since last update
- Parallel execution support
- Detailed logging

### test_fred_connection.py

Validates FRED API and database connectivity.

**Usage:**
```bash
python test_fred_connection.py
```

**Tests:**
- FRED API authentication
- Series metadata retrieval
- Observation downloads
- Database connection
- Search functionality
- Categories and releases

---

## Phase 3: Data Quality & Feature Engineering

This phase adds comprehensive data quality control, cleaning, and feature engineering capabilities for quantitative trading strategies, with special focus on XAUUSD (gold) trading.

### Overview

Phase 3 provides:
- Quality checks (missing values, duplicates, consistency)
- Multi-method outlier detection
- Data imputation
- Feature engineering for ML models
- XAUUSD-specific features

---

### New Scripts

#### clean_fred_data.py

Complete cleaning pipeline combining quality checks, outlier detection, imputation, and feature generation.

**Usage:**
```bash
# Full pipeline - all series
python clean_fred_data.py --all --verbose

# Full pipeline - specific series
python clean_fred_data.py --series GDP,CPIAUCSL --verbose

# Parallel processing
python clean_fred_data.py --all --parallel --workers 8

# Quality checks only
python clean_fred_data.py --series GDP --quality-only

# Outlier detection only
python clean_fred_data.py --series GDP --outliers-only

# Feature generation only
python clean_fred_data.py --series GDP --features-only

# Dry run (preview without saving)
python clean_fred_data.py --all --dry-run

# Save JSON report
python clean_fred_data.py --all --report-path ./report.json
```

**Options:**
| Option | Description |
|--------|-------------|
| `--series` | Process specific series (comma-separated) |
| `--all` | Process all series in database |
| `--quality-only` | Only run quality checks |
| `--outliers-only` | Only detect outliers |
| `--impute-only` | Only run imputation |
| `--features-only` | Only generate features |
| `--parallel` | Enable parallel processing |
| `--workers N` | Number of workers (default: 4) |
| `--verbose` | Detailed logging |
| `--dry-run` | Preview without saving |
| `--report-path` | Path for JSON report |

---

### New Python Modules

#### quantfund.data.fred_quality

Quality control, outlier detection, and data imputation.

**Key Classes:**
- `FredQualityController` - Main controller for quality operations
- `OutlierDetector` - Multi-method outlier detection
- `DataImputer` - Missing value imputation
- `QualityChecker` - Data quality checks
- `FrequencyDetector` - Detect series frequency

**Outlier Detection Methods:**
- Z-Score (threshold: 3.0)
- Median Absolute Deviation (MAD)
- Interquartile Range (IQR)
- Isolation Forest (ML-based)

**Imputation Methods:**
- Linear interpolation
- Forward fill
- Backward fill

**Usage Examples:**

```python
from quantfund.data.fred_quality import (
    FredQualityController,
    OutlierDetector,
    DataImputer,
    DatabaseConnection
)

# Initialize
db = DatabaseConnection("postgresql://localhost/quantfund")
qc = FredQualityController(db)

# Run quality checks
report = qc.generate_quality_report("UNRATE", save_to_db=True)

# Detect outliers
df = qc.get_series_data("UNRATE")
outliers = OutlierDetector.detect_all_outliers(df, "UNRATE")

# Impute missing values
from quantfund.data.fred_quality import FrequencyDetector, DataImputer
freq = FrequencyDetector.detect(df)
result = DataImputer.impute_all(df, freq)
```

---

#### quantfund.data.fred_transform

Time series transformations, rolling statistics, and seasonal decomposition.

**Key Class:**
- `FredTransformer` - Comprehensive time series transformations

**Transformations:**
- Difference (stationarity)
- Percentage change
- Log transform
- Box-Cox transform
- Z-score normalization

**Rolling Statistics:**
- Rolling mean, std, min, max
- Rolling median
- Rolling percentile
- Exponential weighted moving (EWM)

**Seasonal:**
- STL decomposition
- Trend/seasonal/residual extraction
- Seasonal adjustment

**Temporal Features:**
- Month, quarter, year
- Day of week, day of month
- Week of year
- Lag features

**Resampling:**
- Daily, weekly, monthly, quarterly, annual

**Usage Examples:**

```python
from quantfund.data.fred_transform import FredTransformer

transformer = FredTransformer(db_connection="postgresql://localhost/quantfund")

# Get raw data (from client)
df = client.get_observations("UNRATE", "2020-01-01", "2025-01-01")

# Transformations
diff_df = transformer.difference(df, periods=1)
pct_df = transformer.percent_change(df, periods=12)

# Rolling stats
ma_12 = transformer.rolling_mean(df, window=12)
std_20 = transformer.rolling_std(df, window=20)

# Seasonal decomposition
decomposed = transformer.seasonal_decompose(df, period=12)
trend = decomposed["trend"]

# Temporal features
features = transformer.add_time_features(df)
features = transformer.add_lag_features(df, lags=[1, 3, 6, 12])

# Comprehensive features
all_features = transformer.compute_all_features(df)
```

---

#### quantfund.data.fred_features

Advanced feature engineering for quantitative trading.

**Key Classes:**
- `FredFeatureEngine` - Main feature generation engine
- `FeatureConfig` - Configuration for feature generation

**Feature Types:**

1. **Price Features**
   - Returns (lagged)
   - Log returns
   - Cumulative returns

2. **Momentum Features**
   - Rate of change (ROC)
   - Moving average deviation
   - MA slope
   - RSI
   - MACD

3. **Mean Reversion Features**
   - Z-score
   - Bollinger bands (width, position)
   - Distance from extremes

4. **Volatility Features**
   - Realized volatility
   - Volatility ratio
   - Volatility rank

5. **Trend Features**
   - Slope
   - Trend strength
   - Directional ratio

6. **Seasonal Features**
   - Month, quarter, day of week
   - Cyclical encoding (sin/cos)

7. **XAUUSD-Specific Features**
   - Real yield impact (TIPS)
   - Dollar impact (DXY)
   - Inflation hedge (CPI, PPI)
   - Risk-off features (VIX)

**Usage Examples:**

```python
from quantfund.data.fred_features import FredFeatureEngine, FeatureConfig

# Initialize with custom config
config = FeatureConfig(
    window_sizes=[5, 10, 20, 50, 100],
    lags=[1, 2, 3, 5, 10],
    momentum_windows=[5, 10, 20, 50],
    compute_xauusd_features=True
)
engine = FredFeatureEngine(db_connection="postgresql://localhost/quantfund", config=config)

# Generate features for single series
features = engine.compute_all_features("DXY", start_date="2020-01-01", end_date="2024-01-01")

# Process multiple series
results = engine.process_series_list(["DXY", "TIPS10Y", "VIX"], start_date="2020-01-01")

# Parallel processing
results = engine.parallel_process(
    ["DXY", "TIPS10Y", "VIX", "CPIAUCSL"],
    max_workers=4,
    save_to_db=True
)

# Get feature matrix for ML
matrix = engine.get_feature_matrix(
    series_ids=["DXY", "TIPS10Y", "VIX"],
    start_date="2020-01-01",
    end_date="2024-01-01"
)

# Save to feature store
engine.save_to_feature_store("DXY", features)

# Load pre-computed features
loaded = engine.load_features("DXY", start_date="2023-01-01")
```

---

### Usage Examples for Phase 3

#### Run Quality Checks

```python
from quantfund.data.fred_quality import FredQualityController, DatabaseConnection

db = DatabaseConnection("postgresql://localhost/quantfund")
qc = FredQualityController(db)

# Generate quality report
report = qc.generate_quality_report(
    series_id="GDP",
    start_date="2020-01-01",
    save_to_db=True
)

print(f"Valid: {report.data_quality.is_valid}")
print(f"Issues: {report.data_quality.issues_summary}")
print(f"Recommendations: {report.recommendations}")
```

#### Detect Outliers

```python
from quantfund.data.fred_quality import OutlierDetector, DatabaseConnection

db = DatabaseConnection("postgresql://localhost/quantfund")
qc = FredQualityController(db)

df = qc.get_series_data("UNRATE")

# Run all outlier detection methods
outliers = OutlierDetector.detect_all_outliers(df, "UNRATE")

print(f"Consensus outliers: {outliers.consensus_count}")
for outlier in outliers.consensus_outliers[:5]:
    print(f"  {outlier['date']}: {outlier['value']} - {outlier['max_severity']}")
```

#### Generate Features

```python
from quantfund.data.fred_features import FredFeatureEngine

engine = FredFeatureEngine(db_connection="postgresql://localhost/quantfund")

# Generate comprehensive features
features = engine.compute_all_features(
    series_id="DXY",
    start_date="2020-01-01",
    end_date="2024-12-31"
)

print(f"Generated {len(features.columns)} features")
print(f"Feature columns: {features.columns.tolist()[:10]}")
```

#### Complete Pipeline

```python
from quantfund.data.fred_quality import FredQualityController, DatabaseConnection
from quantfund.data.fred_features import FredFeatureEngine

# Initialize
db = DatabaseConnection("postgresql://localhost/quantfund")
qc = FredQualityController(db)
engine = FredFeatureEngine(db_connection="postgresql://localhost/quantfund")

series_list = ["GDP", "UNRATE", "CPIAUCSL", "DXY", "VIX"]

for series_id in series_list:
    # Step 1: Quality check
    report = qc.generate_quality_report(series_id, save_to_db=True)
    
    # Step 2: Generate features
    features = engine.compute_all_features(series_id)
    
    # Step 3: Save features
    if not features.empty:
        engine.save_to_feature_store(series_id, features)
        print(f"Processed {series_id}: {len(features.columns)} features")
```

---

### Feature Types Detail

| Category | Features | Description |
|----------|----------|-------------|
| **Price** | return_*, log_return_*, cumulative_return_* | Returns at various lags and windows |
| **Momentum** | roc_*, ma_deviation_*, rsi_*, macd | Rate of change, MA deviation, RSI, MACD |
| **Mean Reversion** | zscore_*, bollinger_*, position_from_low_* | Z-scores, Bollinger bands, extremes |
| **Volatility** | realized_vol_*, vol_ratio_*, vol_rank_* | Rolling volatility measures |
| **Trend** | slope_*, trend_strength_*, directional_ratio_* | Trend indicators |
| **Seasonal** | month, quarter, month_sin, month_cos | Temporal patterns |
| **XAUUSD** | real_yield_*, dxy_*, vix_*, inflation_* | Gold-specific drivers |

---

### Cron Jobs for Phase 3

```bash
# Daily feature generation (recommended)
0 7 * * * cd /path/to/QuantFund && python research/scripts/clean_fred_data.py --all --features-only --parallel --workers 4 >> /var/log/fred_features.log 2>&1

# Weekly quality check
0 8 * * 0 cd /path/to/QuantFund && python research/scripts/clean_fred_data.py --all --quality-only >> /var/log/fred_quality.log 2>&1

# Monthly outlier detection
0 9 1 * * cd /path/to/QuantFund && python research/scripts/clean_fred_data.py --all --outliers-only >> /var/log/fred_outliers.log 2>&1
```

---

## Phase 4: Anomaly Detection

This phase adds advanced statistical and machine learning anomaly detection for identifying unusual patterns, structural breaks, and outliers in FRED economic data.

### Overview

Phase 4 provides:
- Statistical anomaly detection methods
- ML-based anomaly detection
- Semantic analysis for economic context
- Structural break detection
- Alert generation system

---

### New Scripts

#### detect_fred_anomalies.py

Daily anomaly detection job for automated monitoring.

**Usage:**
```bash
# Run all detectors on all series
python detect_fred_anomalies.py --all

# Run all detectors on specific series
python detect_fred_anomalies.py --series GDP,UNRATE,CPIAUCSL

# Run specific detectors only
python detect_fred_anomalies.py --series GDP --detectors zscore,stl,arima

# Include semantic analysis
python detect_fred_anomalies.py --series GDP --semantic

# Generate alerts for detected anomalies
python detect_fred_anomalies.py --series GDP --alert --alert-threshold high

# Save results to database
python detect_fred_anomalies.py --series GDP --save-to-db

# Quiet mode (less verbose)
python detect_fred_anomalies.py --all --quiet
```

**Options:**
| Option | Description |
|--------|-------------|
| `--series` | Process specific series (comma-separated) |
| `--all` | Process all series in database |
| `--detectors` | Comma-separated detector names |
| `--semantic` | Include semantic analysis |
| `--alert` | Generate alerts for anomalies |
| `--alert-threshold` | Alert threshold: low, medium, high (default: medium) |
| `--save-to-db` | Save results to database |
| `--quiet` | Reduce logging verbosity |

---

### New Python Modules

#### quantfund.data.fred_anomaly

Statistical and ML-based anomaly detection.

**Key Classes:**
- `FredAnomalyController` - Main controller for anomaly operations
- `ZScoreDetector` - Z-score based anomaly detection
- `STLDetector` - Seasonal-Trend decomposition based detection
- `CUSUMDetector` - Cumulative sum detection
- `ChowTestDetector` - Structural break detection
- `ARIMADetector` - ARIMA-based anomaly detection
- `IsolationForestDetector` - ML-based Isolation Forest
- `AutoencoderDetector` - Deep learning autoencoder
- `OneClassSVMDetector` - One-Class SVM anomaly detection
- `MultivariatePCADetector` - Multivariate PCA detection

**Statistical Detectors:**

| Detector | Description | Best For |
|----------|-------------|----------|
| `zscore` | Standard deviation from mean | Point anomalies |
| `stl` | STL decomposition residuals | Seasonal data |
| `cusum` | Cumulative sum detection | Drift detection |
| `chow` | Structural break test | Regime changes |
| `arima` | ARIMA forecast errors | Time series forecasts |

**ML Detectors:**

| Detector | Description | Best For |
|----------|-------------|----------|
| `isolation_forest` | Tree-based isolation | Multivariate outliers |
| `autoencoder` | Neural network reconstruction | Complex patterns |
| `one_class_svm` | Kernel-based boundary | High-dimensional |
| `multivariate_pca` | PCA reconstruction error | Correlated features |

**Usage Examples:**

```python
from quantfund.data.fred_anomaly import (
    FredAnomalyController,
    ZScoreDetector,
    STLDetector,
    IsolationForestDetector,
    DatabaseConnection
)

# Initialize
db = DatabaseConnection("postgresql://localhost/quantfund")
controller = FredAnomalyController(db)

# Z-Score detection
df = controller.get_series_data("UNRATE")
zscore_anomalies = ZScoreDetector.detect(
    df, 
    threshold=3.0,
    min_periods=30
)

# STL decomposition detection
stl_anomalies = STLDetector.detect(
    df,
    period=12,
    robust=True
)

# Isolation Forest
iso_anomalies = IsolationForestDetector.detect(
    df,
    contamination=0.05,
    n_estimators=100
)

# Run all detectors
all_results = controller.run_all_detectors("UNRATE")

# Get consensus anomalies
consensus = controller.get_consensus_anomalies("UNRATE", min_detectors=2)

# Save to database
controller.save_anomalies("UNRATE", all_results)
```

---

#### quantfund.data.fred_semantic_anomaly

Semantic analysis for economic context and interpretation.

**Key Classes:**
- `FredSemanticAnalyzer` - Main semantic analysis engine
- `EconomicContextAnalyzer` - Analyze economic context
- `AnomalyInterpreter` - Interpret detected anomalies
- `SemanticFeatureExtractor` - Extract semantic features

**Features:**
- Economic regime detection
- Seasonality analysis
- Trend analysis
- Volatility analysis
- Correlation analysis

**Usage Examples:**

```python
from quantfund.data.fred_semantic_anomaly import (
    FredSemanticAnalyzer,
    EconomicContextAnalyzer,
    AnomalyInterpreter
)

# Initialize
analyzer = FredSemanticAnalyzer(db_connection="postgresql://localhost/quantfund")

# Get economic context
context = analyzer.get_economic_context("UNRATE", "2024-01-01")

# Analyze semantic features
semantic_features = analyzer.extract_semantic_features("GDP")

# Interpret anomaly
interpreter = AnomalyInterpreter(db)
interpretation = interpreter.interpret(
    series_id="UNRATE",
    anomaly_date="2024-03-01",
    anomaly_value=3.9,
    detector_methods=["zscore", "stl"]
)

print(f"Interpretation: {interpretation.summary}")
print(f"Severity: {interpretation.severity}")
print(f"Economic Context: {interpretation.economic_context}")

# Combined analysis
combined = analyzer.analyze_with_semantics(
    series_id="GDP",
    start_date="2020-01-01",
    detectors=["zscore", "isolation_forest"],
    include_semantic=True
)
```

---

### Usage Examples for Phase 4

#### Run All Detectors

```python
from quantfund.data.fred_anomaly import FredAnomalyController

controller = FredAnomalyController(db_connection="postgresql://localhost/quantfund")

# Run all statistical and ML detectors
results = controller.run_all_detectors("GDP")

print(f"Total anomalies found: {len(results)}")
for result in results:
    print(f"  {result['date']}: {result['method']} - score: {result['score']:.3f}")
```

#### Run Specific Detectors

```python
from quantfund.data.fred_anomaly import (
    ZScoreDetector,
    STLDetector,
    ChowTestDetector,
    IsolationForestDetector
)

df = controller.get_series_data("UNRATE")

# Statistical methods
zscore_results = ZScoreDetector.detect(df, threshold=3.0)
stl_results = STLDetector.detect(df, period=12, robust=True)
chow_results = ChowTestDetector.detect(df, breakpoint_ratio=0.5)

# ML methods
iso_results = IsolationForestDetector.detect(df, contamination=0.05)

# Combine results
all_anomalies = {
    "zscore": zscore_results,
    "stl": stl_results,
    "chow": chow_results,
    "isolation_forest": iso_results
}
```

#### Include Semantic Analysis

```python
from quantfund.data.fred_anomaly import FredAnomalyController
from quantfund.data.fred_semantic_anomaly import FredSemanticAnalyzer

# Get anomaly results
controller = FredAnomalyController(db_connection="postgresql://localhost/quantfund")
anomalies = controller.run_all_detectors("CPIAUCSL")

# Add semantic context
analyzer = FredSemanticAnalyzer(db_connection="postgresql://localhost/quantfund")
semantic_context = analyzer.get_economic_context("CPIAUCSL", "2024-06-01")

# Interpret each anomaly
for anomaly in anomalies:
    interpretation = analyzer.interpret_anomaly(
        series_id="CPIAUCSL",
        date=anomaly["date"],
        value=anomaly["value"],
        method=anomaly["method"]
    )
    anomaly["interpretation"] = interpretation
    anomaly["economic_context"] = semantic_context
```

#### Generate Alerts

```python
from quantfund.data.fred_anomaly import FredAnomalyController, AnomalyAlerter

controller = FredAnomalyController(db_connection="postgresql://localhost/quantfund")

# Run detection
anomalies = controller.run_all_detectors("GDP", min_detectors=2)

# Create alerter
alerter = AnomalyAlerter(
    smtp_host="smtp.example.com",
    smtp_port=587,
    from_addr="alerts@example.com",
    to_addrs=["trader@example.com"]
)

# Generate alerts for high-severity anomalies
high_severity = [a for a in anomalies if a.get("severity") == "high"]

if high_severity:
    alert = alerter.generate_alert(
        series_id="GDP",
        anomalies=high_severity,
        threshold="high"
    )
    alerter.send_alert(alert)
```

---

### Detector Configuration

```python
from quantfund.data.fred_anomaly import (
    ZScoreDetector,
    STLDetector,
    CUSUMDetector,
    IsolationForestDetector,
    AutoencoderDetector
)

# Z-Score configuration
ZScoreDetector.CONFIG = {
    "threshold": 3.0,
    "min_periods": 30,
    "rolling": True,
    "rolling_window": 60
}

# STL configuration
STLDetector.CONFIG = {
    "period": 12,
    "robust": True,
    "seasonal_deg": 1,
    "trend_deg": 1
}

# CUSUM configuration
CUSUMDetector.CONFIG = {
    "threshold": 5.0,
    "drift": 0.5,
    "detection_mode": "both"  # up, down, both
}

# Isolation Forest configuration
IsolationForestDetector.CONFIG = {
    "contamination": 0.05,
    "n_estimators": 100,
    "max_samples": "auto",
    "random_state": 42
}

# Autoencoder configuration
AutoencoderDetector.CONFIG = {
    "encoding_dim": 8,
    "epochs": 50,
    "batch_size": 32,
    "threshold": 0.95
}
```

---

### Cron Jobs for Phase 4

```bash
# Daily anomaly detection (recommended)
0 7 * * * cd /path/to/QuantFund && python research/scripts/detect_fred_anomalies.py --all --save-to-db >> /var/log/fred_anomalies.log 2>&1

# Daily with alerts
0 7 * * * cd /path/to/QuantFund && python research/scripts/detect_fred_anomalies.py --all --alert --alert-threshold high --save-to-db >> /var/log/fred_alerts.log 2>&1

# Weekly with semantic analysis
0 8 * * 0 cd /path/to/QuantFund && python research/scripts/detect_fred_anomalies.py --all --semantic --save-to-db >> /var/log/fred_semantic.log 2>&1
```

---

## Phase 5: Signal Generation & Backtesting

This phase adds comprehensive signal generation, strategy development, and backtesting capabilities for quantitative trading based on FRED macroeconomic data.

### Overview

Phase 5 provides:
- Macro fundamental signal generation
- Cointegration and pairs trading signals
- ML-based predictive signals
- Signal storage and retrieval system
- Walk-forward backtesting framework

---

### New Scripts

#### generate_signals.py

Complete signal generation pipeline for all signal types.

**Usage:**
```bash
# Generate all signals
python generate_signals.py --all

# Generate specific signal types
python generate_signals.py --signals interest_rate,money_supply

# Generate specific signals with date range
python generate_signals.py --signals inflation,employment --start-date 2020-01-01 --end-date 2024-12-31

# Parallel processing
python generate_signals.py --all --parallel --workers 8

# Save to database
python generate_signals.py --all --save-to-db

# Generate ML signals only
python generate_signals.py --signals ml --models xgboost,random_forest

# Quiet mode
python generate_signals.py --all --quiet
```

**Options:**
| Option | Description |
|--------|-------------|
| `--signals` | Signal types: interest_rate, money_supply, inflation, employment, market, cointegration, ml, var (comma-separated) |
| `--all` | Generate all signal types |
| `--start-date` | Start date (YYYY-MM-DD) |
| `--end-date` | End date (YYYY-MM-DD) |
| `--parallel` | Enable parallel processing |
| `--workers N` | Number of workers (default: 4) |
| `--save-to-db` | Save signals to database |
| `--quiet` | Reduce logging verbosity |

---

### New Python Modules

#### quantfund.strategies.fred_signals

Macro fundamental signal generation from FRED data.

**Key Classes:**
- `FredSignalGenerator` - Main signal generation controller
- `InterestRateSignals` - Interest rate related signals
- `MoneySupplySignals` - Money supply M1, M2 signals
- `InflationSignals` - CPI, PCE inflation signals
- `EmploymentSignals` - Unemployment, payrolls signals
- `MarketSignals` - VIX, dollar, risk-off signals

**Signal Types:**

1. **Interest Rate Signals**
   - Real yield (TIPS - nominal)
   - Fed funds rate changes
   - Yield curve slope (10Y - 2Y)
   - Yield curve steepness changes

2. **Money Supply Signals**
   - M2 month-over-month growth
   - M2 year-over-year growth
   - M2 velocity changes
   - Money supply acceleration

3. **Inflation Signals**
   - CPI month-over-month
   - CPI year-over-year
   - PCE month-over-month
   - Real inflation vs expected

4. **Employment Signals**
   - Unemployment rate changes
   - Nonfarm payrolls changes
   - Labor force participation
   - Employment situation score

5. **Market Signals**
   - VIX levels and changes
   - Dollar index (DXY)
   - Risk-off indicator
   - Flight to safety

**Usage Examples:**

```python
from quantfund.strategies.fred_signals import (
    FredSignalGenerator,
    InterestRateSignals,
    MoneySupplySignals,
    InflationSignals,
    EmploymentSignals,
    MarketSignals
)

# Initialize
generator = FredSignalGenerator(db_connection="postgresql://localhost/quantfund")

# Generate all macro signals
signals = generator.generate_all_signals(
    start_date="2020-01-01",
    end_date="2024-12-31"
)

# Generate specific signal type
ir_signals = InterestRateSignals.generate(
    start_date="2020-01-01",
    end_date="2024-12-31"
)

# Generate money supply signals
ms_signals = MoneySupplySignals.generate(
    start_date="2020-01-01",
    end_date="2024-12-31"
)

# Generate inflation signals
inf_signals = InflationSignals.generate(
    start_date="2020-01-01",
    end_date="2024-12-31"
)

# Generate employment signals
emp_signals = EmploymentSignals.generate(
    start_date="2020-01-01",
    end_date="2024-12-31"
)

# Generate market signals
mkt_signals = MarketSignals.generate(
    start_date="2020-01-01",
    end_date="2024-12-31"
)
```

---

#### quantfund.strategies.fred_cointegration

Cointegration analysis and pairs trading signal generation.

**Key Classes:**
- `CointegrationAnalyzer` - Cointegration testing and analysis
- `PairsTradingSignals` - Pairs trading signal generation
- `EngleGrangerTest` - Engle-Granger cointegration test
- `JohansenTest` - Johansen cointegration test
- `HalfLifeCalculator` - Mean reversion half-life

**Features:**
- Engle-Granger two-step cointegration test
- Johansen trace and eigenvalue tests
- CADF test for cointegration
- Half-life of mean reversion
- Pairs selection and ranking
- Spread/beta calculation
- Z-score spread signals

**Usage Examples:**

```python
from quantfund.strategies.fred_cointegration import (
    CointegrationAnalyzer,
    PairsTradingSignals,
    EngleGrangerTest,
    JohansenTest,
    HalfLifeCalculator
)

# Initialize
analyzer = CointegrationAnalyzer(db_connection="postgresql://localhost/quantfund")

# Test cointegration between two series
result = EngleGrangerTest.test(
    series1="DGS10",
    series2="DGS2",
    start_date="2020-01-01",
    end_date="2024-12-31"
)
print(f"Cointegrated: {result.is_cointegrated}")
print(f"P-value: {result.p_value}")
print(f"Beta: {result.beta}")

# Johansen test for multiple series
johansen_result = JohansenTest.test(
    series_list=["DGS10", "DGS2", "FEDFUNDS"],
    start_date="2020-01-01",
    end_date="2024-12-31"
)
print(f"Cointegrating vectors: {johansen_result.r}")

# Calculate half-life
hl = HalfLifeCalculator.calculate(spread_series)
print(f"Half-life: {hl} days")

# Generate pairs trading signals
pairs_signals = PairsTradingSignals.generate(
    pairs=[
        ("DGS10", "DGS2"),
        ("CPIAUCSL", "PCEPI"),
        ("UNRATE", "PAYEMS")
    ],
    start_date="2020-01-01",
    end_date="2024-12-31",
    zscore_threshold=2.0
)

# Get all cointegrated pairs
cointegrated_pairs = analyzer.find_cointegrated_pairs(
    series_list=["DGS10", "DGS2", "DGS30", "FEDFUNDS", "CPIAUCSL", "PCEPI"],
    start_date="2020-01-01",
    end_date="2024-12-31",
    significance_level=0.05
)
```

---

#### quantfund.strategies.fred_ml_signals

Machine learning based predictive signals.

**Key Classes:**
- `MLSignalGenerator` - Main ML signal generation
- `XGBoostSignals` - XGBoost model signals
- `RandomForestSignals` - Random Forest signals
- `LSTMSignals` - LSTM neural network signals
- `FeatureSelector` - Feature selection for ML
- `ModelTrainer` - Model training utilities

**Features:**
- XGBoost classification/regression
- Random Forest models
- LSTM sequential models
- Feature importance analysis
- Multi-horizon predictions
- Probability forecasts

**Usage Examples:**

```python
from quantfund.strategies.fred_ml_signals import (
    MLSignalGenerator,
    XGBoostSignals,
    RandomForestSignals,
    LSTMSignals,
    ModelTrainer
)

# Initialize
ml_generator = MLSignalGenerator(db_connection="postgresql://localhost/quantfund")

# Generate XGBoost signals
xgb_signals = XGBoostSignals.generate(
    target="XAUUSD",
    features=["DGS10", "DXY", "VIX", "CPIAUCSL"],
    start_date="2020-01-01",
    end_date="2024-12-31",
    horizon=5,
    n_estimators=100,
    max_depth=5
)

# Generate Random Forest signals
rf_signals = RandomForestSignals.generate(
    target="XAUUSD",
    features=["DGS10", "DXY", "VIX", "UNRATE", "M2SL"],
    start_date="2020-01-01",
    end_date="2024-12-31",
    horizon=5,
    n_estimators=100
)

# Generate LSTM signals
lstm_signals = LSTMSignals.generate(
    target="XAUUSD",
    features=["DGS10", "DXY", "VIX"],
    start_date="2020-01-01",
    end_date="2024-12-31",
    lookback=20,
    horizon=5,
    lstm_units=50,
    epochs=50
)

# Generate all ML signals
all_ml_signals = ml_generator.generate_all(
    target="XAUUSD",
    start_date="2020-01-01",
    end_date="2024-12-31"
)
```

---

#### quantfund.strategies.signal_store

Signal storage and retrieval system.

**Key Classes:**
- `SignalStore` - Main signal storage manager
- `SignalDatabase` - Database operations for signals
- `SignalCache` - In-memory caching
- `SignalValidator` - Signal validation

**Features:**
- Store signals in database
- Retrieve by date range
- Filter by signal type
- Signal versioning
- Cache management
- Export to CSV/JSON

**Usage Examples:**

```python
from quantfund.strategies.signal_store import (
    SignalStore,
    SignalDatabase,
    SignalCache,
    SignalValidator
)

# Initialize
store = SignalStore(db_connection="postgresql://localhost/quantfund")

# Save signals
store.save_signals(
    signals_df,
    signal_type="interest_rate",
    metadata={"source": "fred_signals", "version": "1.0"}
)

# Retrieve signals
signals = store.get_signals(
    signal_type="interest_rate",
    start_date="2024-01-01",
    end_date="2024-12-31"
)

# Get latest signals
latest = store.get_latest_signals(
    signal_type="inflation",
    n=10
)

# Validate signals
validator = SignalValidator()
is_valid = validator.validate(signals_df)

# Export signals
store.export_to_csv("signals.csv", signal_type="all")
store.export_to_json("signals.json", signal_type="ml")
```

---

#### quantfund.strategies.signal_backtest

Backtesting framework for signal strategies.

**Key Classes:**
- `SignalBacktester` - Main backtesting engine
- `WalkForwardAnalysis` - Walk-forward validation
- `PerformanceMetrics` - Performance calculation
- `SignalQualityAnalyzer` - Signal quality metrics

**Features:**
- Walk-forward analysis
- Rolling window backtests
- Performance metrics (Sharpe, Sortino, max drawdown)
- Signal quality analysis
- Transaction cost modeling
- Position sizing

**Backtest Metrics:**

| Metric | Description |
|--------|-------------|
| Total Return | Cumulative return |
| Annualized Return | CAGR |
| Sharpe Ratio | Risk-adjusted return |
| Sortino Ratio | Downside risk-adjusted |
| Max Drawdown | Maximum peak-to-trough |
| Win Rate | Percentage of profitable trades |
| Profit Factor | Gross profit / gross loss |
| Calmar Ratio | Return / max drawdown |

**Usage Examples:**

```python
from quantfund.strategies.signal_backtest import (
    SignalBacktester,
    WalkForwardAnalysis,
    PerformanceMetrics,
    SignalQualityAnalyzer
)

# Initialize
backtester = SignalBacktester(db_connection="postgresql://localhost/quantfund")

# Run backtest
results = backtester.run_backtest(
    signals=signals_df,
    prices=prices_df,
    initial_capital=100000,
    position_size=0.1,
    transaction_costs=0.001
)

print(f"Total Return: {results.total_return:.2%}")
print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
print(f"Max Drawdown: {results.max_drawdown:.2%}")
print(f"Win Rate: {results.win_rate:.2%}")

# Walk-forward analysis
wf_analysis = WalkForwardAnalysis.run(
    signals=signals_df,
    prices=prices_df,
    train_window=252,  # 1 year
    test_window=63,    # 3 months
    step_size=21       # 1 month
)

for fold in wf_analysis.folds:
    print(f"Train: {fold.train_start} - {fold.train_end}")
    print(f"Test: {fold.test_start} - {fold.test_end}")
    print(f"Test Return: {fold.test_return:.2%}")

# Performance metrics
metrics = PerformanceMetrics.calculate(
    returns=returns_series,
    benchmark_returns=benchmark_series
)

print(f"CAGR: {metrics.cagr:.2%}")
print(f"Sharpe: {metrics.sharpe:.2f}")
print(f"Sortino: {metrics.sortino:.2f}")
print(f"Max Drawdown: {metrics.max_drawdown:.2%}")
print(f"Calmar: {metrics.calmar:.2f}")

# Signal quality analysis
quality = SignalQualityAnalyzer.analyze(
    signals=signals_df,
    returns=returns_series
)

print(f"Signal Edge: {quality.signal_edge:.4f}")
print(f"IC (Information Coefficient): {quality.ic:.4f}")
print(f"Rank IC: {quality.rank_ic:.4f}")
print(f"Turnover: {quality.turnover:.2%}")
```

---

### Usage Examples for Phase 5

#### Generate All Signals

```python
from quantfund.strategies.fred_signals import FredSignalGenerator
from quantfund.strategies.signal_store import SignalStore

# Initialize
generator = FredSignalGenerator(db_connection="postgresql://localhost/quantfund")
store = SignalStore(db_connection="postgresql://localhost/quantfund")

# Generate all macro signals
print("Generating interest rate signals...")
ir_signals = generator.generate_interest_rate_signals(
    start_date="2020-01-01",
    end_date="2024-12-31"
)
store.save_signals(ir_signals, signal_type="interest_rate")

print("Generating money supply signals...")
ms_signals = generator.generate_money_supply_signals(
    start_date="2020-01-01",
    end_date="2024-12-31"
)
store.save_signals(ms_signals, signal_type="money_supply")

print("Generating inflation signals...")
inf_signals = generator.generate_inflation_signals(
    start_date="2020-01-01",
    end_date="2024-12-31"
)
store.save_signals(inf_signals, signal_type="inflation")

print("Generating employment signals...")
emp_signals = generator.generate_employment_signals(
    start_date="2020-01-01",
    end_date="2024-12-31"
)
store.save_signals(emp_signals, signal_type="employment")

print("Generating market signals...")
mkt_signals = generator.generate_market_signals(
    start_date="2020-01-01",
    end_date="2024-12-31"
)
store.save_signals(mkt_signals, signal_type="market")

print("All signals generated and saved!")
```

#### Generate Specific Signal Types

```python
from quantfund.strategies.fred_signals import InterestRateSignals
from quantfund.strategies.fred_cointegration import PairsTradingSignals
from quantfund.strategies.fred_ml_signals import XGBoostSignals

# Interest rate signals only
ir = InterestRateSignals.generate(
    start_date="2023-01-01",
    end_date="2024-12-31"
)

# Cointegration pairs
pairs = PairsTradingSignals.generate(
    pairs=[("DGS10", "DGS2"), ("CPIAUCSL", "PCEPI")],
    start_date="2023-01-01",
    end_date="2024-12-31"
)

# ML signals
xgb = XGBoostSignals.generate(
    target="XAUUSD",
    features=["DGS10", "DXY", "VIX", "M2SL"],
    start_date="2023-01-01",
    end_date="2024-12-31"
)
```

#### Run Backtests

```python
from quantfund.strategies.fred_signals import FredSignalGenerator
from quantfund.strategies.signal_backtest import (
    SignalBacktester,
    WalkForwardAnalysis,
    PerformanceMetrics
)

# Get signals
generator = FredSignalGenerator(db_connection="postgresql://localhost/quantfund")
signals = generator.generate_all_signals(start_date="2020-01-01", end_date="2024-12-31")

# Get price data
prices = get_price_data("XAUUSD", "2020-01-01", "2024-12-31")

# Simple backtest
backtester = SignalBacktester(db_connection="postgresql://localhost/quantfund")
results = backtester.run_backtest(
    signals=signals,
    prices=prices,
    initial_capital=100000,
    position_size=0.1
)

print("=== Backtest Results ===")
print(f"Total Return: {results.total_return:.2%}")
print(f"Annual Return: {results.annual_return:.2%}")
print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
print(f"Sortino Ratio: {results.sortino_ratio:.2f}")
print(f"Max Drawdown: {results.max_drawdown:.2%}")
print(f"Win Rate: {results.win_rate:.2%}")

# Walk-forward analysis
wf = WalkForwardAnalysis.run(
    signals=signals,
    prices=prices,
    train_window=252,
    test_window=63,
    step_size=21
)

print("\n=== Walk-Forward Results ===")
for i, fold in enumerate(wf.folds):
    print(f"Fold {i+1}: Train={fold.train_start.date()}-{fold.train_end.date()}, "
          f"Test={fold.test_start.date()}-{fold.test_end.date()}, "
          f"Return={fold.test_return:.2%}")
```

#### Save to Database

```python
from quantfund.strategies.signal_store import SignalStore

store = SignalStore(db_connection="postgresql://localhost/quantfund")

# Save with metadata
store.save_signals(
    signals_df=signals,
    signal_type="interest_rate",
    metadata={
        "source": "fred_signals",
        "version": "1.0",
        "generated_at": "2024-12-31T12:00:00"
    }
)

# Verify saved signals
saved = store.get_signals(
    signal_type="interest_rate",
    start_date="2024-01-01",
    end_date="2024-12-31"
)
print(f"Saved {len(saved)} signal records")
```

---

### Backtesting Features

#### Walk-Forward Analysis

```python
from quantfund.strategies.signal_backtest import WalkForwardAnalysis

wf = WalkForwardAnalysis.run(
    signals=signals_df,
    prices=prices_df,
    train_window=252,      # 1 year training
    test_window=63,        # 3 months testing
    step_size=21,          # 1 month rolling
    rebalance_frequency="monthly"
)

# Get all fold results
results_df = wf.get_results_dataframe()
print(results_df)

# Get average metrics
avg_sharpe = wf.average_metric("sharpe_ratio")
avg_return = wf.average_metric("annual_return")
print(f"Average Sharpe: {avg_sharpe:.2f}")
print(f"Average Return: {avg_return:.2%}")
```

#### Performance Metrics

```python
from quantfund.strategies.signal_backtest import PerformanceMetrics

metrics = PerformanceMetrics.calculate(
    returns=returns_series,
    benchmark_returns=benchmark_returns,
    risk_free_rate=0.02
)

# All available metrics
print(f"CAGR: {metrics.cagr:.2%}")
print(f"Annual Volatility: {metrics.annual_volatility:.2%}")
print(f"Sharpe Ratio: {metrics.sharpe:.2f}")
print(f"Sortino Ratio: {metrics.sortino:.2f}")
print(f"Max Drawdown: {metrics.max_drawdown:.2%}")
print(f"Max Drawdown Duration: {metrics.max_dd_duration} days")
print(f"Win Rate: {metrics.win_rate:.2%}")
print(f"Profit Factor: {metrics.profit_factor:.2f}")
print(f"Calmar Ratio: {metrics.calmar:.2f}")
print(f"Omega Ratio: {metrics.omega:.2f}")
```

#### Signal Quality Analysis

```python
from quantfund.strategies.signal_backtest import SignalQualityAnalyzer

quality = SignalQualityAnalyzer.analyze(
    signals=signals_df,
    returns=returns_series,
    lookbacks=[5, 10, 20, 60]
)

# Signal predictive power
print(f"IC (Information Coefficient): {quality.ic:.4f}")
print(f"Rank IC: {quality.rank_ic:.4f}")
print(f"Signal Edge: {quality.signal_edge:.4f}")

# Signal turnover
print(f"Turnover: {quality.turnover:.2%}")
print(f"Avg Position Duration: {quality.avg_duration:.1f} days")

# Signal decay
decay_analysis = quality.signal_decay(horizons=[1, 5, 10, 20])
for h, ic in decay_analysis.items():
    print(f"IC at horizon {h}: {ic:.4f}")
```

---

### Cron Jobs for Phase 5

```bash
# Daily signal generation (recommended)
0 8 * * * cd /path/to/QuantFund && python research/scripts/generate_signals.py --all --save-to-db >> /var/log/fred_signals.log 2>&1

# Weekly ML signal refresh
0 9 * * 0 cd /path/to/QuantFund && python research/scripts/generate_signals.py --signals ml --save-to-db >> /var/log/fred_ml_signals.log 2>&1

# Weekly backtest summary
0 10 * * 0 cd /path/to/QuantFund && python research/scripts/backtest_summary.py >> /var/log/fred_backtest.log 2>&1
```

---

## Phase 6: FRED-XAUUSD Integration

This phase adds the FRED-XAUUSD integration module, providing real-time signal generation, composite signal analysis, and position recommendations for gold trading through both Python and Tauri dashboard access.

### Overview

Phase 6 provides:
- FRED-XAUUSD signal integration module
- Composite signal generation combining multiple macro factors
- Real-time signal access via Tauri commands
- Position recommendations for gold trading
- Dashboard integration for signal visualization

---

### New Python Modules

#### quantfund.strategies.fred_xauusd_integration

FRED-XAUUSD integration for gold trading signals.

**Key Classes:**
- `FredXAUUSDIntegration` - Main integration controller
- `CompositeSignalGenerator` - Combines multiple FRED signals
- `XAUUSDSignalGenerator` - XAUUSD-specific signal generation
- `PositionRecommender` - Trading position recommendations
- `SignalHistoryManager` - Historical signal storage and retrieval

**Features:**
- Real yield impact analysis
- Dollar correlation signals
- Inflation hedge signals
- Risk-off detection
- Composite signal generation
- Position sizing recommendations

**Usage Examples:**

```python
from quantfund.strategies.fred_xauusd_integration import (
    FredXAUUSDIntegration,
    CompositeSignalGenerator,
    XAUUSDSignalGenerator,
    PositionRecommender,
    SignalHistoryManager
)

# Initialize integration
integration = FredXAUUSDIntegration(db_connection="postgresql://localhost/quantfund")

# Generate composite signal
composite = integration.get_composite_signal(date="2024-12-31")
print(f"Composite Score: {composite.score}")
print(f"Signal Direction: {composite.direction}")
print(f"Confidence: {composite.confidence}")

# Get XAUUSD-specific signal
xauusd_signal = integration.get_xauusd_signal(
    start_date="2024-01-01",
    end_date="2024-12-31"
)
print(f"XAUUSD Signals: {len(xauusd_signal)}")

# Get position recommendation
recommendation = integration.get_position_recommendation(date="2024-12-31")
print(f"Position: {recommendation.position}")  # LONG, SHORT, NEUTRAL
print(f"Size: {recommendation.size}")  # 0.0 to 1.0
print(f"Confidence: {recommendation.confidence}")
print(f"Reason: {recommendation.reason}")

# Generate signals for date range
signals = integration.generate_signals(
    start_date="2024-01-01",
    end_date="2024-12-31"
)
print(f"Generated {len(signals)} signals")

# Get signal history
history = integration.get_signal_history(
    start_date="2024-01-01",
    end_date="2024-12-31"
)
print(f"History: {len(history)} records")

# Save signals to database
integration.save_signals(signals)
```

---

#### Composite Signal Generator

Combines multiple FRED signals into a unified composite score.

```python
from quantfund.strategies.fred_xauusd_integration import CompositeSignalGenerator

generator = CompositeSignalGenerator(db_connection="postgresql://localhost/quantfund")

# Generate composite from all factors
composite = generator.generate_composite(
    date="2024-12-31",
    weights={
        "real_yield": 0.25,
        "dollar": 0.20,
        "inflation": 0.20,
        "risk_off": 0.20,
        "momentum": 0.15
    }
)

print(f"Score: {composite.score}")  # -1.0 to 1.0
print(f"Direction: {composite.direction}")  # BULLISH, BEARISH, NEUTRAL
print(f"Components: {composite.components}")
```

---

#### Position Recommender

Generates trading position recommendations based on composite signals.

```python
from quantfund.strategies.fred_xauusd_integration import PositionRecommender

recommender = PositionRecommender(db_connection="postgresql://localhost/quantfund")

# Get recommendation
rec = recommender.get_recommendation(
    date="2024-12-31",
    risk_level="moderate"  # conservative, moderate, aggressive
)

print(f"Position: {rec.position}")  # LONG, SHORT, NEUTRAL
print(f"Size: {rec.size}")  # 0.0 to 1.0
print(f"Stop Loss: {rec.stop_loss}")
print(f"Take Profit: {rec.take_profit}")
print(f"Risk/Reward: {rec.risk_reward}")
print(f"Confidence: {rec.confidence}")
```

---

### Tauri Dashboard Commands

The following commands are available in the Tauri dashboard for real-time signal access:

#### Signal Initialization

```typescript
// Initialize signal system
await invoke('fred_signals_init', {
  dbConnection: 'postgresql://localhost/quantfund'
});
```

#### Signal Generation

```typescript
// Generate signals for date range
await invoke('fred_generate_signals', {
  startDate: '2024-01-01',
  endDate: '2024-12-31'
});
```

#### Signal Retrieval

```typescript
// Get latest signals
const latestSignals = await invoke('fred_get_latest_signals', {
  n: 10
});

// Get signal history
const history = await invoke('fred_get_signal_history', {
  startDate: '2024-01-01',
  endDate: '2024-12-31'
});

// Get composite signal for specific date
const composite = await invoke('fred_get_composite_signal', {
  date: '2024-12-31'
});

// Get XAUUSD-specific signal
const xauusdSignal = await invoke('fred_get_xauusd_signal', {
  date: '2024-12-31'
});

// Get position recommendation
const recommendation = await invoke('fred_get_position_recommendation', {
  date: '2024-12-31',
  riskLevel: 'moderate'
});
```

#### Additional Commands

```typescript
// Get all available signal types
const signalTypes = await invoke('fred_get_signal_types');

// Get signal by type
const signals = await invoke('fred_get_signals_by_type', {
  signalType: 'real_yield',
  startDate: '2024-01-01',
  endDate: '2024-12-31'
});

// Get signal statistics
const stats = await invoke('fred_get_signal_stats', {
  startDate: '2024-01-01',
  endDate: '2024-12-31'
});

// Export signals
await invoke('fred_export_signals', {
  format: 'csv',  // csv or json
  path: './signals.csv',
  startDate: '2024-01-01',
  endDate: '2024-12-31'
});
```

---

### Usage Examples for Phase 6

#### Initialize and Generate Signals

```python
from quantfund.strategies.fred_xauusd_integration import FredXAUUSDIntegration

# Initialize
integration = FredXAUUSDIntegration(db_connection="postgresql://localhost/quantfund")

# Generate signals for the past year
signals = integration.generate_signals(
    start_date="2024-01-01",
    end_date="2024-12-31"
)

# Save to database
integration.save_signals(signals)

print(f"Generated {len(signals)} signals")
print(f"Latest composite: {signals.iloc[-1]['composite_signal']}")
```

#### Get Real-Time Position Recommendation

```python
from quantfund.strategies.fred_xauusd_integration import FredXAUUSDIntegration

integration = FredXAUUSDIntegration(db_connection="postgresql://localhost/quantfund")

# Get current position recommendation
recommendation = integration.get_position_recommendation()

print(f"Position: {recommendation.position}")
print(f"Size: {recommendation.size}")
print(f"Confidence: {recommendation.confidence:.1%}")
print(f"Reason: {recommendation.reason}")

# Risk levels
for risk in ['conservative', 'moderate', 'aggressive']:
    rec = integration.get_position_recommendation(risk_level=risk)
    print(f"{risk}: {rec.position} ({rec.size})")
```

#### Access from Dashboard

```typescript
// In your React/Vue component
import { invoke } from '@tauri-apps/api/core';

// Fetch latest signals on mount
const signals = await invoke('fred_get_latest_signals', { n: 5 });

// Update when needed
const recommendation = await invoke('fred_get_position_recommendation', {
  date: new Date().toISOString().split('T')[0],
  riskLevel: 'moderate'
});
```

---

### Cron Jobs for Phase 6

```bash
# Daily signal generation (recommended)
0 8 * * * cd /path/to/QuantFund && python research/scripts/generate_xauusd_signals.py >> /var/log/xauusd_signals.log 2>&1

# Hourly signal updates for trading
0 * * * * cd /path/to/QuantFund && python research/scripts/update_xauusd_signals.py >> /var/log/xauusd_update.log 2>&1

# Weekly composite analysis
0 9 * * 0 cd /path/to/QuantFund && python research/scripts/analyze_xauusd_composite.py >> /var/log/xauusd_composite.log 2>&1
```

---

### Compilation Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Rust** | ✅ Compiles without errors | All Tauri commands registered |
| **Python** | ✅ Imports work correctly | All modules importable |
| **TypeScript** | ✅ Builds successfully | Type definitions generated |

#### Verify Python Imports

```bash
cd /path/to/QuantFund
python -c "from quantfund.strategies.fred_xauusd_integration import FredXAUUSDIntegration; print('OK')"
```

#### Verify Tauri Build

```bash
cd src-tauri
cargo build --release
```

#### Verify TypeScript Types

```bash
cd src
npm run build
```

---

## Priority Series

The pipeline tracks the following FRED series organized by category:

### Interest Rates
- `FEDFUNDS` - Federal Funds Rate
- `DFF` - Effective Federal Funds Rate
- `DFII10` - 10-Year Treasury Inflation-Indexed Security
- `DGS10` - 10-Year Treasury Constant Maturity Rate
- `DGS2` - 2-Year Treasury Constant Maturity Rate
- `DGS30` - 30-Year Treasury Constant Maturity Rate

### Money Supply
- `M2SL` - M2 Money Supply
- `M2MV` - M2 Velocity

### Inflation
- `CPIAUCSL` - Consumer Price Index for All Urban Consumers
- `PCEPI` - Personal Consumption Expenditures Price Index
- `PCECTPI` - Personal Consumption Expenditures Chain-Type Price Index

### Employment
- `UNRATE` - Unemployment Rate
- `PAYEMS` - Total Nonfarm Payrolls
- `CIVPART` - Civilian Labor Force Participation Rate

### GDP
- `GDP` - Gross Domestic Product
- `GDPC1` - Real Gross Domestic Product

### Consumer
- `UMCSENT` - University of Michigan Consumer Sentiment
- `RETAIL` - Retail Sales

### Markets
- `SP500` - S&P 500
- `VIX` - CBOE Volatility Index
- `DTINY` - Trade Weighted Dollar Index

### Housing
- `HOUST` - Housing Starts
- `CSUSHPISA` - S&P/Case-Shiller U.S. National Home Price Index

### Trade
- `BCCA` - Balance on Current Account
- `EXCHUS` - U.S. / Japan Foreign Exchange Rate

### Gold
- `GOLDAMGBD228NLBM` - LBMA Gold Price: Afternoon

## Cron Jobs

### Daily Update (Recommended)

```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 6:00 AM)
0 6 * * * /path/to/venv/bin/python /path/to/QuantFund/research/scripts/update_fred_data.py >> /var/log/fred_update.log 2>&1
```

### Weekly Full Sync

```bash
# Weekly on Sunday at 2:00 AM
0 2 * * 0 /path/to/venv/bin/python /path/to/QuantFund/research/scripts/update_fred_data.py --parallel >> /var/log/fred_weekly.log 2>&1
```

### Common Cron Options

| Schedule | Cron Expression |
|----------|-----------------|
| Every hour | `0 * * * *` |
| Daily at 6 AM | `0 6 * * *` |
| Weekly Sunday | `0 2 * * 0` |
| Monthly 1st | `0 3 1 * *` |

## Troubleshooting

### FRED API Errors

**Error: "api_key is invalid"**
- API key not activated (wait up to 30 minutes)
- Check key at: https://fred.stlouisfed.org/docs/api/api_key.html

**Error: "Too many requests"**
- Rate limit exceeded
- Default: 120 requests/minute
- Reduce with: `--rate-limit 60`

**Error: "Series not found"**
- Series ID may have changed
- Check valid series at: https://fred.stlouisfed.org/

### Database Errors

**Error: "database does not exist"**
```sql
CREATE DATABASE freddata;
```

**Error: "timescaledb extension not found"**
```sql
CREATE EXTENSION timescaledb;
```

**Error: "connection refused"**
- PostgreSQL not running
- Check host/port configuration
- Firewall blocking connection

### Data Issues

**Missing observations**
- Run update script to fetch latest data
- Check if FRED has published the data

**Stale data**
- Verify update cron job is running
- Check logs: `tail -f /var/log/fred_update.log`

**Data gaps**
- Some series have publication lags
- Monthly data typically available 2-4 weeks after period end

### Performance Issues

**Slow ingestion**
- Use parallel mode: `--parallel`
- Increase workers: `--workers 8`
- Check database indexes

**High memory usage**
- Reduce batch size in code
- Process fewer series at once

## Database Schema Details

### Core Tables

| Table | Description |
|-------|-------------|
| `fred_series` | Series metadata (ID, title, frequency, units) |
| `fred_observations` | Time-series data points (TimescaleDB hypertable) |
| `fred_tags` | Tag classifications |
| `fred_categories` | Category hierarchy |
| `fred_releases` | Publication releases |
| `fred_anomalies` | Detected data anomalies |
| `fred_features` | Derived features |

### Indexes

- Primary key on `fred_observations`: `(series_id, date)`
- Composite index: `(series_id, date DESC)`
- Unique constraint: `(series_id, date, realtime_start, realtime_end)`

### TimescaleDB Features

- Automatic chunk management
- Compression after 2 years
- 2-year retention policy

## File Structure

```
research/scripts/
├── fred_schema.py              # Database schema management
├── ingest_fred_data.py         # Initial data ingestion
├── update_fred_data.py         # Daily incremental updates
├── test_fred_connection.py    # Connection testing
├── clean_fred_data.py         # Phase 3: Complete cleaning pipeline
├── detect_fred_anomalies.py   # Phase 4: Daily anomaly detection job
├── migrations/
│   └── 001_fred_schema.sql   # SQL migration
└── __pycache__/              # Python cache

research/quantfund/data/
├── fred_quality.py            # Phase 3: Quality control & outlier detection
├── fred_transform.py          # Phase 3: Data transformations
├── fred_features.py          # Phase 3: Feature engineering
├── fred_anomaly.py           # Phase 4: Statistical & ML anomaly detection
└── fred_semantic_anomaly.py  # Phase 4: Semantic analysis
```

## Additional Resources

- [FRED API Documentation](https://fred.stlouisfed.org/docs/api/fred.html)
- [TimescaleDB Documentation](https://docs.timescale.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

## License

This project is for educational and research purposes. FRED data is provided by the Federal Reserve Bank of St. Louis under their [terms of use](https://fred.stlouisfed.org/legal).
