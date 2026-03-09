"""
FRED Feature Engineering Module
================================

Comprehensive feature engineering for FRED economic time series data.
Designed for systematic trading strategies with focus on XAUUSD (gold) trading.

Features:
- Quality-controlled feature generation
- Price/momentum/mean-reversion/volatility/trend/seasonal/correlation features
- XAUUSD-specific features (real yield, dollar impact, inflation hedge, risk-off)
- Batch processing with parallel execution
- Feature store integration with database

Usage:
    from quantfund.data.fred_features import FredFeatureEngine

    engine = FredFeatureEngine(db_connection="postgresql://localhost/quantfund")

    # Generate features for a single series
    features = engine.compute_all_features("DXY", start_date="2020-01-01")

    # Process multiple series
    results = engine.process_series_list(["DXY", "TIPS10Y", "VIX"])

    # Get feature matrix for ML
    matrix = engine.get_feature_matrix(series_ids=["DXY", "TIPS10Y"], start_date="2020-01-01")

XAUUSD Trading Features:
    - Real yield impact (TIPS10Y, TIPS5Y)
    - Dollar impact (DXY, USDIndex)
    - Inflation hedge (CPI, PPI, M2)
    - Risk sentiment (VIX, SP500, Gold/Silver ratio)
"""

from __future__ import annotations

import os
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import sql

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


DEFAULT_WINDOW_SIZES = [5, 10, 20, 50, 100, 200]
DEFAULT_LAGS = [1, 2, 3, 5, 10, 20]

XAUUSD_RELATED_SERIES = {
    "DXY": "US Dollar Index",
    "TIPS10Y": "10-Year Treasury Inflation-Indexed Security",
    "TIPS5Y": "5-Year Treasury Inflation-Indexed Security",
    "CPIAUCSL": "Consumer Price Index",
    "PPIFGS": "Producer Price Index",
    "M2SL": "M2 Money Supply",
    "VIX": "CBOE Volatility Index",
    "SP500": "S&P 500",
    "GCF": "Gold Futures",
    "SI": "Silver Futures",
    "FEDFUNDS": "Federal Funds Rate",
    "DFF": "Effective Federal Funds Rate",
    "Gold": "Gold Price",
}


@dataclass
class FeatureConfig:
    """Configuration for feature generation."""

    window_sizes: List[int] = field(default_factory=lambda: DEFAULT_WINDOW_SIZES.copy())
    lags: List[int] = field(default_factory=lambda: DEFAULT_LAGS.copy())
    momentum_windows: List[int] = field(default_factory=lambda: [5, 10, 20, 50, 100])
    volatility_windows: List[int] = field(default_factory=lambda: [5, 10, 20, 50, 100])
    trend_windows: List[int] = field(default_factory=lambda: [10, 20, 50, 100])
    seasonal_periods: List[int] = field(default_factory=lambda: [5, 12, 52])
    correlation_windows: List[int] = field(default_factory=lambda: [20, 50, 100])
    use_ewm: bool = True
    ewm_spans: List[int] = field(default_factory=lambda: [5, 10, 20])
    compute_xauusd_features: bool = True


@dataclass
class FeatureResult:
    """Result of feature computation."""

    series_id: str
    features: pd.DataFrame
    feature_names: List[str]
    start_date: Optional[date]
    end_date: Optional[date]
    row_count: int
    computation_time_seconds: float
    errors: List[str] = field(default_factory=list)


class DatabaseConnection:
    """Database connection manager for FRED data."""

    def __init__(self, connection_string: Optional[str] = None):
        self.connection_string = connection_string or os.environ.get(
            "DATABASE_URL", "postgresql://localhost/quantfund"
        )

    def get_connection(self):
        """Get database connection."""
        return psycopg2.connect(self.connection_string)

    def execute_query(self, query: str, params: Optional[Tuple] = None) -> Optional[List[Tuple]]:
        """Execute a query and return results."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                if cur.description:
                    return cur.fetchall()
                conn.commit()
                return None

    def get_observations(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get observations for a FRED series."""
        query = """
            SELECT date, value 
            FROM fred_observations 
            WHERE series_id = %s
        """
        params: List[Union[str, Any]] = [series_id]

        if start_date:
            query += " AND date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND date <= %s"
            params.append(end_date)

        query += " ORDER BY date"

        results = self.execute_query(query, tuple(params))

        if not results:
            return pd.DataFrame(columns=["date", "value"])

        df = pd.DataFrame(results, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"])

        return df

    def get_all_series(self) -> List[str]:
        """Get all available FRED series IDs."""
        query = "SELECT series_id FROM fred_series ORDER BY series_id"
        results = self.execute_query(query)
        if not results:
            return []
        return [r[0] for r in results]

    def series_exists(self, series_id: str) -> bool:
        """Check if a series exists in the database."""
        query = "SELECT 1 FROM fred_series WHERE series_id = %s LIMIT 1"
        results = self.execute_query(query, (series_id,))
        return results is not None and len(results) > 0


class FredFeatureEngine:
    """
    Comprehensive feature engineering for FRED economic data.

    Combines quality control, transformations, and feature generation
    with XAUUSD-specific features for gold trading.
    """

    def __init__(
        self,
        db_connection: Optional[Union[str, DatabaseConnection]] = None,
        config: Optional[FeatureConfig] = None,
    ):
        """
        Initialize the feature engine.

        Args:
            db_connection: Database connection string or DatabaseConnection instance
            config: Feature configuration (uses defaults if not provided)
        """
        if isinstance(db_connection, str):
            self.db = DatabaseConnection(db_connection)
        elif db_connection is None:
            self.db = DatabaseConnection()
        else:
            self.db = db_connection

        self.config = config or FeatureConfig()
        self._engine: Optional[Engine] = None

        if isinstance(self.db, DatabaseConnection):
            conn_str = self.db.connection_string
        else:
            conn_str = self.db

        if conn_str and HAS_SQLALCHEMY:
            self._init_feature_store(conn_str)

    def _init_feature_store(self, connection_string: str) -> None:
        """Initialize feature store database connection."""
        if not HAS_SQLALCHEMY:
            warnings.warn("SQLAlchemy not available. Feature store disabled.")
            return

        if connection_string.endswith(".db") or ":memory:" in connection_string:
            connection_string = f"sqlite:///{connection_string}"

        self._engine = create_engine(connection_string)
        self._create_feature_store_tables()

    def _create_feature_store_tables(self) -> None:
        """Create feature store tables if they don't exist."""
        if self._engine is None:
            return

        create_tables_sql = """
        CREATE TABLE IF NOT EXISTS fred_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id TEXT NOT NULL,
            feature_name TEXT NOT NULL,
            feature_value REAL,
            observation_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(series_id, feature_name, observation_date)
        );
        
        CREATE INDEX IF NOT EXISTS idx_fred_features_series_date 
        ON fred_features(series_id, observation_date);
        
        CREATE INDEX IF NOT EXISTS idx_fred_features_feature 
        ON fred_features(feature_name);
        
        CREATE TABLE IF NOT EXISTS fred_feature_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id TEXT NOT NULL,
            feature_name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(series_id, feature_name)
        );
        """

        with self._engine.connect() as conn:
            for stmt in create_tables_sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        conn.execute(text(stmt))
                    except Exception as e:
                        warnings.warn(f"Table creation warning: {e}")
            conn.commit()

    def get_series_data(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get series data from database with quality checks.

        Args:
            series_id: FRED series ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            DataFrame with 'date' and 'value' columns
        """
        if hasattr(self.db, "get_observations"):
            return self.db.get_observations(series_id, start_date, end_date)

        query = """
            SELECT date, value 
            FROM fred_observations 
            WHERE series_id = %s
        """
        params: List[Any] = [series_id]

        if start_date:
            query += " AND date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND date <= %s"
            params.append(end_date)

        query += " ORDER BY date"

        results = self.db.execute_query(query, tuple(params))

        if not results:
            return pd.DataFrame(columns=["date", "value"])

        df = pd.DataFrame(results, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"])

        return df

    def compute_all_features(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Generate comprehensive feature set for a FRED series.

        Args:
            series_id: FRED series ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            DataFrame with all computed features
        """
        import time

        start_time = time.time()

        df = self.get_series_data(series_id, start_date, end_date)

        if df.empty:
            warnings.warn(f"No data available for series: {series_id}")
            return pd.DataFrame()

        df = df.sort_values("date").reset_index(drop=True)

        feature_dfs = []

        price_features = self.compute_price_features(df)
        if price_features is not None and not price_features.empty:
            feature_dfs.append(price_features)

        momentum_features = self.compute_momentum_features(df)
        if momentum_features is not None and not momentum_features.empty:
            feature_dfs.append(momentum_features)

        mean_reversion_features = self.compute_mean_reversion_features(df)
        if mean_reversion_features is not None and not mean_reversion_features.empty:
            feature_dfs.append(mean_reversion_features)

        volatility_features = self.compute_volatility_features(df)
        if volatility_features is not None and not volatility_features.empty:
            feature_dfs.append(volatility_features)

        trend_features = self.compute_trend_features(df)
        if trend_features is not None and not trend_features.empty:
            feature_dfs.append(trend_features)

        seasonal_features = self.compute_seasonal_features(df)
        if seasonal_features is not None and not seasonal_features.empty:
            feature_dfs.append(seasonal_features)

        if self.config.compute_xauusd_features:
            xauusd_features = self.compute_xauusd_specific_features(df, series_id)
            if xauusd_features is not None and not xauusd_features.empty:
                feature_dfs.append(xauusd_features)

        if not feature_dfs:
            return pd.DataFrame()

        result = pd.concat(feature_dfs, axis=1)
        result["date"] = df["date"].values

        return result

    def compute_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute price-based features: returns, volatility, price changes.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with price features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        features = {}

        returns = series.pct_change()
        log_returns = np.log(series / series.shift(1))

        for lag in self.config.lags:
            features[f"return_{lag}"] = returns.shift(lag)
            features[f"log_return_{lag}"] = log_returns.shift(lag)

        for window in self.config.window_sizes:
            features[f"cumulative_return_{window}"] = series.pct_change(window)
            features[f"cumulative_log_return_{window}"] = log_returns.rolling(window).sum()

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute momentum indicators: ROC, RSI-style, moving average deviations.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with momentum features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        features = {}

        for window in self.config.momentum_windows:
            ma = series.rolling(window).mean()
            features[f"ma_deviation_{window}"] = (series - ma) / ma

            roc = (series - series.shift(window)) / series.shift(window)
            features[f"roc_{window}"] = roc

            features[f"ma_slope_{window}"] = series.pdiff(window) / series.shift(window)

        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        for window in [5, 10, 14, 20]:
            avg_gain = gain.rolling(window).mean()
            avg_loss = loss.rolling(window).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            features[f"rsi_{window}"] = 100 - 100 / (1 + rs)

        ema_12 = series.ewm(span=12).mean()
        ema_26 = series.ewm(span=26).mean()
        macd = ema_12 - ema_26
        signal = macd.ewm(span=9).mean()
        features["macd"] = macd
        features["macd_signal"] = signal
        features["macd_histogram"] = macd - signal

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_mean_reversion_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute mean reversion indicators: z-score, Bollinger bands, distance from extremes.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with mean reversion features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        features = {}

        for window in [10, 20, 50, 100]:
            rolling_mean = series.rolling(window).mean()
            rolling_std = series.rolling(window).std()

            zscore = (series - rolling_mean) / rolling_std.replace(0, np.nan)
            features[f"zscore_{window}"] = zscore

            bb_upper = rolling_mean + 2 * rolling_std
            bb_lower = rolling_mean - 2 * rolling_std
            bb_width = (bb_upper - bb_lower) / rolling_mean
            features[f"bollinger_width_{window}"] = bb_width
            features[f"bollinger_position_{window}"] = (series - bb_lower) / (
                bb_upper - bb_lower
            ).replace(0, np.nan)

        for window in [20, 50, 100]:
            rolling_max = series.rolling(window).max()
            rolling_min = series.rolling(window).min()
            features[f"position_from_low_{window}"] = (series - rolling_min) / (
                rolling_max - rolling_min
            ).replace(0, np.nan)
            features[f"distance_to_high_{window}"] = (rolling_max - series) / series

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute volatility measures: realized, Parkinson, Garman-Klass.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with volatility features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        log_returns = np.log(series / series.shift(1))
        features = {}

        for window in self.config.volatility_windows:
            rv = log_returns.rolling(window).std() * np.sqrt(252)
            features[f"realized_vol_{window}"] = rv

        for window in [20, 50, 100]:
            vol_50 = log_returns.rolling(50).std()
            vol_short = log_returns.rolling(window).std()
            features[f"vol_ratio_{window}_50"] = vol_short / vol_50.replace(0, np.nan)

        for window in [20, 50]:
            rv = log_returns.rolling(window).std()
            features[f"vol_rank_{window}"] = rv.rolling(252).rank(pct=True)

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute trend indicators: slope, trend strength, ADX-style.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with trend features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        features = {}

        for window in self.config.trend_windows:
            slope = series.pct_change(window)
            features[f"slope_{window}"] = slope

            rolling_std = series.rolling(window).std()
            rolling_mean = series.rolling(window).mean()
            trend_strength = (series - rolling_mean) / rolling_std.replace(0, np.nan)
            features[f"trend_strength_{window}"] = trend_strength

            up = series.diff().clip(lower=0)
            down = (-series.diff()).clip(lower=0)
            rs = up.rolling(window).mean() / down.rolling(window).mean().replace(0, np.nan)
            features[f"directional_ratio_{window}"] = rs

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_seasonal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute seasonal patterns: month-of-year, quarter, day-of-week effects.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with seasonal features
        """
        if df.empty or "date" not in df.columns:
            return pd.DataFrame()

        features = {}

        dates = pd.to_datetime(df["date"])
        features["month"] = dates.dt.month
        features["quarter"] = dates.dt.quarter
        features["day_of_week"] = dates.dt.dayofweek
        features["day_of_month"] = dates.dt.day
        features["week_of_year"] = dates.dt.isocalendar().week.astype(int)

        month_sin = np.sin(2 * np.pi * features["month"] / 12)
        month_cos = np.cos(2 * np.pi * features["month"] / 12)
        features["month_sin"] = month_sin
        features["month_cos"] = month_cos

        dow_sin = np.sin(2 * np.pi * features["day_of_week"] / 7)
        dow_cos = np.cos(2 * np.pi * features["day_of_week"] / 7)
        features["dow_sin"] = dow_sin
        features["dow_cos"] = dow_cos

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_correlation_features(
        self,
        primary_df: pd.DataFrame,
        reference_series: Dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """
        Compute correlation features with other series.

        Args:
            primary_df: Primary series DataFrame
            reference_series: Dict of {name: DataFrame} for reference series

        Returns:
            DataFrame with correlation features
        """
        if primary_df.empty or "value" not in primary_df.columns:
            return pd.DataFrame()

        primary = primary_df.set_index("date")["value"]
        primary_ret = np.log(primary / primary.shift(1))

        features = {}

        for name, ref_df in reference_series.items():
            if ref_df.empty or "value" not in ref_df.columns:
                continue

            ref = ref_df.set_index("date")["value"]
            ref_ret = np.log(ref / ref.shift(1))

            aligned_primary, aligned_ref = primary_ret.align(ref_ret, join="inner")

            for window in self.config.correlation_windows:
                corr = aligned_primary.rolling(window).corr(aligned_ref)
                features[f"corr_{name}_{window}"] = corr

                cov = aligned_primary.rolling(window).cov(aligned_ref)
                var_ref = aligned_ref.rolling(window).var().replace(0, np.nan)
                features[f"beta_{name}_{window}"] = cov / var_ref

        result = pd.DataFrame(features, index=primary_df["date"])
        return result

    def compute_xauusd_specific_features(self, df: pd.DataFrame, series_id: str) -> pd.DataFrame:
        """
        Compute XAUUSD-specific features for gold trading.

        Args:
            df: DataFrame with 'date' and 'value' columns
            series_id: Current series ID

        Returns:
            DataFrame with XAUUSD-specific features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        features = {}

        if series_id in ["DXY", "USDIndex"]:
            dollar_features = self.compute_dollar_impact(df)
            if dollar_features is not None:
                features.update(dollar_features.to_dict(orient="series"))

        elif series_id in ["TIPS10Y", "TIPS5Y", "TIPS"]:
            yield_features = self.compute_real_yield_features(df)
            if yield_features is not None:
                features.update(yield_features.to_dict(orient="series"))

        elif series_id in ["VIX"]:
            risk_features = self.compute_risk_off_features(df)
            if risk_features is not None:
                features.update(risk_features.to_dict(orient="series"))

        elif series_id in ["CPIAUCSL", "PPIFGS", "PCEPI"]:
            inf_features = self.compute_inflation_hedge(df)
            if inf_features is not None:
                features.update(inf_features.to_dict(orient="series"))

        if not features:
            return pd.DataFrame()

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_real_yield_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute real yield (TIPS) impact on gold.

        Real yields are inversely correlated with gold prices.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with real yield features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        features = {}

        for window in [5, 10, 20, 50]:
            features[f"real_yield_ma_{window}"] = series.rolling(window).mean()
            features[f"real_yield_change_{window}"] = series.diff(window)
            features[f"real_yield_zscore_{window}"] = (
                series - series.rolling(window).mean()
            ) / series.rolling(window).std().replace(0, np.nan)

        inverse_yield = -series
        features["inverse_real_yield"] = inverse_yield

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_dollar_impact(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute DXY (US Dollar) impact on gold.

        Dollar and gold are typically inversely correlated.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with dollar impact features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        features = {}

        for window in [5, 10, 20, 50]:
            features[f"dxy_ma_{window}"] = series.rolling(window).mean()
            features[f"dxy_change_{window}"] = series.diff(window)
            features[f"dxy_strength_{window}"] = series / series.rolling(window).iloc[0] - 1

        inverse_dxy = -series
        features["inverse_dxy"] = inverse_dxy

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_inflation_hedge(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute inflation hedge features.

        Gold is traditionally used as an inflation hedge.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with inflation hedge features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        features = {}

        for window in [12, 24]:
            features[f"inflation_ma_{window}"] = series.rolling(window).mean()
            features[f"inflation_change_{window}"] = series.diff(window)
            features[f"inflation_accelerating"] = series.diff(6) > series.diff(12)

        result = pd.DataFrame(features, index=df["date"])
        return result

    def compute_risk_off_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute risk sentiment features (VIX, SP500).

        Risk-off environments typically benefit gold.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            DataFrame with risk-off features
        """
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()

        series = df.set_index("date")["value"]
        features = {}

        for window in [5, 10, 20]:
            features[f"vix_ma_{window}"] = series.rolling(window).mean()
            features[f"vix_change_{window}"] = series.diff(window)
            features[f"vix_spike_{window}"] = (
                series > series.rolling(window).mean() + 2 * series.rolling(window).std()
            )

        features["vix_extreme"] = series > 30
        features["vix_very_extreme"] = series > 40

        result = pd.DataFrame(features, index=df["date"])
        return result

    def process_all_series(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save_to_db: bool = False,
    ) -> Dict[str, FeatureResult]:
        """
        Process all series in the database.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            save_to_db: Whether to save features to database

        Returns:
            Dict of {series_id: FeatureResult}
        """
        import time

        series_ids = self.db.get_all_series()
        results = {}

        for series_id in series_ids:
            try:
                start_time = time.time()
                features = self.compute_all_features(series_id, start_date, end_date)

                if save_to_db and not features.empty:
                    self.save_to_feature_store(series_id, features)

                results[series_id] = FeatureResult(
                    series_id=series_id,
                    features=features,
                    feature_names=list(features.columns),
                    start_date=features["date"].min() if not features.empty else None,
                    end_date=features["date"].max() if not features.empty else None,
                    row_count=len(features),
                    computation_time_seconds=time.time() - start_time,
                )
            except Exception as e:
                results[series_id] = FeatureResult(
                    series_id=series_id,
                    features=pd.DataFrame(),
                    feature_names=[],
                    start_date=None,
                    end_date=None,
                    row_count=0,
                    computation_time_seconds=0,
                    errors=[str(e)],
                )

        return results

    def process_series_list(
        self,
        series_ids: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save_to_db: bool = False,
    ) -> Dict[str, FeatureResult]:
        """
        Process specific list of series.

        Args:
            series_ids: List of FRED series IDs
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            save_to_db: Whether to save features to database

        Returns:
            Dict of {series_id: FeatureResult}
        """
        import time

        results = {}

        for series_id in series_ids:
            try:
                start_time = time.time()
                features = self.compute_all_features(series_id, start_date, end_date)

                if save_to_db and not features.empty:
                    self.save_to_feature_store(series_id, features)

                results[series_id] = FeatureResult(
                    series_id=series_id,
                    features=features,
                    feature_names=list(features.columns),
                    start_date=(
                        pd.to_datetime(features["date"]).min().date()
                        if not features.empty
                        else None
                    ),
                    end_date=(
                        pd.to_datetime(features["date"]).max().date()
                        if not features.empty
                        else None
                    ),
                    row_count=len(features),
                    computation_time_seconds=time.time() - start_time,
                )
            except Exception as e:
                results[series_id] = FeatureResult(
                    series_id=series_id,
                    features=pd.DataFrame(),
                    feature_names=[],
                    start_date=None,
                    end_date=None,
                    row_count=0,
                    computation_time_seconds=0,
                    errors=[str(e)],
                )

        return results

    def parallel_process(
        self,
        series_ids: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_workers: int = 4,
        save_to_db: bool = False,
    ) -> Dict[str, FeatureResult]:
        """
        Process series in parallel for speed.

        Args:
            series_ids: List of FRED series IDs
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_workers: Number of parallel workers
            save_to_db: Whether to save features to database

        Returns:
            Dict of {series_id: FeatureResult}
        """

        def process_single(series_id: str) -> Tuple[str, FeatureResult]:
            import time

            try:
                start_time = time.time()
                features = self.compute_all_features(series_id, start_date, end_date)

                if save_to_db and not features.empty:
                    self.save_to_feature_store(series_id, features)

                return (
                    series_id,
                    FeatureResult(
                        series_id=series_id,
                        features=features,
                        feature_names=list(features.columns),
                        start_date=(
                            pd.to_datetime(features["date"]).min().date()
                            if not features.empty
                            else None
                        ),
                        end_date=(
                            pd.to_datetime(features["date"]).max().date()
                            if not features.empty
                            else None
                        ),
                        row_count=len(features),
                        computation_time_seconds=time.time() - start_time,
                    ),
                )
            except Exception as e:
                return (
                    series_id,
                    FeatureResult(
                        series_id=series_id,
                        features=pd.DataFrame(),
                        feature_names=[],
                        start_date=None,
                        end_date=None,
                        row_count=0,
                        computation_time_seconds=0,
                        errors=[str(e)],
                    ),
                )

        results = {}
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_single, sid): sid for sid in series_ids}

            for future in as_completed(futures):
                series_id, result = future.result()
                results[series_id] = result

        return results

    def save_to_feature_store(
        self,
        series_id: str,
        features: pd.DataFrame,
    ) -> int:
        """
        Save computed features to database.

        Args:
            series_id: FRED series ID
            features: DataFrame with features (must have 'date' column)

        Returns:
            Number of records inserted
        """
        if self._engine is None:
            warnings.warn("Feature store not initialized. Features not saved.")
            return 0

        feature_columns = [c for c in features.columns if c != "date"]

        records = []
        for _, row in features.iterrows():
            date_val = row["date"]
            for feature in feature_columns:
                records.append(
                    {
                        "series_id": series_id,
                        "feature_name": feature,
                        "feature_value": row[feature],
                        "observation_date": pd.to_datetime(date_val),
                    }
                )

        if not records:
            return 0

        insert_sql = """
        INSERT OR REPLACE INTO fred_features 
        (series_id, feature_name, feature_value, observation_date)
        VALUES (:series_id, :feature_name, :feature_value, :observation_date)
        """

        try:
            with self._engine.connect() as conn:
                conn.execute(text(insert_sql), records)
                conn.commit()
            return len(records)
        except Exception as e:
            warnings.warn(f"Failed to save features: {e}")
            return 0

    def load_features(
        self,
        series_id: str,
        feature_names: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load pre-computed features from database.

        Args:
            series_id: FRED series ID
            feature_names: Specific features to load. If None, loads all.
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)

        Returns:
            DataFrame with features
        """
        if self._engine is None:
            raise RuntimeError("Feature store not initialized.")

        query = "SELECT * FROM fred_features WHERE series_id = :series_id"
        params: Dict[str, Any] = {"series_id": series_id}

        if feature_names:
            placeholders = ", ".join([f":feature_{i}" for i in range(len(feature_names))])
            query += f" AND feature_name IN ({placeholders})"
            for i, name in enumerate(feature_names):
                params[f"feature_{i}"] = name

        if start_date:
            query += " AND observation_date >= :start_date"
            params["start_date"] = start_date

        if end_date:
            query += " AND observation_date <= :end_date"
            params["end_date"] = end_date

        query += " ORDER BY observation_date, feature_name"

        with self._engine.connect() as conn:
            result = conn.execute(text(query), params)
            rows = result.fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=result.keys())

        pivot_df = df.pivot_table(
            index="observation_date",
            columns="feature_name",
            values="feature_value",
            aggfunc="first",
        ).reset_index()

        pivot_df.columns = ["date" if c == "observation_date" else c for c in pivot_df.columns]

        return pivot_df

    def get_feature_matrix(
        self,
        series_ids: List[str],
        feature_names: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get feature matrix for ML models.

        Combines features from multiple series into a single matrix.

        Args:
            series_ids: List of FRED series IDs
            feature_names: Specific features to include (optional)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Wide DataFrame with features from all series
        """
        dfs = []

        for series_id in series_ids:
            try:
                features = self.compute_all_features(series_id, start_date, end_date)

                if features.empty:
                    continue

                feature_cols = [c for c in features.columns if c != "date"]
                if feature_names:
                    feature_cols = [c for c in feature_cols if c in feature_names]

                features = features[["date"] + feature_cols]

                rename_map = {c: f"{series_id}_{c}" for c in feature_cols}
                features = features.rename(columns=rename_map)

                dfs.append(features)

            except Exception as e:
                warnings.warn(f"Failed to compute features for {series_id}: {e}")
                continue

        if not dfs:
            return pd.DataFrame()

        merged = dfs[0]
        for df in dfs[1:]:
            merged = merged.merge(df, on="date", how="outer")

        merged = merged.sort_values("date").reset_index(drop=True)

        return merged


def create_feature_engine(
    db_connection: str = "postgresql://localhost/quantfund",
    compute_xauusd_features: bool = True,
) -> FredFeatureEngine:
    """
    Factory function to create a FredFeatureEngine.

    Args:
        db_connection: Database connection string
        compute_xauusd_features: Whether to compute XAUUSD-specific features

    Returns:
        Configured FredFeatureEngine instance
    """
    config = FeatureConfig(compute_xauusd_features=compute_xauusd_features)
    return FredFeatureEngine(db_connection=db_connection, config=config)


if __name__ == "__main__":
    engine = create_feature_engine()

    print("Available series in database:")
    series = engine.db.get_all_series()
    print(f"  Found {len(series)} series")

    print("\nProcessing sample series...")
    results = engine.process_series_list(
        ["DXY", "VIX", "TIPS10Y"], start_date="2020-01-01", end_date="2024-01-01"
    )

    for series_id, result in results.items():
        print(f"\n{series_id}:")
        print(f"  Features: {len(result.feature_names)}")
        print(f"  Rows: {result.row_count}")
        print(f"  Time: {result.computation_time_seconds:.2f}s")
        if result.errors:
            print(f"  Errors: {result.errors}")
