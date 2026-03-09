"""
Volatility-Regime Mean Reversion Strategy
==========================================
Uses a 3-state HMM to detect the current market regime, then applies a
regime-specific Ridge regression to generate alpha signals.

Regimes:
  low_vol  → momentum-oriented features → trend-following tilt
  high_vol → mean-reversion features    → fade-the-move tilt
  crisis   → vol/calendar features      → defensive / flat signals

Design:
- ``fit()`` is called ONCE offline on labelled training data
- ``predict()`` is called online per bar with new features
- Separate ``RobustScaler`` per regime prevents cross-contamination
- Falls back to all-data fit if a regime has < ``min_train_samples`` bars
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from quantfund.regime import RegimeDetector, RegimeConfig

__all__ = ["VolRegimeConfig", "VolRegimeMeanReversion"]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class VolRegimeConfig:
    """Hyperparameters for VolRegimeMeanReversion."""

    # HMM detector
    n_regimes: int = 3
    hmm_vol_window: int = 20

    # Ridge regularisation per regime
    alpha_low_vol: float = 1.0
    alpha_high_vol: float = 0.5
    alpha_crisis: float = 2.0

    # Feature prefixes selected per regime (match FeaturePipeline column names)
    features_low_vol: list[str] = field(default_factory=lambda: ["ret_", "mom_", "rsi_", "macd_"])
    features_high_vol: list[str] = field(
        default_factory=lambda: ["zscore_", "bb_", "rv_", "ret_1", "ret_5"]
    )
    features_crisis: list[str] = field(
        default_factory=lambda: ["rv_", "parkinson_", "hour_sin", "hour_cos", "session_"]
    )

    # Signal normalisation
    signal_clip: float = 1.0

    # Minimum bars per regime to train a dedicated model
    min_train_samples: int = 200


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class VolRegimeMeanReversion:
    """
    Regime-aware mean-reversion strategy.

    Implements the ``StrategyProtocol``:
      - ``fit(train_features, train_ohlcv)``
      - ``predict(test_features) -> pd.Series``
    """

    def __init__(self, config: Optional[VolRegimeConfig] = None) -> None:
        self.config = config or VolRegimeConfig()
        self._detector: Optional[RegimeDetector] = None
        self._models: dict[str, object] = {}  # regime → fitted Ridge
        self._scalers: dict[str, object] = {}  # regime → fitted RobustScaler
        self._fallback_model = None  # trained on all data
        self._fallback_scaler = None
        self._fitted = False

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(
        self, train_features: pd.DataFrame, train_ohlcv: pd.DataFrame
    ) -> "VolRegimeMeanReversion":
        """
        Fit HMM detector and per-regime Ridge regression models.

        Parameters
        ----------
        train_features:
            Feature matrix from FeaturePipeline.transform(), aligned to train_ohlcv.
        train_ohlcv:
            Raw OHLCV DataFrame with a 'close' column.
        """
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import RobustScaler

        # Align indices
        idx = train_features.index.intersection(train_ohlcv.index)
        feats = train_features.loc[idx]
        ohlcv = train_ohlcv.loc[idx]

        # Forward returns (target, shifted back 1 so it's the return from bar t to t+1)
        log_close = pd.Series(np.log(ohlcv["close"].values), index=ohlcv.index)
        fwd_ret = log_close.diff(1).shift(-1)  # future 1-bar log return

        # Drop NaN rows (warm-up + last bar)
        valid = feats.notna().all(axis=1) & fwd_ret.notna()
        feats = feats.loc[valid]
        fwd_ret = fwd_ret.loc[valid]

        if len(feats) == 0:
            raise ValueError("No valid training rows after NaN removal.")

        # Fit HMM regime detector on log returns
        log_ret = log_close.diff().loc[valid]
        regime_cfg = RegimeConfig(
            n_regimes=self.config.n_regimes,
            vol_window=self.config.hmm_vol_window,
        )
        self._detector = RegimeDetector(regime_cfg)
        self._detector.fit(log_ret)
        regime_labels = self._detector.predict_named(log_ret)

        # Align feats/fwd_ret to the valid (non-warmup) regime index
        shared_idx = feats.index.intersection(regime_labels.index)
        feats = feats.loc[shared_idx]
        fwd_ret = fwd_ret.loc[shared_idx]
        regime_labels = regime_labels.loc[shared_idx]

        # Fit fallback model on all data
        all_cols = list(feats.columns)
        fallback_scaler = RobustScaler()
        X_all = fallback_scaler.fit_transform(feats[all_cols].values)
        y_all = fwd_ret.values
        fallback_model = Ridge(alpha=1.0)
        fallback_model.fit(X_all, y_all)
        self._fallback_scaler = fallback_scaler
        self._fallback_model = fallback_model

        # Fit per-regime models
        regime_alpha_map = {
            "low_vol": self.config.alpha_low_vol,
            "high_vol": self.config.alpha_high_vol,
            "crisis": self.config.alpha_crisis,
        }
        regime_prefix_map = {
            "low_vol": self.config.features_low_vol,
            "high_vol": self.config.features_high_vol,
            "crisis": self.config.features_crisis,
        }

        for regime_name in ["low_vol", "high_vol", "crisis"]:
            mask = regime_labels == regime_name
            n_regime = int(mask.sum())

            # Select regime-specific features
            prefixes = regime_prefix_map[regime_name]
            regime_cols = [c for c in all_cols if any(c.startswith(p) for p in prefixes)]
            if not regime_cols:
                regime_cols = all_cols  # fallback to all if no prefix matches

            if n_regime < self.config.min_train_samples:
                # Insufficient data: use fallback
                self._models[regime_name] = None
                self._scalers[regime_name] = None
                continue

            feats_regime = feats.loc[mask, regime_cols]
            y_regime = fwd_ret.loc[mask].values

            scaler = RobustScaler()
            X_regime = scaler.fit_transform(feats_regime.values)
            model = Ridge(alpha=regime_alpha_map[regime_name])
            model.fit(X_regime, y_regime)

            self._models[regime_name] = model
            self._scalers[regime_name] = (scaler, regime_cols)

        self._fitted = True
        return self

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(self, test_features: pd.DataFrame) -> pd.Series:
        """
        Generate signals in [-1, 1] for each bar in test_features.

        Returns
        -------
        pd.Series
            Float signal series, index aligned to test_features.
        """
        if not self._fitted:
            # Return zeros if not fitted (safe default)
            return pd.Series(0.0, index=test_features.index)

        # Need 'ret_1' column for regime detection
        if "ret_1" not in test_features.columns:
            raise ValueError("test_features must contain 'ret_1' column for regime detection.")

        log_ret = test_features["ret_1"]
        regime_labels = self._detector.predict_named(log_ret)  # type: ignore[union-attr]

        # Align test_features to the valid (non-warmup) regime index
        original_index = test_features.index
        shared_idx = original_index.intersection(regime_labels.index)
        aligned_features = test_features.loc[shared_idx]
        regime_labels = regime_labels.loc[shared_idx]

        signals = pd.Series(np.nan, index=shared_idx, dtype=float)

        all_cols = list(test_features.columns)

        for regime_name in ["low_vol", "high_vol", "crisis"]:
            mask = regime_labels == regime_name
            if not mask.any():
                continue

            model = self._models.get(regime_name)
            scaler_info = self._scalers.get(regime_name)

            if model is None or scaler_info is None:
                # Use fallback
                X_sub = aligned_features.loc[mask, all_cols].fillna(0.0).values
                X_scaled = self._fallback_scaler.transform(X_sub)  # type: ignore[union-attr]
                raw = self._fallback_model.predict(X_scaled)  # type: ignore[union-attr]
            else:
                scaler, regime_cols = scaler_info
                # Align to regime columns (fill missing with 0)
                sub = aligned_features.loc[mask].reindex(columns=regime_cols, fill_value=0.0)
                X_scaled = scaler.transform(sub.values)
                raw = model.predict(X_scaled)

            # Normalise: divide by 3 * rolling std of the raw predictions
            std = float(np.std(raw)) if len(raw) > 1 else 1.0
            if std < 1e-10:
                std = 1.0
            normalised = raw / (3.0 * std)
            clipped = np.clip(normalised, -self.config.signal_clip, self.config.signal_clip)
            signals.loc[mask] = clipped

        # Fill any remaining NaN with 0
        signals = signals.fillna(0.0)
        # Reindex to original input index (warmup rows → 0.0)
        return signals.reindex(original_index, fill_value=0.0)
