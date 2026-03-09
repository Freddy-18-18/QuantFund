"""
FRED Anomaly Detection Module
=============================

Comprehensive anomaly detection for FRED economic time series.
Implements statistical and machine learning based detectors.

Usage:
    from quantfund.data.fred_anomaly import FredAnomalyDetector

    detector = FredAnomalyDetector()

    # Load data
    df = client.get_observations("UNRATE", "2020-01-01", "2025-01-01")

    # Run all detectors
    report = detector.run_all_detectors(df, "UNRATE")

    # Get consensus anomalies
    consensus = detector.consensus_scoring(report.anomalies)

    # Save to database
    detector.save_to_database(consensus)

Detectors:
    Statistical:
    - ZScoreDetector: Rolling z-score with adaptive threshold
    - STLDetector: STL decomposition residual analysis
    - CusumDetector: Cumulative sum change detection
    - ChowTestDetector: Structural break detection
    - BinarySegmentationDetector: Binary segmentation change points
    - ArimaOutlierDetector: ARIMA-based outlier detection

    Machine Learning:
    - IsolationForestDetector: Isolation forest anomaly detection
    - AutoencoderDetector: LSTM/dense autoencoder reconstruction error
    - OneClassSVMDetector: One-class SVM for anomaly detection
    - MultivariateDetector: PCA + T² Hotelling for multivariate series
"""

from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.seasonal import STL

    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

try:
    from sklearn.svm import OneClassSVM

    HAS_SKLEARN_SVM = True
except ImportError:
    HAS_SKLEARN_SVM = False

try:
    from sklearn.decomposition import PCA

    HAS_SKLEARN_PCA = True
except ImportError:
    HAS_SKLEARN_PCA = False

try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers

    HAS_TENSORFLOW = True
except ImportError:
    HAS_TENSORFLOW = False

logger = logging.getLogger(__name__)


class AnomalySeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Anomaly:
    """Single anomaly result."""

    date: date
    score: float
    method: str
    severity: AnomalySeverity
    details: Dict[str, Any] = field(default_factory=dict)
    series_id: Optional[str] = None
    value: Optional[float] = None
    expected_value: Optional[float] = None
    deviation: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat() if isinstance(self.date, date) else str(self.date),
            "score": self.score,
            "method": self.method,
            "severity": self.severity.value,
            "details": self.details,
            "series_id": self.series_id,
            "value": self.value,
            "expected_value": self.expected_value,
            "deviation": self.deviation,
        }


@dataclass
class AnomalyReport:
    """Aggregated anomaly detection report."""

    series_id: str
    total_observations: int
    anomalies: List[Anomaly]
    detector_results: Dict[str, List[Anomaly]]
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @property
    def anomaly_count(self) -> int:
        return len(self.anomalies)

    @property
    def anomaly_rate(self) -> float:
        if self.total_observations == 0:
            return 0.0
        return self.anomaly_count / self.total_observations

    @property
    def severity_distribution(self) -> Dict[str, int]:
        dist = {s.value: 0 for s in AnomalySeverity}
        for a in self.anomalies:
            dist[a.severity.value] += 1
        return dist

    @property
    def method_coverage(self) -> Dict[str, int]:
        coverage = {}
        for a in self.anomalies:
            coverage[a.method] = coverage.get(a.method, 0) + 1
        return coverage

    def summary(self) -> Dict[str, Any]:
        return {
            "series_id": self.series_id,
            "total_observations": self.total_observations,
            "anomaly_count": self.anomaly_count,
            "anomaly_rate": self.anomaly_rate,
            "severity_distribution": self.severity_distribution,
            "method_coverage": self.method_coverage,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
        }


class ThresholdConfig:
    """Configuration for anomaly severity thresholds."""

    def __init__(
        self,
        low: float = 1.5,
        medium: float = 2.5,
        high: float = 3.5,
        critical: float = 5.0,
    ):
        self.low = low
        self.medium = medium
        self.high = high
        self.critical = critical

    def get_severity(self, score: float) -> AnomalySeverity:
        if abs(score) >= self.critical:
            return AnomalySeverity.CRITICAL
        elif abs(score) >= self.high:
            return AnomalySeverity.HIGH
        elif abs(score) >= self.medium:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW


class ZScoreDetector:
    """
    Z-Score based anomaly detector.

    Uses rolling z-score with configurable threshold and adaptive
    threshold based on volatility.
    """

    def __init__(
        self,
        threshold: float = 3.0,
        window: int = 30,
        adaptive: bool = True,
        min_periods: Optional[int] = None,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        self.threshold = threshold
        self.window = window
        self.adaptive = adaptive
        self.min_periods = min_periods or window // 2
        self.threshold_config = threshold_config or ThresholdConfig()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        if not HAS_STATSMODELS:
            raise ImportError("statsmodels is required for ZScoreDetector")

        series = self._prepare_series(df)

        if len(series) < self.min_periods:
            return []

        rolling_mean = series.rolling(window=self.window, min_periods=self.min_periods).mean()
        rolling_std = series.rolling(window=self.window, min_periods=self.min_periods).std()

        z_scores = (series - rolling_mean) / rolling_std
        z_scores = z_scores.dropna()

        anomalies = []
        for dt, score in z_scores.items():
            if pd.isna(score):
                continue

            severity = (
                self.threshold_config.get_severity(score)
                if self.adaptive
                else (AnomalySeverity.HIGH if abs(score) >= self.threshold else AnomalySeverity.LOW)
            )

            if abs(score) >= self.threshold:
                idx = series.index.get_loc(dt)
                expected = rolling_mean.loc[dt] if dt in rolling_mean.index else np.nan

                anomalies.append(
                    Anomaly(
                        date=dt.date() if hasattr(dt, "date") else dt,
                        score=float(score),
                        method="zscore",
                        severity=severity,
                        series_id=series_id,
                        value=float(series.loc[dt]),
                        expected_value=float(expected) if not pd.isna(expected) else None,
                        deviation=float(score),
                        details={"threshold": self.threshold, "window": self.window},
                    )
                )

        return anomalies

    def _prepare_series(self, df: pd.DataFrame) -> pd.Series:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        return series.sort_index()


class STLDetector:
    """
    STL Decomposition based anomaly detector.

    Detects anomalies in the residual component of STL decomposition
    and measures seasonal strength.
    """

    def __init__(
        self,
        period: Optional[int] = None,
        robust: bool = True,
        seasonal_deg: int = 1,
        trend_deg: int = 1,
        threshold: float = 3.0,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        self.period = period
        self.robust = robust
        self.seasonal_deg = seasonal_deg
        self.trend_deg = trend_deg
        self.threshold = threshold
        self.threshold_config = threshold_config or ThresholdConfig()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        if not HAS_STATSMODELS:
            raise ImportError("statsmodels is required for STLDetector")

        series = self._prepare_series(df)

        if len(series) < 2 * (self.period or 12):
            return []

        if series.isnull().any():
            series = series.ffill().bfill()

        period = self.period
        if period is None:
            inferred = pd.infer_freq(series.index)
            if inferred:
                freq_map = {"M": 12, "Q": 4, "W": 52, "D": 7}
                period = freq_map.get(inferred[0], 12)
            else:
                period = 12

        stl = STL(
            series,
            period=period,
            robust=self.robust,
            seasonal_deg=self.seasonal_deg,
            trend_deg=self.trend_deg,
        )
        result = stl.fit()

        residuals = result.resid
        resid_mean = residuals.mean()
        resid_std = residuals.std()

        if resid_std == 0:
            return []

        z_residuals = (residuals - resid_mean) / resid_std

        seasonal_strength = 1 - (result.seasonal.var() / (result.seasonal + result.resid).var())

        anomalies = []
        for dt, score in z_residuals.items():
            if pd.isna(score):
                continue

            severity = self.threshold_config.get_severity(score)

            if abs(score) >= self.threshold:
                expected = series.loc[dt] - result.seasonal.loc[dt] - result.trend.loc[dt]

                anomalies.append(
                    Anomaly(
                        date=dt.date() if hasattr(dt, "date") else dt,
                        score=float(score),
                        method="stl",
                        severity=severity,
                        series_id=series_id,
                        value=float(series.loc[dt]),
                        expected_value=float(expected) if not pd.isna(expected) else None,
                        deviation=float(score),
                        details={
                            "seasonal_strength": float(seasonal_strength),
                            "residual_std": float(resid_std),
                            "trend": float(result.trend.loc[dt])
                            if dt in result.trend.index
                            else None,
                            "seasonal": float(result.seasonal.loc[dt])
                            if dt in result.seasonal.index
                            else None,
                        },
                    )
                )

        return anomalies

    def _prepare_series(self, df: pd.DataFrame) -> pd.Series:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        return series.sort_index()


class CusumDetector:
    """
    CUSUM (Cumulative Sum) change point detector.

    Detects shifts in the mean of a time series using cumulative sum.
    """

    def __init__(
        self,
        threshold: float = 5.0,
        drift: float = 0.5,
        detection_threshold: float = 3.0,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        self.threshold = threshold
        self.drift = drift
        self.detection_threshold = detection_threshold
        self.threshold_config = threshold_config or ThresholdConfig()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        series = self._prepare_series(df)

        if len(series) < 10:
            return []

        mean_val = series.mean()
        std_val = series.std()

        if std_val == 0:
            return []

        normalized = (series - mean_val) / std_val

        cusum_pos = np.zeros(len(series))
        cusum_neg = np.zeros(len(series))

        for i in range(1, len(series)):
            cusum_pos[i] = max(0, cusum_pos[i - 1] + normalized.iloc[i] - self.drift)
            cusum_neg[i] = max(0, cusum_neg[i - 1] - normalized.iloc[i] - self.drift)

        anomalies = []
        for i, (dt, (pos, neg)) in enumerate(zip(series.index, zip(cusum_pos, cusum_neg))):
            score = max(pos, neg)

            if score >= self.detection_threshold:
                severity = self.threshold_config.get_severity(score)

                anomalies.append(
                    Anomaly(
                        date=dt.date() if hasattr(dt, "date") else dt,
                        score=float(score),
                        method="cusum",
                        severity=severity,
                        series_id=series_id,
                        value=float(series.loc[dt]),
                        expected_value=float(mean_val),
                        deviation=float(score),
                        details={
                            "cusum_pos": float(pos),
                            "cusum_neg": float(neg),
                            "drift": self.drift,
                        },
                    )
                )

        return anomalies

    def _prepare_series(self, df: pd.DataFrame) -> pd.Series:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        return series.sort_index()


class ChowTestDetector:
    """
    Chow Test structural break detector.

    Tests for structural breaks at potential change points using
    the Chow test statistic.
    """

    def __init__(
        self,
        breakpoints: Optional[List[int]] = None,
        test_size: int = 20,
        significance: float = 0.05,
        threshold: float = 10.0,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        self.breakpoints = breakpoints
        self.test_size = test_size
        self.significance = significance
        self.threshold = threshold
        self.threshold_config = threshold_config or ThresholdConfig()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        series = self._prepare_series(df)

        if len(series) < 2 * self.test_size:
            return []

        if self.breakpoints is None:
            breakpoints = list(range(self.test_size, len(series) - self.test_size, self.test_size))
        else:
            breakpoints = self.breakpoints

        anomalies = []

        for bp in breakpoints:
            if bp < self.test_size or bp >= len(series) - self.test_size:
                continue

            try:
                f_stat, p_value = self._chow_test(series, bp)

                if p_value < self.significance and f_stat > self.threshold:
                    dt = series.index[bp]
                    severity = self.threshold_config.get_severity(f_stat)

                    anomalies.append(
                        Anomaly(
                            date=dt.date() if hasattr(dt, "date") else dt,
                            score=float(f_stat),
                            method="chow_test",
                            severity=severity,
                            series_id=series_id,
                            value=float(series.iloc[bp]),
                            expected_value=float(series.iloc[:bp].mean()),
                            deviation=float(series.iloc[bp] - series.iloc[:bp].mean()),
                            details={
                                "breakpoint_index": bp,
                                "p_value": float(p_value),
                                "significance": self.significance,
                            },
                        )
                    )
            except Exception:
                continue

        return anomalies

    def _chow_test(self, series: pd.Series, breakpoint: int) -> Tuple[float, float]:
        y = series.values
        n = len(y)
        k = 1

        y1 = y[:breakpoint]
        y2 = y[breakpoint:]
        n1 = len(y1)
        n2 = len(y2)

        x1 = np.arange(n1)
        x2 = np.arange(n2)

        if len(x1) < 2 or len(x2) < 2:
            return 0.0, 1.0

        try:
            beta1 = np.polyfit(x1, y1, 1)[0]
            beta2 = np.polyfit(x2, y2, 1)[0]

            y_pred1 = np.polyval([beta1], x1)
            y_pred2 = np.polyval([beta2], x2)

            rss = np.sum((y1 - y_pred1) ** 2) + np.sum((y2 - y_pred2) ** 2)
            rss_full = np.sum((y - np.polyfit(np.arange(n), y, 1)[0]) ** 2)

            f_stat = ((rss_full - rss) / k) / (rss / (n - 2 * k - 1))

            p_value = 1 - stats.f.cdf(f_stat, k, n - 2 * k - 1)

            return f_stat, p_value
        except Exception:
            return 0.0, 1.0

    def _prepare_series(self, df: pd.DataFrame) -> pd.Series:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        return series.sort_index()


class BinarySegmentationDetector:
    """
    Binary Segmentation change point detector.

    Recursively splits the time series to detect multiple change points.
    """

    def __init__(
        self,
        min_size: int = 30,
        max_changepoints: int = 5,
        significance: float = 0.05,
        threshold: float = 3.0,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        self.min_size = min_size
        self.max_changepoints = max_changepoints
        self.significance = significance
        self.threshold = threshold
        self.threshold_config = threshold_config or ThresholdConfig()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        series = self._prepare_series(df)

        if len(series) < 2 * self.min_size:
            return []

        changepoints = self._binary_segmentation(series.values)

        anomalies = []
        for cp_idx in changepoints[: self.max_changepoints]:
            if cp_idx < 0 or cp_idx >= len(series):
                continue

            dt = series.index[cp_idx]
            score = self._compute_cost_reduction(series.values, cp_idx)
            severity = self.threshold_config.get_severity(score)

            anomalies.append(
                Anomaly(
                    date=dt.date() if hasattr(dt, "date") else dt,
                    score=float(score),
                    method="binary_segmentation",
                    severity=severity,
                    series_id=series_id,
                    value=float(series.iloc[cp_idx]),
                    expected_value=float(series.iloc[:cp_idx].mean()) if cp_idx > 0 else None,
                    deviation=float(score),
                    details={
                        "changepoint_index": cp_idx,
                        "changepoints_total": len(changepoints),
                    },
                )
            )

        return anomalies

    def _binary_segmentation(self, data: np.ndarray) -> List[int]:
        changepoints = []
        self._find_changepoints(data, 0, len(data), changepoints, 0)
        return changepoints

    def _find_changepoints(
        self,
        data: np.ndarray,
        start: int,
        end: int,
        changepoints: List[int],
        depth: int,
    ) -> None:
        if end - start < 2 * self.min_size or depth >= self.max_changepoints:
            return

        best_idx = -1
        best_cost = -np.inf

        for i in range(start + self.min_size, end - self.min_size):
            cost = self._compute_cost_reduction(data[start:end], i - start)
            if cost > best_cost:
                best_cost = cost
                best_idx = i

        if best_idx > 0 and best_cost > 0:
            p_value = self._compute_p_value(data[start:end], best_idx - start)
            if p_value < self.significance:
                changepoints.append(best_idx)
                self._find_changepoints(data, start, best_idx, changepoints, depth + 1)
                self._find_changepoints(data, best_idx, end, changepoints, depth + 1)

    def _compute_cost_reduction(self, data: np.ndarray, breakpoint: int) -> float:
        n = len(data)
        if breakpoint <= 0 or breakpoint >= n:
            return 0.0

        seg1 = data[:breakpoint]
        seg2 = data[breakpoint:]

        cost_full = np.var(data) * n
        cost_split = np.var(seg1) * len(seg1) + np.var(seg2) * len(seg2)

        return (cost_full - cost_split) / n

    def _compute_p_value(self, data: np.ndarray, breakpoint: int) -> float:
        n = len(data)
        stat = self._compute_cost_reduction(data, breakpoint)

        null_dist = []
        for _ in range(100):
            shuffled = np.random.permutation(data)
            null_dist.append(self._compute_cost_reduction(shuffled, breakpoint))

        return np.mean([1 if s >= stat else 0 for s in null_dist])

    def _prepare_series(self, df: pd.DataFrame) -> pd.Series:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        return series.sort_index()


class ArimaOutlierDetector:
    """
    ARIMA-based outlier detector.

    Detects additive outliers (AO), level shifts (LS), and transitory changes (TC)
    using ARIMA model residuals.
    """

    def __init__(
        self,
        order: Tuple[int, int, int] = (1, 1, 1),
        threshold: float = 3.0,
        outlier_types: Optional[List[str]] = None,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        self.order = order
        self.threshold = threshold
        self.outlier_types = outlier_types or ["AO", "LS", "TC"]
        self.threshold_config = threshold_config or ThresholdConfig()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        if not HAS_STATSMODELS:
            raise ImportError("statsmodels is required for ArimaOutlierDetector")

        series = self._prepare_series(df)

        if len(series) < 2 * (sum(self.order) + 10):
            return []

        try:
            model = ARIMA(series, order=self.order)
            fitted = model.fit()

            residuals = fitted.resid
            resid_std = residuals.std()
            resid_mean = residuals.mean()

            if resid_std == 0:
                return []

            anomalies = []

            for i, (dt, resid) in enumerate(residuals.items()):
                if pd.isna(resid):
                    continue

                z_resid = (resid - resid_mean) / resid_std

                if abs(z_resid) >= self.threshold:
                    severity = self.threshold_config.get_severity(z_resid)
                    outlier_type = self._classify_outlier(series, residuals, i)

                    if outlier_type in self.outlier_types:
                        expected = series.loc[dt] - resid

                        anomalies.append(
                            Anomaly(
                                date=dt.date() if hasattr(dt, "date") else dt,
                                score=float(z_resid),
                                method="arima_outlier",
                                severity=severity,
                                series_id=series_id,
                                value=float(series.loc[dt]),
                                expected_value=float(expected) if not pd.isna(expected) else None,
                                deviation=float(resid),
                                details={
                                    "outlier_type": outlier_type,
                                    "residual": float(resid),
                                    "arima_order": self.order,
                                },
                            )
                        )

            return anomalies

        except Exception as e:
            logger.warning(f"ARIMA fitting failed: {e}")
            return []

    def _classify_outlier(
        self,
        series: pd.Series,
        residuals: pd.Series,
        idx: int,
    ) -> str:
        if idx < len(residuals) - 1 and idx > 0:
            if abs(residuals.iloc[idx]) > 2 * abs(residuals.iloc[idx - 1]):
                return "TC"
            return "AO"
        return "AO"

    def _prepare_series(self, df: pd.DataFrame) -> pd.Series:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        return series.sort_index()


class IsolationForestDetector:
    """
    Isolation Forest based anomaly detector.

    Uses sklearn's IsolationForest for detecting anomalies based on
    isolation properties.
    """

    def __init__(
        self,
        contamination: float = 0.1,
        n_estimators: int = 100,
        max_samples: Union[int, float, str] = "auto",
        random_state: Optional[int] = 42,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.max_samples = max_samples
        self.random_state = random_state
        self.threshold_config = threshold_config or ThresholdConfig()
        self._model = None
        self._scaler = StandardScaler()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        features = self._create_features(df)

        if len(features) < 10:
            return []

        scaled_features = self._scaler.fit_transform(features)

        max_samples_val = self.max_samples
        if max_samples_val == "auto" or max_samples_val is None:
            max_samples_val = min(256, len(scaled_features))

        self._model = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            max_samples=max_samples_val,
            random_state=self.random_state,
            n_jobs=-1,
        )

        anomaly_scores = self._model.fit_predict(scaled_features)
        scores = self._model.score_samples(scaled_features)

        anomalies = []
        for i, (is_anomaly, score) in enumerate(zip(anomaly_scores, scores)):
            if is_anomaly == -1:
                dt = features.index[i]
                severity = self.threshold_config.get_severity(-score)

                anomalies.append(
                    Anomaly(
                        date=dt.date() if hasattr(dt, "date") else dt,
                        score=float(-score),
                        method="isolation_forest",
                        severity=severity,
                        series_id=series_id,
                        value=float(df.iloc[i]["value"])
                        if "value" in df.columns
                        else float(df.iloc[i, 0]),
                        details={
                            "raw_score": float(score),
                            "contamination": self.contamination,
                        },
                    )
                )

        return anomalies

    def _create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        series = series.sort_index()

        features = pd.DataFrame(index=series.index)
        features["value"] = series.values

        for lag in [1, 2, 3, 6, 12]:
            features[f"lag_{lag}"] = series.shift(lag)

        features["diff_1"] = series.diff(1)
        features["diff_12"] = series.diff(12)

        for window in [3, 6, 12]:
            features[f"rolling_mean_{window}"] = series.rolling(window).mean()
            features[f"rolling_std_{window}"] = series.rolling(window).std()

        features = features.dropna()

        return features


class AutoencoderDetector:
    """
    Autoencoder based anomaly detector.

    Uses reconstruction error from autoencoder to detect anomalies.
    Supports both dense and LSTM architectures.
    """

    def __init__(
        self,
        encoding_dim: int = 8,
        threshold_percentile: float = 95,
        architecture: str = "dense",
        epochs: int = 50,
        batch_size: int = 32,
        learning_rate: float = 0.001,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        self.encoding_dim = encoding_dim
        self.threshold_percentile = threshold_percentile
        self.architecture = architecture
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.threshold_config = threshold_config or ThresholdConfig()
        self._model = None
        self._threshold = None
        self._scaler = StandardScaler()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        if not HAS_TENSORFLOW:
            warnings.warn("TensorFlow not available. Using fallback implementation.")
            return self._detect_fallback(df, series_id)

        features = self._create_features(df)

        if len(features) < 50:
            return self._detect_fallback(df, series_id)

        scaled_features = self._scaler.fit_transform(features)

        self._model = self._build_model(scaled_features.shape[1])

        self._model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=self.learning_rate),
            loss="mse",
        )

        self._model.fit(
            scaled_features,
            scaled_features,
            epochs=self.epochs,
            batch_size=self.batch_size,
            verbose=0,
            validation_split=0.1,
        )

        reconstructed = self._model.predict(scaled_features, verbose=0)
        mse = np.mean(np.power(scaled_features - reconstructed, 2), axis=1)

        self._threshold = np.percentile(mse, self.threshold_percentile)

        anomalies = []
        for i, (dt, err) in enumerate(zip(features.index, mse)):
            if err >= self._threshold:
                severity = self.threshold_config.get_severity(err / self._threshold * 3)

                anomalies.append(
                    Anomaly(
                        date=dt.date() if hasattr(dt, "date") else dt,
                        score=float(err),
                        method="autoencoder",
                        severity=severity,
                        series_id=series_id,
                        value=float(df.iloc[i]["value"])
                        if "value" in df.columns
                        else float(df.iloc[i, 0]),
                        expected_value=float(features.iloc[i]["value"] - err),
                        deviation=float(err),
                        details={
                            "reconstruction_error": float(err),
                            "threshold": float(self._threshold),
                            "encoding_dim": self.encoding_dim,
                        },
                    )
                )

        return anomalies

    def _build_model(self, input_dim: int) -> keras.Model:
        if self.architecture == "lstm":
            return self._build_lstm_model(input_dim)
        return self._build_dense_model(input_dim)

    def _build_dense_model(self, input_dim: int) -> keras.Model:
        encoder = keras.Sequential(
            [
                layers.Dense(input_dim, activation="relu", input_shape=(input_dim,)),
                layers.Dense(self.encoding_dim, activation="relu"),
            ]
        )

        decoder = keras.Sequential(
            [
                layers.Dense(
                    self.encoding_dim, activation="relu", input_shape=(self.encoding_dim,)
                ),
                layers.Dense(input_dim, activation="linear"),
            ]
        )

        autoencoder = keras.Sequential([encoder, decoder])
        return autoencoder

    def _build_lstm_model(self, input_dim: int) -> keras.Model:
        inputs = keras.Input(shape=(input_dim, 1))
        x = layers.LSTM(64, activation="relu", return_sequences=True)(inputs)
        x = layers.LSTM(self.encoding_dim, activation="relu")(x)
        x = layers.RepeatVector(input_dim)(x)
        x = layers.LSTM(self.encoding_dim, activation="relu", return_sequences=True)(x)
        x = layers.LSTM(64, activation="relu", return_sequences=True)(x)
        outputs = layers.TimeDistributed(layers.Dense(1))(x)

        autoencoder = keras.Model(inputs, outputs)
        return autoencoder

    def _detect_fallback(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        features = self._create_features(df)
        if len(features) < 10:
            return []

        scaler = StandardScaler()
        scaled = scaler.fit_transform(features)

        cov = np.cov(scaled.T)
        try:
            inv_cov = np.linalg.pinv(cov)
            mean = np.mean(scaled, axis=0)

            mahal = np.array([(x - mean) @ inv_cov @ (x - mean).T for x in scaled])

            threshold = np.percentile(mahal, self.threshold_percentile)

            anomalies = []
            for i, (dt, score) in enumerate(zip(features.index, mahal)):
                if score >= threshold:
                    severity = self.threshold_config.get_severity(score / threshold * 3)

                    anomalies.append(
                        Anomaly(
                            date=dt.date() if hasattr(dt, "date") else dt,
                            score=float(score),
                            method="autoencoder_fallback",
                            severity=severity,
                            series_id=series_id,
                            details={"fallback": "mahalanobis_distance"},
                        )
                    )

            return anomalies

        except Exception:
            return []

    def _create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        series = series.sort_index()

        features = pd.DataFrame(index=series.index)
        features["value"] = series.values

        for lag in [1, 2, 3, 6, 12]:
            features[f"lag_{lag}"] = series.shift(lag)

        features["diff_1"] = series.diff(1)
        features["diff_12"] = series.diff(12)

        for window in [3, 6, 12]:
            features[f"rolling_mean_{window}"] = series.rolling(window).mean()
            features[f"rolling_std_{window}"] = series.rolling(window).std()

        features = features.dropna()

        return features


class OneClassSVMDetector:
    """
    One-Class SVM anomaly detector.

    Uses sklearn's OneClassSVM with RBF kernel for non-linear
    boundary detection.
    """

    def __init__(
        self,
        kernel: str = "rbf",
        gamma: str = "scale",
        nu: float = 0.1,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        if not HAS_SKLEARN_SVM:
            raise ImportError("sklearn.svm is required for OneClassSVMDetector")

        self.kernel = kernel
        self.gamma = gamma
        self.nu = nu
        self.threshold_config = threshold_config or ThresholdConfig()
        self._model = None
        self._scaler = StandardScaler()

    def detect(self, df: pd.DataFrame, series_id: Optional[str] = None) -> List[Anomaly]:
        features = self._create_features(df)

        if len(features) < 20:
            return []

        scaled_features = self._scaler.fit_transform(features)

        self._model = OneClassSVM(kernel=self.kernel, gamma=self.gamma, nu=self.nu)
        self._model.fit(scaled_features)

        anomaly_scores = self._model.predict(scaled_features)
        scores = self._model.score_samples(scaled_features)

        threshold = np.percentile(scores, self.nu * 100)

        anomalies = []
        for i, (is_anomaly, score) in enumerate(zip(anomaly_scores, scores)):
            if is_anomaly == -1 or score <= threshold:
                dt = features.index[i]
                severity = self.threshold_config.get_severity(-score)

                anomalies.append(
                    Anomaly(
                        date=dt.date() if hasattr(dt, "date") else dt,
                        score=float(-score),
                        method="one_class_svm",
                        severity=severity,
                        series_id=series_id,
                        value=float(df.iloc[i]["value"])
                        if "value" in df.columns
                        else float(df.iloc[i, 0]),
                        details={
                            "raw_score": float(score),
                            "nu": self.nu,
                            "kernel": self.kernel,
                        },
                    )
                )

        return anomalies

    def _create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "date" in df.columns and "value" in df.columns:
            series = df.set_index("date")["value"]
        elif isinstance(df, pd.DataFrame):
            series = df.iloc[:, 0]
        else:
            series = df

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)

        series = series.sort_index()

        features = pd.DataFrame(index=series.index)
        features["value"] = series.values

        for lag in [1, 2, 3, 6]:
            features[f"lag_{lag}"] = series.shift(lag)

        features["diff_1"] = series.diff(1)

        for window in [3, 6, 12]:
            features[f"rolling_mean_{window}"] = series.rolling(window).mean()
            features[f"rolling_std_{window}"] = series.rolling(window).std()

        features = features.dropna()

        return features


class MultivariateDetector:
    """
    Multivariate anomaly detector using PCA and T² Hotelling.

    Detects anomalies across multiple series using principal component
    analysis and Hotelling's T² statistic.
    """

    def __init__(
        self,
        n_components: Optional[int] = None,
        threshold_percentile: float = 95,
        threshold_config: Optional[ThresholdConfig] = None,
    ):
        if not HAS_SKLEARN_PCA:
            raise ImportError("sklearn.decomposition.PCA is required for MultivariateDetector")

        self.n_components = n_components
        self.threshold_percentile = threshold_percentile
        self.threshold_config = threshold_config or ThresholdConfig()
        self._pca = None
        self._scaler = StandardScaler()
        self._threshold = None

    def detect(
        self,
        df: pd.DataFrame,
        series_id: Optional[str] = None,
    ) -> List[Anomaly]:
        features = self._prepare_features(df)

        if features.shape[1] < 2 or features.shape[0] < 20:
            return []

        scaled_features = self._scaler.fit_transform(features)

        n_components = self.n_components or min(3, features.shape[1] - 1)

        self._pca = PCA(n_components=n_components)
        transformed = self._pca.fit_transform(scaled_features)

        n = len(transformed)
        p = n_components

        t2_scores = np.sum(transformed**2 / self._pca.explained_variance_, axis=1)

        f_critical = (p * (n - 1) * (n + 1)) / (n * (n - p))
        critical_value = f_critical * stats.f.ppf(0.95, p, n - p)

        self._threshold = np.percentile(t2_scores, self.threshold_percentile)

        anomalies = []
        for i, (dt, t2) in enumerate(zip(features.index, t2_scores)):
            if t2 >= self._threshold or t2 >= critical_value:
                severity = self.threshold_config.get_severity(t2 / self._threshold * 3)

                anomalies.append(
                    Anomaly(
                        date=dt.date() if hasattr(dt, "date") else dt,
                        score=float(t2),
                        method="multivariate_pca",
                        severity=severity,
                        series_id=series_id,
                        details={
                            "t2_score": float(t2),
                            "critical_value": float(critical_value),
                            "explained_variance": float(sum(self._pca.explained_variance_ratio_)),
                            "n_components": n_components,
                        },
                    )
                )

        return anomalies

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "date" in df.columns:
            feature_cols = [c for c in df.columns if c != "date" and c != "value"]
            if not feature_cols:
                feature_cols = [c for c in df.columns if c != "date"]
            features = df[feature_cols].copy()
            features.index = df["date"] if "date" in df.columns else df.index
        else:
            features = df.select_dtypes(include=[np.number]).copy()

        if features.empty:
            if "value" in df.columns:
                series = df["value"]
            else:
                series = df.iloc[:, 0]
            features = pd.DataFrame({"value": series})

            for lag in [1, 2, 3]:
                features[f"lag_{lag}"] = series.shift(lag)

            features["diff_1"] = series.diff(1)

        if not isinstance(features.index, pd.DatetimeIndex):
            try:
                features.index = pd.to_datetime(features.index)
            except Exception:
                pass

        features = features.dropna()

        return features


class FredAnomalyDetector:
    """
    Main anomaly detection orchestrator for FRED data.

    Runs multiple detectors, combines results, and supports
    database persistence.
    """

    def __init__(
        self,
        db_connection: Optional[str] = None,
        threshold_config: Optional[ThresholdConfig] = None,
        consensus_weights: Optional[Dict[str, float]] = None,
    ):
        self.db_connection = db_connection or os.environ.get(
            "FRED_DB_CONNECTION",
            "postgresql://postgres:postgres@localhost:5432/freddata",
        )
        self.threshold_config = threshold_config or ThresholdConfig()
        self.consensus_weights = consensus_weights or {
            "zscore": 1.0,
            "stl": 1.0,
            "cusum": 0.8,
            "chow_test": 0.7,
            "binary_segmentation": 0.7,
            "arima_outlier": 1.0,
            "isolation_forest": 1.0,
            "autoencoder": 1.0,
            "one_class_svm": 0.9,
            "multivariate_pca": 0.8,
        }

        self._init_detectors()

    def _init_detectors(self) -> None:
        self.detectors = {
            "zscore": ZScoreDetector(threshold_config=self.threshold_config),
            "stl": STLDetector(threshold_config=self.threshold_config),
            "cusum": CusumDetector(threshold_config=self.threshold_config),
            "chow_test": ChowTestDetector(threshold_config=self.threshold_config),
            "binary_segmentation": BinarySegmentationDetector(
                threshold_config=self.threshold_config
            ),
            "arima_outlier": ArimaOutlierDetector(threshold_config=self.threshold_config),
            "isolation_forest": IsolationForestDetector(threshold_config=self.threshold_config),
            "autoencoder": AutoencoderDetector(threshold_config=self.threshold_config),
            "one_class_svm": OneClassSVMDetector(threshold_config=self.threshold_config),
            "multivariate_pca": MultivariateDetector(threshold_config=self.threshold_config),
        }

    def run_all_detectors(
        self,
        df: pd.DataFrame,
        series_id: str,
        detectors: Optional[List[str]] = None,
    ) -> AnomalyReport:
        if detectors is None:
            detectors = list(self.detectors.keys())

        detector_results = {}
        all_anomalies = []

        for name in detectors:
            if name not in self.detectors:
                logger.warning(f"Unknown detector: {name}")
                continue

            try:
                anomalies = self.detectors[name].detect(df, series_id)
                detector_results[name] = anomalies
                all_anomalies.extend(anomalies)
                logger.info(f"{name}: detected {len(anomalies)} anomalies")
            except Exception as e:
                logger.error(f"Detector {name} failed: {e}")
                detector_results[name] = []

        start_date = None
        end_date = None
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"])
            start_date = dates.min().date()
            end_date = dates.max().date()

        return AnomalyReport(
            series_id=series_id,
            total_observations=len(df),
            anomalies=all_anomalies,
            detector_results=detector_results,
            start_date=start_date,
            end_date=end_date,
        )

    def run_statistical_detectors(
        self,
        df: pd.DataFrame,
        series_id: str,
    ) -> AnomalyReport:
        statistical = [
            "zscore",
            "stl",
            "cusum",
            "chow_test",
            "binary_segmentation",
            "arima_outlier",
        ]
        return self.run_all_detectors(df, series_id, statistical)

    def run_ml_detectors(
        self,
        df: pd.DataFrame,
        series_id: str,
    ) -> AnomalyReport:
        ml = ["isolation_forest", "autoencoder", "one_class_svm"]
        return self.run_all_detectors(df, series_id, ml)

    def consensus_scoring(
        self,
        anomalies: List[Anomaly],
        method: str = "weighted",
        min_detectors: int = 2,
    ) -> List[Anomaly]:
        if not anomalies:
            return []

        anomaly_dict: Dict[Tuple[date, str], List[Anomaly]] = {}

        for a in anomalies:
            key = (a.date, a.method.split("_")[0])
            if key not in anomaly_dict:
                anomaly_dict[key] = []
            anomaly_dict[key].append(a)

        consensus_anomalies = []

        date_method_anomalies: Dict[date, List[Anomaly]] = {}
        for a in anomalies:
            if a.date not in date_method_anomalies:
                date_method_anomalies[a.date] = []
            date_method_anomalies[a.date].append(a)

        for dt, date_anomalies in date_method_anomalies.items():
            if len(date_anomalies) < min_detectors:
                continue

            total_weight = 0.0
            weighted_score = 0.0
            severities = []

            for a in date_anomalies:
                weight = self.consensus_weights.get(a.method, 0.5)
                weighted_score += abs(a.score) * weight
                total_weight += weight
                severities.append(a.severity)

            if total_weight > 0:
                avg_score = weighted_score / total_weight

                severity_counts = {s: 0 for s in AnomalySeverity}
                for s in severities:
                    severity_counts[s] += 1

                consensus_severity = max(severity_counts, key=severity_counts.get)

                avg_value = np.mean([a.value for a in date_anomalies if a.value is not None])
                avg_expected = np.mean(
                    [a.expected_value for a in date_anomalies if a.expected_value is not None]
                )

                consensus_anomalies.append(
                    Anomaly(
                        date=dt,
                        score=avg_score,
                        method="consensus",
                        severity=consensus_severity,
                        series_id=date_anomalies[0].series_id,
                        value=avg_value if not pd.isna(avg_value) else None,
                        expected_value=avg_expected if not pd.isna(avg_expected) else None,
                        deviation=avg_score,
                        details={
                            "contributing_methods": list(set(a.method for a in date_anomalies)),
                            "detector_count": len(date_anomalies),
                        },
                    )
                )

        return consensus_anomalies

    def save_to_database(
        self,
        anomalies: List[Anomaly],
        series_id: Optional[str] = None,
    ) -> int:
        if not anomalies:
            return 0

        try:
            import psycopg2

            conn = psycopg2.connect(self.db_connection)
            cur = conn.cursor()

            count = 0
            for anomaly in anomalies:
                try:
                    cur.execute(
                        """
                        INSERT INTO fred_anomalies 
                        (series_id, date, method, score, severity, notes)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            anomaly.series_id or series_id,
                            anomaly.date,
                            anomaly.method,
                            anomaly.score,
                            anomaly.severity.value,
                            str(anomaly.details),
                        ),
                    )
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to insert anomaly: {e}")

            conn.commit()
            cur.close()
            conn.close()

            logger.info(f"Saved {count} anomalies to database")
            return count

        except ImportError:
            logger.warning("psycopg2 not available. Saving to CSV instead.")
            return self._save_to_csv(anomalies, series_id)
        except Exception as e:
            logger.error(f"Database save failed: {e}")
            return self._save_to_csv(anomalies, series_id)

    def _save_to_csv(self, anomalies: List[Anomaly], series_id: Optional[str] = None) -> int:
        if not anomalies:
            return 0

        records = []
        for a in anomalies:
            records.append(
                {
                    "series_id": a.series_id or series_id,
                    "date": a.date.isoformat() if isinstance(a.date, date) else str(a.date),
                    "method": a.method,
                    "score": a.score,
                    "severity": a.severity.value,
                    "value": a.value,
                    "expected_value": a.expected_value,
                    "deviation": a.deviation,
                    "details": str(a.details),
                }
            )

        df = pd.DataFrame(records)
        filename = (
            f"anomalies_{series_id or 'unknown'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        df.to_csv(filename, index=False)

        logger.info(f"Saved {len(records)} anomalies to {filename}")
        return len(records)

    def detect_realtime(
        self,
        df: pd.DataFrame,
        series_id: str,
        known_anomalies: Optional[List[Anomaly]] = None,
    ) -> List[Anomaly]:
        if len(df) < 30:
            logger.warning("Insufficient data for real-time detection")
            return []

        historical = df.iloc[:-1]
        current = df.iloc[-1:]

        report = self.run_all_detectors(historical, series_id)

        recent_anomalies = [a for a in report.anomalies if a.date == df.iloc[-1]["date"]]

        if known_anomalies:
            for ka in known_anomalies:
                recent_anomalies = [a for a in recent_anomalies if a.date != ka.date]

        return recent_anomalies

    def get_anomaly_summary(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        try:
            import psycopg2

            conn = psycopg2.connect(self.db_connection)

            query = "SELECT date, method, score, severity FROM fred_anomalies WHERE series_id = %s"
            params = [series_id]

            if start_date:
                query += " AND date >= %s"
                params.append(start_date)
            if end_date:
                query += " AND date <= %s"
                params.append(end_date)

            df = pd.read_sql(query, conn, params=params)
            conn.close()

            if df.empty:
                return {"series_id": series_id, "anomaly_count": 0}

            return {
                "series_id": series_id,
                "anomaly_count": len(df),
                "severity_distribution": df["severity"].value_counts().to_dict(),
                "method_distribution": df["method"].value_counts().to_dict(),
                "date_range": {"start": str(df["date"].min()), "end": str(df["date"].max())},
            }

        except Exception as e:
            logger.error(f"Failed to get summary: {e}")
            return {"series_id": series_id, "error": str(e)}


def create_anomaly_detector(
    db_connection: Optional[str] = None,
    thresholds: Optional[Dict[str, float]] = None,
) -> FredAnomalyDetector:
    """
    Factory function to create a FredAnomalyDetector.

    Args:
        db_connection: Database connection string.
        thresholds: Custom threshold configuration.

    Returns:
        Configured FredAnomalyDetector instance.
    """
    threshold_config = None
    if thresholds:
        threshold_config = ThresholdConfig(
            low=thresholds.get("low", 1.5),
            medium=thresholds.get("medium", 2.5),
            high=thresholds.get("high", 3.5),
            critical=thresholds.get("critical", 5.0),
        )

    return FredAnomalyDetector(
        db_connection=db_connection,
        threshold_config=threshold_config,
    )
