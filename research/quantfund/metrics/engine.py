"""
Metrics Engine
==============
Institutional-grade performance and risk metrics.

Metrics computed:
  - Sharpe ratio (annualised)
  - Sortino ratio (downside deviation)
  - Calmar ratio (return / max drawdown)
  - Maximum drawdown and drawdown duration
  - Profit factor (gross wins / gross losses)
  - Hit rate (% winning trades)
  - Average win / average loss ratio
  - Information Coefficient (IC) and ICIR
  - t-statistic and p-value for mean return
  - Value at Risk (95%, 99%)
  - Expected Shortfall (CVaR)

All metrics are computed on log returns to be consistent with
portfolio-level aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats

__all__ = [
    "PerformanceMetrics",
    "compute_metrics",
    "compute_ic",
    "compute_drawdown_series",
]

# ---------------------------------------------------------------------------
# Annualisation factors (number of periods per year)
# ---------------------------------------------------------------------------
_ANN = {
    "1min": 525_600,
    "5min": 105_120,
    "15min": 35_040,
    "30min": 17_520,
    "1h": 8_760,
    "4h": 2_190,
    "1D": 252,
}


@dataclass
class PerformanceMetrics:
    """All performance metrics for one strategy / walk-forward window."""

    # Return statistics
    total_return: float = 0.0
    annualised_return: float = 0.0
    annualised_vol: float = 0.0

    # Risk-adjusted ratios
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0

    # Drawdown
    max_drawdown: float = 0.0  # as fraction (negative)
    avg_drawdown: float = 0.0
    max_drawdown_duration_bars: int = 0

    # Trade statistics
    profit_factor: float = 0.0
    hit_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_loss_ratio: float = 0.0

    # Statistical significance
    t_stat: float = 0.0
    p_value: float = 1.0
    n_bars: int = 0

    # Tail risk
    var_95: float = 0.0  # 1-day VaR at 95%
    var_99: float = 0.0
    cvar_95: float = 0.0  # Expected Shortfall at 95%

    def to_dict(self) -> dict:
        return asdict(self)

    def is_significant(self, alpha: float = 0.05) -> bool:
        return self.p_value < alpha and self.sharpe > 0

    def summary(self) -> str:
        return (
            f"Sharpe={self.sharpe:.2f}  Sortino={self.sortino:.2f}  "
            f"Calmar={self.calmar:.2f}  MaxDD={self.max_drawdown:.1%}  "
            f"PF={self.profit_factor:.2f}  Hit={self.hit_rate:.1%}  "
            f"p={self.p_value:.4f}  n={self.n_bars}"
        )


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_metrics(
    returns: pd.Series | np.ndarray,
    freq: str = "1min",
    risk_free_rate: float = 0.04,  # annualised
) -> PerformanceMetrics:
    """
    Compute all performance metrics from a return series.

    Parameters
    ----------
    returns : Log returns (one per bar). NaN values are dropped.
    freq    : Bar frequency string (used for annualisation).
    risk_free_rate : Annualised risk-free rate (default 4%).

    Returns
    -------
    PerformanceMetrics dataclass.
    """
    r = pd.Series(returns).dropna().values.astype(float)
    n = len(r)
    if n < 2:
        return PerformanceMetrics(n_bars=n)

    ann = _ANN.get(freq, 252)  # periods per year
    rf_per_bar = risk_free_rate / ann  # risk-free rate per bar

    # ------------------------------------------------------------------
    # Return stats
    # ------------------------------------------------------------------
    total_ret = float(r.sum())
    ann_ret = float(r.mean() * ann)
    ann_vol = float(r.std(ddof=1) * np.sqrt(ann))

    # ------------------------------------------------------------------
    # Sharpe
    # ------------------------------------------------------------------
    excess = r - rf_per_bar
    excess_std = excess.std(ddof=1)
    # When returns are all identical (e.g. all zero), excess std ≈ 0 → Sharpe = 0
    if excess_std < 1e-10:
        sharpe = 0.0
    else:
        sharpe = float(excess.mean() / excess_std * np.sqrt(ann))

    # ------------------------------------------------------------------
    # Sortino (downside deviation)
    # ------------------------------------------------------------------
    downside = r[r < rf_per_bar] - rf_per_bar
    dd_vol = float(downside.std(ddof=1) * np.sqrt(ann)) if len(downside) > 1 else 1e-12
    sortino = float((r.mean() - rf_per_bar) * ann / (dd_vol + 1e-12))

    # ------------------------------------------------------------------
    # Drawdown
    # ------------------------------------------------------------------
    dd_series, max_dd, avg_dd, max_dur = _drawdown_stats(r)

    # ------------------------------------------------------------------
    # Calmar
    # ------------------------------------------------------------------
    calmar = float(ann_ret / abs(max_dd + 1e-12))

    # ------------------------------------------------------------------
    # Trade statistics (treat each bar return as a "trade")
    # ------------------------------------------------------------------
    wins = r[r > 0]
    losses = r[r < 0]
    hit_rate = float(len(wins) / n)
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0
    profit_factor = (
        float(wins.sum() / abs(losses.sum()))
        if len(losses) > 0 and losses.sum() != 0
        else float("inf")
    )
    wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    # ------------------------------------------------------------------
    # Statistical significance
    # ------------------------------------------------------------------
    t_stat, p_value = stats.ttest_1samp(r, 0.0)

    # ------------------------------------------------------------------
    # Tail risk (VaR / CVaR on 1-bar returns)
    # ------------------------------------------------------------------
    var_95 = float(np.percentile(r, 5))
    var_99 = float(np.percentile(r, 1))
    cvar_95 = float(r[r <= var_95].mean()) if (r <= var_95).any() else var_95

    return PerformanceMetrics(
        total_return=total_ret,
        annualised_return=ann_ret,
        annualised_vol=ann_vol,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_drawdown=max_dd,
        avg_drawdown=avg_dd,
        max_drawdown_duration_bars=max_dur,
        profit_factor=profit_factor,
        hit_rate=hit_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        win_loss_ratio=wl_ratio,
        t_stat=float(t_stat),
        p_value=float(p_value),
        n_bars=n,
        var_95=var_95,
        var_99=var_99,
        cvar_95=cvar_95,
    )


def compute_drawdown_series(returns: pd.Series) -> pd.Series:
    """
    Compute the underwater (drawdown) equity curve.

    Returns a Series of drawdown values in [−1, 0].
    """
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    return equity / peak - 1


def _drawdown_stats(r: np.ndarray) -> tuple[np.ndarray, float, float, int]:
    """Return (dd_series, max_dd, avg_dd, max_duration_bars)."""
    equity = np.cumprod(1 + r)
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1

    max_dd = float(dd.min())
    avg_dd = float(dd[dd < 0].mean()) if (dd < 0).any() else 0.0

    # Max drawdown duration
    in_dd = dd < 0
    max_dur = 0
    cur_dur = 0
    for v in in_dd:
        if v:
            cur_dur += 1
            max_dur = max(max_dur, cur_dur)
        else:
            cur_dur = 0

    return dd, max_dd, avg_dd, max_dur


# ---------------------------------------------------------------------------
# Information Coefficient
# ---------------------------------------------------------------------------


def compute_ic(
    predictions: pd.Series | np.ndarray,
    outcomes: pd.Series | np.ndarray,
    method: str = "spearman",
) -> tuple[float, float]:
    """
    Compute Information Coefficient (IC) between predictions and outcomes.

    Parameters
    ----------
    predictions : Forward-looking signal values.
    outcomes    : Actual returns over the prediction horizon.
    method      : ``"spearman"`` (rank IC) or ``"pearson"`` (linear IC).

    Returns
    -------
    (ic, p_value)
    """
    pred = np.asarray(predictions, dtype=float)
    out = np.asarray(outcomes, dtype=float)

    mask = np.isfinite(pred) & np.isfinite(out)
    pred, out = pred[mask], out[mask]

    if len(pred) < 5:
        return 0.0, 1.0

    if method == "spearman":
        result = stats.spearmanr(pred, out)
    else:
        result = stats.pearsonr(pred, out)

    return float(result.statistic), float(result.pvalue)
