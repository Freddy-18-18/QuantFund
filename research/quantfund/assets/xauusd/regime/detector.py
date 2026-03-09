"""
Gold-specific market regime detector.

Gold has structurally different regimes than equities. The key distinction
is the *driver* of price action, not just volatility:

    Regime 0 — RATES_DRIVEN (most common, ~50% of time)
        - Gold moves inversely with real yields
        - DXY has moderate negative correlation
        - Macro fundamentals dominate
        - Typical: Fed hiking/cutting cycles, rate vol elevated

    Regime 1 — RISK_OFF / SAFE_HAVEN (~20%)
        - Gold rallies with VIX spikes, equity sell-offs
        - Real yield correlation breaks down (both yields and gold rise)
        - Typical: geopolitical shocks, credit events, pandemic

    Regime 2 — DOLLAR_DRIVEN (~20%)
        - Gold primary mover is DXY (high negative corr DXY/XAU)
        - Real yield correlation muted
        - Typical: EM crises, dollar strength episodes

    Regime 3 — MOMENTUM / TREND (~10%)
        - Gold trending strongly in one direction
        - Fundamental correlations stretched or decoupled
        - Typical: multi-month bull/bear runs

Detection method:
    - Rolling 63-day correlation of gold returns vs real yield changes
      and vs DXY changes to identify which driver is dominant
    - VIX level and trend to flag risk-off
    - Gold momentum z-score for trend detection
    - No ML required — rules-based with smooth transitions

Usage:
    detector = GoldRegimeDetector()
    regimes = detector.detect(factors_df)
    # returns pd.Series with values {0,1,2,3} aligned to factors_df.index
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Regime constants
REGIME_RATES_DRIVEN = 0
REGIME_RISK_OFF = 1
REGIME_DOLLAR_DRIVEN = 2
REGIME_MOMENTUM = 3

REGIME_NAMES = {
    REGIME_RATES_DRIVEN: "rates_driven",
    REGIME_RISK_OFF: "risk_off",
    REGIME_DOLLAR_DRIVEN: "dollar_driven",
    REGIME_MOMENTUM: "momentum",
}

# Thresholds (tuned to historical gold behaviour)
_VIX_RISK_OFF = 28.0  # VIX above this → risk-off candidate
_VIX_EXTREME = 40.0  # VIX above this → strong risk-off
_CORR_RATES_STRONG = -0.35  # gold/real_yield rolling corr < this → rates regime
_CORR_DXY_STRONG = -0.45  # gold/dxy rolling corr < this → dollar regime
_MOM_ZSCORE_TREND = 1.5  # |mom_zscore| > this → momentum regime
_LOOKBACK = 63  # rolling window in trading days (~3 months)
_MOM_LOOKBACK = 63


class GoldRegimeDetector:
    """
    Rules-based gold market regime detector.

    Requires the factor DataFrame produced by GoldFactors.build() with at
    minimum: gold_ret_1d, real_yield_1d_chg, dxy_1d_chg, vix, gold_mom_63d

    For columns that are missing, the corresponding regime rule is skipped.
    """

    def detect(self, factors: pd.DataFrame) -> pd.Series:
        """
        Classify each day into one of 4 gold market regimes.

        Args:
            factors: Daily factor DataFrame from GoldFactors.build().
                     Must have DatetimeIndex.

        Returns:
            pd.Series of int (0-3) aligned to factors.index.
            Values: 0=rates_driven, 1=risk_off, 2=dollar_driven, 3=momentum.
            NaN for days with insufficient lookback history.
        """
        idx = factors.index
        regimes = pd.Series(np.nan, index=idx, name="regime")

        # --- Rolling correlations ---
        gold_ret = factors.get("gold_ret_1d")
        real_yield_chg = factors.get("real_yield_1d_chg")
        dxy_chg = factors.get("dxy_1d_chg")
        vix = factors.get("vix")
        mom_63d = factors.get("gold_mom_63d")

        corr_rates: pd.Series | None = None
        if gold_ret is not None and real_yield_chg is not None:
            corr_rates = gold_ret.rolling(_LOOKBACK, min_periods=_LOOKBACK // 2).corr(
                real_yield_chg
            )

        corr_dxy: pd.Series | None = None
        if gold_ret is not None and dxy_chg is not None:
            corr_dxy = gold_ret.rolling(_LOOKBACK, min_periods=_LOOKBACK // 2).corr(dxy_chg)

        # --- Momentum z-score ---
        mom_zscore: pd.Series | None = None
        if mom_63d is not None:
            mu = mom_63d.rolling(_MOM_LOOKBACK, min_periods=_MOM_LOOKBACK // 2).mean()
            sigma = mom_63d.rolling(_MOM_LOOKBACK, min_periods=_MOM_LOOKBACK // 2).std()
            mom_zscore = (mom_63d - mu) / sigma.replace(0, float("nan"))

        # --- Regime assignment (priority order) ---
        # Higher priority rules override lower ones.

        # Default: rates-driven
        regimes[:] = REGIME_RATES_DRIVEN

        # Dollar-driven: DXY correlation stronger than rates correlation
        if corr_dxy is not None and corr_rates is not None:
            dollar_flag = (corr_dxy < _CORR_DXY_STRONG) & (corr_dxy < corr_rates)
            regimes[dollar_flag] = REGIME_DOLLAR_DRIVEN

        # Rates-driven: strong negative correlation with real yields
        if corr_rates is not None:
            rates_flag = corr_rates < _CORR_RATES_STRONG
            regimes[rates_flag] = REGIME_RATES_DRIVEN

        # Momentum: extreme price trend regardless of macro
        if mom_zscore is not None:
            mom_flag = mom_zscore.abs() > _MOM_ZSCORE_TREND
            regimes[mom_flag] = REGIME_MOMENTUM

        # Risk-off: elevated VIX (highest priority, overrides everything)
        if vix is not None:
            risk_off_flag = vix > _VIX_RISK_OFF
            regimes[risk_off_flag] = REGIME_RISK_OFF

        # Convert to int where not NaN
        regimes = regimes.astype("Int64")  # nullable int

        return regimes

    def describe(self, regimes: pd.Series) -> pd.DataFrame:
        """
        Return a summary of regime distribution and transitions.

        Args:
            regimes: Output of .detect().

        Returns:
            DataFrame with columns: regime, name, days, pct, avg_run_length
        """
        clean = regimes.dropna()
        total = len(clean)
        rows = []
        for code, name in REGIME_NAMES.items():
            mask = clean == code
            days = int(mask.sum())
            pct = days / total * 100 if total > 0 else 0.0
            # Average run length
            runs = (mask != mask.shift()).cumsum()
            run_lengths = mask.groupby(runs).sum()
            run_lengths = run_lengths[run_lengths > 0]
            avg_run = float(run_lengths.mean()) if len(run_lengths) > 0 else 0.0
            rows.append(
                {
                    "regime": code,
                    "name": name,
                    "days": days,
                    "pct": round(pct, 1),
                    "avg_run_length": round(avg_run, 1),
                }
            )
        return pd.DataFrame(rows).set_index("regime")

    def add_to_factors(self, factors: pd.DataFrame) -> pd.DataFrame:
        """
        Convenience: add regime column(s) directly to the factor DataFrame.

        Adds:
            - regime (int): primary regime code
            - regime_name (str): human-readable name
            - regime_is_risk_off (bool)
            - regime_is_rates_driven (bool)
        """
        df = factors.copy()
        df["regime"] = self.detect(factors)
        df["regime_name"] = df["regime"].map(REGIME_NAMES)
        df["regime_is_risk_off"] = df["regime"] == REGIME_RISK_OFF
        df["regime_is_rates_driven"] = df["regime"] == REGIME_RATES_DRIVEN
        return df
