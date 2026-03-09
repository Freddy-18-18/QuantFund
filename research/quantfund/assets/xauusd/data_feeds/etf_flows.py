"""
ETF flows data feed for XAUUSD — GLD and IAU.

ETF shares outstanding × NAV per share = total AUM (proxy for institutional
gold demand). Daily changes in shares outstanding indicate net creation/
redemption activity (inflows/outflows).

Sources (all free via yfinance):
    - GLD  : SPDR Gold Shares (largest gold ETF, ~$60B AUM)
    - IAU  : iShares Gold Trust (second largest, ~$30B AUM)
    - SGOL : Aberdeen Physical Gold Shares
    - GDX  : VanEck Gold Miners ETF (miner equity proxy)
    - GDXJ : VanEck Junior Gold Miners ETF

yfinance provides:
    - daily close price
    - shares outstanding (via .info or fast_info)
    - AUM can be approximated from market cap / price

Derived signals:
    - gld_iau_flow_ratio  : relative flow between GLD and IAU
    - total_etf_chg_shares: daily change in total ETF shares (net flows proxy)
    - etf_flow_zscore_20d : 20-day z-score of net flows

Usage:
    feed = ETFFeed()
    df = feed.fetch(start=datetime(2020, 1, 1))
    # daily frequency
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

_ETF_TICKERS: List[str] = ["GLD", "IAU", "SGOL", "GDX", "GDXJ"]

# Gold price ETF tickers (hold physical gold, not miners)
_GOLD_ETFS = ["GLD", "IAU", "SGOL"]


class ETFFeed:
    """
    Fetches gold ETF price and volume data via yfinance.

    Note: yfinance does not expose actual shares-outstanding time series
    (only the current snapshot). We use daily volume × price as a flow
    proxy, which is noisier but available historically.

    For true AUM flows research, use the World Gold Council / ETF provider
    files (manual download). This feed provides the best automated proxy.
    """

    def fetch(
        self,
        start: datetime,
        end: Optional[datetime] = None,
        tickers: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Return daily ETF price/volume data and flow proxies.

        Args:
            start:   Inclusive start date.
            end:     Inclusive end date. Defaults to today.
            tickers: ETF tickers to include. Defaults to all 5.

        Returns:
            DataFrame with daily DatetimeIndex (UTC) and multi-level columns:
            (ticker, metric) where metric ∈ {close, volume, dollar_volume}
            Plus derived columns:
              - gld_close, iau_close, gld_iau_ratio
              - total_gold_etf_dv (dollar volume of GLD+IAU+SGOL)
              - gold_etf_dv_chg   (daily change)
              - gold_etf_dv_zscore_20d
        """
        try:
            import yfinance as yf  # type: ignore[import]
        except ImportError:
            raise ImportError("yfinance is required: pip install yfinance")

        if end is None:
            end = datetime.now(timezone.utc)
        if tickers is None:
            tickers = _ETF_TICKERS

        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        raw = yf.download(
            tickers=tickers,
            start=start_str,
            end=end_str,
            auto_adjust=True,
            progress=False,
            threads=True,
        )

        if raw.empty:
            return pd.DataFrame()

        # Normalise index to UTC
        raw.index = pd.to_datetime(raw.index, utc=True)  # type: ignore[assignment]

        # Build flat output
        out = pd.DataFrame(index=raw.index)

        for ticker in tickers:
            try:
                # yfinance multi-ticker returns (metric, ticker) column tuples
                close = raw[("Close", ticker)]
                volume = raw[("Volume", ticker)]
            except KeyError:
                continue
            out[f"{ticker.lower()}_close"] = close
            out[f"{ticker.lower()}_volume"] = volume
            out[f"{ticker.lower()}_dv"] = close * volume  # dollar volume

        # GLD/IAU ratio: gold demand distribution between the two main ETFs
        if "gld_close" in out.columns and "iau_close" in out.columns:
            out["gld_iau_ratio"] = out["gld_close"] / out["iau_close"].replace(0, float("nan"))

        # Total physical-gold-ETF dollar volume
        dv_cols = [f"{t.lower()}_dv" for t in _GOLD_ETFS if f"{t.lower()}_dv" in out.columns]
        if dv_cols:
            out["total_gold_etf_dv"] = out[dv_cols].sum(axis=1)
            out["gold_etf_dv_chg"] = out["total_gold_etf_dv"].diff()
            out["gold_etf_dv_zscore_20d"] = _rolling_zscore(out["total_gold_etf_dv"], window=20)
            out["gold_etf_dv_chg_zscore_20d"] = _rolling_zscore(out["gold_etf_dv_chg"], window=20)

        # GDX / GDXJ relative strength vs gold (miner discount/premium signal)
        if "gdx_close" in out.columns and "gld_close" in out.columns:
            out["gdx_gld_ratio"] = out["gdx_close"] / out["gld_close"].replace(0, float("nan"))
            out["gdx_gld_ratio_chg"] = out["gdx_gld_ratio"].diff()

        return out.sort_index()


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling z-score."""
    mu = series.rolling(window, min_periods=window // 2).mean()
    sigma = series.rolling(window, min_periods=window // 2).std()
    return (series - mu) / sigma.replace(0, float("nan"))
