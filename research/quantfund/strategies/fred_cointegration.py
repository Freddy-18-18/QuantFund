"""
Cointegration and Pairs Trading Signals Module
==============================================
Comprehensive cointegration analysis and pairs trading signal generation
for XAUUSD (Gold) and related macro instruments.

Features:
- Engle-Granger and Johansen cointegration tests
- Spread calculation and z-score analysis
- Entry/exit signal generation with Bollinger bands
- Mean reversion half-life estimation
- Kalman filter for adaptive hedge ratio
- Pre-defined pairs for gold trading

Usage:
    from quantfund.strategies.fred_cointegration import (
        CointegrationAnalyzer,
        PairsTradingSignals,
        CointegrationResult,
        PairSignal
    )

    analyzer = CointegrationAnalyzer()
    result = analyzer.test_cointegration(series1, series2)

    signals = PairsTradingSignals()
    signals.add_pair('GOLDAMGBD', 'DFII10')
    signals_df = signals.generate_signals(spread_data)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Trading signal type enumeration."""

    LONG = 1
    SHORT = -1
    FLAT = 0


class TestType(Enum):
    """Cointegration test type."""

    ENGLE_GRANGER = "engle_granger"
    JOHANSEN_TRACE = "johansen_trace"
    JOHANSEN_EIGEN = "johansen_eigen"


@dataclass
class CointegrationResult:
    """Results from cointegration testing."""

    pair_name: str
    test_type: str
    is_cointegrated: bool
    p_value: Optional[float]
    test_statistic: Optional[float]
    critical_value: Optional[float]
    hedge_ratio: Optional[float]
    intercept: Optional[float]
    half_life: Optional[float]
    eigenvectors: Optional[np.ndarray] = None
    eigenvalues: Optional[np.ndarray] = None
    tested_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair_name": self.pair_name,
            "test_type": self.test_type,
            "is_cointegrated": self.is_cointegrated,
            "p_value": self.p_value,
            "test_statistic": self.test_statistic,
            "critical_value": self.critical_value,
            "hedge_ratio": self.hedge_ratio,
            "intercept": self.intercept,
            "half_life": self.half_life,
            "eigenvectors": self.eigenvectors.tolist() if self.eigenvectors is not None else None,
            "eigenvalues": self.eigenvalues.tolist() if self.eigenvalues is not None else None,
            "tested_at": self.tested_at.isoformat(),
        }


@dataclass
class PairSignal:
    """Trading signal for a pair."""

    date: datetime
    pair_name: str
    signal_type: SignalType
    spread: float
    zscore: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: Optional[float] = None
    hedge_ratio: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat() if isinstance(self.date, datetime) else self.date,
            "pair_name": self.pair_name,
            "signal_type": self.signal_type.name
            if isinstance(self.signal_type, SignalType)
            else self.signal_type,
            "spread": self.spread,
            "zscore": self.zscore,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_size": self.position_size,
            "hedge_ratio": self.hedge_ratio,
            "details": self.details,
        }


@dataclass
class PairsConfig:
    """Configuration for pairs trading."""

    entry_threshold: float = 2.0
    exit_threshold: float = 0.5
    stop_loss_bands: float = 3.0
    take_profit_bands: float = 1.0
    lookback_window: int = 252
    min_observations: int = 30
    coint_pvalue_threshold: float = 0.05
    half_life_max: float = 252.0
    trailing_stop_pct: float = 0.02
    kalman_delta: float = 1e-5
    kalman_epsilon: float = 50.0
    kalman_zscore_threshold: float = 1.5


class CointegrationAnalyzer:
    """
    Cointegration analysis for pairs trading.

    Implements Engle-Granger two-step test, Johansen test,
    and Kalman filter for adaptive hedge ratios.
    """

    XAUUSD_PAIRS: Dict[str, Tuple[str, str]] = {
        "GOLDAMGBD_DFII10": ("GOLDAMGBD", "DFII10"),
        "GOLDAMGBD_DXY": ("GOLDAMGBD", "DTINYUS"),
        "GOLDAMGBD_CPIAUCSL": ("GOLDAMGBD", "CPIAUCSL"),
        "GOLDAMGBD_SP500": ("GOLDAMGBD", "SP500"),
        "DFII10_CPIAUCSL": ("DFII10", "CPIAUCSL"),
        "DXY_BCOM": ("DTINYUS", "BCOM"),
    }

    def __init__(self, config: Optional[PairsConfig] = None):
        self.config = config or PairsConfig()

    def test_cointegration(
        self,
        series1: pd.Series,
        series2: pd.Series,
        pair_name: str = "pair",
    ) -> CointegrationResult:
        """
        Engle-Granger two-step test for cointegration.

        Args:
            series1: First time series
            series2: Second time series
            pair_name: Name of the pair

        Returns:
            CointegrationResult with test statistics
        """
        try:
            from statsmodels.regression.linear_model import OLS
            from statsmodels.tsa.stattools import adfuller, coint
        except ImportError:
            logger.error("statsmodels not available")
            return CointegrationResult(
                pair_name=pair_name,
                test_type=TestType.ENGLE_GRANGER.value,
                is_cointegrated=False,
                p_value=None,
                test_statistic=None,
                critical_value=None,
                hedge_ratio=None,
                intercept=None,
                half_life=None,
            )

        df = pd.DataFrame({"y": series1, "x": series2}).dropna()

        if len(df) < self.config.min_observations:
            logger.warning(f"Insufficient observations: {len(df)}")
            return CointegrationResult(
                pair_name=pair_name,
                test_type=TestType.ENGLE_GRANGER.value,
                is_cointegrated=False,
                p_value=1.0,
                test_statistic=None,
                critical_value=None,
                hedge_ratio=None,
                intercept=None,
                half_life=None,
            )

        y = df["y"].values
        x = df["x"].values
        x_with_const = np.column_stack([np.ones(len(x)), x])

        model = OLS(y, x_with_const).fit()
        residuals = model.resid

        hedge_ratio = model.params[1]
        intercept = model.params[0]

        adf_result = adfuller(residuals, maxlag=1, regression="c")
        adf_stat = adf_result[0]
        p_value = adf_result[1]

        half_life_val = self.half_life(residuals)

        is_cointegrated = p_value < self.config.coint_pvalue_threshold

        critical_values = {
            0.10: -2.89,
            0.05: -3.34,
            0.01: -3.96,
        }

        return CointegrationResult(
            pair_name=pair_name,
            test_type=TestType.ENGLE_GRANGER.value,
            is_cointegrated=is_cointegrated,
            p_value=p_value,
            test_statistic=adf_stat,
            critical_value=critical_values.get(0.05, -3.34),
            hedge_ratio=hedge_ratio,
            intercept=intercept,
            half_life=half_life_val,
        )

    def coint_test(
        self,
        series1: pd.Series,
        series2: pd.Series,
        pair_name: str = "pair",
    ) -> CointegrationResult:
        """
        Cointegration test with p-value using statsmodels.

        Args:
            series1: First time series
            series2: Second time series
            pair_name: Name of the pair

        Returns:
            CointegrationResult with p-value
        """
        try:
            from statsmodels.tsa.stattools import coint
        except ImportError:
            logger.error("statsmodels not available")
            return CointegrationResult(
                pair_name=pair_name,
                test_type="coint_test",
                is_cointegrated=False,
                p_value=1.0,
                test_statistic=None,
                critical_value=None,
                hedge_ratio=None,
                intercept=None,
                half_life=None,
            )

        df = pd.DataFrame({"y": series1, "x": series2}).dropna()

        if len(df) < self.config.min_observations:
            return CointegrationResult(
                pair_name=pair_name,
                test_type="coint_test",
                is_cointegrated=False,
                p_value=1.0,
                test_statistic=None,
                critical_value=None,
                hedge_ratio=None,
                intercept=None,
                half_life=None,
            )

        coint_stat, p_value, crit_values = coint(df["y"], df["x"])

        hedge_ratio = self.hedge_ratio(df["y"], df["x"])

        is_cointegrated = p_value < self.config.coint_pvalue_threshold

        return CointegrationResult(
            pair_name=pair_name,
            test_type="coint_test",
            is_cointegrated=is_cointegrated,
            p_value=p_value,
            test_statistic=coint_stat,
            critical_value=crit_values[1],
            hedge_ratio=hedge_ratio,
            intercept=None,
            half_life=None,
        )

    def hedge_ratio(
        self,
        series1: pd.Series,
        series2: pd.Series,
    ) -> float:
        """
        Calculate optimal hedge ratio using OLS.

        Args:
            series1: First time series
            series2: Second time series

        Returns:
            Hedge ratio (beta)
        """
        try:
            from statsmodels.regression.linear_model import OLS
        except ImportError:
            return 1.0

        df = pd.DataFrame({"y": series1, "x": series2}).dropna()

        if len(df) < 2:
            return 1.0

        model = OLS(df["y"].values, df["x"].values).fit()

        return model.params[0] if len(model.params) > 0 else 1.0

    def johansen_test(
        self,
        data: pd.DataFrame,
        det_order: int = -1,
        k_ar_diff: int = 1,
    ) -> Dict[str, Any]:
        """
        Johansen cointegration test (trace and eigenvalue tests).

        Args:
            data: DataFrame with multiple time series
            det_order: Deterministic terms (-1: no constant, 0: constant, 1: trend)
            k_ar_diff: Number of lagged differences

        Returns:
            Dictionary with trace and eigenvalue test results
        """
        try:
            from statsmodels.tsa.vector_ar.vecm import coint_johansen
        except ImportError:
            logger.error("statsmodels not available for Johansen test")
            return {}

        data_clean = data.dropna()

        if len(data_clean) < self.config.min_observations + k_ar_diff:
            logger.warning(f"Insufficient observations for Johansen test: {len(data_clean)}")
            return {}

        try:
            result = coint_johansen(data_clean.values, det_order=det_order, k_ar_diff=k_ar_diff)

            return {
                "trace_stat": result.lr1,
                "eigen_stat": result.lr2,
                "trace_crit": result.cvt,
                "eigen_crit": result.cvm,
                "evec": result.evec,
                "eig": result.eig,
                "max_eig_rank": result.max_eig_rank,
            }
        except Exception as e:
            logger.error(f"Johansen test failed: {e}")
            return {}

    def eigen_test(
        self,
        data: pd.DataFrame,
        significance_level: int = 0,
    ) -> Tuple[bool, float, float]:
        """
        Maximum eigenvalue test from Johansen results.

        Args:
            data: DataFrame with time series
            significance_level: 0=90%, 1=95%, 2=99%

        Returns:
            Tuple of (is_cointegrated, test_statistic, critical_value)
        """
        johansen_result = self.johansen_test(data)

        if not johansen_result:
            return False, 0.0, 0.0

        eigen_stat = johansen_result["eigen_stat"]
        eigen_crit = johansen_result["eigen_crit"]

        if len(eigen_stat) == 0 or len(eigen_crit) == 0:
            return False, 0.0, 0.0

        test_stat = eigen_stat[0]
        critical_val = eigen_crit[0, significance_level]

        is_cointegrated = test_stat > critical_val

        return is_cointegrated, test_stat, critical_val

    def get_cointegrating_vectors(
        self,
        data: pd.DataFrame,
    ) -> Optional[np.ndarray]:
        """
        Extract cointegrating vectors from Johansen test.

        Args:
            data: DataFrame with time series

        Returns:
            Array of cointegrating vectors
        """
        johansen_result = self.johansen_test(data)

        if "evec" in johansen_result:
            return johansen_result["evec"]

        return None

    def half_life(self, spread: pd.Series) -> Optional[float]:
        """
        Calculate mean reversion half-life.

        Estimates how many periods it takes for the spread
        to revert halfway to its mean.

        Args:
            spread: Spread series

        Returns:
            Half-life in periods, or None if calculation fails
        """
        try:
            from statsmodels.regression.linear_model import OLS
        except ImportError:
            return None

        spread_clean = spread.dropna()

        if len(spread_clean) < 3:
            return None

        y = spread_clean.values
        x = np.column_stack([np.ones(len(y) - 1), y[:-1]])

        try:
            model = OLS(y[1:], x).fit()
            lambda_param = model.params[1]

            if lambda_param <= 0 or lambda_param >= 1:
                return None

            half_life = -np.log(2) / np.log(lambda_param)

            return half_life if np.isfinite(half_life) else None
        except Exception as e:
            logger.debug(f"Half-life calculation failed: {e}")
            return None

    def ornstein_uhlenbeck(
        self,
        spread: pd.Series,
    ) -> Dict[str, float]:
        """
        Estimate Ornstein-Uhlenbeck process parameters.

        dX = theta * (mu - X) * dt + sigma * dW

        Args:
            spread: Spread series

        Returns:
            Dictionary with OU parameters (theta, mu, sigma)
        """
        try:
            from statsmodels.regression.linear_model import OLS
        except ImportError:
            return {"theta": 0.0, "mu": 0.0, "sigma": 0.0}

        spread_clean = spread.dropna()

        if len(spread_clean) < 3:
            return {"theta": 0.0, "mu": 0.0, "sigma": 0.0}

        y = spread_clean.values
        x = np.column_stack([np.ones(len(y) - 1), y[:-1]])

        try:
            model = OLS(y[1:], x).fit()
            theta = -np.log(model.params[1]) if model.params[1] > 0 else 0.0
            mu = (
                model.params[0] / (1 - model.params[1])
                if model.params[1] < 1
                else spread_clean.mean()
            )

            residuals = model.resid
            sigma = np.std(residuals)

            return {
                "theta": theta,
                "mu": mu,
                "sigma": sigma,
            }
        except Exception as e:
            logger.debug(f"OU parameter estimation failed: {e}")
            return {"theta": 0.0, "mu": 0.0, "sigma": 0.0}

    def kalman_filter(
        self,
        y: pd.Series,
        x: pd.Series,
        delta: float = 1e-5,
        Ve: float = 1e-3,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Kalman filter for adaptive hedge ratio estimation.

        Args:
            y: Dependent variable (e.g., gold price)
            x: Independent variable (e.g., real yields)
            delta: Transition covariance parameter
            Ve: Measurement noise variance

        Returns:
            Tuple of (hedge_ratios, intercepts, spreads)
        """
        n = len(y)

        theta = np.zeros(n)
        alpha = np.zeros(n)
        R = np.eye(2)
        P = np.eye(2)

        hedge_ratios = pd.Series(index=y.index, dtype=float)
        intercepts = pd.Series(index=y.index, dtype=float)
        spreads = pd.Series(index=y.index, dtype=float)

        y_arr = y.values
        x_arr = x.values

        for t in range(n):
            if t == 0:
                theta[t] = self.hedge_ratio(y.iloc[:10], x.iloc[:10]) if t < 10 else 1.0
                alpha[t] = y_arr[t] - theta[t] * x_arr[t]
                hedge_ratios.iloc[t] = theta[t]
                intercepts.iloc[t] = alpha[t]
                spreads.iloc[t] = 0.0
                continue

            F = np.array([[x_arr[t], 1]])

            y_pred = F @ np.array([theta[t - 1], alpha[t - 1]])
            e = y_arr[t] - y_pred

            S = F @ P @ F.T + Ve
            if S == 0:
                S = 1e-10

            K = P @ F.T / S

            R = P - np.outer(K, F) @ P + delta * np.eye(2)

            theta[t] = theta[t - 1] + K[0] * e
            alpha[t] = alpha[t - 1] + K[1] * e

            P = R

            hedge_ratios.iloc[t] = theta[t]
            intercepts.iloc[t] = alpha[t]
            spreads.iloc[t] = y_arr[t] - theta[t] * x_arr[t] - alpha[t]

        return hedge_ratios, intercepts, spreads

    def kalman_signals(
        self,
        y: pd.Series,
        x: pd.Series,
        entry_threshold: float = 1.5,
        exit_threshold: float = 0.5,
        lookback: int = 60,
    ) -> pd.DataFrame:
        """
        Generate trading signals using Kalman filter hedge ratio.

        Args:
            y: Dependent variable
            x: Independent variable
            entry_threshold: Z-score threshold for entry
            exit_threshold: Z-score threshold for exit
            lookback: Window for z-score calculation

        Returns:
            DataFrame with signals and hedge ratios
        """
        hedge_ratios, intercepts, spreads = self.kalman_filter(y, x)

        spread_ma = spreads.rolling(lookback, min_periods=10).mean()
        spread_std = spreads.rolling(lookback, min_periods=10).std()
        spread_std = spread_std.replace(0, 1.0)

        zscore = (spreads - spread_ma) / spread_std

        signals = pd.DataFrame(
            {
                "y": y,
                "x": x,
                "hedge_ratio": hedge_ratios,
                "intercept": intercepts,
                "spread": spreads,
                "zscore": zscore,
            }
        )

        signals["signal"] = SignalType.FLAT.value

        signals.loc[zscore < -entry_threshold, "signal"] = SignalType.LONG.value
        signals.loc[zscore > entry_threshold, "signal"] = SignalType.SHORT.value

        signals.loc[(zscore > -exit_threshold) & (zscore < exit_threshold), "signal"] = (
            SignalType.FLAT.value
        )

        return signals


class PairsTradingSignals:
    """
    Pairs trading signal generation.

    Calculates spreads, z-scores, Bollinger bands,
    and generates entry/exit signals.
    """

    SERIES_MAP: Dict[str, str] = {
        "GOLDAMGBD": "GOLDAMGBD",
        "DFII10": "DFII10",
        "DXY": "DTINYUS",
        "CPIAUCSL": "CPIAUCSL",
        "SP500": "SP500",
        "BCOM": "BCOM",
    }

    def __init__(self, config: Optional[PairsConfig] = None):
        self.config = config or PairsConfig()
        self.analyzer = CointegrationAnalyzer(config)
        self._pairs: Dict[str, Tuple[str, str]] = {}
        self._cached_data: Dict[str, pd.DataFrame] = {}
        self._fred_client = None

        self._init_xauusd_pairs()

    def _init_xauusd_pairs(self):
        """Initialize pre-defined XAUUSD pairs."""
        for name, (series1, series2) in CointegrationAnalyzer.XAUUSD_PAIRS.items():
            self.add_pair(series1, series2, name)

    def add_pair(self, series1: str, series2: str, name: Optional[str] = None):
        """
        Add a trading pair.

        Args:
            series1: First series identifier
            series2: Second series identifier
            name: Optional custom name for the pair
        """
        if name is None:
            name = f"{series1}_{series2}"

        self._pairs[name] = (series1, series2)

    def remove_pair(self, name: str):
        """Remove a trading pair."""
        if name in self._pairs:
            del self._pairs[name]

    def get_pairs(self) -> Dict[str, Tuple[str, str]]:
        """Get all configured pairs."""
        return self._pairs.copy()

    def _get_fred_client(self):
        """Get or create FRED client."""
        if self._fred_client is None:
            try:
                import os
                from quantfund.data.fred_client import FredClient

                api_key = os.environ.get("FRED_API_KEY")
                if api_key:
                    self._fred_client = FredClient(api_key=api_key)
            except Exception as e:
                logger.warning(f"Could not create FRED client: {e}")
        return self._fred_client

    def fetch_data(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.Series:
        """Fetch series data from FRED."""
        client = self._get_fred_client()

        if client is None:
            return pd.Series()

        try:
            df = client.get_observations(series_id, start_date, end_date)
            if not df.empty:
                df = df.set_index("date").sort_index()
                return df["value"]
        except Exception as e:
            logger.warning(f"Failed to fetch {series_id}: {e}")

        return pd.Series()

    def calculate_spread(
        self,
        series1: pd.Series,
        series2: pd.Series,
        hedge_ratio: Optional[float] = None,
    ) -> pd.Series:
        """
        Calculate spread between two series.

        Args:
            series1: First series
            series2: Second series
            hedge_ratio: Optional hedge ratio (calculated if not provided)

        Returns:
            Spread series
        """
        if hedge_ratio is None:
            hedge_ratio = self.analyzer.hedge_ratio(series1, series2)

        spread = series1 - hedge_ratio * series2

        return spread

    def calculate_zscore(
        self,
        spread: pd.Series,
        lookback: Optional[int] = None,
    ) -> pd.Series:
        """
        Calculate z-score of spread.

        Args:
            spread: Spread series
            lookback: Rolling window for z-score calculation

        Returns:
            Z-score series
        """
        if lookback is None:
            lookback = self.config.lookback_window

        rolling_mean = spread.rolling(lookback, min_periods=10).mean()
        rolling_std = spread.rolling(lookback, min_periods=10).std()
        rolling_std = rolling_std.replace(0, 1.0)

        zscore = (spread - rolling_mean) / rolling_std

        return zscore

    def bollinger_bands(
        self,
        spread: pd.Series,
        lookback: Optional[int] = None,
        num_std: float = 2.0,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate Bollinger bands on spread.

        Args:
            spread: Spread series
            lookback: Rolling window
            num_std: Number of standard deviations

        Returns:
            Tuple of (upper_band, middle_band, lower_band)
        """
        if lookback is None:
            lookback = self.config.lookback_window

        middle = spread.rolling(lookback, min_periods=10).mean()
        std = spread.rolling(lookback, min_periods=10).std()

        upper = middle + num_std * std
        lower = middle - num_std * std

        return upper, middle, lower

    def mean_reversion_signal(
        self,
        spread: pd.Series,
        zscore: Optional[pd.Series] = None,
    ) -> pd.Series:
        """
        Mean reversion entry signal based on z-score.

        Args:
            spread: Spread series
            zscore: Optional pre-calculated z-score

        Returns:
            Signal series (1=long, -1=short, 0=flat)
        """
        if zscore is None:
            zscore = self.calculate_zscore(spread)

        signal = pd.Series(0, index=spread.index)

        entry = self.config.entry_threshold
        exit_z = self.config.exit_threshold

        signal[zscore < -entry] = 1
        signal[zscore > entry] = -1

        signal[(zscore >= -exit_z) & (zscore <= exit_z)] = 0

        return signal

    def generate_signals(
        self,
        spread: pd.Series,
        pair_name: str = "pair",
        use_kalman: bool = False,
        y: Optional[pd.Series] = None,
        x: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Generate entry/exit trading signals.

        Args:
            spread: Spread series
            pair_name: Name of the pair
            use_kalman: Whether to use Kalman filter hedge ratio
            y: Required if use_kalman=True
            x: Required if use_kalman=True

        Returns:
            DataFrame with signals and indicators
        """
        if use_kalman and y is not None and x is not None:
            kalman_result = self.analyzer.kalman_filter(y, x)
            spread = kalman_result[2]
            hedge_ratio_series = kalman_result[0]
        else:
            hedge_ratio_series = None

        zscore = self.calculate_zscore(spread)
        upper_bb, middle_bb, lower_bb = self.bollinger_bands(spread)

        df = pd.DataFrame(
            {
                "spread": spread,
                "zscore": zscore,
                "bb_upper": upper_bb,
                "bb_middle": middle_bb,
                "bb_lower": lower_bb,
                "hedge_ratio": hedge_ratio_series,
            }
        )

        df["entry_signal"] = SignalType.FLAT.value
        df["exit_signal"] = False
        df["position"] = 0

        entry = self.config.entry_threshold
        exit_z = self.config.exit_threshold
        stop_bands = self.config.stop_loss_bands
        tp_bands = self.config.take_profit_bands

        in_position = False

        for i in range(len(df)):
            z = df["zscore"].iloc[i]

            if not in_position:
                if z < -entry:
                    df.iloc[i, df.columns.get_loc("entry_signal")] = SignalType.LONG.value
                    in_position = True
                elif z > entry:
                    df.iloc[i, df.columns.get_loc("entry_signal")] = SignalType.SHORT.value
                    in_position = True
            else:
                if abs(z) < exit_z:
                    df.iloc[i, df.columns.get_loc("exit_signal")] = True
                    in_position = False
                elif abs(z) > stop_bands:
                    df.iloc[i, df.columns.get_loc("exit_signal")] = True
                    in_position = False
                elif abs(z) < tp_bands:
                    df.iloc[i, df.columns.get_loc("exit_signal")] = True
                    in_position = False

        return df

    def entry_signal(
        self,
        zscore: pd.Series,
        position: int = 0,
    ) -> int:
        """
        Determine entry signal based on z-score.

        Args:
            zscore: Current z-score
            position: Current position (0=flat, 1=long, -1=short)

        Returns:
            Signal type (1=long, -1=short, 0=flat)
        """
        if position != 0:
            return 0

        entry = self.config.entry_threshold

        if zscore < -entry:
            return SignalType.LONG.value
        elif zscore > entry:
            return SignalType.SHORT.value

        return SignalType.FLAT.value

    def exit_signal(
        self,
        zscore: pd.Series,
        position: int,
    ) -> bool:
        """
        Determine exit signal based on z-score.

        Args:
            zscore: Current z-score
            position: Current position

        Returns:
            True if should exit, False otherwise
        """
        if position == 0:
            return False

        exit_z = self.config.exit_threshold
        stop_bands = self.config.stop_loss_bands

        if abs(zscore) < exit_z:
            return True
        if abs(zscore) > stop_bands:
            return True

        return False

    def trailing_stop(
        self,
        spread: pd.Series,
        position: int,
        entry_spread: float,
        trailing_pct: float = 0.02,
    ) -> bool:
        """
        Trailing stop logic.

        Args:
            spread: Current spread
            position: Current position (1=long, -1=short)
            entry_spread: Spread at entry
            trailing_pct: Trailing stop percentage

        Returns:
            True if stop hit, False otherwise
        """
        if position == 0:
            return False

        if position == 1:
            stop_level = entry_spread * (1 + trailing_pct)
            if spread > stop_level:
                new_stop = spread * (1 - trailing_pct)
                if new_stop > stop_level:
                    return False
                return spread < new_stop

        elif position == -1:
            stop_level = entry_spread * (1 - trailing_pct)
            if spread < stop_level:
                new_stop = spread * (1 + trailing_pct)
                if new_stop < stop_level:
                    return False
                return spread > new_stop

        return False

    def analyze_pair(
        self,
        series1: pd.Series,
        series2: pd.Series,
        pair_name: str = "pair",
    ) -> Dict[str, Any]:
        """
        Complete analysis of a pair.

        Args:
            series1: First series
            series2: Second series
            pair_name: Name of the pair

        Returns:
            Dictionary with analysis results
        """
        coint_result = self.analyzer.test_cointegration(series1, series2, pair_name)

        hedge_ratio = coint_result.hedge_ratio or 1.0
        spread = self.calculate_spread(series1, series2, hedge_ratio)
        zscore = self.calculate_zscore(spread)

        upper_bb, middle_bb, lower_bb = self.bollinger_bands(spread)

        half_life = coint_result.half_life
        if half_life is None:
            half_life = self.analyzer.half_life(spread)

        ou_params = self.analyzer.ornstein_uhlenbeck(spread)

        signals = self.generate_signals(spread, pair_name)

        return {
            "cointegration": coint_result.to_dict(),
            "spread": spread,
            "zscore": zscore,
            "bollinger_bands": {
                "upper": upper_bb,
                "middle": middle_bb,
                "lower": lower_bb,
            },
            "half_life": half_life,
            "ou_parameters": ou_params,
            "signals": signals,
        }

    def run_batch_analysis(
        self,
        data: Dict[str, pd.Series],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, CointegrationResult]:
        """
        Run cointegration analysis on multiple pairs.

        Args:
            data: Dictionary of series name -> series data
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Dictionary of pair name -> CointegrationResult
        """
        results = {}

        for pair_name, (series1_name, series2_name) in self._pairs.items():
            if series1_name not in data or series2_name not in data:
                continue

            series1 = data[series1_name]
            series2 = data[series2_name]

            if start_date:
                series1 = series1[series1.index >= start_date]
                series2 = series2[series2.index >= start_date]
            if end_date:
                series1 = series1[series1.index <= end_date]
                series2 = series2[series2.index <= end_date]

            result = self.analyzer.test_cointegration(series1, series2, pair_name)
            results[pair_name] = result

        return results

    def get_cointegrated_pairs(
        self,
        results: Dict[str, CointegrationResult],
    ) -> List[str]:
        """
        Get list of cointegrated pairs.

        Args:
            results: Dictionary of cointegration results

        Returns:
            List of pair names that are cointegrated
        """
        return [name for name, result in results.items() if result.is_cointegrated]

    def save_to_db(
        self,
        results: List[CointegrationResult],
        host: Optional[str] = None,
        database: str = "freddata",
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """Save cointegration results to database."""
        try:
            import os
            import psycopg2
        except ImportError:
            logger.warning("psycopg2 not available, skipping DB save")
            return False

        host = host or os.environ.get("FRED_DB_HOST", "localhost")
        user = user or os.environ.get("FRED_DB_USER", "postgres")
        password = password or os.environ.get("FRED_DB_PASSWORD", "")

        conn_str = f"host={host} port=5432 dbname={database} user={user} password={password}"

        try:
            conn = psycopg2.connect(conn_str)
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS cointegration_results (
                    id SERIAL PRIMARY KEY,
                    pair_name VARCHAR(100) NOT NULL,
                    test_type VARCHAR(50) NOT NULL,
                    is_cointegrated BOOLEAN NOT NULL,
                    p_value DOUBLE PRECISION,
                    test_statistic DOUBLE PRECISION,
                    critical_value DOUBLE PRECISION,
                    hedge_ratio DOUBLE PRECISION,
                    intercept DOUBLE PRECISION,
                    half_life DOUBLE PRECISION,
                    eigenvectors JSONB,
                    eigenvalues JSONB,
                    tested_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(pair_name, test_type, tested_at)
                )
            """)

            for result in results:
                cur.execute(
                    """
                    INSERT INTO cointegration_results 
                    (pair_name, test_type, is_cointegrated, p_value, test_statistic,
                     critical_value, hedge_ratio, intercept, half_life, eigenvectors,
                     eigenvalues, tested_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        result.pair_name,
                        result.test_type,
                        result.is_cointegrated,
                        result.p_value,
                        result.test_statistic,
                        result.critical_value,
                        result.hedge_ratio,
                        result.intercept,
                        result.half_life,
                        str(result.eigenvectors.tolist())
                        if result.eigenvectors is not None
                        else None,
                        str(result.eigenvalues.tolist())
                        if result.eigenvalues is not None
                        else None,
                        result.tested_at,
                    ),
                )

            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"Saved {len(results)} cointegration results to database")
            return True

        except Exception as e:
            logger.error(f"Failed to save cointegration results: {e}")
            return False

    def save_signals_to_db(
        self,
        signals: pd.DataFrame,
        pair_name: str,
        host: Optional[str] = None,
        database: str = "freddata",
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """Save trading signals to database."""
        try:
            import os
            import psycopg2
        except ImportError:
            logger.warning("psycopg2 not available, skipping DB save")
            return False

        host = host or os.environ.get("FRED_DB_HOST", "localhost")
        user = user or os.environ.get("FRED_DB_USER", "postgres")
        password = password or os.environ.get("FRED_DB_PASSWORD", "")

        conn_str = f"host={host} port=5432 dbname={database} user={user} password={password}"

        try:
            conn = psycopg2.connect(conn_str)
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pair_signals (
                    id SERIAL PRIMARY KEY,
                    date TIMESTAMP NOT NULL,
                    pair_name VARCHAR(100) NOT NULL,
                    signal_type INTEGER NOT NULL,
                    spread DOUBLE PRECISION,
                    zscore DOUBLE PRECISION,
                    hedge_ratio DOUBLE PRECISION,
                    bb_upper DOUBLE PRECISION,
                    bb_middle DOUBLE PRECISION,
                    bb_lower DOUBLE PRECISION,
                    entry_signal INTEGER,
                    exit_signal BOOLEAN,
                    position INTEGER,
                    generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(date, pair_name)
                )
            """)

            for idx, row in signals.iterrows():
                cur.execute(
                    """
                    INSERT INTO pair_signals 
                    (date, pair_name, signal_type, spread, zscore, hedge_ratio,
                     bb_upper, bb_middle, bb_lower, entry_signal, exit_signal, position)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        idx,
                        pair_name,
                        int(row.get("entry_signal", 0)),
                        row.get("spread"),
                        row.get("zscore"),
                        row.get("hedge_ratio"),
                        row.get("bb_upper"),
                        row.get("bb_middle"),
                        row.get("bb_lower"),
                        row.get("entry_signal"),
                        row.get("exit_signal"),
                        row.get("position"),
                    ),
                )

            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"Saved {len(signals)} signals to database")
            return True

        except Exception as e:
            logger.error(f"Failed to save signals to database: {e}")
            return False


def create_cointegration_table() -> str:
    """SQL to create cointegration_results table."""
    return """
    CREATE TABLE IF NOT EXISTS cointegration_results (
        id SERIAL PRIMARY KEY,
        pair_name VARCHAR(100) NOT NULL,
        test_type VARCHAR(50) NOT NULL,
        is_cointegrated BOOLEAN NOT NULL,
        p_value DOUBLE PRECISION,
        test_statistic DOUBLE PRECISION,
        critical_value DOUBLE PRECISION,
        hedge_ratio DOUBLE PRECISION,
        intercept DOUBLE PRECISION,
        half_life DOUBLE PRECISION,
        eigenvectors JSONB,
        eigenvalues JSONB,
        tested_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(pair_name, test_type, tested_at)
    );
    
    CREATE INDEX IF NOT EXISTS idx_coint_results_pair ON cointegration_results(pair_name);
    CREATE INDEX IF NOT EXISTS idx_coint_results_date ON cointegration_results(tested_at);
    """


def create_pair_signals_table() -> str:
    """SQL to create pair_signals table."""
    return """
    CREATE TABLE IF NOT EXISTS pair_signals (
        id SERIAL PRIMARY KEY,
        date TIMESTAMP NOT NULL,
        pair_name VARCHAR(100) NOT NULL,
        signal_type INTEGER NOT NULL,
        spread DOUBLE PRECISION,
        zscore DOUBLE PRECISION,
        hedge_ratio DOUBLE PRECISION,
        bb_upper DOUBLE PRECISION,
        bb_middle DOUBLE PRECISION,
        bb_lower DOUBLE PRECISION,
        entry_signal INTEGER,
        exit_signal BOOLEAN,
        position INTEGER,
        generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(date, pair_name)
    );
    
    CREATE INDEX IF NOT EXISTS idx_pair_signals_pair ON pair_signals(pair_name);
    CREATE INDEX IF NOT EXISTS idx_pair_signals_date ON pair_signals(date);
    """


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    if len(sys.argv) > 1:
        if sys.argv[1] == "--create-coint-table":
            print(create_cointegration_table())
        elif sys.argv[1] == "--create-signals-table":
            print(create_pair_signals_table())
    else:
        print("Cointegration and Pairs Trading Module")
        print("=" * 50)
        print("Usage:")
        print("  python fred_cointegration.py --create-coint-table   # Print SQL for results table")
        print("  python fred_cointegration.py --create-signals-table # Print SQL for signals table")
        print("")
        print("Example:")
        print(
            "  from quantfund.strategies.fred_cointegration import CointegrationAnalyzer, PairsTradingSignals"
        )
        print("  analyzer = CointegrationAnalyzer()")
        print("  signals = PairsTradingSignals()")
