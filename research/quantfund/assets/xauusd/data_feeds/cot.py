"""
CFTC Commitments of Traders (COT) data feed for XAUUSD.

Source: CFTC publishes free weekly COT reports every Friday at ~3:30 PM ET.
Historical data: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalViewable/index.htm
Current year: https://www.cftc.gov/dea/newcot/deahistfo.zip  (Disaggregated, futures-only)

Report type used: "Disaggregated Futures Only" — separates managed money
(hedge funds) from producers/merchants and swaps dealers.

Gold futures contract: COMEX "GOLD - COMMODITY EXCHANGE INC." (CFTC code 088691)

Key positions tracked:
    - managed_money_long / managed_money_short  → speculative positioning
    - producer_long / producer_short            → commercial hedging
    - net_speculative = mm_long - mm_short       → primary signal
    - net_speculative_pct = net_spec / open_interest  → normalised

Usage:
    feed = COTFeed()
    df = feed.fetch(start=datetime(2010, 1, 1))
    # weekly frequency, forward-fill to daily with .resample("1D").ffill()
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

# CFTC Disaggregated Futures-Only report URL
# Pattern confirmed from CFTC website (as of 2025): /files/dea/history/fut_disagg_txt_{year}.zip
_COT_ANNUAL_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
# Current-year rolling file (updated weekly)
_COT_CURRENT_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"

# CFTC commodity code for COMEX Gold
_GOLD_CODE = "088691"
_GOLD_NAME_FRAGMENT = "GOLD"

# Column mapping from CFTC CSV to our standardised names
_COL_MAP = {
    "Market_and_Exchange_Names": "market_name",
    "As_of_Date_In_Form_YYMMDD": "date",
    "Open_Interest_All": "open_interest",
    "Prod_Merc_Positions_Long_All": "producer_long",
    "Prod_Merc_Positions_Short_All": "producer_short",
    "Swap_Positions_Long_All": "swap_long",
    "Swap__Positions_Short_All": "swap_short",
    "M_Money_Positions_Long_All": "managed_money_long",
    "M_Money_Positions_Short_All": "managed_money_short",
    "Other_Rept_Positions_Long_All": "other_long",
    "Other_Rept_Positions_Short_All": "other_short",
    "NonRept_Positions_Long_All": "nonrep_long",
    "NonRept_Positions_Short_All": "nonrep_short",
}


class COTFeed:
    """
    Downloads and parses CFTC Disaggregated COT reports for COMEX Gold.

    Data is released weekly (Tuesdays data, published Fridays).
    All positions are in number of contracts (1 contract = 100 troy oz).
    """

    def fetch(
        self,
        start: datetime,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Return weekly COT positioning for COMEX Gold.

        Args:
            start: Inclusive start date.
            end:   Inclusive end date. Defaults to today.

        Returns:
            DataFrame with weekly DatetimeIndex (UTC) and columns:
            open_interest, producer_long, producer_short, swap_long,
            swap_short, managed_money_long, managed_money_short,
            other_long, other_short, nonrep_long, nonrep_short,
            net_speculative, net_speculative_pct, commercial_net,
            mm_long_pct, mm_short_pct
        """
        if end is None:
            end = datetime.now(timezone.utc)

        start_year = start.year
        end_year = end.year
        current_year = datetime.now(timezone.utc).year

        frames = []

        # Fetch all years in range (including current year which is updated weekly)
        for year in range(start_year, end_year + 1):
            url = _COT_ANNUAL_URL.format(year=year)
            df_hist = self._fetch_zip(url)
            if df_hist is not None:
                frames.append(df_hist)

        if not frames:
            raise RuntimeError("No COT data could be downloaded from CFTC.")

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.drop_duplicates(subset=["date"])
        combined = combined.sort_values("date")

        # Filter date range
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
        mask = (combined["date"] >= start_ts) & (combined["date"] <= end_ts)
        combined = combined[mask].copy()
        combined = combined.set_index("date")

        # Derived features
        combined["net_speculative"] = (
            combined["managed_money_long"] - combined["managed_money_short"]
        )
        combined["net_speculative_pct"] = combined["net_speculative"] / combined[
            "open_interest"
        ].replace(0, float("nan"))
        combined["commercial_net"] = (
            combined["producer_long"]
            - combined["producer_short"]
            + combined["swap_long"]
            - combined["swap_short"]
        )
        combined["mm_long_pct"] = combined["managed_money_long"] / combined[
            "open_interest"
        ].replace(0, float("nan"))
        combined["mm_short_pct"] = combined["managed_money_short"] / combined[
            "open_interest"
        ].replace(0, float("nan"))

        # Rolling z-score of net_speculative (52-week lookback)
        combined["net_spec_zscore_52w"] = _rolling_zscore(combined["net_speculative"], window=52)

        return combined

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_zip(self, url: str) -> Optional[pd.DataFrame]:
        """Download a CFTC ZIP file and parse the CSV inside."""
        try:
            import httpx  # type: ignore[import]

            response = httpx.get(url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()
        except Exception as exc:
            print(f"[COTFeed] Warning: could not fetch {url}: {exc}")
            return None

        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                # The ZIP contains one CSV; find it
                csv_names = [n for n in zf.namelist() if n.endswith(".txt") or n.endswith(".csv")]
                if not csv_names:
                    print(f"[COTFeed] Warning: no CSV found in {url}")
                    return None
                with zf.open(csv_names[0]) as f:
                    raw = pd.read_csv(f, low_memory=False)
        except Exception as exc:
            print(f"[COTFeed] Warning: could not parse ZIP from {url}: {exc}")
            return None

        return self._parse_gold(raw)

    def _parse_gold(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Filter the raw COT DataFrame to COMEX Gold rows and rename columns."""
        # Filter to gold rows
        if "Market_and_Exchange_Names" in df.columns:
            mask = df["Market_and_Exchange_Names"].str.contains(
                _GOLD_NAME_FRAGMENT, na=False, case=False
            )
            df = df[mask].copy()
        else:
            return None

        if df.empty:
            return None

        # Keep only columns we care about
        available = {k: v for k, v in _COL_MAP.items() if k in df.columns}
        df = df[list(available.keys())].rename(columns=available)

        # Parse date: YYMMDD format
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], format="%y%m%d", utc=True)

        # Cast numeric columns
        numeric_cols = [c for c in df.columns if c != "date" and c != "market_name"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return df


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling z-score."""
    mu = series.rolling(window, min_periods=window // 2).mean()
    sigma = series.rolling(window, min_periods=window // 2).std()
    return (series - mu) / sigma.replace(0, float("nan"))
