"""
Portfolio Allocation Engine
============================
Volatility targeting, correlation-aware position sizing, and capital scaling.

Approach: Equal Risk Contribution (ERC) modified with:
  - Volatility targeting (constant portfolio vol = target)
  - Correlation-aware weight dampening
  - Drawdown-based capital scaling (reduce when underwater)
  - Maximum position limits per instrument and strategy

This is the layer between raw strategy signals and actual position sizes
sent to the Rust execution engine.

References:
  - Roncalli (2013), "Introduction to Risk Parity and Budgeting"
  - Bruder & Roncalli (2012), ERC portfolio construction
  - Hurst, Ooi, Pedersen (2012), volatility scaling in trend following
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

__all__ = [
    "AllocationConfig",
    "PortfolioAllocator",
    "VolatilityTargeter",
    "RiskBudget",
    "AllocationResult",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class AllocationConfig:
    """Portfolio-level risk parameters."""

    # Volatility targeting
    target_annual_vol: float = 0.15  # 15% annualised portfolio vol
    vol_lookback_bars: int = 20 * 390  # 1 month of 1-min bars
    vol_floor: float = 0.005  # Minimum vol estimate (prevent over-leverage)
    vol_cap: float = 2.0  # Maximum vol estimate (prevent near-zero sizing)

    # Position limits
    max_position_pct: float = 0.25  # Max 25% of capital in any single instrument
    max_gross_exposure: float = 2.0  # Max 200% gross leverage (long + short)
    max_net_exposure: float = 1.0  # Max 100% net exposure (long - short)

    # Correlation dampening
    use_correlation: bool = True
    corr_lookback_bars: int = 60 * 390  # 3 months
    corr_dampening: float = 0.5  # Scale weights by (1 - rho * dampening)

    # Drawdown scaling
    use_dd_scaling: bool = True
    dd_halflife_pct: float = 0.10  # Scale to 50% at 10% drawdown
    dd_floor: float = 0.25  # Minimum capital fraction during drawdown

    # Capital
    initial_capital: float = 100_000.0
    min_trade_notional: float = 1_000.0  # Skip positions below this notional


# ---------------------------------------------------------------------------
# Volatility targeter
# ---------------------------------------------------------------------------


class VolatilityTargeter:
    """
    Compute per-instrument scalar multiplier to achieve target volatility.

    scalar = target_vol / instrument_vol

    If instrument is more volatile than target, scale down.
    If less volatile, scale up (up to max_leverage limit).
    """

    def __init__(self, config: AllocationConfig) -> None:
        self.cfg = config

    def compute_scalars(self, returns: pd.DataFrame, ann_factor: int = 525_600) -> pd.Series:
        """
        Parameters
        ----------
        returns     : DataFrame of log returns, columns = instrument names.
        ann_factor  : Annualisation factor (periods per year).

        Returns
        -------
        Series of vol-targeting scalars, indexed by instrument name.
        """
        lookback = min(self.cfg.vol_lookback_bars, len(returns))
        recent = returns.tail(lookback)

        # Annualised volatility per instrument
        inst_vols = recent.std(ddof=1) * np.sqrt(ann_factor)

        # Clamp vol estimates
        inst_vols = inst_vols.clip(
            lower=self.cfg.vol_floor,
            upper=self.cfg.vol_cap,
        )

        scalars = self.cfg.target_annual_vol / inst_vols

        # Enforce max position limit (individual instrument)
        scalars = scalars.clip(
            upper=self.cfg.max_position_pct / scalars.abs().max()
            if scalars.abs().max() > 0
            else scalars
        )

        return scalars


# ---------------------------------------------------------------------------
# Risk budget (Equal Risk Contribution)
# ---------------------------------------------------------------------------


class RiskBudget:
    """
    Compute Equal Risk Contribution (ERC) weights.

    In ERC, each instrument contributes the same amount to total portfolio
    variance. This is more robust than naive equal-weighting because high-vol
    instruments don't dominate.
    """

    def __init__(self, config: AllocationConfig) -> None:
        self.cfg = config

    def compute_weights(
        self,
        returns: pd.DataFrame,
        risk_budgets: dict[str, float] | None = None,
    ) -> pd.Series:
        """
        Parameters
        ----------
        returns      : Return DataFrame, columns = instrument names.
        risk_budgets : Optional {instrument: budget_fraction}.
                       If None, equal budgets are used (pure ERC).

        Returns
        -------
        Series of portfolio weights summing to 1.
        """
        instruments = returns.columns.tolist()
        n = len(instruments)

        if n == 0:
            return pd.Series(dtype=float)

        if n == 1:
            return pd.Series({instruments[0]: 1.0})

        lookback = min(self.cfg.corr_lookback_bars, len(returns))
        cov = returns.tail(lookback).cov() * 525_600  # annualised

        if risk_budgets is None:
            budgets = np.ones(n) / n
        else:
            budgets = np.array([risk_budgets.get(inst, 1.0 / n) for inst in instruments])
            budgets /= budgets.sum()

        weights = self._erc_optimise(cov.values, budgets)
        return pd.Series(weights, index=instruments)

    @staticmethod
    def _erc_optimise(
        cov: np.ndarray,
        budgets: np.ndarray,
        max_iter: int = 500,
        tol: float = 1e-8,
    ) -> np.ndarray:
        """
        Solve ERC via iterative algorithm (Roncalli 2013).

        Convergence criterion: ||RC - b||_inf < tol
        where RC = marginal risk contribution.
        """
        n = cov.shape[0]
        w = np.ones(n) / n

        for _ in range(max_iter):
            sigma_w = cov @ w
            port_var = float(w @ sigma_w)

            if port_var <= 0:
                break

            # Risk contribution of each instrument
            rc = w * sigma_w / np.sqrt(port_var)
            rc /= rc.sum()

            # Gradient step: move weights toward target budget
            grad = rc - budgets
            if np.max(np.abs(grad)) < tol:
                break

            # Update weights proportional to target / current RC
            w = w * budgets / (rc + 1e-10)
            w = np.clip(w, 1e-6, None)
            w /= w.sum()

        return w


# ---------------------------------------------------------------------------
# Drawdown scaling
# ---------------------------------------------------------------------------


class DrawdownScaler:
    """
    Scale overall capital allocation down when the portfolio is underwater.

    This implements a simple but effective risk management rule:
    lose less when already losing.

    Formula: scale = max(dd_floor, 1 - |dd| / dd_halflife)
    """

    def __init__(self, config: AllocationConfig) -> None:
        self.cfg = config

    def compute_scale(self, portfolio_returns: pd.Series) -> float:
        """
        Parameters
        ----------
        portfolio_returns : Historical portfolio returns (log returns).

        Returns
        -------
        Scale factor in [dd_floor, 1.0].
        """
        if not self.cfg.use_dd_scaling or len(portfolio_returns) == 0:
            return 1.0

        equity = (1 + portfolio_returns).cumprod()
        peak = equity.cummax()
        current_dd = float(equity.iloc[-1] / peak.iloc[-1] - 1)

        if current_dd >= 0:
            return 1.0

        scale = 1.0 - abs(current_dd) / self.cfg.dd_halflife_pct
        return float(max(self.cfg.dd_floor, scale))


# ---------------------------------------------------------------------------
# Allocation result
# ---------------------------------------------------------------------------


@dataclass
class AllocationResult:
    """Final allocation decision: position sizes in notional and lots."""

    timestamp: pd.Timestamp
    capital: float
    capital_at_risk: float  # capital * scale * target_vol

    # Per-instrument
    instruments: list[str] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)
    vol_scalars: dict[str, float] = field(default_factory=dict)
    erc_weights: dict[str, float] = field(default_factory=dict)
    final_weights: dict[str, float] = field(default_factory=dict)
    notional_sizes: dict[str, float] = field(default_factory=dict)

    # Portfolio totals
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    dd_scale: float = 1.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "capital": self.capital,
            "dd_scale": self.dd_scale,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "positions": {
                inst: {
                    "signal": self.signals.get(inst, 0.0),
                    "erc_weight": self.erc_weights.get(inst, 0.0),
                    "final_weight": self.final_weights.get(inst, 0.0),
                    "notional": self.notional_sizes.get(inst, 0.0),
                }
                for inst in self.instruments
            },
        }


# ---------------------------------------------------------------------------
# Main allocator
# ---------------------------------------------------------------------------


class PortfolioAllocator:
    """
    Combines volatility targeting, ERC risk budgeting, and drawdown scaling
    into final position sizes.

    Usage::

        config    = AllocationConfig(target_annual_vol=0.15, initial_capital=100_000)
        allocator = PortfolioAllocator(config)

        result = allocator.allocate(
            signals={"EURUSD": 0.8, "GBPUSD": -0.3, "XAUUSD": 0.5},
            returns={"EURUSD": eurusd_returns, "GBPUSD": gbpusd_returns, ...},
            portfolio_returns=combined_returns,
            capital=current_equity,
        )
    """

    def __init__(self, config: AllocationConfig | None = None) -> None:
        self.cfg = config or AllocationConfig()
        self._vt = VolatilityTargeter(self.cfg)
        self._rb = RiskBudget(self.cfg)
        self._dd = DrawdownScaler(self.cfg)

    def allocate(
        self,
        signals: dict[str, float],
        returns: dict[str, pd.Series],
        portfolio_returns: pd.Series | None = None,
        capital: float | None = None,
        timestamp: pd.Timestamp | None = None,
        ann_factor: int = 525_600,
    ) -> AllocationResult:
        """
        Compute final allocation.

        Parameters
        ----------
        signals           : {instrument: signal_value} where signal ∈ [-1, 1].
        returns           : {instrument: log_return_series}.
        portfolio_returns : Historical portfolio-level log returns (for DD scaling).
        capital           : Current equity (defaults to initial_capital).
        timestamp         : Current timestamp (defaults to now).
        ann_factor        : Annualisation periods per year.
        """
        capital = capital or self.cfg.initial_capital
        timestamp = timestamp or pd.Timestamp.now(tz="UTC")

        instruments = [k for k in signals if k in returns]
        if not instruments:
            return AllocationResult(timestamp=timestamp, capital=capital, capital_at_risk=0.0)

        ret_df = pd.DataFrame({k: returns[k] for k in instruments})

        # 1. Volatility scalars (per instrument)
        vol_scalars = self._vt.compute_scalars(ret_df, ann_factor)

        # 2. ERC weights (correlation-aware)
        erc_weights = self._rb.compute_weights(ret_df)

        # 3. Drawdown scale (portfolio level)
        dd_scale = (
            self._dd.compute_scale(portfolio_returns) if portfolio_returns is not None else 1.0
        )

        # 4. Combine: signal * vol_scalar * erc_weight
        raw_weights: dict[str, float] = {}
        for inst in instruments:
            sig = signals[inst]
            vs = float(vol_scalars.get(inst, 1.0))
            ew = float(erc_weights.get(inst, 1.0 / len(instruments)))
            raw_weights[inst] = sig * vs * ew

        # 5. Normalise to gross exposure target
        gross = sum(abs(v) for v in raw_weights.values())
        if gross > self.cfg.max_gross_exposure:
            scale_factor = self.cfg.max_gross_exposure / gross
            raw_weights = {k: v * scale_factor for k, v in raw_weights.items()}

        # 6. Net exposure check
        net = sum(raw_weights.values())
        if abs(net) > self.cfg.max_net_exposure:
            net_excess = abs(net) - self.cfg.max_net_exposure
            # Reduce largest positions proportionally
            for inst in instruments:
                raw_weights[inst] -= (
                    np.sign(net) * net_excess * (abs(raw_weights[inst]) / (gross + 1e-12))
                )

        # 7. Apply drawdown scaling
        final_weights = {k: v * dd_scale for k, v in raw_weights.items()}

        # 8. Convert to notional sizes
        notional: dict[str, float] = {}
        for inst in instruments:
            n_size = final_weights[inst] * capital
            if abs(n_size) >= self.cfg.min_trade_notional:
                notional[inst] = n_size
            else:
                notional[inst] = 0.0
                final_weights[inst] = 0.0

        gross_exp = sum(abs(v) for v in final_weights.values())
        net_exp = sum(final_weights.values())

        return AllocationResult(
            timestamp=timestamp,
            capital=capital,
            capital_at_risk=capital * dd_scale * self.cfg.target_annual_vol,
            instruments=instruments,
            signals={k: signals[k] for k in instruments},
            vol_scalars={k: float(vol_scalars.get(k, 1.0)) for k in instruments},
            erc_weights={k: float(erc_weights.get(k, 0.0)) for k in instruments},
            final_weights=final_weights,
            notional_sizes=notional,
            gross_exposure=gross_exp,
            net_exposure=net_exp,
            dd_scale=dd_scale,
        )

    def scale_to_capital(
        self,
        result: AllocationResult,
        new_capital: float,
    ) -> AllocationResult:
        """Rescale an existing AllocationResult to a new capital amount."""
        scale = new_capital / max(result.capital, 1.0)
        result.notional_sizes = {k: v * scale for k, v in result.notional_sizes.items()}
        result.capital = new_capital
        return result
