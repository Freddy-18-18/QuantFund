"""
Export Pipeline: Python Research → Rust Engine
================================================
Converts Python research outputs (signals, strategy specs, allocation results)
into JSON formats consumed by the Rust execution engine.

The Rust engine expects:
  - SignalEvent: {timestamp_ns, strategy_id, instrument_id, side, strength, metadata}
  - StrategySpec: configuration that the Rust engine loads to instantiate a strategy
  - AllocationSpec: position sizes and risk parameters per instrument

All timestamps are nanoseconds since Unix epoch (i64) to match Rust's Timestamp type.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from quantfund.portfolio.allocator import AllocationResult

__all__ = [
    "RustSignalEvent",
    "StrategySpec",
    "AllocationSpec",
    "PositionSpec",
    "RustExporter",
]

# ---------------------------------------------------------------------------
# Rust-compatible data structures
# ---------------------------------------------------------------------------

Side = Literal["Buy", "Sell"]


@dataclass
class RustSignalEvent:
    """
    Mirrors the Rust ``SignalEvent`` struct exactly.

    Rust definition (engine/core/src/event.rs):
        pub struct SignalEvent {
            pub timestamp: Timestamp,       // i64 nanos
            pub strategy_id: StrategyId,    // String
            pub instrument_id: InstrumentId, // String
            pub side: Option<Side>,         // "Buy" | "Sell" | null
            pub strength: f64,              // [-1.0, 1.0]
            pub metadata: serde_json::Value,
        }
    """

    timestamp_ns: int
    strategy_id: str
    instrument_id: str
    side: Side | None  # None = flat
    strength: float  # [-1.0, 1.0]
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (-1.0 <= self.strength <= 1.0):
            raise ValueError(f"strength must be in [-1, 1], got {self.strength}")

    def to_rust_json(self) -> dict:
        """Serialize to Rust-compatible JSON dict."""
        return {
            "timestamp": {"nanos_since_epoch": self.timestamp_ns},
            "strategy_id": self.strategy_id,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "strength": self.strength,
            "metadata": self.metadata,
        }


@dataclass
class StrategySpec:
    """
    Configuration spec exported from Python research to be loaded by the Rust engine.

    The Rust engine reads this JSON to:
    1. Instantiate the correct strategy type
    2. Configure its parameters
    3. Assign instruments and risk budget

    This is the primary integration point between Python research and Rust execution.
    """

    strategy_id: str
    strategy_type: str  # e.g. "PythonSignalRelay", "SMAcrossover"
    name: str
    instruments: list[str]
    parameters: dict  # Strategy-specific parameters
    risk_budget: float = 0.1  # Fraction of portfolio risk budget [0, 1]
    max_position: float = 0.25  # Max single position as pct of capital
    enabled: bool = True

    # Walk-forward validation results (informational)
    backtest_sharpe: float = 0.0
    backtest_calmar: float = 0.0
    backtest_ic: float = 0.0
    backtest_icir: float = 0.0
    backtest_n_windows: int = 0
    is_deployable: bool = False

    # Feature list (used by PythonSignalRelay strategy in Rust)
    feature_names: list[str] = field(default_factory=list)

    def to_json(self, path: str | Path | None = None) -> str:
        """Serialise to JSON string, optionally writing to file."""
        d = asdict(self)
        s = json.dumps(d, indent=2)
        if path is not None:
            Path(path).write_text(s, encoding="utf-8")
        return s

    @classmethod
    def from_json(cls, path: str | Path) -> "StrategySpec":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**d)


@dataclass
class AllocationSpec:
    """
    Position sizing spec exported to the Rust execution engine.

    Sent before each trading session (or when portfolio rebalancing is triggered).
    The Rust engine uses this to determine lot sizes when signals arrive.
    """

    timestamp_ns: int
    capital: float
    dd_scale: float  # [0, 1] drawdown scaling factor
    target_annual_vol: float

    # Per-instrument: notional allocation in account currency
    positions: dict[str, PositionSpec] = field(default_factory=dict)

    def to_json(self, path: str | Path | None = None) -> str:
        d = {
            "timestamp": {"nanos_since_epoch": self.timestamp_ns},
            "capital": self.capital,
            "dd_scale": self.dd_scale,
            "target_annual_vol": self.target_annual_vol,
            "positions": {inst: asdict(spec) for inst, spec in self.positions.items()},
        }
        s = json.dumps(d, indent=2)
        if path is not None:
            Path(path).write_text(s, encoding="utf-8")
        return s


@dataclass
class PositionSpec:
    """Per-instrument allocation parameters."""

    max_notional: float  # Max notional size in account currency
    max_lots: float  # Max lots (calculated from notional + pip value)
    signal_direction: int  # +1 = long-biased, -1 = short-biased, 0 = both
    risk_budget_pct: float  # Fraction of total portfolio vol budget


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


class RustExporter:
    """
    Converts Python research outputs to Rust-compatible JSON.

    Usage::

        exporter = RustExporter(output_dir="research/export")

        # After walk-forward validation
        exporter.export_strategy_spec(
            strategy_id="mom_vol_v1",
            summary=wf_summary,
            features=feature_names,
        )

        # At signal generation time (called by live research process)
        signals = {"EURUSD": 0.72, "GBPUSD": -0.31}
        exporter.export_signals(signals, strategy_id="mom_vol_v1")

        # After portfolio allocation
        exporter.export_allocation(allocation_result)
    """

    def __init__(self, output_dir: str | Path = "export") -> None:
        self.out = Path(output_dir)
        self.out.mkdir(parents=True, exist_ok=True)

        self._signals_path = self.out / "signals.jsonl"  # append-only log
        self._allocation_path = self.out / "allocation.json"  # latest only
        self._specs_dir = self.out / "specs"
        self._specs_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Strategy spec
    # ------------------------------------------------------------------

    def export_strategy_spec(
        self,
        strategy_id: str,
        name: str,
        instruments: list[str],
        parameters: dict,
        feature_names: list[str] | None = None,
        summary=None,  # WalkForwardSummary
        risk_budget: float = 0.1,
        strategy_type: str = "PythonSignalRelay",
    ) -> StrategySpec:
        """
        Export strategy specification for the Rust engine.

        Parameters
        ----------
        summary : WalkForwardSummary from validation module (optional).
                  If provided, backtest metrics are included.
        """
        spec = StrategySpec(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            name=name,
            instruments=instruments,
            parameters=parameters,
            risk_budget=risk_budget,
            feature_names=feature_names or [],
        )

        if summary is not None:
            spec.backtest_sharpe = round(summary.mean_sharpe, 4)
            spec.backtest_calmar = round(summary.combined_metrics.calmar, 4)
            spec.backtest_ic = round(summary.mean_ic, 4)
            spec.backtest_icir = round(summary.icir, 4)
            spec.backtest_n_windows = summary.n_windows
            spec.is_deployable = summary.is_deployable()

        path = self._specs_dir / f"{strategy_id}.json"
        spec.to_json(path)
        return spec

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def export_signals(
        self,
        signals: dict[str, float],
        strategy_id: str,
        timestamp: pd.Timestamp | None = None,
        metadata: dict | None = None,
        append: bool = True,
    ) -> list[RustSignalEvent]:
        """
        Convert {instrument: strength} signals to RustSignalEvent JSON and write.

        Parameters
        ----------
        signals   : {instrument_id: strength} where strength ∈ [-1.0, 1.0].
        append    : If True, append to signals.jsonl. If False, overwrite.
        """
        ts_ns = _to_nanos(timestamp or pd.Timestamp.now(tz="UTC"))
        events = []

        for inst, strength in signals.items():
            strength = float(np.clip(strength, -1.0, 1.0))
            side: Side | None = "Buy" if strength > 0.0 else "Sell" if strength < 0.0 else None

            ev = RustSignalEvent(
                timestamp_ns=ts_ns,
                strategy_id=strategy_id,
                instrument_id=inst,
                side=side,
                strength=strength,
                metadata=metadata or {},
            )
            events.append(ev)

        # Write as JSONL (one JSON object per line)
        mode = "a" if append else "w"
        with self._signals_path.open(mode, encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev.to_rust_json()) + "\n")

        # Also write a "latest" file for the Rust engine to poll
        latest = self.out / "signals_latest.json"
        latest.write_text(
            json.dumps([ev.to_rust_json() for ev in events], indent=2),
            encoding="utf-8",
        )

        return events

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    def export_allocation(
        self,
        result: AllocationResult,
        pip_values: dict[str, float] | None = None,
        lot_size: float = 100_000.0,
    ) -> AllocationSpec:
        """
        Export AllocationResult to Rust-compatible AllocationSpec.

        Parameters
        ----------
        result      : From PortfolioAllocator.allocate()
        pip_values  : {instrument: pip_value_in_account_currency}. Used to
                      convert notional to lots. Defaults to 10.0 per lot.
        lot_size    : Standard lot size (100,000 for FX).
        """
        pip_values = pip_values or {}
        ts_ns = _to_nanos(result.timestamp)

        positions: dict[str, PositionSpec] = {}
        for inst in result.instruments:
            notional = abs(result.notional_sizes.get(inst, 0.0))
            lots = notional / lot_size if lot_size > 0 else 0.0

            # Direction: 0 = bidirectional, +1 = long only, -1 = short only
            sig = result.signals.get(inst, 0.0)
            direction = int(np.sign(sig))

            positions[inst] = PositionSpec(
                max_notional=notional,
                max_lots=round(lots, 2),
                signal_direction=direction,
                risk_budget_pct=result.erc_weights.get(inst, 0.0),
            )

        spec = AllocationSpec(
            timestamp_ns=ts_ns,
            capital=result.capital,
            dd_scale=result.dd_scale,
            target_annual_vol=0.15,  # from config - caller should pass this
            positions=positions,
        )
        spec.to_json(self._allocation_path)
        return spec

    # ------------------------------------------------------------------
    # Utility: load all strategy specs
    # ------------------------------------------------------------------

    def list_strategy_specs(self) -> list[StrategySpec]:
        """Load all exported strategy specs from disk."""
        specs = []
        for path in sorted(self._specs_dir.glob("*.json")):
            try:
                specs.append(StrategySpec.from_json(path))
            except Exception:
                pass
        return specs

    def latest_signals(self) -> list[dict]:
        """Read the latest signals JSON (for debugging)."""
        latest = self.out / "signals_latest.json"
        if not latest.exists():
            return []
        return json.loads(latest.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_nanos(ts: pd.Timestamp | datetime) -> int:
    """Convert pandas Timestamp or datetime to nanoseconds since epoch (i64)."""
    if isinstance(ts, pd.Timestamp):
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        return int(ts.value)  # pandas stores as ns since epoch internally
    elif isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(ts.timestamp() * 1_000_000_000)
    else:
        raise TypeError(f"Cannot convert {type(ts)} to nanoseconds")
