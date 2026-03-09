"""
Factor analysis for XAUUSD — Information Coefficient and regime-conditional correlations.

Run this script after building the factor matrix to understand which factors
have predictive power and in which regimes.

Usage:
    cd research/
    python -m quantfund.assets.xauusd.analysis.factor_analysis

Output:
    - Console: IC summary table, regime-conditional correlations
    - research/quantfund/assets/xauusd/analysis/results/factor_ic.csv
    - research/quantfund/assets/xauusd/analysis/results/regime_correlations.csv
    - research/quantfund/assets/xauusd/analysis/results/regime_distribution.csv
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# Allow running as a script directly
_ROOT = Path(__file__).parent.parent.parent.parent.parent  # research/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from quantfund.assets.xauusd.factors.builder import GoldFactors
from quantfund.assets.xauusd.regime.detector import GoldRegimeDetector, REGIME_NAMES

_RESULTS_DIR = Path(__file__).parent / "results"

# Forward return horizons to test (in trading days)
_HORIZONS = {
    "1d": 1,
    "5d": 5,
    "21d": 21,
}

# Factors to analyse — skip raw position counts and volumes (not signals)
_SIGNAL_FACTORS = [
    "real_yield",
    "nominal_yield",
    "dxy",
    "vix",
    "fed_funds",
    "breakeven_inflation",
    "real_yield_1d_chg",
    "dxy_1d_chg",
    "net_speculative_pct",
    "net_spec_zscore_52w",
    "mm_long_pct",
    "mm_short_pct",
    "commercial_net",
    "total_gold_etf_dv",
    "gold_etf_dv_chg",
    "gold_etf_dv_zscore_20d",
    "gold_etf_dv_chg_zscore_20d",
    "gdx_gld_ratio",
    "gdx_gld_ratio_chg",
    "gold_ret_1d",
    "gold_ret_5d",
    "gold_ret_21d",
    "gold_rvol_10d",
    "gold_rvol_21d",
    "gold_mom_63d",
    "gold_mom_252d",
    "gold_dist_ema20",
    "gold_ema20_50_cross",
    "gold_hl_range",
]


def _ic(factor: pd.Series, fwd_ret: pd.Series) -> float:
    """Rank IC (Spearman) between a factor and forward returns."""
    aligned = pd.concat([factor, fwd_ret], axis=1).dropna()
    if len(aligned) < 20:
        return float("nan")
    return float(aligned.iloc[:, 0].rank().corr(aligned.iloc[:, 1].rank()))


def _ic_series(factor: pd.Series, fwd_ret: pd.Series, window: int = 252) -> pd.Series:
    """Rolling Spearman IC over a window."""
    aligned = pd.concat([factor, fwd_ret], axis=1).dropna()
    ic_vals = []
    dates = []
    for i in range(window, len(aligned) + 1):
        chunk = aligned.iloc[i - window : i]
        ic = float(chunk.iloc[:, 0].rank().corr(chunk.iloc[:, 1].rank()))
        ic_vals.append(ic)
        dates.append(aligned.index[i - 1])
    return pd.Series(ic_vals, index=dates)


def load_price_data(start: datetime) -> pd.DataFrame:
    """Download GC=F (COMEX gold futures) as daily OHLCV stand-in."""
    print("Downloading GC=F price data...")
    gc = yf.download("GC=F", start=start.strftime("%Y-%m-%d"), auto_adjust=True, progress=False)
    if isinstance(gc.columns, pd.MultiIndex):
        gc.columns = gc.columns.droplevel(1)
    gc.columns = [c.lower() for c in gc.columns]
    gc.index = pd.to_datetime(gc.index, utc=True)
    return gc


def build_factor_matrix(price_df: pd.DataFrame, start: datetime) -> pd.DataFrame:
    """Build the full gold factor matrix."""
    print("Building factor matrix (downloading macro, COT, ETF data)...")
    gf = GoldFactors()
    df = gf.build(start=start, price_ohlcv=price_df)
    print(f"Factor matrix: {df.shape[0]} rows × {df.shape[1]} columns")
    return df


def add_forward_returns(df: pd.DataFrame, price_col: str = "gold_ret_1d") -> pd.DataFrame:
    """
    Add forward return columns for each horizon.

    We reconstruct the cumulative forward return from the return series.
    """
    # Reconstruct price level from returns for forward-return computation
    # gold_ret_1d is already shifted (prior close → current close)
    # So fwd_ret_Nd at time t = return over next N days
    out = df.copy()
    for name, h in _HORIZONS.items():
        # Sum of next h daily log returns
        log_r = df["gold_log_ret_1d"] if "gold_log_ret_1d" in df.columns else df["gold_ret_1d"]
        out[f"fwd_{name}"] = log_r.rolling(h).sum().shift(-h)
    return out


def compute_ic_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute IC (Spearman rank correlation) for each factor × forward horizon.
    Also compute IC_IR = mean(rolling_IC) / std(rolling_IC).
    """
    available_factors = [f for f in _SIGNAL_FACTORS if f in df.columns]
    results = []

    for factor in available_factors:
        row: dict = {"factor": factor}
        for horizon_name in _HORIZONS:
            fwd_col = f"fwd_{horizon_name}"
            if fwd_col not in df.columns:
                continue
            ic = _ic(df[factor], df[fwd_col])
            row[f"ic_{horizon_name}"] = round(ic, 4)

        # IC_IR over 252-day rolling windows for 1d horizon
        if "fwd_1d" in df.columns:
            rolling = _ic_series(df[factor], df["fwd_1d"])
            if len(rolling) > 10:
                row["ic_ir_1d"] = round(
                    rolling.mean() / rolling.std() if rolling.std() > 0 else float("nan"), 3
                )
                row["ic_mean_1d"] = round(rolling.mean(), 4)
                row["ic_hit_rate_1d"] = round((rolling > 0).mean(), 3)
            else:
                row["ic_ir_1d"] = float("nan")
                row["ic_mean_1d"] = float("nan")
                row["ic_hit_rate_1d"] = float("nan")

        results.append(row)

    return pd.DataFrame(results).set_index("factor").sort_values("ic_1d", ascending=False)


def compute_regime_correlations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute pearson correlation of each factor vs fwd_1d, stratified by regime.
    Shows which factors work best in which regime.
    """
    if "regime" not in df.columns or "fwd_1d" not in df.columns:
        return pd.DataFrame()

    available_factors = [f for f in _SIGNAL_FACTORS if f in df.columns]
    results = []

    for regime_id, regime_name in REGIME_NAMES.items():
        sub = df[df["regime"] == regime_id]
        if len(sub) < 30:
            continue
        row = {"regime": regime_name, "n_obs": len(sub)}
        for factor in available_factors:
            aligned = sub[[factor, "fwd_1d"]].dropna()
            if len(aligned) < 10:
                row[factor] = float("nan")
                continue
            corr = float(aligned[factor].corr(aligned["fwd_1d"]))
            row[factor] = round(corr, 4)
        results.append(row)

    return pd.DataFrame(results).set_index("regime")


def main() -> None:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    START = datetime(2015, 1, 1)

    # 1. Load price data
    price = load_price_data(start=START)

    # 2. Build factor matrix
    factors = build_factor_matrix(price_df=price, start=START)

    # 3. Add regime labels
    print("Detecting regimes...")
    detector = GoldRegimeDetector()
    factors = detector.add_to_factors(factors)

    # 4. Add forward returns
    factors = add_forward_returns(factors)

    # 5. Clean — require at least the price-based factors to be present
    clean = factors.dropna(subset=["gold_ret_1d", "real_yield", "dxy", "vix"])
    print(f"Clean rows for analysis: {len(clean)} (from {len(factors)} total)")

    # 6. Regime distribution
    regime_dist = (
        factors["regime"]
        .dropna()
        .map(REGIME_NAMES)
        .value_counts(normalize=True)
        .rename("frequency")
        .to_frame()
    )
    regime_dist["count"] = factors["regime"].dropna().map(REGIME_NAMES).value_counts()
    print("\n=== REGIME DISTRIBUTION ===")
    print(regime_dist.to_string())
    regime_dist.to_csv(_RESULTS_DIR / "regime_distribution.csv")

    # 7. IC table
    print("\nComputing IC table (this takes a minute)...")
    ic_table = compute_ic_table(clean)
    print("\n=== INFORMATION COEFFICIENT TABLE ===")
    pd.set_option("display.width", 120)
    pd.set_option("display.max_columns", 20)
    print(ic_table.to_string())
    ic_table.to_csv(_RESULTS_DIR / "factor_ic.csv")

    # 8. Regime-conditional correlations
    print("\nComputing regime-conditional correlations...")
    regime_corr = compute_regime_correlations(clean)
    if not regime_corr.empty:
        print("\n=== REGIME-CONDITIONAL CORRELATIONS (factor vs fwd_1d) ===")
        # Show only top signal factors for readability
        top_factors = [
            f
            for f in [
                "real_yield_1d_chg",
                "dxy_1d_chg",
                "vix",
                "net_spec_zscore_52w",
                "gold_etf_dv_chg_zscore_20d",
                "gold_ret_1d",
                "gold_mom_63d",
                "gold_dist_ema20",
            ]
            if f in regime_corr.columns
        ]
        print(regime_corr[["n_obs"] + top_factors].to_string())
        regime_corr.to_csv(_RESULTS_DIR / "regime_correlations.csv")

    # 9. Summary: best factors per regime
    print("\n=== STRONGEST FACTORS OVERALL (by abs IC 1d) ===")
    if "ic_1d" in ic_table.columns:
        top = ic_table["ic_1d"].dropna().abs().sort_values(ascending=False).head(10)
        for factor, abs_ic in top.items():
            signed_ic = ic_table.loc[factor, "ic_1d"]
            direction = "+" if signed_ic > 0 else "-"
            print(f"  {factor:40s}  IC={signed_ic:+.4f}  ({direction}direction)")

    print(f"\nResults saved to {_RESULTS_DIR}")


if __name__ == "__main__":
    main()
