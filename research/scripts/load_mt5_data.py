#!/usr/bin/env python3
"""
Bulk-load MT5 historical OHLCV data into the research data catalog.

Usage examples::

    # Load 5 years of 1-min data for default symbols (dry run)
    python scripts/load_mt5_data.py --dry-run

    # Load 5 years of M1 + H1 for default symbols
    python scripts/load_mt5_data.py --freq 1min 1h --years 5

    # Override symbols
    python scripts/load_mt5_data.py --symbols EURUSD GBPUSD --freq 1min

    # Include cross-asset instruments at H1
    python scripts/load_mt5_data.py --cross-asset
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from either project root or scripts/ directory
_script_dir = Path(__file__).resolve().parent
_research_dir = _script_dir.parent
sys.path.insert(0, str(_research_dir))

from quantfund.data import DataCatalog, OHLCVLoader, ResampleFreq

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

PRIMARY_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD"]

CROSS_ASSET_SYMBOLS = [
    ("US30", ResampleFreq.H1),
    ("USDX", ResampleFreq.H1),
    ("USDJPY", ResampleFreq.H1),
]

FREQ_ALIAS = {
    "1min": ResampleFreq.M1,
    "5min": ResampleFreq.M5,
    "15min": ResampleFreq.M15,
    "30min": ResampleFreq.M30,
    "1h": ResampleFreq.H1,
    "4h": ResampleFreq.H4,
    "1d": ResampleFreq.D1,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk-load MT5 historical data into the research catalog."
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=PRIMARY_SYMBOLS,
        metavar="SYM",
        help=f"Symbols to load. Default: {PRIMARY_SYMBOLS}",
    )
    parser.add_argument(
        "--freq",
        nargs="+",
        default=["1min"],
        choices=list(FREQ_ALIAS.keys()),
        metavar="FREQ",
        help="Bar frequencies (space-separated). Default: 1min",
    )
    parser.add_argument(
        "--years",
        type=float,
        default=5.0,
        help="Number of years of history to load. Default: 5",
    )
    parser.add_argument(
        "--catalog",
        default="data",
        help="DataCatalog root directory. Default: data",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=30,
        help="Days per MT5 API request chunk. Default: 30",
    )
    parser.add_argument(
        "--cross-asset",
        action="store_true",
        help="Also load cross-asset instruments at H1.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be loaded without calling MT5.",
    )
    args = parser.parse_args()

    catalog = DataCatalog(args.catalog)
    loader = OHLCVLoader(catalog)

    date_to = datetime.now(tz=timezone.utc)
    date_from = date_to - timedelta(days=int(args.years * 365))

    # Build load plan
    plan: list[tuple[str, str]] = []
    for sym in args.symbols:
        for freq_str in args.freq:
            plan.append((sym, FREQ_ALIAS[freq_str]))

    if args.cross_asset:
        for sym, freq in CROSS_ASSET_SYMBOLS:
            plan.append((sym, freq))

    print(f"Date range : {date_from.date()} → {date_to.date()}")
    print(f"Catalog    : {args.catalog}")
    print(f"Chunk days : {args.chunk_days}")
    print(f"Instruments: {len(plan)}")
    print()

    if args.dry_run:
        print("[DRY RUN] Would load:")
        for sym, freq in plan:
            print(f"  {sym:12s}  {freq}")
        return

    summary: list[tuple[str, str, int]] = []
    for sym, freq in plan:
        print(f"  Loading {sym} @ {freq} ...", end=" ", flush=True)
        try:
            df = loader.from_mt5_range(
                sym,
                date_from=date_from,
                date_to=date_to,
                freq=freq,
                save=True,
                chunk_days=args.chunk_days,
            )
            n = len(df)
            print(f"OK ({n:,} bars)")
            summary.append((sym, freq, n))
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED: {exc}")
            summary.append((sym, freq, -1))

    print()
    print("Summary:")
    for sym, freq, n in summary:
        status = f"{n:>10,} bars" if n >= 0 else "       FAILED"
        print(f"  {sym:12s}  {freq:8s}  {status}")


if __name__ == "__main__":
    main()
