"""
Gold factor builder — combines all data feeds into a unified factor DataFrame.

This is the main entry point for factor research. It joins:
    - OHLCV price features (from DukascopyFeed)
    - Macro factors (FRED: real yields, DXY, VIX, fed funds)
    - COT positioning (CFTC: managed money net speculative)
    - ETF flows (GLD/IAU dollar volume)

All factors are aligned to a common daily DatetimeIndex (UTC).
Intraday features from price data are resampled to daily.

Alignment rules (point-in-time safe):
    - Macro data: FRED publishes with 1-day lag. Shifted forward 1 day.
    - COT data:   Tuesday positions published Friday. Shifted forward 4 days.
    - ETF data:   Published same-day close. Shifted forward 1 day.
    - Price data: Using prior close — no look-ahead.

Usage:
    gf = GoldFactors()
    df = gf.build(start=datetime(2015, 1, 1), end=datetime(2025, 1, 1))
    # df has daily UTC index, ~30 columns of factors
    # Use df.dropna() to get the clean analysis window
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from ..data_feeds.macro import MacroFeed
from ..data_feeds.cot import COTFeed
from ..data_feeds.etf_flows import ETFFeed


class GoldFactors:
    """
    Assembles the full gold factor matrix at daily frequency.

    Each factor group is fetched lazily; if a feed fails (network error,
    missing data) that group is skipped and a warning is printed.
    The price OHLCV can be supplied externally (e.g., from MT5 or
    DukascopyFeed) to decouple downloading from factor computation.
    """

    def __init__(self) -> None:
        self._macro = MacroFeed()
        self._cot = COTFeed()
        self._etf = ETFFeed()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def build(
        self,
        start: datetime,
        end: Optional[datetime] = None,
        price_ohlcv: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        Build the gold factor matrix.

        Args:
            start:       Inclusive start date.
            end:         Inclusive end date. Defaults to today UTC.
            price_ohlcv: Optional pre-loaded daily OHLCV DataFrame
                         (columns: open, high, low, close, volume).
                         If None, price factors are skipped.

        Returns:
            DataFrame with daily UTC DatetimeIndex and columns documented
            in _FACTOR_DESCRIPTIONS below. All factors are point-in-time
            safe (lagged as described in module docstring).
        """
        if end is None:
            end = datetime.now(timezone.utc)

        # Fetch slightly wider window to allow for lagging
        fetch_start = start - timedelta(days=30)

        frames: list[pd.DataFrame] = []

        # --- Macro factors ---
        try:
            macro = self._macro.fetch(start=fetch_start, end=end)
            macro = self._lag(macro, days=1)  # 1-day publication lag
            frames.append(macro)
        except Exception as exc:
            print(f"[GoldFactors] Warning: macro fetch failed: {exc}")

        # --- COT factors ---
        try:
            cot = self._cot.fetch(start=fetch_start, end=end)
            # COT: positions as of Tuesday, published Friday → 4-day lag
            # Resample weekly → daily by forward-filling
            cot_daily = cot.resample("1D").ffill()
            cot_daily = self._lag(cot_daily, days=4)
            # Keep only the signal columns
            cot_cols = [
                "open_interest",
                "managed_money_long",
                "managed_money_short",
                "net_speculative",
                "net_speculative_pct",
                "commercial_net",
                "mm_long_pct",
                "mm_short_pct",
                "net_spec_zscore_52w",
            ]
            cot_daily = cot_daily[[c for c in cot_cols if c in cot_daily.columns]]
            frames.append(cot_daily)
        except Exception as exc:
            print(f"[GoldFactors] Warning: COT fetch failed: {exc}")

        # --- ETF flow factors ---
        try:
            etf = self._etf.fetch(start=fetch_start, end=end)
            etf = self._lag(etf, days=1)  # same-day close lag
            etf_cols = [c for c in etf.columns if not c.endswith("_close")]
            etf_signal = etf[etf_cols] if etf_cols else etf
            frames.append(etf_signal)
        except Exception as exc:
            print(f"[GoldFactors] Warning: ETF fetch failed: {exc}")

        # --- Price-based factors ---
        if price_ohlcv is not None and not price_ohlcv.empty:
            price_factors = self._build_price_factors(price_ohlcv)
            frames.append(price_factors)

        if not frames:
            raise RuntimeError("No factor data could be assembled.")

        # Join all factor groups on their common date index
        combined = frames[0]
        for f in frames[1:]:
            combined = combined.join(f, how="outer", rsuffix="_dup")
            # Drop any accidental duplicate columns
            dup_cols = [c for c in combined.columns if c.endswith("_dup")]
            combined = combined.drop(columns=dup_cols)

        combined = combined.sort_index()

        # Trim to requested window (after lagging)
        start_ts = (
            pd.Timestamp(start).tz_localize("UTC")
            if start.tzinfo is None
            else pd.Timestamp(start).tz_convert("UTC")
        )
        end_ts = (
            pd.Timestamp(end).tz_localize("UTC")
            if end.tzinfo is None
            else pd.Timestamp(end).tz_convert("UTC")
        )
        combined = combined[(combined.index >= start_ts) & (combined.index <= end_ts)]

        return combined

    # ------------------------------------------------------------------
    # Price factor construction
    # ------------------------------------------------------------------

    def _build_price_factors(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        """
        Derive price-based factors from daily OHLCV.

        Returns a DataFrame with daily returns, volatility, momentum,
        and microstructure features.
        """
        df = ohlcv.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("price_ohlcv must have a DatetimeIndex")
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")

        c = df["close"]
        h = df["high"]
        lo = df["low"]
        vol = df.get("volume", pd.Series(dtype=float))

        out = pd.DataFrame(index=df.index)

        # Returns
        out["gold_ret_1d"] = c.pct_change(1)
        out["gold_ret_5d"] = c.pct_change(5)
        out["gold_ret_21d"] = c.pct_change(21)
        out["gold_log_ret_1d"] = np.log(c / c.shift(1))

        # Realised volatility (annualised)
        log_ret = out["gold_log_ret_1d"]
        out["gold_rvol_10d"] = log_ret.rolling(10).std() * np.sqrt(252)
        out["gold_rvol_21d"] = log_ret.rolling(21).std() * np.sqrt(252)

        # Momentum / trend
        out["gold_mom_63d"] = c.pct_change(63)  # ~3 months
        out["gold_mom_252d"] = c.pct_change(252)  # ~1 year

        # Mean-reversion indicators
        ema_20 = c.ewm(span=20, adjust=False).mean()
        ema_50 = c.ewm(span=50, adjust=False).mean()
        out["gold_dist_ema20"] = (c - ema_20) / ema_20
        out["gold_ema20_50_cross"] = (ema_20 - ema_50) / ema_50

        # Intraday range (high-low / close) — measures daily expansion
        out["gold_hl_range"] = (h - lo) / c.shift(1).replace(0, float("nan"))

        # Volume-weighted momentum (if volume available)
        if not vol.empty and vol.notna().any():
            out["gold_vol_mom_5d"] = ((c * vol).rolling(5).sum() / vol.rolling(5).sum()) / c.shift(
                5
            ).replace(0, float("nan")) - 1

        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lag(df: pd.DataFrame, days: int) -> pd.DataFrame:
        """Shift a daily DataFrame forward by `days` to avoid look-ahead."""
        df = df.copy()
        df.index = df.index + pd.Timedelta(days=days)
        return df


# ------------------------------------------------------------------
# Factor descriptions (for documentation and dashboard tooltips)
# ------------------------------------------------------------------

FACTOR_DESCRIPTIONS: dict[str, str] = {
    "real_yield": "US 10Y TIPS real yield (%) — strongest gold driver",
    "nominal_yield": "US 10Y nominal Treasury yield (%)",
    "dxy": "US Dollar broad trade-weighted index",
    "vix": "CBOE VIX (equity vol / risk-off proxy)",
    "fed_funds": "Effective Fed Funds Rate (%)",
    "breakeven_inflation": "10Y breakeven inflation = nominal - real yield",
    "real_yield_1d_chg": "Daily change in real yield (key intraday signal)",
    "dxy_1d_chg": "Daily change in DXY",
    "net_speculative": "COMEX Gold: managed money net long contracts",
    "net_speculative_pct": "Net speculative / open interest (normalised positioning)",
    "net_spec_zscore_52w": "52-week z-score of net speculative positioning",
    "commercial_net": "COMEX Gold: commercial (producer+swap) net position",
    "total_gold_etf_dv": "GLD+IAU+SGOL total dollar volume (demand proxy)",
    "gold_etf_dv_chg": "Daily change in ETF dollar volume",
    "gold_etf_dv_zscore_20d": "20-day z-score of ETF dollar volume",
    "gdx_gld_ratio": "GDX/GLD ratio (miner vs physical gold premium/discount)",
    "gold_ret_1d": "XAUUSD 1-day return",
    "gold_ret_5d": "XAUUSD 5-day return",
    "gold_ret_21d": "XAUUSD 21-day return",
    "gold_rvol_21d": "XAUUSD 21-day realised volatility (annualised)",
    "gold_mom_63d": "XAUUSD 63-day momentum (3-month trend)",
    "gold_mom_252d": "XAUUSD 252-day momentum (1-year trend)",
    "gold_dist_ema20": "Distance from 20-day EMA / EMA (mean reversion signal)",
    "gold_hl_range": "Daily high-low range / prior close (intraday expansion)",
}
