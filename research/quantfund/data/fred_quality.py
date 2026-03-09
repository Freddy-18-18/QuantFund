"""
FRED Data Quality Control Module

Comprehensive data quality checking, outlier detection, and imputation
for FRED economic time series data.

Usage:
    from quantfund.data.fred_quality import (
        FredQualityController,
        detect_missing_values,
        zscore_outliers,
        generate_quality_report
    )

    qc = FredQualityController(db_connection)
    report = qc.generate_quality_report("UNRATE")
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import sql
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


class AnomalySeverity(str, Enum):
    """Severity levels for anomalies."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Frequency(str, Enum):
    """FRED data frequencies."""

    DAILY = "d"
    WEEKLY = "w"
    BIWEEKLY = "bw"
    MONTHLY = "m"
    QUARTERLY = "q"
    SEMIANNUAL = "sa"
    ANNUAL = "a"

    @classmethod
    def from_string(cls, freq: str) -> "Frequency":
        """Convert string to Frequency enum."""
        mapping = {
            "d": cls.DAILY,
            "w": cls.WEEKLY,
            "bw": cls.BIWEEKLY,
            "m": cls.MONTHLY,
            "q": cls.QUARTERLY,
            "sa": cls.SEMIANNUAL,
            "a": cls.ANNUAL,
        }
        return mapping.get(freq.lower(), cls.MONTHLY)

    def get_date_range(self, start: date, end: date) -> pd.DatetimeIndex:
        """Generate expected date range for this frequency."""
        if self == self.DAILY:
            return pd.date_range(start, end, freq="D")
        elif self == self.WEEKLY:
            return pd.date_range(start, end, freq="W")
        elif self == self.BIWEEKLY:
            return pd.date_range(start, end, freq="2W")
        elif self == self.MONTHLY:
            return pd.date_range(start, end, freq="MS")
        elif self == self.QUARTERLY:
            return pd.date_range(start, end, freq="QS")
        elif self == self.SEMIANNUAL:
            return pd.date_range(start, end, freq="6MS")
        elif self == self.ANNUAL:
            return pd.date_range(start, end, freq="YS")
        return pd.date_range(start, end, freq="D")


@dataclass
class MissingValueGap:
    """Represents a gap in time series data."""

    expected_date: date
    previous_date: Optional[date]
    gap_days: int


@dataclass
class DataQualityResult:
    """Result of data quality checks."""

    series_id: str
    total_observations: int
    missing_count: int
    duplicate_count: int
    consistency_issues: List[str]
    value_range_issues: List[Dict[str, Any]]
    gaps: List[MissingValueGap]
    start_date: Optional[date]
    end_date: Optional[date]
    frequency: Optional[str]
    is_valid: bool
    issues_summary: str


@dataclass
class OutlierResult:
    """Result of outlier detection."""

    method: str
    outlier_dates: List[date]
    outlier_values: List[float]
    scores: List[float]
    severity: List[AnomalySeverity]
    count: int


@dataclass
class CombinedOutlierResult:
    """Combined results from all outlier detection methods."""

    series_id: str
    zscore_outliers: OutlierResult
    mad_outliers: OutlierResult
    iqr_outliers: OutlierResult
    isolation_forest_outliers: OutlierResult
    consensus_outliers: List[Dict[str, Any]]
    consensus_count: int


@dataclass
class ImputationResult:
    """Result of data imputation."""

    method: str
    imputed_count: int
    imputed_dates: List[date]
    imputed_values: List[float]
    data_before: pd.DataFrame
    data_after: pd.DataFrame


@dataclass
class QualityReport:
    """Comprehensive quality report."""

    series_id: str
    generated_at: pd.Timestamp
    data_quality: DataQualityResult
    outliers: CombinedOutlierResult
    imputation_applied: Optional[ImputationResult]
    recommendations: List[str]
    db_saved: bool


class DatabaseConnection:
    """Database connection manager."""

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


class FrequencyDetector:
    """Detect frequency from date range."""

    @staticmethod
    def detect(df: pd.DataFrame) -> Frequency:
        """Detect frequency from DataFrame."""
        if len(df) < 2:
            return Frequency.MONTHLY

        df_sorted = df.sort_values("date")
        dates = pd.to_datetime(df_sorted["date"])
        diffs = dates.diff().dropna()

        if len(diffs) == 0:
            return Frequency.MONTHLY

        median_diff = diffs.median()
        days = median_diff.days

        if days <= 1:
            return Frequency.DAILY
        elif days <= 8:
            return Frequency.WEEKLY
        elif days <= 16:
            return Frequency.BIWEEKLY
        elif days <= 35:
            return Frequency.MONTHLY
        elif days <= 100:
            return Frequency.QUARTERLY
        elif days <= 200:
            return Frequency.SEMIANNUAL
        else:
            return Frequency.ANNUAL


class QualityChecker:
    """Base class for quality checks."""

    @staticmethod
    def detect_missing_values(
        df: pd.DataFrame, frequency: Optional[Frequency] = None
    ) -> Tuple[List[MissingValueGap], pd.DataFrame]:
        """
        Identify gaps in time series (real vs expected dates).

        Args:
            df: DataFrame with 'date' and 'value' columns
            frequency: Data frequency. If None, auto-detected.

        Returns:
            Tuple of (list of MissingValueGap, DataFrame with expected dates)
        """
        if df.empty or "date" not in df.columns or "value" not in df.columns:
            return [], df

        df_sorted = df.sort_values("date").copy()
        df_sorted["date"] = pd.to_datetime(df_sorted["date"])

        if frequency is None:
            frequency = FrequencyDetector.detect(df_sorted)

        start_date = df_sorted["date"].min()
        end_date = df_sorted["date"].max()

        expected_dates = frequency.get_date_range(start_date, end_date)

        existing_dates = set(df_sorted["date"].dt.date)
        expected_set = set(expected_dates.date)

        missing_dates = expected_set - existing_dates

        gaps = []
        all_dates = sorted(existing_dates | missing_dates)

        for missing_date in sorted(missing_dates):
            idx = all_dates.index(missing_date)
            prev_date = all_dates[idx - 1] if idx > 0 else None
            gap_days = (missing_date - prev_date).days if prev_date else 0

            gaps.append(
                MissingValueGap(
                    expected_date=missing_date,
                    previous_date=prev_date,
                    gap_days=gap_days,
                )
            )

        full_df = pd.DataFrame({"date": expected_dates})
        full_df = full_df.merge(df_sorted[["date", "value"]], on="date", how="left")

        return gaps, full_df

    @staticmethod
    def check_data_consistency(
        df: pd.DataFrame, frequency: Optional[Frequency] = None
    ) -> List[str]:
        """
        Verify dates are consecutive per frequency.

        Args:
            df: DataFrame with 'date' column
            frequency: Expected frequency. If None, auto-detected.

        Returns:
            List of consistency issues
        """
        issues = []

        if df.empty or "date" not in df.columns:
            issues.append("DataFrame is empty or missing 'date' column")
            return issues

        df_sorted = df.sort_values("date").copy()
        df_sorted["date"] = pd.to_datetime(df_sorted["date"])

        if frequency is None:
            frequency = FrequencyDetector.detect(df_sorted)

        dates = df_sorted["date"]
        diffs = dates.diff().dropna()

        if len(diffs) == 0:
            return issues

        expected_freq = {
            Frequency.DAILY: timedelta(days=1),
            Frequency.WEEKLY: timedelta(days=7),
            Frequency.BIWEEKLY: timedelta(days=14),
            Frequency.MONTHLY: pd.DateOffset(months=1),
            Frequency.QUARTERLY: pd.DateOffset(months=3),
            Frequency.SEMIANNUAL: pd.DateOffset(months=6),
            Frequency.ANNUAL: pd.DateOffset(years=1),
        }

        expected_delta = expected_freq.get(frequency, timedelta(days=1))

        for i, diff in enumerate(diffs):
            actual_delta = diff
            if isinstance(expected_delta, pd.DateOffset):
                if not (
                    actual_delta >= expected_delta - pd.Timedelta(days=1)
                    and actual_delta <= expected_delta + pd.Timedelta(days=1)
                ):
                    issues.append(
                        f"Gap at index {i + 1}: expected ~{expected_delta}, got {actual_delta}"
                    )
            else:
                if abs(actual_delta - expected_delta) > timedelta(days=1):
                    issues.append(
                        f"Gap at index {i + 1}: expected {expected_delta}, got {actual_delta}"
                    )

        return issues

    @staticmethod
    def detect_duplicates(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Find duplicate observations.

        Args:
            df: DataFrame with 'date' column

        Returns:
            List of duplicate entries with details
        """
        if df.empty or "date" not in df.columns:
            return []

        df_sorted = df.sort_values("date").copy()
        duplicates = df_sorted[df_sorted.duplicated(subset=["date"], keep=False)]

        result = []
        for date_val in duplicates["date"].unique():
            mask = df_sorted["date"] == date_val
            rows = df_sorted[mask]
            if len(rows) > 1:
                result.append(
                    {
                        "date": pd.to_datetime(date_val),
                        "count": len(rows),
                        "indices": rows.index.tolist(),
                        "values": rows["value"].tolist() if "value" in rows.columns else [],
                    }
                )

        return result

    @staticmethod
    def validate_value_ranges(
        df: pd.DataFrame,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        allow_nulls: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Check if values are within reasonable bounds.

        Args:
            df: DataFrame with 'value' column
            min_value: Minimum acceptable value
            max_value: Maximum acceptable value
            allow_nulls: Whether to allow null values

        Returns:
            List of range violations
        """
        issues = []

        if df.empty or "value" not in df.columns:
            return issues

        df_sorted = df.sort_values("date").copy()

        if not allow_nulls:
            null_mask = df_sorted["value"].isna()
            null_indices = df_sorted[null_mask].index.tolist()
            if null_indices:
                issues.append(
                    {
                        "type": "null_values",
                        "count": len(null_indices),
                        "dates": df_sorted.loc[null_indices, "date"].tolist(),
                    }
                )

        if min_value is not None:
            below_min = df_sorted[df_sorted["value"] < min_value]
            if not below_min.empty:
                issues.append(
                    {
                        "type": "below_minimum",
                        "min_value": min_value,
                        "count": len(below_min),
                        "dates": below_min["date"].tolist(),
                        "values": below_min["value"].tolist(),
                    }
                )

        if max_value is not None:
            above_max = df_sorted[df_sorted["value"] > max_value]
            if not above_max.empty:
                issues.append(
                    {
                        "type": "above_maximum",
                        "max_value": max_value,
                        "count": len(above_max),
                        "dates": above_max["date"].tolist(),
                        "values": above_max["value"].tolist(),
                    }
                )

        return issues


class OutlierDetector:
    """Base class for outlier detection methods."""

    @staticmethod
    def _calculate_severity(score: float, method: str) -> AnomalySeverity:
        """Calculate severity based on score and method."""
        if method == "zscore":
            abs_score = abs(score)
            if abs_score > 5:
                return AnomalySeverity.CRITICAL
            elif abs_score > 4:
                return AnomalySeverity.HIGH
            elif abs_score > 3:
                return AnomalySeverity.MEDIUM
            return AnomalySeverity.LOW

        elif method == "mad":
            if score > 5:
                return AnomalySeverity.CRITICAL
            elif score > 3.5:
                return AnomalySeverity.HIGH
            elif score > 2.5:
                return AnomalySeverity.MEDIUM
            return AnomalySeverity.LOW

        elif method == "iqr":
            if score > 3:
                return AnomalySeverity.CRITICAL
            elif score > 2:
                return AnomalySeverity.HIGH
            elif score > 1.5:
                return AnomalySeverity.MEDIUM
            return AnomalySeverity.LOW

        elif method == "isolation_forest":
            if score < -0.9:
                return AnomalySeverity.CRITICAL
            elif score < -0.7:
                return AnomalySeverity.HIGH
            elif score < -0.5:
                return AnomalySeverity.MEDIUM
            return AnomalySeverity.LOW

        return AnomalySeverity.LOW

    @staticmethod
    def zscore_outliers(df: pd.DataFrame, threshold: float = 3.0) -> OutlierResult:
        """
        Detect values > 3 standard deviations from mean.

        Args:
            df: DataFrame with 'date' and 'value' columns
            threshold: Z-score threshold (default 3.0)

        Returns:
            OutlierResult with detected outliers
        """
        if df.empty or "value" not in df.columns:
            return OutlierResult("zscore", [], [], [], [], 0)

        df_sorted = df.sort_values("date").copy()
        values = df_sorted["value"].dropna()

        if len(values) < 3:
            return OutlierResult("zscore", [], [], [], [], 0)

        mean = values.mean()
        std = values.std()

        if std == 0:
            return OutlierResult("zscore", [], [], [], [], 0)

        z_scores = (values - mean) / std

        outlier_mask = np.abs(z_scores) > threshold
        outlier_indices = z_scores[outlier_mask].index

        outlier_dates = df_sorted.loc[outlier_indices, "date"].tolist()
        outlier_values = df_sorted.loc[outlier_indices, "value"].tolist()
        scores = z_scores[outlier_mask].tolist()
        severity = [OutlierDetector._calculate_severity(s, "zscore") for s in scores]

        return OutlierResult(
            method="zscore",
            outlier_dates=outlier_dates,
            outlier_values=outlier_values,
            scores=scores,
            severity=severity,
            count=len(outlier_dates),
        )

    @staticmethod
    def mad_outliers(df: pd.DataFrame, threshold: float = 3.5) -> OutlierResult:
        """
        Median Absolute Deviation method (more robust).

        Args:
            df: DataFrame with 'date' and 'value' columns
            threshold: MAD threshold (default 3.5)

        Returns:
            OutlierResult with detected outliers
        """
        if df.empty or "value" not in df.columns:
            return OutlierResult("mad", [], [], [], [], 0)

        df_sorted = df.sort_values("date").copy()
        values = df_sorted["value"].dropna()

        if len(values) < 3:
            return OutlierResult("mad", [], [], [], [], 0)

        median = values.median()
        mad = (values - median).abs().median()

        if mad == 0:
            return OutlierResult("mad", [], [], [], [], 0)

        modified_z_scores = 0.6745 * (values - median) / mad

        outlier_mask = np.abs(modified_z_scores) > threshold
        outlier_indices = modified_z_scores[outlier_mask].index

        outlier_dates = df_sorted.loc[outlier_indices, "date"].tolist()
        outlier_values = df_sorted.loc[outlier_indices, "value"].tolist()
        scores = modified_z_scores[outlier_mask].tolist()
        severity = [OutlierDetector._calculate_severity(s, "mad") for s in scores]

        return OutlierResult(
            method="mad",
            outlier_dates=outlier_dates,
            outlier_values=outlier_values,
            scores=scores,
            severity=severity,
            count=len(outlier_dates),
        )

    @staticmethod
    def iqr_outliers(df: pd.DataFrame, multiplier: float = 1.5) -> OutlierResult:
        """
        Interquartile Range method.

        Args:
            df: DataFrame with 'date' and 'value' columns
            multiplier: IQR multiplier (default 1.5)

        Returns:
            OutlierResult with detected outliers
        """
        if df.empty or "value" not in df.columns:
            return OutlierResult("iqr", [], [], [], [], 0)

        df_sorted = df.sort_values("date").copy()
        values = df_sorted["value"].dropna()

        if len(values) < 4:
            return OutlierResult("iqr", [], [], [], [], 0)

        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1

        if iqr == 0:
            return OutlierResult("iqr", [], [], [], [], 0)

        lower_bound = q1 - multiplier * iqr
        upper_bound = q3 + multiplier * iqr

        outlier_mask = (values < lower_bound) | (values > upper_bound)
        outlier_indices = values[outlier_mask].index

        outlier_dates = df_sorted.loc[outlier_indices, "date"].tolist()
        outlier_values = df_sorted.loc[outlier_indices, "value"].tolist()

        scores = []
        for val in outlier_values:
            if val < lower_bound:
                scores.append((val - lower_bound) / iqr)
            else:
                scores.append((val - upper_bound) / iqr)

        severity = [OutlierDetector._calculate_severity(abs(s), "iqr") for s in scores]

        return OutlierResult(
            method="iqr",
            outlier_dates=outlier_dates,
            outlier_values=outlier_values,
            scores=scores,
            severity=severity,
            count=len(outlier_dates),
        )

    @staticmethod
    def isolation_forest_outliers(
        df: pd.DataFrame, contamination: float = 0.1, random_state: int = 42
    ) -> OutlierResult:
        """
        Machine learning based outlier detection using Isolation Forest.

        Args:
            df: DataFrame with 'date' and 'value' columns
            contamination: Expected proportion of outliers (0.0 to 0.5)
            random_state: Random seed for reproducibility

        Returns:
            OutlierResult with detected outliers
        """
        if df.empty or "value" not in df.columns:
            return OutlierResult("isolation_forest", [], [], [], [], 0)

        df_sorted = df.sort_values("date").copy()
        values = df_sorted["value"].dropna()

        if len(values) < 10:
            return OutlierResult("isolation_forest", [], [], [], [], 0)

        X = values.values.reshape(-1, 1)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        iso_forest = IsolationForest(
            contamination=contamination,
            random_state=random_state,
            n_estimators=100,
        )
        predictions = iso_forest.fit_predict(X_scaled)
        scores = iso_forest.score_samples(X_scaled)

        outlier_mask = predictions == -1
        outlier_indices = values[outlier_mask].index

        outlier_dates = df_sorted.loc[outlier_indices, "date"].tolist()
        outlier_values = df_sorted.loc[outlier_indices, "value"].tolist()
        outlier_scores = scores[outlier_mask].tolist()
        severity = [
            OutlierDetector._calculate_severity(s, "isolation_forest") for s in outlier_scores
        ]

        return OutlierResult(
            method="isolation_forest",
            outlier_dates=outlier_dates,
            outlier_values=outlier_values,
            scores=outlier_scores,
            severity=severity,
            count=len(outlier_dates),
        )

    @staticmethod
    def detect_all_outliers(df: pd.DataFrame, series_id: str = "unknown") -> CombinedOutlierResult:
        """
        Run all outlier detection methods and combine results.

        Args:
            df: DataFrame with 'date' and 'value' columns
            series_id: Series identifier

        Returns:
            CombinedOutlierResult with all methods' results
        """
        zscore_result = OutlierDetector.zscore_outliers(df)
        mad_result = OutlierDetector.mad_outliers(df)
        iqr_result = OutlierDetector.iqr_outliers(df)
        iforest_result = OutlierDetector.isolation_forest_outliers(df)

        date_to_outliers = {}

        for result in [zscore_result, mad_result, iqr_result, iforest_result]:
            for date, value, score, severity in zip(
                result.outlier_dates,
                result.outlier_values,
                result.scores,
                result.severity,
            ):
                date_key = pd.to_datetime(date)
                if date_key not in date_to_outliers:
                    date_to_outliers[date_key] = {
                        "date": date,
                        "value": value,
                        "methods": [],
                        "scores": [],
                        "severities": [],
                    }
                date_to_outliers[date_key]["methods"].append(result.method)
                date_to_outliers[date_key]["scores"].append(score)
                date_to_outliers[date_key]["severities"].append(severity)

        consensus_outliers = []
        for date_key, data in date_to_outliers.items():
            max_severity = max(
                data["severities"],
                key=lambda s: [
                    AnomalySeverity.LOW,
                    AnomalySeverity.MEDIUM,
                    AnomalySeverity.HIGH,
                    AnomalySeverity.CRITICAL,
                ].index(s),
            )
            consensus_outliers.append(
                {
                    "date": data["date"],
                    "value": data["value"],
                    "methods": data["methods"],
                    "scores": data["scores"],
                    "max_severity": max_severity,
                    "method_count": len(data["methods"]),
                }
            )

        consensus_outliers.sort(
            key=lambda x: [
                AnomalySeverity.LOW,
                AnomalySeverity.MEDIUM,
                AnomalySeverity.HIGH,
                AnomalySeverity.CRITICAL,
            ].index(x["max_severity"]),
            reverse=True,
        )

        return CombinedOutlierResult(
            series_id=series_id,
            zscore_outliers=zscore_result,
            mad_outliers=mad_result,
            iqr_outliers=iqr_result,
            isolation_forest_outliers=iforest_result,
            consensus_outliers=consensus_outliers,
            consensus_count=len(consensus_outliers),
        )


class DataImputer:
    """Data imputation methods."""

    @staticmethod
    def linear_interpolate(df: pd.DataFrame, limit_direction: str = "both") -> ImputationResult:
        """
        Linear interpolation for missing values.

        Args:
            df: DataFrame with 'date' and 'value' columns
            limit_direction: Direction for interpolation ('both', 'forward', 'backward')

        Returns:
            ImputationResult with imputation details
        """
        if df.empty or "value" not in df.columns:
            return ImputationResult("linear_interpolate", 0, [], [], df, df)

        df_sorted = df.sort_values("date").copy()
        df_sorted["date"] = pd.to_datetime(df_sorted["date"])
        df_sorted = df_sorted.set_index("date")

        missing_before = df_sorted["value"].isna().sum()

        df_sorted["value"] = df_sorted["value"].interpolate(
            method="linear", limit_direction=limit_direction
        )

        missing_after = df_sorted["value"].isna().sum()
        imputed_count = missing_before - missing_after

        imputed_mask = df_sorted["value"].notna() & (
            df_sorted["value"].index.isin(df_sorted[df_sorted["value"].isna()].index) == False
        )

        df_sorted = df_sorted.reset_index()

        imputed_dates = []
        imputed_values = []

        original_missing = df["value"].isna()
        if hasattr(original_missing, "index"):
            imputed_indices = original_missing[~original_missing].index
            if len(imputed_indices) > 0 and len(df_sorted) > max(imputed_indices):
                for idx in imputed_indices:
                    if idx < len(df_sorted):
                        imputed_dates.append(df_sorted.loc[idx, "date"])
                        imputed_values.append(df_sorted.loc[idx, "value"])

        return ImputationResult(
            method="linear_interpolate",
            imputed_count=imputed_count,
            imputed_dates=imputed_dates[:imputed_count]
            if len(imputed_dates) > imputed_count
            else imputed_dates,
            imputed_values=imputed_values[:imputed_count]
            if len(imputed_values) > imputed_count
            else imputed_values,
            data_before=df,
            data_after=df_sorted,
        )

    @staticmethod
    def forward_fill(df: pd.DataFrame) -> ImputationResult:
        """
        Forward fill missing values.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            ImputationResult with imputation details
        """
        if df.empty or "value" not in df.columns:
            return ImputationResult("forward_fill", 0, [], [], df, df)

        df_sorted = df.sort_values("date").copy()
        df_sorted["date"] = pd.to_datetime(df_sorted["date"])

        missing_before = df_sorted["value"].isna().sum()

        df_sorted["value"] = df_sorted["value"].ffill()

        imputed_count = missing_before - df_sorted["value"].isna().sum()

        imputed_dates = (
            df_sorted[df_sorted["value"].notna()].iloc[-imputed_count:]["date"].tolist()
            if imputed_count > 0
            else []
        )
        imputed_values = (
            df_sorted[df_sorted["value"].notna()].iloc[-imputed_count:]["value"].tolist()
            if imputed_count > 0
            else []
        )

        return ImputationResult(
            method="forward_fill",
            imputed_count=imputed_count,
            imputed_dates=imputed_dates,
            imputed_values=imputed_values,
            data_before=df,
            data_after=df_sorted,
        )

    @staticmethod
    def backward_fill(df: pd.DataFrame) -> ImputationResult:
        """
        Backward fill missing values.

        Args:
            df: DataFrame with 'date' and 'value' columns

        Returns:
            ImputationResult with imputation details
        """
        if df.empty or "value" not in df.columns:
            return ImputationResult("backward_fill", 0, [], [], df, df)

        df_sorted = df.sort_values("date").copy()
        df_sorted["date"] = pd.to_datetime(df_sorted["date"])

        missing_before = df_sorted["value"].isna().sum()

        df_sorted["value"] = df_sorted["value"].bfill()

        imputed_count = missing_before - df_sorted["value"].isna().sum()

        imputed_dates = (
            df_sorted[df_sorted["value"].notna()].iloc[:imputed_count]["date"].tolist()
            if imputed_count > 0
            else []
        )
        imputed_values = (
            df_sorted[df_sorted["value"].notna()].iloc[:imputed_count]["value"].tolist()
            if imputed_count > 0
            else []
        )

        return ImputationResult(
            method="backward_fill",
            imputed_count=imputed_count,
            imputed_dates=imputed_dates,
            imputed_values=imputed_values,
            data_before=df,
            data_after=df_sorted,
        )

    @staticmethod
    def impute_all(df: pd.DataFrame, frequency: Optional[Frequency] = None) -> ImputationResult:
        """
        Apply appropriate method based on series frequency.

        Args:
            df: DataFrame with 'date' and 'value' columns
            frequency: Data frequency

        Returns:
            ImputationResult
        """
        if df.empty or "value" not in df.columns:
            return ImputationResult("auto", 0, [], [], df, df)

        if frequency is None:
            frequency = FrequencyDetector.detect(df)

        if frequency in [Frequency.MONTHLY, Frequency.QUARTERLY, Frequency.ANNUAL]:
            result = DataImputer.linear_interpolate(df, limit_direction="both")
        elif frequency == Frequency.DAILY:
            result = DataImputer.forward_fill(df)
            if result.imputed_count == 0:
                result = DataImputer.backward_fill(df)
        else:
            result = DataImputer.linear_interpolate(df)

        return result


class AnomalyDatabase:
    """Database operations for anomalies."""

    @staticmethod
    def save_anomalies_to_db(
        db_connection: DatabaseConnection,
        series_id: str,
        outliers: CombinedOutlierResult,
        overwrite: bool = False,
    ) -> int:
        """
        Store detected issues in database.

        Args:
            db_connection: Database connection
            series_id: Series identifier
            outliers: CombinedOutlierResult
            overwrite: Whether to delete existing anomalies first

        Returns:
            Number of records inserted
        """
        conn = db_connection.get_connection()
        cursor = conn.cursor()

        try:
            if overwrite:
                cursor.execute(
                    "DELETE FROM fred_anomalies WHERE series_id = %s",
                    (series_id,),
                )

            inserted = 0
            for outlier in outliers.consensus_outliers:
                date_val = outlier["date"]
                if isinstance(date_val, pd.Timestamp):
                    date_val = date_val.to_pydatetime().date()
                elif isinstance(date_val, str):
                    date_val = pd.to_datetime(date_val).date()

                max_severity = (
                    outlier["max_severity"].value
                    if isinstance(outlier["max_severity"], AnomalySeverity)
                    else outlier["max_severity"]
                )

                max_score = max(outlier["scores"]) if outlier["scores"] else 0

                cursor.execute(
                    """
                    INSERT INTO fred_anomalies 
                    (series_id, date, method, score, severity, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        series_id,
                        date_val,
                        ",".join(outlier["methods"]),
                        max_score,
                        max_severity,
                        f"Detected by {outlier['method_count']} methods",
                    ),
                )
                inserted += 1

            conn.commit()
            return inserted

        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Failed to save anomalies: {e}")
        finally:
            cursor.close()
            conn.close()


class FredQualityController:
    """Main controller for FRED data quality operations."""

    def __init__(self, db_connection: Optional[DatabaseConnection] = None):
        """
        Initialize quality controller.

        Args:
            db_connection: Database connection (optional)
        """
        self.db = db_connection

    def get_series_data(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get series data from database.

        Args:
            series_id: FRED series ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            DataFrame with 'date' and 'value' columns
        """
        if self.db is None:
            raise ValueError("Database connection not configured")

        query = """
            SELECT date, value 
            FROM fred_observations 
            WHERE series_id = %s
        """
        params = [series_id]

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

    def get_series_metadata(self, series_id: str) -> Dict[str, Any]:
        """Get series metadata from database."""
        if self.db is None:
            return {}

        query = "SELECT * FROM fred_series WHERE series_id = %s"
        results = self.db.execute_query(query, (series_id,))

        if not results:
            return {}

        columns = [
            "id",
            "series_id",
            "title",
            "frequency",
            "units",
            "seasonal_adjustment",
            "popularity",
            "notes",
            "last_updated",
            "created_at",
        ]

        return dict(zip(columns, results[0]))

    def generate_quality_report(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save_to_db: bool = True,
        apply_imputation: bool = False,
    ) -> QualityReport:
        """
        Create comprehensive quality report.

        Args:
            series_id: FRED series ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            save_to_db: Whether to save anomalies to database
            apply_imputation: Whether to apply imputation

        Returns:
            Comprehensive QualityReport
        """
        df = self.get_series_data(series_id, start_date, end_date)

        if df.empty:
            return QualityReport(
                series_id=series_id,
                generated_at=pd.Timestamp.now(),
                data_quality=DataQualityResult(
                    series_id=series_id,
                    total_observations=0,
                    missing_count=0,
                    duplicate_count=0,
                    consistency_issues=["No data available"],
                    value_range_issues=[],
                    gaps=[],
                    start_date=None,
                    end_date=None,
                    frequency=None,
                    is_valid=False,
                    issues_summary="No data found for series",
                ),
                outliers=CombinedOutlierResult(
                    series_id=series_id,
                    zscore_outliers=OutlierResult("zscore", [], [], [], [], 0),
                    mad_outliers=OutlierResult("mad", [], [], [], [], 0),
                    iqr_outliers=OutlierResult("iqr", [], [], [], [], 0),
                    isolation_forest_outliers=OutlierResult("isolation_forest", [], [], [], [], 0),
                    consensus_outliers=[],
                    consensus_count=0,
                ),
                imputation_applied=None,
                recommendations=["Check if series ID is correct"],
                db_saved=False,
            )

        metadata = self.get_series_metadata(series_id)
        frequency_str = metadata.get("frequency", "m")
        frequency = Frequency.from_string(frequency_str)

        quality_result = self._run_quality_checks(df, series_id, frequency)

        outlier_result = OutlierDetector.detect_all_outliers(df, series_id)

        imputation_result = None
        if apply_imputation:
            imputation_result = DataImputer.impute_all(df, frequency)

        recommendations = self._generate_recommendations(
            quality_result, outlier_result, imputation_result
        )

        db_saved = False
        if save_to_db and self.db is not None and outlier_result.consensus_count > 0:
            try:
                AnomalyDatabase.save_anomalies_to_db(
                    self.db, series_id, outlier_result, overwrite=True
                )
                db_saved = True
            except Exception as e:
                print(f"Warning: Could not save anomalies to database: {e}")

        return QualityReport(
            series_id=series_id,
            generated_at=pd.Timestamp.now(),
            data_quality=quality_result,
            outliers=outlier_result,
            imputation_applied=imputation_result,
            recommendations=recommendations,
            db_saved=db_saved,
        )

    def _run_quality_checks(
        self,
        df: pd.DataFrame,
        series_id: str,
        frequency: Frequency,
    ) -> DataQualityResult:
        """Run all quality checks."""
        gaps, full_df = QualityChecker.detect_missing_values(df, frequency)

        consistency_issues = QualityChecker.check_data_consistency(df, frequency)

        duplicates = QualityChecker.detect_duplicates(df)

        value_issues = QualityChecker.validate_value_ranges(df)

        return DataQualityResult(
            series_id=series_id,
            total_observations=len(df),
            missing_count=len(gaps),
            duplicate_count=len(duplicates),
            consistency_issues=consistency_issues,
            value_range_issues=value_issues,
            gaps=gaps,
            start_date=df["date"].min().date() if not df.empty else None,
            end_date=df["date"].max().date() if not df.empty else None,
            frequency=frequency.value,
            is_valid=len(consistency_issues) == 0
            and len(gaps) == 0
            and len(duplicates) == 0
            and len(value_issues) == 0,
            issues_summary=self._summarize_issues(
                len(gaps), len(duplicates), consistency_issues, value_issues
            ),
        )

    def _summarize_issues(
        self,
        missing: int,
        duplicates: int,
        consistency: List[str],
        value_issues: List[Dict],
    ) -> str:
        """Summarize issues into a string."""
        parts = []

        if missing > 0:
            parts.append(f"{missing} missing values")
        if duplicates > 0:
            parts.append(f"{duplicates} duplicates")
        if consistency:
            parts.append(f"{len(consistency)} consistency issues")
        if value_issues:
            parts.append(f"{len(value_issues)} value range issues")

        if not parts:
            return "Data quality is good"

        return "; ".join(parts)

    def _generate_recommendations(
        self,
        quality: DataQualityResult,
        outliers: CombinedOutlierResult,
        imputation: Optional[ImputationResult],
    ) -> List[str]:
        """Generate recommendations based on analysis."""
        recommendations = []

        if quality.missing_count > 0:
            recommendations.append(f"Consider imputing {quality.missing_count} missing values")

        if quality.duplicate_count > 0:
            recommendations.append(f"Remove {quality.duplicate_count} duplicate observations")

        if quality.consistency_issues:
            recommendations.append("Review date sequence - there may be gaps in the data")

        if outliers.consensus_count > 0:
            critical = sum(
                1
                for o in outliers.consensus_outliers
                if o["max_severity"] == AnomalySeverity.CRITICAL
            )
            high = sum(
                1 for o in outliers.consensus_outliers if o["max_severity"] == AnomalySeverity.HIGH
            )

            if critical > 0:
                recommendations.append(
                    f"Investigate {critical} critical outliers (possible data errors)"
                )
            if high > 0:
                recommendations.append(f"Review {high} high-severity outliers")

        if imputation and imputation.imputed_count > 0:
            recommendations.append(
                f"Applied {imputation.method} to fill {imputation.imputed_count} values"
            )

        if not recommendations:
            recommendations.append("No issues found - data quality is good")

        return recommendations


def detect_missing_values(
    df: pd.DataFrame, frequency: Optional[str] = None
) -> Tuple[List[MissingValueGap], pd.DataFrame]:
    """
    Identify gaps in time series (real vs expected dates).

    Args:
        df: DataFrame with 'date' and 'value' columns
        frequency: Data frequency string ('d', 'w', 'm', 'q', 'a')

    Returns:
        Tuple of (list of MissingValueGap, DataFrame with expected dates)
    """
    freq = Frequency.from_string(frequency) if frequency else None
    return QualityChecker.detect_missing_values(df, freq)


def check_data_consistency(df: pd.DataFrame, frequency: Optional[str] = None) -> List[str]:
    """
    Verify dates are consecutive per frequency.

    Args:
        df: DataFrame with 'date' column
        frequency: Expected frequency string

    Returns:
        List of consistency issues
    """
    freq = Frequency.from_string(frequency) if frequency else None
    return QualityChecker.check_data_consistency(df, freq)


def detect_duplicates(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Find duplicate observations.

    Args:
        df: DataFrame with 'date' column

    Returns:
        List of duplicate entries with details
    """
    return QualityChecker.detect_duplicates(df)


def validate_value_ranges(
    df: pd.DataFrame,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    allow_nulls: bool = False,
) -> List[Dict[str, Any]]:
    """
    Check if values are within reasonable bounds.

    Args:
        df: DataFrame with 'value' column
        min_value: Minimum acceptable value
        max_value: Maximum acceptable value
        allow_nulls: Whether to allow null values

    Returns:
        List of range violations
    """
    return QualityChecker.validate_value_ranges(df, min_value, max_value, allow_nulls)


def zscore_outliers(df: pd.DataFrame, threshold: float = 3.0) -> OutlierResult:
    """
    Detect values > 3 standard deviations from mean.

    Args:
        df: DataFrame with 'date' and 'value' columns
        threshold: Z-score threshold (default 3.0)

    Returns:
        OutlierResult with detected outliers
    """
    return OutlierDetector.zscore_outliers(df, threshold)


def mad_outliers(df: pd.DataFrame, threshold: float = 3.5) -> OutlierResult:
    """
    Median Absolute Deviation method (more robust).

    Args:
        df: DataFrame with 'date' and 'value' columns
        threshold: MAD threshold (default 3.5)

    Returns:
        OutlierResult with detected outliers
    """
    return OutlierDetector.mad_outliers(df, threshold)


def iqr_outliers(df: pd.DataFrame, multiplier: float = 1.5) -> OutlierResult:
    """
    Interquartile Range method.

    Args:
        df: DataFrame with 'date' and 'value' columns
        multiplier: IQR multiplier (default 1.5)

    Returns:
        OutlierResult with detected outliers
    """
    return OutlierDetector.iqr_outliers(df, multiplier)


def isolation_forest_outliers(df: pd.DataFrame, contamination: float = 0.1) -> OutlierResult:
    """
    Machine learning based outlier detection.

    Args:
        df: DataFrame with 'date' and 'value' columns
        contamination: Expected proportion of outliers

    Returns:
        OutlierResult with detected outliers
    """
    return OutlierDetector.isolation_forest_outliers(df, contamination)


def detect_all_outliers(df: pd.DataFrame, series_id: str = "unknown") -> CombinedOutlierResult:
    """
    Run all outlier detection methods and combine results.

    Args:
        df: DataFrame with 'date' and 'value' columns
        series_id: Series identifier

    Returns:
        CombinedOutlierResult with all methods' results
    """
    return OutlierDetector.detect_all_outliers(df, series_id)


def linear_interpolate(df: pd.DataFrame, limit_direction: str = "both") -> ImputationResult:
    """
    Linear interpolation for missing values.

    Args:
        df: DataFrame with 'date' and 'value' columns
        limit_direction: Direction for interpolation

    Returns:
        ImputationResult with imputation details
    """
    return DataImputer.linear_interpolate(df, limit_direction)


def forward_fill(df: pd.DataFrame) -> ImputationResult:
    """
    Forward fill missing values.

    Args:
        df: DataFrame with 'date' and 'value' columns

    Returns:
        ImputationResult with imputation details
    """
    return DataImputer.forward_fill(df)


def backward_fill(df: pd.DataFrame) -> ImputationResult:
    """
    Backward fill missing values.

    Args:
        df: DataFrame with 'date' and 'value' columns

    Returns:
        ImputationResult with imputation details
    """
    return DataImputer.backward_fill(df)


def impute_all(df: pd.DataFrame, frequency: Optional[str] = None) -> ImputationResult:
    """
    Apply appropriate method based on series frequency.

    Args:
        df: DataFrame with 'date' and 'value' columns
        frequency: Data frequency string

    Returns:
        ImputationResult
    """
    freq = Frequency.from_string(frequency) if frequency else None
    return DataImputer.impute_all(df, freq)


def generate_quality_report(
    series_id: str,
    db_connection: Optional[DatabaseConnection] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    save_to_db: bool = True,
    apply_imputation: bool = False,
) -> QualityReport:
    """
    Create comprehensive quality report.

    Args:
        series_id: FRED series ID
        db_connection: Database connection
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        save_to_db: Whether to save anomalies to database
        apply_imputation: Whether to apply imputation

    Returns:
        Comprehensive QualityReport
    """
    controller = FredQualityController(db_connection)
    return controller.generate_quality_report(
        series_id, start_date, end_date, save_to_db, apply_imputation
    )


def save_anomalies_to_db(
    db_connection: DatabaseConnection,
    series_id: str,
    outliers: CombinedOutlierResult,
    overwrite: bool = False,
) -> int:
    """
    Store detected issues in database.

    Args:
        db_connection: Database connection
        series_id: Series identifier
        outliers: CombinedOutlierResult
        overwrite: Whether to delete existing anomalies first

    Returns:
        Number of records inserted
    """
    return AnomalyDatabase.save_anomalies_to_db(db_connection, series_id, outliers, overwrite)
