"""
Walk-Forward Validation System
================================
Rigorous out-of-sample strategy evaluation following Renaissance/Two Sigma
institutional standards.

Key design decisions:
  - Embargo periods prevent lookahead bias near window boundaries
  - Z-score normalisation is fit on TRAIN only, applied to TEST
  - Each window is fully independent (no state leaks across windows)
  - Multiple hypothesis testing correction applied across signals
  - Results accumulate into a time-series of OOS metrics
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np
import pandas as pd
from scipy import stats

from quantfund.data.pipeline import PointInTimeWindow
from quantfund.metrics.engine import PerformanceMetrics, compute_metrics, compute_ic

__all__ = [
    "WalkForwardResult",
    "WalkForwardValidator",
    "SignalEvaluator",
    "MultipleTestingCorrector",
]


# ---------------------------------------------------------------------------
# Protocol for strategies
# ---------------------------------------------------------------------------


class StrategyProtocol(Protocol):
    """
    Minimum interface a strategy must implement for walk-forward validation.
    """

    def fit(self, train_features: pd.DataFrame, train_ohlcv: pd.DataFrame) -> None:
        """Train on historical data. Must NOT see test data."""
        ...

    def predict(self, test_features: pd.DataFrame) -> pd.Series:
        """
        Return signal series on the test window.

        Values: positive = long, negative = short, zero = flat.
        Magnitude = conviction (will be normalised to position size).
        """
        ...


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class WalkForwardResult:
    """Results from a single walk-forward window."""

    window_idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp

    # OOS performance on this window
    metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)

    # Signal quality
    ic: float = 0.0  # Information Coefficient
    ic_pvalue: float = 1.0
    icir: float = 0.0  # IC / std(IC)

    # Raw returns produced by strategy in this window
    returns: pd.Series = field(default_factory=pd.Series)

    def is_live_worthy(self) -> bool:
        """
        Minimum bar to consider deploying capital on this strategy.
        Sharpe > 0.5, p < 0.05, IC > 0.02.
        """
        return self.metrics.sharpe > 0.5 and self.metrics.p_value < 0.05 and self.ic > 0.02


@dataclass
class WalkForwardSummary:
    """Aggregated statistics across all windows."""

    n_windows: int
    n_significant: int  # windows with p < 0.05
    mean_sharpe: float
    std_sharpe: float
    mean_ic: float
    icir: float  # mean(IC) / std(IC)
    combined_returns: pd.Series  # concatenation of all OOS returns
    combined_metrics: PerformanceMetrics
    window_results: list[WalkForwardResult] = field(default_factory=list)

    def is_deployable(self) -> bool:
        """
        Strategy is deployable if:
          - ICIR >= 0.5
          - Mean Sharpe >= 0.5
          - >50% windows are significant
        """
        return (
            self.icir >= 0.5
            and self.mean_sharpe >= 0.5
            and (self.n_significant / max(self.n_windows, 1)) > 0.5
        )

    def summary(self) -> str:
        pct = self.n_significant / max(self.n_windows, 1) * 100
        return (
            f"Windows={self.n_windows}  Sig={self.n_significant} ({pct:.0f}%)  "
            f"MeanSharpe={self.mean_sharpe:.2f}±{self.std_sharpe:.2f}  "
            f"MeanIC={self.mean_ic:.4f}  ICIR={self.icir:.2f}  "
            f"OOS Sharpe={self.combined_metrics.sharpe:.2f}  "
            f"Deployable={'YES' if self.is_deployable() else 'NO'}"
        )


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------


class WalkForwardValidator:
    """
    Walk-forward validation engine.

    Usage::

        validator = WalkForwardValidator(
            window=PointInTimeWindow(train_bars=252*390, test_bars=63*390),
            freq="1min",
        )
        summary = validator.run(strategy, ohlcv_df, feature_df)
        print(summary.summary())
    """

    def __init__(
        self,
        window: PointInTimeWindow | None = None,
        freq: str = "1min",
        transaction_cost_pct: float = 0.0001,  # 1 pip on FX
        slippage_pct: float = 0.00005,  # half-pip
        risk_free_rate: float = 0.04,
        verbose: bool = True,
    ) -> None:
        self.window = window or PointInTimeWindow()
        self.freq = freq
        self.tc = transaction_cost_pct
        self.slip = slippage_pct
        self.rf = risk_free_rate
        self.verbose = verbose

    def run(
        self,
        strategy: StrategyProtocol,
        ohlcv: pd.DataFrame,
        features: pd.DataFrame,
        forward_return_bars: int = 1,
    ) -> WalkForwardSummary:
        """
        Run walk-forward validation.

        Parameters
        ----------
        strategy            : Strategy implementing StrategyProtocol.
        ohlcv               : Full OHLCV history (aligned with features).
        features            : Full feature matrix (same index as ohlcv).
        forward_return_bars : How many bars ahead the signal predicts.
        """
        # Align features and OHLCV on common index
        common_idx = ohlcv.index.intersection(features.index)
        ohlcv = ohlcv.loc[common_idx]
        features = features.loc[common_idx]

        # Compute forward returns (target variable)
        log_close = np.log(ohlcv["close"])
        fwd_returns = log_close.shift(-forward_return_bars) - log_close

        window_results: list[WalkForwardResult] = []

        for idx, (train_ohlcv, test_ohlcv) in enumerate(self.window.generate(ohlcv)):
            train_feat = features.loc[train_ohlcv.index]
            test_feat = features.loc[test_ohlcv.index]
            train_fwd = fwd_returns.loc[train_ohlcv.index]
            test_fwd = fwd_returns.loc[test_ohlcv.index]

            # --- Normalise features (fit on train, apply to test) ---
            train_feat_norm, test_feat_norm = self._normalise(train_feat, test_feat)

            # --- Train ---
            strategy.fit(train_feat_norm, train_ohlcv)

            # --- Predict on test (OOS) ---
            signals = strategy.predict(test_feat_norm)
            signals = signals.reindex(test_ohlcv.index).fillna(0.0)

            # --- Convert signals to returns ---
            oos_returns = self._signals_to_returns(signals, test_ohlcv, forward_return_bars)

            # --- Compute metrics ---
            metrics = compute_metrics(oos_returns, freq=self.freq, risk_free_rate=self.rf)

            # --- IC on test window ---
            ic, ic_pval = compute_ic(signals.values, test_fwd.reindex(signals.index).values)

            result = WalkForwardResult(
                window_idx=idx,
                train_start=train_ohlcv.index[0],
                train_end=train_ohlcv.index[-1],
                test_start=test_ohlcv.index[0],
                test_end=test_ohlcv.index[-1],
                metrics=metrics,
                ic=ic,
                ic_pvalue=ic_pval,
                returns=oos_returns,
            )
            window_results.append(result)

            if self.verbose:
                print(
                    f"  Window {idx:02d} | "
                    f"Test {result.test_start.date()} → {result.test_end.date()} | "
                    f"{metrics.summary()}"
                )

        return self._aggregate(window_results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Z-score normalise features.
        Parameters estimated on TRAIN only, applied to both.
        """
        mu = train.mean()
        sig = train.std(ddof=1).replace(0, np.nan)

        train_norm = (train - mu) / sig
        test_norm = (test - mu) / sig

        # Cap outliers at ±5 sigma
        train_norm = train_norm.clip(-5, 5)
        test_norm = test_norm.clip(-5, 5)

        return train_norm.fillna(0.0), test_norm.fillna(0.0)

    def _signals_to_returns(
        self,
        signals: pd.Series,
        ohlcv: pd.DataFrame,
        fwd_bars: int,
    ) -> pd.Series:
        """
        Convert a signal series to a P&L return series.

        Assumes:
        - Signal at bar t is acted on at bar t+1 open (execution lag)
        - Transaction costs + slippage deducted on position change
        - Signal is normalised to ±1 (position direction + magnitude)
        """
        close_ret = np.log(ohlcv["close"]).diff().shift(-fwd_bars)

        # Position is signal clipped to [-1, 1] and normalised
        pos_max = signals.abs().max()
        if pos_max > 0:
            positions = signals / pos_max
        else:
            positions = signals * 0.0

        # Execution lag: position established at next bar
        pos_lagged = positions.shift(1).fillna(0.0)

        # Gross P&L
        gross_pnl = pos_lagged * close_ret

        # Transaction costs on position changes
        delta_pos = pos_lagged.diff().abs().fillna(0.0)
        costs = delta_pos * (self.tc + self.slip)

        net_pnl = gross_pnl - costs
        return net_pnl.dropna()

    @staticmethod
    def _aggregate(windows: list[WalkForwardResult]) -> WalkForwardSummary:
        """Aggregate across all walk-forward windows."""
        if not windows:
            return WalkForwardSummary(
                n_windows=0,
                n_significant=0,
                mean_sharpe=0.0,
                std_sharpe=0.0,
                mean_ic=0.0,
                icir=0.0,
                combined_returns=pd.Series(dtype=float),
                combined_metrics=PerformanceMetrics(),
            )

        sharpes = np.array([w.metrics.sharpe for w in windows])
        ics = np.array([w.ic for w in windows])
        sig_count = sum(1 for w in windows if w.metrics.p_value < 0.05)

        icir = float(ics.mean() / (ics.std(ddof=1) + 1e-12))

        all_returns = pd.concat([w.returns for w in windows]).sort_index()
        combined = compute_metrics(all_returns)

        # Update ICIR on each window
        ic_std = float(ics.std(ddof=1)) if len(ics) > 1 else 1e-12
        for w in windows:
            w.icir = float(w.ic / ic_std) if ic_std > 0 else 0.0

        return WalkForwardSummary(
            n_windows=len(windows),
            n_significant=sig_count,
            mean_sharpe=float(sharpes.mean()),
            std_sharpe=float(sharpes.std(ddof=1)),
            mean_ic=float(ics.mean()),
            icir=icir,
            combined_returns=all_returns,
            combined_metrics=combined,
            window_results=windows,
        )


# ---------------------------------------------------------------------------
# Signal evaluator (batch IC testing for alpha research)
# ---------------------------------------------------------------------------


class SignalEvaluator:
    """
    Evaluate many candidate signals against forward returns.

    Applies multiple hypothesis testing correction to control false discovery
    rate (FDR) - critical when testing hundreds of features.

    Usage::

        evaluator = SignalEvaluator(features_df, forward_returns_series)
        results   = evaluator.evaluate_all(fdr_alpha=0.05)
        good      = evaluator.get_significant_signals(results)
    """

    def __init__(
        self,
        features: pd.DataFrame,
        forward_returns: pd.Series,
        method: str = "spearman",
    ) -> None:
        self.features = features
        self.forward_returns = forward_returns
        self.method = method

    def evaluate_all(self) -> pd.DataFrame:
        """
        Compute IC, t-stat, and raw p-value for every feature column.
        Returns a DataFrame sorted by |IC|.
        """
        results = []
        for col in self.features.columns:
            sig = self.features[col].dropna()
            fwd = self.forward_returns.reindex(sig.index).dropna()
            aligned_sig = sig.reindex(fwd.index)

            ic, pval = compute_ic(aligned_sig.values, fwd.values, method=self.method)
            n = len(fwd)

            results.append(
                {
                    "signal": col,
                    "ic": ic,
                    "abs_ic": abs(ic),
                    "p_value": pval,
                    "n": n,
                }
            )

        df = pd.DataFrame(results).sort_values("abs_ic", ascending=False)
        df.reset_index(drop=True, inplace=True)
        return df

    def get_significant_signals(
        self,
        evaluated: pd.DataFrame,
        fdr_alpha: float = 0.05,
    ) -> pd.DataFrame:
        """
        Apply Benjamini-Hochberg FDR correction and return significant signals.

        This prevents false discoveries when testing many features simultaneously.
        """
        n = len(evaluated)
        sorted_df = evaluated.sort_values("p_value").copy()
        sorted_df["rank"] = np.arange(1, n + 1)
        sorted_df["bh_threshold"] = sorted_df["rank"] / n * fdr_alpha
        sorted_df["significant"] = sorted_df["p_value"] <= sorted_df["bh_threshold"]

        # BH: all hypotheses up to the last significant one are accepted
        if sorted_df["significant"].any():
            last_sig_rank = sorted_df[sorted_df["significant"]]["rank"].max()
            sorted_df.loc[sorted_df["rank"] <= last_sig_rank, "significant"] = True

        return sorted_df[sorted_df["significant"]].drop(columns=["rank"])


# ---------------------------------------------------------------------------
# Multiple testing corrector (standalone utility)
# ---------------------------------------------------------------------------


class MultipleTestingCorrector:
    """
    Standalone Benjamini-Hochberg and Bonferroni correctors.

    Use after running many backtests to avoid false discoveries.
    """

    @staticmethod
    def benjamini_hochberg(
        p_values: Sequence[float],
        alpha: float = 0.05,
    ) -> np.ndarray:
        """
        Returns a boolean array: True if the null hypothesis is rejected.

        Parameters
        ----------
        p_values : Raw p-values from independent tests.
        alpha    : FDR control level.
        """
        p = np.asarray(p_values, dtype=float)
        n = len(p)
        order = np.argsort(p)
        thresholds = (np.arange(1, n + 1) / n) * alpha
        significant = np.zeros(n, dtype=bool)

        # Find last significant rank
        below = p[order] <= thresholds
        if below.any():
            last = np.where(below)[0].max()
            significant[order[: last + 1]] = True

        return significant

    @staticmethod
    def bonferroni(
        p_values: Sequence[float],
        alpha: float = 0.05,
    ) -> np.ndarray:
        """Most conservative: divide alpha by number of tests."""
        p = np.asarray(p_values, dtype=float)
        return p < (alpha / len(p))


# ---------------------------------------------------------------------------
# Type alias for sequence
# ---------------------------------------------------------------------------
from typing import Sequence  # noqa: E402 (keep at bottom to avoid circular)
