"""
FRED Data Transformation Module
================================

Time series transformations, rolling statistics, seasonal decomposition,
temporal features, and aggregation for FRED economic data.

Usage:
    from quantfund.data.fred_transform import FredTransformer

    transformer = FredTransformer()
    df = client.get_observations("UNRATE", "2020-01-01", "2025-01-01")

    # Transformations
    diff_df = transformer.difference(df)
    pct_df = transformer.percent_change(df)

    # Rolling stats
    ma = transformer.rolling_mean(df, window=12)

    # Seasonal
    decomposed = transformer.seasonal_decompose(df)

    # Features
    features = transformer.add_time_features(df)
    features = transformer.add_lag_features(df, lags=[1, 3, 6, 12])

    # Save to database
    transformer.save_features_to_db(features, "unrate_features")
"""

from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL, seasonal_decompose
from statsmodels.tsa.statespace.tools import diff as statespace_diff

try:
    from scipy import stats
    from scipy.special import boxcox

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

__all__ = ["FredTransformer"]


class FredTransformer:
    """
    Comprehensive time series transformation for FRED data.

    Provides transformations, rolling statistics, seasonal decomposition,
    temporal features, and database integration.
    """

    def __init__(
        self,
        db_connection: Optional[str] = None,
        value_column: str = "value",
        date_column: str = "date",
    ):
        """
        Initialize transformer.

        Args:
            db_connection: SQLAlchemy connection string or SQLite path.
            value_column: Name of the value column in DataFrames.
            date_column: Name of the date column in DataFrames.
        """
        self.value_column = value_column
        self.date_column = date_column
        self._engine: Optional[Engine] = None

        if db_connection:
            self._init_db(db_connection)

    def _init_db(self, connection_string: str) -> None:
        """Initialize database connection."""
        if not HAS_SQLALCHEMY:
            raise ImportError(
                "sqlalchemy is required for database features. Install with: pip install sqlalchemy"
            )

        if connection_string.endswith(".db") or ":memory:" in connection_string:
            connection_string = f"sqlite:///{connection_string}"

        self._engine = create_engine(connection_string)
        self._create_features_table()

    def _create_features_table(self) -> None:
        """Create fred_features table if it doesn't exist."""
        if self._engine is None:
            return

        create_table_sql = """
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
        """
        with self._engine.connect() as conn:
            for stmt in create_table_sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
            conn.commit()

    def _get_series_as_indexed(self, df: pd.DataFrame) -> pd.Series:
        """
        Convert DataFrame to indexed Series suitable for transformations.

        Args:
            df: DataFrame with date_column and value_column.

        Returns:
            pd.Series with DatetimeIndex.
        """
        if df.empty:
            return pd.Series(dtype=float)

        series = df.set_index(self.date_column)[self.value_column].copy()

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        if series.index.tz is None:
            series.index = series.index.tz_localize("UTC")

        return series.sort_index()

    def _ensure_value_column(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure DataFrame has the expected structure."""
        df = df.copy()

        if self.value_column not in df.columns:
            if "value" in df.columns:
                df = df.rename(columns={"value": self.value_column})
            elif len(df.columns) == 2:
                df.columns = [self.date_column, self.value_column]

        return df

    # -------------------------------------------------------------------------
    # Time Series Transformations
    # -------------------------------------------------------------------------

    def difference(
        self,
        df: pd.DataFrame,
        periods: int = 1,
        drop_na: bool = True,
    ) -> pd.DataFrame:
        """
        Compute first difference for stationarity.

        Args:
            df: Input DataFrame with date and value columns.
            periods: Number of periods to difference (default 1).
            drop_na: Drop NaN values from the result.

        Returns:
            DataFrame with differenced values.
        """
        series = self._get_series_as_indexed(df)
        diffed = series.diff(periods=periods)

        if drop_na:
            diffed = diffed.dropna()

        return pd.DataFrame(
            {
                self.date_column: diffed.index,
                self.value_column: diffed.values,
            }
        )

    def percent_change(
        self,
        df: pd.DataFrame,
        periods: int = 1,
        drop_na: bool = True,
    ) -> pd.DataFrame:
        """
        Compute percentage change.

        Args:
            df: Input DataFrame with date and value columns.
            periods: Number of periods for change calculation.
            drop_na: Drop NaN values from the result.

        Returns:
            DataFrame with percentage change values.
        """
        series = self._get_series_as_indexed(df)
        pct = series.pct_change(periods=periods)

        if drop_na:
            pct = pct.dropna()

        return pd.DataFrame(
            {
                self.date_column: pct.index,
                self.value_column: pct.values,
            }
        )

    def log_transform(
        self,
        df: pd.DataFrame,
        drop_na: bool = True,
    ) -> pd.DataFrame:
        """
        Apply log transformation to stabilize variance.

        Args:
            df: Input DataFrame with date and value columns.
            drop_na: Drop NaN values from the result.

        Returns:
            DataFrame with log-transformed values.
        """
        series = self._get_series_as_indexed(df)

        if (series <= 0).any():
            warnings.warn("Non-positive values detected. Adding offset for log transform.")
            offset = abs(series.min()) + 1 if (series <= 0).any() else 0
            series = series + offset

        logged = np.log(series)

        if drop_na:
            logged = logged.dropna()

        return pd.DataFrame(
            {
                self.date_column: logged.index,
                self.value_column: logged.values,
            }
        )

    def box_cox_transform(
        self,
        df: pd.DataFrame,
        lmbda: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Apply Box-Cox transformation for stabilizing variance.

        Args:
            df: Input DataFrame with date and value columns.
            lmbda: Box-Cox parameter. If None, it's estimated.

        Returns:
            DataFrame with Box-Cox transformed values.
        """
        if not HAS_SCIPY:
            raise ImportError(
                "scipy is required for Box-Cox transform. Install with: pip install scipy"
            )

        series = self._get_series_as_indexed(df)

        if (series <= 0).any():
            offset = abs(series.min()) + 1 if (series < 0).any() else 0
            series = series + offset

        if lmbda is None:
            transformed, fitted_lambda = stats.boxcox(series.values)
        else:
            transformed = boxcox(series.values, lmbda)
            fitted_lambda = lmbda

        return pd.DataFrame(
            {
                self.date_column: series.index,
                self.value_column: transformed,
            }
        )

    def z_score_normalize(
        self,
        df: pd.DataFrame,
        mean: Optional[float] = None,
        std: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Z-score normalization.

        Args:
            df: Input DataFrame with date and value columns.
            mean: Optional pre-computed mean. If None, computed from data.
            std: Optional pre-computed std. If None, computed from data.

        Returns:
            DataFrame with z-score normalized values.
        """
        series = self._get_series_as_indexed(df)

        if mean is None:
            mean = series.mean()
        if std is None:
            std = series.std()

        if std == 0:
            raise ValueError("Standard deviation is zero. Cannot normalize.")

        normalized = (series - mean) / std

        return pd.DataFrame(
            {
                self.date_column: normalized.index,
                self.value_column: normalized.values,
            }
        )

    # -------------------------------------------------------------------------
    # Rolling Statistics
    # -------------------------------------------------------------------------

    def rolling_mean(
        self,
        df: pd.DataFrame,
        window: int = 12,
        min_periods: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Compute rolling mean (moving average).

        Args:
            df: Input DataFrame with date and value columns.
            window: Window size.
            min_periods: Minimum observations required.

        Returns:
            DataFrame with rolling mean values.
        """
        series = self._get_series_as_indexed(df)
        rolled = series.rolling(window=window, min_periods=min_periods or window).mean()

        return pd.DataFrame(
            {
                self.date_column: rolled.index,
                self.value_column: rolled.values,
            }
        )

    def rolling_std(
        self,
        df: pd.DataFrame,
        window: int = 12,
        min_periods: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Compute rolling standard deviation.

        Args:
            df: Input DataFrame with date and value columns.
            window: Window size.
            min_periods: Minimum observations required.

        Returns:
            DataFrame with rolling std values.
        """
        series = self._get_series_as_indexed(df)
        rolled = series.rolling(window=window, min_periods=min_periods or window).std()

        return pd.DataFrame(
            {
                self.date_column: rolled.index,
                self.value_column: rolled.values,
            }
        )

    def rolling_min_max(
        self,
        df: pd.DataFrame,
        window: int = 12,
        min_periods: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Compute rolling min and max.

        Args:
            df: Input DataFrame with date and value columns.
            window: Window size.
            min_periods: Minimum observations required.

        Returns:
            DataFrame with rolling_min and rolling_max columns.
        """
        series = self._get_series_as_indexed(df)
        rolled_min = series.rolling(window=window, min_periods=min_periods or window).min()
        rolled_max = series.rolling(window=window, min_periods=min_periods or window).max()

        return pd.DataFrame(
            {
                self.date_column: rolled_min.index,
                "rolling_min": rolled_min.values,
                "rolling_max": rolled_max.values,
            }
        )

    def rolling_median(
        self,
        df: pd.DataFrame,
        window: int = 12,
        min_periods: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Compute rolling median.

        Args:
            df: Input DataFrame with date and value columns.
            window: Window size.
            min_periods: Minimum observations required.

        Returns:
            DataFrame with rolling median values.
        """
        series = self._get_series_as_indexed(df)
        rolled = series.rolling(window=window, min_periods=min_periods or window).median()

        return pd.DataFrame(
            {
                self.date_column: rolled.index,
                self.value_column: rolled.values,
            }
        )

    def rolling_percentile(
        self,
        df: pd.DataFrame,
        window: int = 12,
        percentile: float = 50.0,
        min_periods: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Compute rolling percentile.

        Args:
            df: Input DataFrame with date and value columns.
            window: Window size.
            percentile: Percentile to compute (0-100).
            min_periods: Minimum observations required.

        Returns:
            DataFrame with rolling percentile values.
        """
        series = self._get_series_as_indexed(df)
        rolled = series.rolling(window=window, min_periods=min_periods or window).quantile(
            percentile / 100.0
        )

        return pd.DataFrame(
            {
                self.date_column: rolled.index,
                self.value_column: rolled.values,
            }
        )

    # -------------------------------------------------------------------------
    # Seasonal Decomposition
    # -------------------------------------------------------------------------

    def seasonal_decompose(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None,
        model: str = "additive",
    ) -> Dict[str, pd.DataFrame]:
        """
        Perform STL decomposition using statsmodels.

        Args:
            df: Input DataFrame with date and value columns.
            period: Seasonal period. If None, inferred from frequency.
            model: 'additive' or 'multiplicative'.

        Returns:
            Dictionary with 'trend', 'seasonal', 'residual' DataFrames.
        """
        series = self._get_series_as_indexed(df)

        if series.isnull().any():
            series = series.ffill().bfill()

        if period is None:
            inferred = pd.infer_freq(series.index)
            if inferred:
                freq_map = {"M": 12, "Q": 4, "W": 52, "D": 7, "A": 1}
                period = freq_map.get(inferred[0], 12)
            else:
                period = 12

        if model == "multiplicative" and (series <= 0).any():
            warnings.warn("Multiplicative model requires positive values. Using additive.")
            model = "additive"

        stl = STL(series, period=period, robust=True)
        result = stl.fit()

        return {
            "observed": pd.DataFrame(
                {
                    self.date_column: series.index,
                    self.value_column: series.values,
                }
            ),
            "trend": pd.DataFrame(
                {
                    self.date_column: series.index,
                    self.value_column: result.trend,
                }
            ),
            "seasonal": pd.DataFrame(
                {
                    self.date_column: series.index,
                    self.value_column: result.seasonal,
                }
            ),
            "residual": pd.DataFrame(
                {
                    self.date_column: series.index,
                    self.value_column: result.resid,
                }
            ),
        }

    def seasonal_adjust(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Apply seasonal adjustment (X-13ARIMA-SEATS style).

        Args:
            df: Input DataFrame with date and value columns.
            period: Seasonal period.

        Returns:
            DataFrame with seasonally adjusted values.
        """
        decomposition = self.seasonal_decompose(df, period=period)

        seasonal = decomposition["seasonal"].set_index(self.date_column)[self.value_column]
        original = self._get_series_as_indexed(df)

        adjusted = original - seasonal

        return pd.DataFrame(
            {
                self.date_column: adjusted.index,
                self.value_column: adjusted.values,
            }
        )

    def extract_trend(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None,
    ) -> pd.DataFrame:
        """Extract trend component from decomposition."""
        decomposition = self.seasonal_decompose(df, period=period)
        return decomposition["trend"]

    def extract_seasonal(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None,
    ) -> pd.DataFrame:
        """Extract seasonal component from decomposition."""
        decomposition = self.seasonal_decompose(df, period=period)
        return decomposition["seasonal"]

    def extract_resid(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None,
    ) -> pd.DataFrame:
        """Extract residual component from decomposition."""
        decomposition = self.seasonal_decompose(df, period=period)
        return decomposition["residual"]

    # -------------------------------------------------------------------------
    # Temporal Features
    # -------------------------------------------------------------------------

    def add_time_features(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Add temporal features: month, quarter, year, day_of_week.

        Args:
            df: Input DataFrame with date column.

        Returns:
            DataFrame with additional time feature columns.
        """
        df = df.copy()

        if self.date_column not in df.columns:
            df = self._ensure_value_column(df)

        dates = pd.to_datetime(df[self.date_column])

        df["month"] = dates.dt.month
        df["quarter"] = dates.dt.quarter
        df["year"] = dates.dt.year
        df["day_of_week"] = dates.dt.dayofweek
        df["day_of_month"] = dates.dt.day
        df["week_of_year"] = dates.dt.isocalendar().week.astype(int)
        df["is_month_start"] = dates.dt.is_month_start.astype(int)
        df["is_month_end"] = dates.dt.is_month_end.astype(int)
        df["is_quarter_start"] = dates.dt.is_quarter_start.astype(int)
        df["is_quarter_end"] = dates.dt.is_quarter_end.astype(int)

        return df

    def add_lag_features(
        self,
        df: pd.DataFrame,
        lags: List[int] = None,
        drop_na: bool = True,
    ) -> pd.DataFrame:
        """
        Add lagged values as features.

        Args:
            df: Input DataFrame with date and value columns.
            lags: List of lag periods (e.g., [1, 3, 6, 12]).
            drop_na: Drop rows with NaN values.

        Returns:
            DataFrame with lag columns.
        """
        df = df.copy()

        if lags is None:
            lags = [1, 3, 6, 12]

        series = self._get_series_as_indexed(df)

        for lag in lags:
            df[f"lag_{lag}"] = series.shift(lag).values

        if drop_na:
            df = df.dropna()

        return df

    def add_ewm_features(
        self,
        df: pd.DataFrame,
        spans: List[int] = None,
        alpha: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Add exponential weighted moving features.

        Args:
            df: Input DataFrame with date and value columns.
            spans: List of spans for EWM (e.g., [3, 6, 12]).
            alpha: Smoothing factor. If provided, used instead of span.

        Returns:
            DataFrame with EWM columns.
        """
        df = df.copy()

        if spans is None:
            spans = [3, 6, 12]

        series = self._get_series_as_indexed(df)

        if alpha is not None:
            ewm = series.ewm(alpha=alpha)
            df["ewm_alpha"] = ewm.mean().values
        else:
            for span in spans:
                ewm = series.ewm(span=span)
                df[f"ewm_{span}"] = ewm.mean().values

        return df

    # -------------------------------------------------------------------------
    # Aggregation / Resampling
    # -------------------------------------------------------------------------

    def resample_daily(
        self,
        df: pd.DataFrame,
        agg_method: str = "last",
    ) -> pd.DataFrame:
        """
        Convert to daily frequency.

        Args:
            df: Input DataFrame with date and value columns.
            agg_method: Aggregation method ('last', 'mean', 'sum', 'first', 'max', 'min').

        Returns:
            DataFrame resampled to daily frequency.
        """
        series = self._get_series_as_indexed(df)

        agg_map = {
            "last": "last",
            "mean": "mean",
            "sum": "sum",
            "first": "first",
            "max": "max",
            "min": "min",
        }

        resampled = series.resample("D").agg(agg_map.get(agg_method, "last"))
        resampled = resampled.dropna()

        return pd.DataFrame(
            {
                self.date_column: resampled.index,
                self.value_column: resampled.values,
            }
        )

    def resample_weekly(
        self,
        df: pd.DataFrame,
        agg_method: str = "last",
    ) -> pd.DataFrame:
        """Convert to weekly frequency."""
        series = self._get_series_as_indexed(df)

        agg_map = {
            "last": "last",
            "mean": "mean",
            "sum": "sum",
            "first": "first",
            "max": "max",
            "min": "min",
        }

        resampled = series.resample("W").agg(agg_map.get(agg_method, "last"))
        resampled = resampled.dropna()

        return pd.DataFrame(
            {
                self.date_column: resampled.index,
                self.value_column: resampled.values,
            }
        )

    def resample_monthly(
        self,
        df: pd.DataFrame,
        agg_method: str = "last",
    ) -> pd.DataFrame:
        """Convert to monthly frequency."""
        series = self._get_series_as_indexed(df)

        agg_map = {
            "last": "last",
            "mean": "mean",
            "sum": "sum",
            "first": "first",
            "max": "max",
            "min": "min",
        }

        resampled = series.resample("ME").agg(agg_map.get(agg_method, "last"))
        resampled = resampled.dropna()

        return pd.DataFrame(
            {
                self.date_column: resampled.index,
                self.value_column: resampled.values,
            }
        )

    def resample_quarterly(
        self,
        df: pd.DataFrame,
        agg_method: str = "last",
    ) -> pd.DataFrame:
        """Convert to quarterly frequency."""
        series = self._get_series_as_indexed(df)

        agg_map = {
            "last": "last",
            "mean": "mean",
            "sum": "sum",
            "first": "first",
            "max": "max",
            "min": "min",
        }

        resampled = series.resample("QE").agg(agg_map.get(agg_method, "last"))
        resampled = resampled.dropna()

        return pd.DataFrame(
            {
                self.date_column: resampled.index,
                self.value_column: resampled.values,
            }
        )

    def resample_annual(
        self,
        df: pd.DataFrame,
        agg_method: str = "last",
    ) -> pd.DataFrame:
        """Convert to annual frequency."""
        series = self._get_series_as_indexed(df)

        agg_map = {
            "last": "last",
            "mean": "mean",
            "sum": "sum",
            "first": "first",
            "max": "max",
            "min": "min",
        }

        resampled = series.resample("YE").agg(agg_map.get(agg_method, "last"))
        resampled = resampled.dropna()

        return pd.DataFrame(
            {
                self.date_column: resampled.index,
                self.value_column: resampled.values,
            }
        )

    # -------------------------------------------------------------------------
    # Database Integration
    # -------------------------------------------------------------------------

    def save_features_to_db(
        self,
        df: pd.DataFrame,
        series_id: str,
        feature_columns: Optional[List[str]] = None,
    ) -> int:
        """
        Save computed features to fred_features table.

        Args:
            df: DataFrame with features. Must have date column.
            series_id: FRED series identifier (e.g., 'UNRATE').
            feature_columns: Columns to save. If None, saves all except date column.

        Returns:
            Number of rows inserted.
        """
        if self._engine is None:
            raise RuntimeError(
                "Database not initialized. Provide db_connection to constructor or call set_db_connection()."
            )

        df = df.copy()

        if self.date_column not in df.columns:
            df = self._ensure_value_column(df)

        if feature_columns is None:
            feature_columns = [c for c in df.columns if c != self.date_column]

        records = []
        for _, row in df.iterrows():
            date_val = row[self.date_column]
            for feature in feature_columns:
                records.append(
                    {
                        "series_id": series_id,
                        "feature_name": feature,
                        "feature_value": row[feature],
                        "observation_date": pd.to_datetime(date_val),
                    }
                )

        if records:
            insert_sql = """
            INSERT OR REPLACE INTO fred_features 
            (series_id, feature_name, feature_value, observation_date)
            VALUES (:series_id, :feature_name, :feature_value, :observation_date)
            """

            with self._engine.connect() as conn:
                conn.execute(text(insert_sql), records)
                conn.commit()

            return len(records)

        return 0

    def load_features_from_db(
        self,
        series_id: str,
        feature_names: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load features from database.

        Args:
            series_id: FRED series identifier.
            feature_names: Specific features to load. If None, loads all.
            start_date: Start date filter (YYYY-MM-DD).
            end_date: End date filter (YYYY-MM-DD).

        Returns:
            DataFrame with features.
        """
        if self._engine is None:
            raise RuntimeError("Database not initialized.")

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

        pivot_df.columns = [
            self.date_column if c == "observation_date" else c for c in pivot_df.columns
        ]

        return pivot_df

    def set_db_connection(self, connection_string: str) -> None:
        """Set database connection after initialization."""
        self._init_db(connection_string)

    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------

    def compute_all_features(
        self,
        df: pd.DataFrame,
        lags: List[int] = None,
        rolling_windows: List[int] = None,
        ewm_spans: List[int] = None,
    ) -> pd.DataFrame:
        """
        Compute a comprehensive feature set.

        Args:
            df: Input DataFrame with date and value columns.
            lags: Lags for lag features.
            rolling_windows: Windows for rolling statistics.
            ewm_spans: Spans for EWM features.

        Returns:
            DataFrame with all computed features.
        """
        df = df.copy()

        if lags is None:
            lags = [1, 3, 6, 12]
        if rolling_windows is None:
            rolling_windows = [3, 6, 12]
        if ewm_spans is None:
            ewm_spans = [3, 6, 12]

        series = self._get_series_as_indexed(df)

        df["diff_1"] = series.diff(1).values
        df["diff_12"] = series.diff(12).values
        df["pct_change_1"] = series.pct_change(1).values
        df["pct_change_12"] = series.pct_change(12).values

        for window in rolling_windows:
            df[f"rolling_mean_{window}"] = series.rolling(window).mean().values
            df[f"rolling_std_{window}"] = series.rolling(window).std().values
            df[f"rolling_min_{window}"] = series.rolling(window).min().values
            df[f"rolling_max_{window}"] = series.rolling(window).max().values

        for span in ewm_spans:
            df[f"ewm_{span}"] = series.ewm(span=span).mean().values

        df = self.add_lag_features(df, lags=lags, drop_na=False)
        df = self.add_time_features(df)

        df = df.fillna(method="bfill").fillna(method="ffill")

        return df


def create_fred_transformer(
    db_path: str = "data/fred_features.db",
) -> FredTransformer:
    """
    Factory function to create a FredTransformer with SQLite backend.

    Args:
        db_path: Path to SQLite database file.

    Returns:
        Configured FredTransformer instance.
    """
    return FredTransformer(db_connection=db_path)
