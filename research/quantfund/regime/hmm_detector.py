"""
HMM-based Market Regime Detector
==================================
Classifies market into 3 regimes using a Gaussian Hidden Markov Model:
  - low_vol  (state 0): calm trending markets
  - high_vol (state 1): elevated volatility, mean-reverting
  - crisis   (state 2): extreme volatility, fat tails

Design principles (Renaissance-style):
- Only causal features: no future data leaks into regime labels
- States are relabelled deterministically by ascending mean realised-vol,
  so semantics are stable regardless of HMM random initialisation
- ``predict()`` never refits — must call ``fit()`` offline on training data
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

__all__ = ["RegimeConfig", "RegimeDetector", "RegimeLabel"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RegimeLabel = str  # "low_vol" | "high_vol" | "crisis"

_LABEL_MAP = {0: "low_vol", 1: "high_vol", 2: "crisis"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class RegimeConfig:
    """Hyperparameters for the HMM regime detector."""

    n_regimes: int = 3
    n_iter: int = 100
    covariance_type: str = "diag"
    random_state: int = 42
    # Rolling windows (bars) for feature construction — all causal
    vol_window: int = 20
    return_window: int = 5


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class RegimeDetector:
    """
    Gaussian HMM regime classifier.

    Usage::

        detector = RegimeDetector()
        detector.fit(train_returns)
        labels = detector.predict_named(test_returns)
    """

    def __init__(self, config: Optional[RegimeConfig] = None) -> None:
        self.config = config or RegimeConfig()
        self._model = None  # hmmlearn GaussianHMM, set on fit()
        self._state_map: dict[int, int] = {}  # raw HMM state → relabelled state

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, train_returns: pd.Series) -> "RegimeDetector":
        """
        Fit the HMM on a log-return series.

        Parameters
        ----------
        train_returns:
            Log returns (e.g. ``np.log(close).diff()``), tz-aware or naive.
        """
        try:
            from hmmlearn.hmm import GaussianHMM
        except ImportError:
            raise ImportError("hmmlearn not installed. Run: pip install hmmlearn>=0.3")

        X = self._build_features(train_returns)

        model = GaussianHMM(
            n_components=self.config.n_regimes,
            covariance_type=self.config.covariance_type,
            n_iter=self.config.n_iter,
            random_state=self.config.random_state,
        )
        model.fit(X)
        self._model = model

        # Relabel states: sort by ascending mean realised-vol (feature index 1)
        raw_states = model.predict(X)
        rv_col = 1  # realised_vol column in feature matrix
        mean_rv_per_state = [
            X[raw_states == s, rv_col].mean() if (raw_states == s).any() else 0.0
            for s in range(self.config.n_regimes)
        ]
        # Map: sorted order → relabelled index (0=low, 1=high, 2=crisis)
        sorted_states = np.argsort(mean_rv_per_state)
        self._state_map = {
            int(raw): int(relabelled) for relabelled, raw in enumerate(sorted_states)
        }

        return self

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(self, returns: pd.Series) -> np.ndarray:
        """
        Return integer regime array (0=low_vol, 1=high_vol, 2=crisis).

        Never refits — ``fit()`` must be called first.
        Length matches the **valid** (non-warmup) suffix of ``returns``.
        """
        self._check_fitted()
        X, valid_mask = self._build_features_with_mask(returns)
        raw = self._model.predict(X)  # type: ignore[union-attr]
        return np.array([self._state_map[int(s)] for s in raw])

    def predict_named(self, returns: pd.Series) -> pd.Series:
        """
        Return pd.Series of regime label strings aligned to the valid
        (non-warmup) portion of ``returns.index``.
        """
        self._check_fitted()
        X, valid_mask = self._build_features_with_mask(returns)
        raw = self._model.predict(X)  # type: ignore[union-attr]
        int_regimes = np.array([self._state_map[int(s)] for s in raw])
        valid_index = returns.index[valid_mask]
        return pd.Series(
            [_LABEL_MAP[s] for s in int_regimes],
            index=valid_index,
            name="regime",
        )

    def predict_proba(self, returns: pd.Series) -> pd.DataFrame:
        """
        Return posterior state probabilities, columns = ["low_vol", "high_vol", "crisis"].
        Rows aligned to the valid (non-warmup) portion of ``returns.index``.
        Rows sum to 1.0.
        """
        self._check_fitted()
        X, valid_mask = self._build_features_with_mask(returns)
        raw_proba = self._model.predict_proba(X)  # type: ignore[union-attr]
        # Re-order columns according to relabelled state map
        n = self.config.n_regimes
        reordered = np.zeros_like(raw_proba)
        for raw_s, rel_s in self._state_map.items():
            reordered[:, rel_s] = raw_proba[:, raw_s]
        cols = [_LABEL_MAP[i] for i in range(n)]
        valid_index = returns.index[valid_mask]
        return pd.DataFrame(reordered, index=valid_index, columns=cols)

    def regime_stats(self, returns: pd.Series) -> pd.DataFrame:
        """
        Summary statistics per regime.

        Returns DataFrame with columns:
        n_bars, pct_time, mean_return, vol, sharpe
        """
        self._check_fitted()
        labels = self.predict_named(returns)
        records = []
        ann_factor = np.sqrt(252 * 390)  # 1-min bars

        for regime_name in _LABEL_MAP.values():
            mask = labels == regime_name
            ret_slice = returns[mask]
            n = int(mask.sum())
            if n == 0:
                records.append(
                    {
                        "regime": regime_name,
                        "n_bars": 0,
                        "pct_time": 0.0,
                        "mean_return": np.nan,
                        "vol": np.nan,
                        "sharpe": np.nan,
                    }
                )
                continue
            mean_ret = float(ret_slice.mean())
            vol = float(ret_slice.std())
            sharpe = (mean_ret * ann_factor / (vol * ann_factor)) if vol > 0 else 0.0
            records.append(
                {
                    "regime": regime_name,
                    "n_bars": n,
                    "pct_time": n / len(returns),
                    "mean_return": mean_ret,
                    "vol": vol,
                    "sharpe": sharpe,
                }
            )
        return pd.DataFrame(records).set_index("regime")

    # ------------------------------------------------------------------
    # Feature construction (causal only)
    # ------------------------------------------------------------------

    def _build_features(self, returns: pd.Series) -> np.ndarray:
        """Return clean feature matrix (NaN rows dropped). Used in fit()."""
        X_clean, _ = self._build_features_with_mask(returns)
        return X_clean

    def _build_features_with_mask(self, returns: pd.Series) -> tuple[np.ndarray, np.ndarray]:
        """
        Build 4-column feature matrix from log returns.

        Returns
        -------
        X_clean : np.ndarray, shape (n_valid, 4)
            Feature matrix with warmup rows removed.
        valid_mask : np.ndarray of bool, shape (n,)
            True where the row is valid (not NaN warmup).

        Columns (all causal, no lookahead):
        0: log_return       — current bar log return
        1: realized_vol     — rolling std over ``vol_window`` bars
        2: vol_change       — 1-bar diff of realized vol
        3: momentum         — rolling mean over ``return_window`` bars
        """
        w_vol = self.config.vol_window
        w_ret = self.config.return_window

        log_ret = returns.values.astype(float)
        n = len(log_ret)

        rv = np.full(n, np.nan)
        for i in range(w_vol, n + 1):
            rv[i - 1] = float(np.std(log_ret[i - w_vol : i], ddof=1))

        vol_change = np.full(n, np.nan)
        for i in range(1, n):
            if not np.isnan(rv[i]) and not np.isnan(rv[i - 1]):
                vol_change[i] = rv[i] - rv[i - 1]

        momentum = np.full(n, np.nan)
        for i in range(w_ret, n + 1):
            momentum[i - 1] = float(np.mean(log_ret[i - w_ret : i]))

        X = np.column_stack([log_ret, rv, vol_change, momentum])

        # Drop rows with any NaN (warm-up period)
        valid_mask = ~np.isnan(X).any(axis=1)
        X_clean = X[valid_mask]

        if len(X_clean) == 0:
            raise ValueError(
                f"No valid rows after feature construction. Need at least {w_vol} bars; got {n}."
            )

        return X_clean.astype(np.float64), valid_mask

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_fitted(self) -> None:
        if self._model is None:
            raise RuntimeError("RegimeDetector has not been fitted. Call fit() first.")
