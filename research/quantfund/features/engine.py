"""
Feature Engineering Framework
==============================
Institutional-grade feature extraction for alpha research.

Feature families:
  - Price features (momentum, mean-reversion, microstructure)
  - Volatility features (realized vol, vol-of-vol, vol regimes)
  - Volume features (VWAP, participation rate, volume clock)
  - Cross-asset features (correlation, beta, relative strength)
  - Calendar features (session, day-of-week, hour-of-day)

Design principles:
  - All features are LOOK-AHEAD FREE: computed only from t <= current bar
  - Numba-accelerated rolling computations where possible
  - Returns a flat feature DataFrame suitable for ML models
  - Each feature is z-score normalised in the walk-forward loop (NOT here)
"""

from __future__ import annotations

from typing import Sequence
import numpy as np
import pandas as pd

__all__ = [
    "PriceFeatures",
    "VolatilityFeatures",
    "VolumeFeatures",
    "CrossAssetFeatures",
    "CalendarFeatures",
    "FeaturePipeline",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()  # type: ignore[return-value]


def _log(series: pd.Series) -> pd.Series:
    """Natural log of a Series, preserving the pandas type for type checkers."""
    return pd.Series(np.log(series.values), index=series.index, name=series.name)


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Z-score of series relative to its own rolling window."""
    mu = series.rolling(window, min_periods=window // 2).mean()
    sig = series.rolling(window, min_periods=window // 2).std(ddof=1)
    return (series - mu) / sig.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Price Features
# ---------------------------------------------------------------------------


class PriceFeatures:
    """
    Momentum, mean-reversion, and microstructure price signals.

    All returns are log-returns to ensure stationarity.
    """

    def __init__(
        self,
        momentum_windows: Sequence[int] = (5, 15, 60, 240, 1440),
        zscore_window: int = 240,
    ) -> None:
        self.momentum_windows = list(momentum_windows)
        self.zscore_window = zscore_window

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Parameters
        ----------
        df : OHLCV DataFrame with DatetimeIndex (UTC).

        Returns
        -------
        DataFrame of price features aligned on same index.
        """
        out: dict[str, pd.Series] = {}
        close = df["close"]
        log_c = _log(close)

        # --- Log returns ---
        out["ret_1"] = log_c.diff(1)
        out["ret_5"] = log_c.diff(5)
        out["ret_15"] = log_c.diff(15)
        out["ret_60"] = log_c.diff(60)

        # --- Momentum: price vs n-bar rolling mean ---
        for w in self.momentum_windows:
            ma = log_c.rolling(w).mean()
            out[f"mom_{w}"] = log_c - ma  # deviation from MA
            out[f"mom_zscore_{w}"] = _rolling_zscore(log_c - ma, self.zscore_window)

        # --- Mean reversion: distance from rolling high/low ---
        for w in (20, 60, 240):
            roll_high = df["high"].rolling(w).max()
            roll_low = df["low"].rolling(w).min()
            rng = (roll_high - roll_low).replace(0, np.nan)
            out[f"pos_in_range_{w}"] = (close - roll_low) / rng  # [0, 1]

        # --- Candle body / wick features ---
        body = (df["close"] - df["open"]).abs()
        candle = (df["high"] - df["low"]).replace(0, np.nan)
        out["body_ratio"] = body / candle  # 0=doji, 1=marubozu
        out["upper_wick_ratio"] = (df["high"] - df[["open", "close"]].max(axis=1)) / candle
        out["lower_wick_ratio"] = (df[["open", "close"]].min(axis=1) - df["low"]) / candle
        out["bull_bar"] = (df["close"] > df["open"]).astype(float)

        # --- RSI (14) ---
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta).clip(lower=0).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        out["rsi_14"] = 100 - 100 / (1 + rs)

        # --- MACD signal ---
        macd_line = _ema(close, 12) - _ema(close, 26)
        signal_line = _ema(macd_line, 9)
        out["macd_hist"] = macd_line - signal_line
        out["macd_signal"] = _rolling_zscore(out["macd_hist"], self.zscore_window)

        return pd.DataFrame(out, index=df.index)


# ---------------------------------------------------------------------------
# Volatility Features
# ---------------------------------------------------------------------------


class VolatilityFeatures:
    """
    Realised volatility, vol-of-vol, and vol regime signals.

    Volatility is THE single most important feature in systematic trading.
    It drives position sizing, regime classification, and risk limits.
    """

    def __init__(
        self,
        vol_windows: Sequence[int] = (5, 20, 60, 240, 1440),
        annualise_factor: int = 525_600,  # minutes per year
    ) -> None:
        self.vol_windows = list(vol_windows)
        self.annualise_k = np.sqrt(annualise_factor)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out: dict[str, pd.Series] = {}
        log_ret = _log(df["close"]).diff()

        # --- Realised volatility (rolling std of log returns) ---
        for w in self.vol_windows:
            rv = log_ret.rolling(w).std(ddof=1) * self.annualise_k
            out[f"rv_{w}"] = rv

        # --- Vol of vol (second-order vol) ---
        rv_20 = log_ret.rolling(20).std(ddof=1)
        out["vol_of_vol_20"] = rv_20.rolling(20).std(ddof=1)

        # --- Vol ratio: short / long (regime proxy) ---
        rv_5 = log_ret.rolling(5).std(ddof=1)
        rv_60 = log_ret.rolling(60).std(ddof=1).replace(0, np.nan)
        out["vol_ratio_5_60"] = rv_5 / rv_60

        # --- Parkinson high-low estimator (more efficient than close-to-close) ---
        log_hl = _log(df["high"] / df["low"].replace(0, np.nan))
        pk_raw = log_hl**2 / (4 * np.log(2))
        for w in (5, 20, 60):
            pk_vol = np.sqrt(pk_raw.rolling(w).mean()) * self.annualise_k
            out[f"parkinson_rv_{w}"] = pk_vol

        # --- Garman-Klass estimator ---
        log_hl2 = 0.5 * _log(df["high"] / df["low"].replace(0, np.nan)) ** 2
        log_co2 = (2 * np.log(2) - 1) * _log(df["close"] / df["open"].replace(0, np.nan)) ** 2
        gk_raw = log_hl2 - log_co2
        for w in (5, 20, 60):
            out[f"gk_rv_{w}"] = np.sqrt(gk_raw.rolling(w).mean().clip(lower=0)) * self.annualise_k

        # --- Vol percentile rank (0=calm, 1=extreme) ---
        rv_ref = log_ret.rolling(20).std(ddof=1)
        for w in (60, 240, 1440):
            out[f"vol_rank_{w}"] = rv_ref.rolling(w).rank(pct=True)

        # --- ATR normalised ---
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_14 = tr.rolling(14).mean()
        out["atr_14_pct"] = atr_14 / df["close"]

        return pd.DataFrame(out, index=df.index)


# ---------------------------------------------------------------------------
# Volume Features
# ---------------------------------------------------------------------------


class VolumeFeatures:
    """
    VWAP, volume participation, and order flow proxies.

    Note: with OHLCV (no tick data) we use proxies.
    Tick data would yield cleaner signals via bid-ask imbalance.
    """

    def __init__(self, vwap_window: int = 390) -> None:  # 390 = 1 trading session of 1-min bars
        self.vwap_window = vwap_window

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out: dict[str, pd.Series] = {}
        typical = (df["high"] + df["low"] + df["close"]) / 3
        vol = df["volume"].replace(0, np.nan)

        # --- VWAP and distance from VWAP ---
        tpv = typical * vol
        vwap = tpv.rolling(self.vwap_window).sum() / vol.rolling(self.vwap_window).sum()
        out["vwap"] = vwap
        out["dist_from_vwap"] = (df["close"] - vwap) / vwap.replace(0, np.nan)

        # --- Volume z-score ---
        for w in (20, 60, 240):
            out[f"vol_zscore_{w}"] = _rolling_zscore(df["volume"], w)

        # --- Volume trend ---
        out["vol_ratio_5_20"] = vol.rolling(5).mean() / vol.rolling(20).mean().replace(0, np.nan)

        # --- Ease of Movement (volume-weighted price change) ---
        midpoint_move = typical.diff()
        box_ratio = (df["high"] - df["low"]) / (vol / 100_000)
        emv = midpoint_move / box_ratio.replace(0, np.nan)
        out["emv_14"] = emv.rolling(14).mean()

        # --- Klinger oscillator proxy (volume sign * direction) ---
        dm = typical - typical.shift(1)
        out["vol_signed_flow"] = np.sign(dm) * vol
        out["vol_flow_ema_5"] = _ema(out["vol_signed_flow"], 5)
        out["vol_flow_ema_20"] = _ema(out["vol_signed_flow"], 20)
        out["vol_klinger"] = out["vol_flow_ema_5"] - out["vol_flow_ema_20"]

        # --- Price-volume correlation (on-balance volume proxy) ---
        log_ret = _log(df["close"]).diff()
        obv_raw = (np.sign(log_ret) * vol).fillna(0).cumsum()
        out["obv_zscore"] = _rolling_zscore(obv_raw, 60)

        return pd.DataFrame(out, index=df.index)


# ---------------------------------------------------------------------------
# Cross-Asset Features
# ---------------------------------------------------------------------------


class CrossAssetFeatures:
    """
    Correlation, beta, and relative-strength signals across instruments.

    Example use: EURUSD vs DXY, GBPUSD vs gilt yields, XAUUSD vs VIX.
    Requires a dict of aligned DataFrames.
    """

    def __init__(self, windows: Sequence[int] = (20, 60, 240)) -> None:
        self.windows = list(windows)

    def transform(
        self,
        primary: pd.DataFrame,
        others: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """
        Parameters
        ----------
        primary : OHLCV for the instrument being modelled.
        others  : Dict of {label: OHLCV} for reference instruments.
                  Must be on the same (or aligned) index.

        Returns
        -------
        Cross-asset feature DataFrame.
        """
        out: dict[str, pd.Series] = {}
        primary_ret = _log(primary["close"]).diff()

        for label, other_df in others.items():
            # Align on common timestamps
            other_ret = _log(other_df["close"]).diff().reindex(primary.index)

            for w in self.windows:
                # Rolling correlation
                corr = primary_ret.rolling(w).corr(other_ret)
                out[f"corr_{label}_{w}"] = corr

                # Rolling beta
                cov = primary_ret.rolling(w).cov(other_ret)
                var = other_ret.rolling(w).var(ddof=1).replace(0, np.nan)
                out[f"beta_{label}_{w}"] = cov / var

            # Relative strength (primary return - other return)
            out[f"rel_str_{label}_5"] = primary_ret.rolling(5).sum() - other_ret.rolling(5).sum()
            out[f"rel_str_{label}_20"] = primary_ret.rolling(20).sum() - other_ret.rolling(20).sum()

        return pd.DataFrame(out, index=primary.index)


# ---------------------------------------------------------------------------
# Calendar Features
# ---------------------------------------------------------------------------


class CalendarFeatures:
    """
    Time-of-day, day-of-week, and session features.

    Markets have strong intraday seasonality:
    - London open (08:00 UTC): high vol
    - NY open overlap (13:00-17:00 UTC): highest vol for FX
    - Asian session (00:00-07:00 UTC): low vol, mean-reverting
    """

    # UTC hours for major session opens
    _LONDON_OPEN = 8
    _NY_OPEN = 13
    _NY_CLOSE = 21
    _TOKYO_OPEN = 0
    _TOKYO_CLOSE = 7

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out: dict[str, pd.Series] = {}

        # Ensure we have a DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError("CalendarFeatures requires a DatetimeIndex")

        dti: pd.DatetimeIndex = df.index
        if dti.tz is None:
            dti = dti.tz_localize("UTC")

        hour = dti.hour + dti.minute / 60.0
        dow = dti.dayofweek  # 0=Monday, 4=Friday
        moy = dti.month  # 1-12
        hour_int = dti.hour
        out["session_tokyo"] = (
            (hour_int >= self._TOKYO_OPEN) & (hour_int < self._TOKYO_CLOSE)
        ).astype(float)
        out["session_london"] = (
            (hour_int >= self._LONDON_OPEN) & (hour_int < self._NY_OPEN)
        ).astype(float)
        out["session_ny"] = ((hour_int >= self._NY_OPEN) & (hour_int < self._NY_CLOSE)).astype(
            float
        )
        out["session_overlap"] = (
            (hour_int >= self._LONDON_OPEN) & (hour_int < self._NY_CLOSE)
        ).astype(float)

        # --- Time since session open (minutes, normalised) ---
        london_mins = ((hour_int - self._LONDON_OPEN) * 60 + dti.minute) % (24 * 60)
        ny_mins = ((hour_int - self._NY_OPEN) * 60 + dti.minute) % (24 * 60)
        out["mins_since_london_open"] = pd.Series(london_mins, index=dti) / (24 * 60)
        out["mins_since_ny_open"] = pd.Series(ny_mins, index=dti) / (24 * 60)

        # --- Cyclical encodings (sin/cos) ---
        out["hour_sin"] = pd.Series(np.sin(2 * np.pi * hour / 24), index=dti)
        out["hour_cos"] = pd.Series(np.cos(2 * np.pi * hour / 24), index=dti)
        out["dow_sin"] = pd.Series(np.sin(2 * np.pi * dow / 7), index=dti)
        out["dow_cos"] = pd.Series(np.cos(2 * np.pi * dow / 7), index=dti)
        out["moy_sin"] = pd.Series(np.sin(2 * np.pi * moy / 12), index=dti)
        out["moy_cos"] = pd.Series(np.cos(2 * np.pi * moy / 12), index=dti)

        # --- Day of week binary flags ---
        out["is_monday"] = (dow == 0).astype(float)
        out["is_friday"] = (dow == 4).astype(float)

        return pd.DataFrame(out, index=df.index)


# ---------------------------------------------------------------------------
# Feature Pipeline (combine all families)
# ---------------------------------------------------------------------------


class FeaturePipeline:
    """
    Composes all feature families into a single feature matrix.

    Usage::

        pipeline = FeaturePipeline()
        features = pipeline.transform(eurusd_ohlcv)

        # With cross-asset
        features = pipeline.transform(
            eurusd_ohlcv,
            cross_assets={"DXY": dxy_ohlcv, "VIX": vix_ohlcv}
        )
    """

    def __init__(
        self,
        include_price: bool = True,
        include_volatility: bool = True,
        include_volume: bool = True,
        include_calendar: bool = True,
        include_cross_asset: bool = False,
        price_kwargs: dict | None = None,
        volatility_kwargs: dict | None = None,
        volume_kwargs: dict | None = None,
        cross_asset_kwargs: dict | None = None,
    ) -> None:
        self.include_price = include_price
        self.include_volatility = include_volatility
        self.include_volume = include_volume
        self.include_calendar = include_calendar
        self.include_cross_asset = include_cross_asset

        self._price = PriceFeatures(**(price_kwargs or {}))
        self._vol = VolatilityFeatures(**(volatility_kwargs or {}))
        self._volume = VolumeFeatures(**(volume_kwargs or {}))
        self._calendar = CalendarFeatures()
        self._crossasset = CrossAssetFeatures(**(cross_asset_kwargs or {}))

    def transform(
        self,
        df: pd.DataFrame,
        cross_assets: dict[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        """
        Parameters
        ----------
        df           : Primary instrument OHLCV DataFrame.
        cross_assets : Optional {label: OHLCV} for cross-asset signals.

        Returns
        -------
        Wide feature DataFrame. NaN rows at start (warm-up period) are kept;
        drop them in the walk-forward loop after windowing.
        """
        parts: list[pd.DataFrame] = []

        if self.include_price:
            parts.append(self._price.transform(df))

        if self.include_volatility:
            parts.append(self._vol.transform(df))

        if self.include_volume:
            parts.append(self._volume.transform(df))

        if self.include_calendar:
            parts.append(self._calendar.transform(df))

        if self.include_cross_asset and cross_assets:
            parts.append(self._crossasset.transform(df, cross_assets))

        result = pd.concat(parts, axis=1)
        result.sort_index(inplace=True)
        return result

    @property
    def feature_names(self) -> list[str]:
        """Return list of all feature names (requires calling transform first)."""
        raise NotImplementedError("Call transform() and use result.columns.tolist()")
