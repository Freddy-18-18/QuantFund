"""
Macro Fundamental Signals Module
=================================
Comprehensive signal generation based on macroeconomic indicators for
XAUUSD (Gold) trading and general macro regime detection.

Signal Categories:
- Interest Rate Signals: Real yields, Fed funds, yield curve, term premium
- Money Supply Signals: M2 growth, velocity, money printing detection
- Inflation Signals: CPI/PCE acceleration, real vs nominal, breakeven
- Employment Signals: NFP surprises, wage growth, labor force participation
- Market Signals: VIX extremes, Dollar strength, risk-on/risk-off

Usage:
    from quantfund.strategies.fred_signals import MacroFundamentalSignals

    signals = MacroFundamentalSignals()
    all_signals = signals.generate_all_signals(start_date, end_date)
    gold_signal = signals.gold_macro_signal(all_signals)
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SignalDirection(Enum):
    """Signal direction enumeration."""

    BULLISH = 1
    BEARISH = -1
    NEUTRAL = 0


class SignalCategory(Enum):
    """Signal category enumeration."""

    INTEREST_RATE = "interest_rate"
    MONEY_SUPPLY = "money_supply"
    INFLATION = "inflation"
    EMPLOYMENT = "employment"
    MARKET = "market"
    GOLD = "gold"


@dataclass
class Signal:
    """Individual signal data structure."""

    date: date
    name: str
    value: float
    direction: SignalDirection
    strength: float
    category: SignalCategory
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.direction, str):
            self.direction = SignalDirection[self.direction.upper()]
        if isinstance(self.category, str):
            self.category = SignalCategory[self.category.upper()]

    def to_dict(self) -> Dict[str, Any]:
        """Convert signal to dictionary."""
        return {
            "date": self.date.isoformat() if isinstance(self.date, date) else self.date,
            "name": self.name,
            "value": self.value,
            "direction": self.direction.name,
            "strength": self.strength,
            "category": self.category.value,
            "details": self.details,
        }


@dataclass
class SignalPortfolio:
    """Portfolio of multiple signals."""

    signals: List[Signal] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    def add_signal(self, signal: Signal) -> None:
        """Add a signal to the portfolio."""
        self.signals.append(signal)

    def get_signals_by_category(self, category: SignalCategory) -> List[Signal]:
        """Get signals filtered by category."""
        return [s for s in self.signals if s.category == category]

    def get_signals_by_direction(self, direction: SignalDirection) -> List[Signal]:
        """Get signals filtered by direction."""
        return [s for s in self.signals if s.direction == direction]

    def to_dataframe(self) -> pd.DataFrame:
        """Convert signals to pandas DataFrame."""
        if not self.signals:
            return pd.DataFrame()

        records = [s.to_dict() for s in self.signals]
        df = pd.DataFrame(records)

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()

        return df

    def save_to_db(
        self,
        host: Optional[str] = None,
        database: str = "freddata",
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """Save signals to database."""
        try:
            import psycopg2
        except ImportError:
            logger.warning("psycopg2 not available, skipping DB save")
            return False

        host = host or os.environ.get("FRED_DB_HOST", "localhost")
        user = user or os.environ.get("FRED_DB_USER", "postgres")
        password = password or os.environ.get("FRED_DB_PASSWORD", "")

        conn_str = f"host={host} port=5432 dbname={database} user={user} password={password}"

        try:
            conn = psycopg2.connect(conn_str)
            cur = conn.cursor()

            for signal in self.signals:
                cur.execute(
                    """
                    INSERT INTO macro_signals 
                    (date, name, value, direction, strength, category, details, generated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        signal.date,
                        signal.name,
                        signal.value,
                        signal.direction.name,
                        signal.strength,
                        signal.category.value,
                        str(signal.details),
                        self.generated_at,
                    ),
                )

            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"Saved {len(self.signals)} signals to database")
            return True

        except Exception as e:
            logger.error(f"Failed to save signals to database: {e}")
            return False


@dataclass
class SignalConfig:
    """Configuration for signal generation parameters."""

    # Lookback periods
    lookback_m2: int = 52
    lookback_inflation: int = 12
    lookback_employment: int = 6
    lookback_momentum: int = 20

    # Thresholds
    real_yield_threshold: float = 1.0
    yield_curve_threshold: float = 0.5
    m2_growth_threshold: float = 0.05
    inflation_accel_threshold: float = 0.5
    vix_spike_threshold: float = 25.0
    dollar_threshold: float = 105.0

    # Combination weights
    weights: Dict[str, float] = field(
        default_factory=lambda: {
            "interest_rate": 0.25,
            "money_supply": 0.20,
            "inflation": 0.25,
            "employment": 0.15,
            "market": 0.15,
        }
    )

    # Z-score normalization window
    zscore_window: int = 252


class MacroFundamentalSignals:
    """
    Main signal generator based on macroeconomic indicators.

    Provides comprehensive macro signals for XAUUSD trading and
    general market regime detection.
    """

    SERIES_MAP: Dict[str, str] = {
        # Interest Rate Series
        "DFII10": "DFII10",  # 10-Year Treasury Inflation-Indexed Security (TIPS)
        "FEDFUNDS": "FEDFUNDS",  # Federal Funds Rate
        "DGS10": "DGS10",  # 10-Year Treasury Constant Maturity Rate
        "DGS2": "DGS2",  # 2-Year Treasury Constant Maturity Rate
        "M2SL": "M2SL",  # M2 Money Supply
        "M2V": "M2V",  # M2 Velocity
        # Inflation Series
        "CPIAUCSL": "CPIAUCSL",  # CPI for All Urban Consumers
        "PCEPI": "PCEPI",  # Personal Consumption Expenditures Price Index
        "BEILAST": "BEILAST",  # Breakeven Inflation Rate
        # Employment Series
        "PAYEMS": "PAYEMS",  # Nonfarm Payrolls
        "AHISE": "AHISE",  # Average Hourly Earnings
        "LBSSA": "LBSSA",  # Labor Force Participation Rate
        "UNRATE": "UNRATE",  # Unemployment Rate
        # Market Series
        "VIXCLS": "VIXCLS",  # VIX
        "DTINYUS": "DTINYUS",  # US Dollar Index
    }

    def __init__(self, config: Optional[SignalConfig] = None):
        """
        Initialize macro signals generator.

        Args:
            config: Optional signal configuration
        """
        self.config = config or SignalConfig()
        self._data_cache: Dict[str, pd.DataFrame] = {}
        self._fred_client = None

    def _get_fred_client(self):
        """Get or create FRED client."""
        if self._fred_client is None:
            try:
                from quantfund.data.fred_client import FredClient

                api_key = os.environ.get("FRED_API_KEY")
                if not api_key:
                    raise ValueError("FRED_API_KEY not set")
                self._fred_client = FredClient(api_key=api_key)
            except Exception as e:
                logger.warning(f"Could not create FRED client: {e}")
                return None
        return self._fred_client

    def fetch_series(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch series data from FRED or cache."""
        cache_key = f"{series_id}_{start_date}_{end_date}"

        if cache_key in self._data_cache:
            return self._data_cache[cache_key]

        client = self._get_fred_client()
        if client is None:
            logger.warning(f"No FRED client available for {series_id}")
            return pd.DataFrame()

        try:
            df = client.get_observations(series_id, start_date, end_date)
            if not df.empty:
                df = df.set_index("date").sort_index()
                self._data_cache[cache_key] = df
            return df
        except Exception as e:
            logger.warning(f"Failed to fetch {series_id}: {e}")
            return pd.DataFrame()

    def load_data(
        self,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        Load all required macro data for signal generation.

        Returns DataFrame with all indicators.
        """
        data = {}

        for name, series_id in self.SERIES_MAP.items():
            df = self.fetch_series(series_id, start_date, end_date)
            if not df.empty:
                data[name] = df["value"]

        if not data:
            logger.warning("No macro data loaded")
            return pd.DataFrame()

        result = pd.DataFrame(data)
        result = result.ffill().bfill()

        return result

    # ========================================================================
    # Interest Rate Signals
    # ========================================================================

    def real_yield_signal(
        self,
        tips: pd.Series,
        nominal: pd.Series,
    ) -> pd.Series:
        """
        Real yield signal based on TIPS (DFII10) impact on gold.

        Negative real yields (below inflation) are bullish for gold.
        """
        real_yield = tips - nominal

        zscore_window = self.config.zscore_window
        rolling_mean = real_yield.rolling(zscore_window, min_periods=20).mean()
        rolling_std = real_yield.rolling(zscore_window, min_periods=20).std()
        zscore = (real_yield - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=real_yield.index)

        threshold = self.config.real_yield_threshold
        signal[zscore < -threshold] = -1.0
        signal[zscore > threshold] = 1.0
        signal[(zscore >= -threshold) & (zscore <= threshold)] = zscore[
            (zscore >= -threshold) & (zscore <= threshold)
        ]

        return signal.fillna(0.0)

    def fed_funds_signal(self, fed_funds: pd.Series) -> pd.Series:
        """
        Fed funds rate direction signal.

        Rising rates = bearish for gold (opportunity cost)
        Falling rates = bullish for gold
        """
        rate_change = fed_funds.diff(1)

        signal = pd.Series(0.0, index=fed_funds.index)
        signal[rate_change > 0.25] = -1.0
        signal[rate_change < -0.25] = 1.0
        signal[(rate_change <= 0.25) & (rate_change >= -0.25)] = np.clip(
            rate_change[(rate_change <= 0.25) & (rate_change >= -0.25)] * 2, -1.0, 1.0
        )

        return signal.fillna(0.0)

    def yield_curve_signal(
        self,
        ten_year: pd.Series,
        two_year: pd.Series,
    ) -> pd.Series:
        """
        Yield curve signal (10Y-2Y spread).

        Steepening (positive spread) = bullish for gold (inflation expectations)
        Flattening/inverting = bearish for gold (recession risk, flight to safety USD)
        """
        spread = ten_year - two_year

        zscore_window = self.config.zscore_window
        rolling_mean = spread.rolling(zscore_window, min_periods=20).mean()
        rolling_std = spread.rolling(zscore_window, min_periods=20).std()
        zscore = (spread - rolling_mean) / rolling_std

        threshold = self.config.yield_curve_threshold

        signal = pd.Series(0.0, index=spread.index)
        signal[zscore > threshold] = 0.5
        signal[zscore < -threshold] = -0.5
        signal[(zscore > -threshold) & (zscore < threshold)] = (
            zscore[(zscore > -threshold) & (zscore < threshold)] * 0.3
        )

        return signal.fillna(0.0)

    def term_premium_signal(self, ten_year: pd.Series, fed_funds: pd.Series) -> pd.Series:
        """
        Term premium signal based on 10Y - Fed Funds spread.

        High term premium = inflation expectations = bullish for gold
        Low/negative term premium = deflation concerns = bearish for gold
        """
        term_premium = ten_year - fed_funds

        signal = np.clip(term_premium / 3.0, -1.0, 1.0)

        return pd.Series(signal, index=ten_year.index).fillna(0.0)

    # ========================================================================
    # Money Supply Signals
    # ========================================================================

    def m2_growth_signal(self, m2: pd.Series) -> pd.Series:
        """
        M2 growth rate signal.

        High M2 growth = inflationary pressure = bullish for gold
        """
        lookback = self.config.lookback_m2

        m2_pct_change = m2.pct_change(lookback)

        threshold = self.config.m2_growth_threshold

        signal = pd.Series(0.0, index=m2.index)
        signal[m2_pct_change > threshold * 2] = 1.0
        signal[m2_pct_change < -threshold] = -0.5
        signal[(m2_pct_change > -threshold) & (m2_pct_change <= threshold * 2)] = np.clip(
            m2_pct_change[(m2_pct_change > -threshold) & (m2_pct_change <= threshold * 2)]
            / (threshold * 2),
            -1.0,
            1.0,
        )

        return signal.fillna(0.0)

    def m2_velocity_signal(self, m2: pd.Series, m2_velocity: pd.Series) -> pd.Series:
        """
        M2 velocity changes signal.

        Declining velocity (money not circulating) = potential inflation = bullish for gold
        Rising velocity = economic strength = bearish for gold
        """
        vel_change = m2_velocity.diff(1)

        zscore_window = self.config.zscore_window
        rolling_mean = vel_change.rolling(zscore_window, min_periods=20).mean()
        rolling_std = vel_change.rolling(zscore_window, min_periods=20).std()
        zscore = (vel_change - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=vel_change.index)
        signal[zscore < -1.5] = 1.0
        signal[zscore > 1.5] = -0.5
        signal[(zscore >= -1.5) & (zscore <= 1.5)] = np.clip(
            -zscore[(zscore >= -1.5) & (zscore <= 1.5)] * 0.3, -1.0, 1.0
        )

        return signal.fillna(0.0)

    def money_printing_signal(self, m2: pd.Series) -> pd.Series:
        """
        Excessive money printing detection.

        Rapid M2 expansion relative to trend = bullish for gold
        """
        lookback = self.config.lookback_m2

        m2_log = np.log(m2)
        trend = m2_log.rolling(lookback * 2, min_periods=lookback).apply(
            lambda x: np.polyfit(range(len(x)), x, 1)[0] * len(x), raw=True
        )
        deviation = m2_log - trend

        zscore_window = self.config.zscore_window
        rolling_mean = deviation.rolling(zscore_window, min_periods=20).mean()
        rolling_std = deviation.rolling(zscore_window, min_periods=20).std()
        zscore = (deviation - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=m2.index)
        signal[zscore > 2.0] = 1.0
        signal[zscore < -1.5] = -0.5
        signal[(zscore >= -1.5) & (zscore <= 2.0)] = np.clip(
            zscore[(zscore >= -1.5) & (zscore <= 2.0)] * 0.3, -1.0, 1.0
        )

        return signal.fillna(0.0)

    # ========================================================================
    # Inflation Signals
    # ========================================================================

    def inflation_acceleration_signal(self, cpi: pd.Series) -> pd.Series:
        """
        CPI/PCE acceleration signal.

        Accelerating inflation = bullish for gold
        Decelerating inflation = bearish for gold
        """
        lookback = self.config.lookback_inflation

        cpi_pct_change = cpi.pct_change(lookback)
        acceleration = cpi_pct_change.diff(1)

        threshold = self.config.inflation_accel_threshold

        signal = pd.Series(0.0, index=cpi.index)
        signal[acceleration > threshold] = 1.0
        signal[acceleration < -threshold] = -0.5
        signal[(acceleration >= -threshold) & (acceleration <= threshold)] = np.clip(
            acceleration[(acceleration >= -threshold) & (acceleration <= threshold)] / threshold,
            -1.0,
            1.0,
        )

        return signal.fillna(0.0)

    def real_inflation_signal(
        self,
        nominal: pd.Series,
        cpi: pd.Series,
    ) -> pd.Series:
        """
        Real vs nominal rates signal.

        Negative real rates = very bullish for gold
        Positive real rates = bearish for gold
        """
        cpi_yoy = cpi.pct_change(12) * 100
        real_rate = nominal - cpi_yoy

        signal = pd.Series(0.0, index=nominal.index)
        signal[real_rate < -2.0] = 1.0
        signal[real_rate > 4.0] = -1.0
        signal[(real_rate >= -2.0) & (real_rate <= 4.0)] = np.clip(
            -(real_rate[(real_rate >= -2.0) & (real_rate <= 4.0)] - 1.0) / 3.0, -1.0, 1.0
        )

        return signal.fillna(0.0)

    def inflation_expectation_signal(self, breakeven: pd.Series) -> pd.Series:
        """
        Breakeven inflation signal.

        Rising breakeven = inflation expectations up = bullish for gold
        Falling breakeven = deflation expectations = bearish for gold
        """
        be_change = breakeven.diff(1)

        zscore_window = self.config.zscore_window
        rolling_mean = be_change.rolling(zscore_window, min_periods=20).mean()
        rolling_std = be_change.rolling(zscore_window, min_periods=20).std()
        rolling_std = rolling_std.replace(0, 1.0)
        zscore = (be_change - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=breakeven.index)
        signal[zscore > 1.5] = 1.0
        signal[zscore < -1.5] = -0.5
        signal[(zscore >= -1.5) & (zscore <= 1.5)] = np.clip(
            zscore[(zscore >= -1.5) & (zscore <= 1.5)] * 0.4, -1.0, 1.0
        )

        return signal.fillna(0.0)

    # ========================================================================
    # Employment Signals
    # ========================================================================

    def employment_signal(
        self,
        payrolls: pd.Series,
    ) -> pd.Series:
        """
        NFP surprises signal.

        Weak employment = Fed dovish = bullish for gold
        Strong employment = Fed hawkish = bearish for gold
        """
        lookback = self.config.lookback_employment

        surprise = payrolls.diff(lookback)

        rolling_mean = surprise.rolling(lookback * 2, min_periods=lookback).mean()
        rolling_std = surprise.rolling(lookback * 2, min_periods=lookback).std()
        rolling_std = rolling_std.replace(0, 1.0)
        zscore = (surprise - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=payrolls.index)
        signal[zscore < -1.5] = 1.0
        signal[zscore > 1.5] = -0.5
        signal[(zscore >= -1.5) & (zscore <= 1.5)] = np.clip(
            -zscore[(zscore >= -1.5) & (zscore <= 1.5)] * 0.4, -1.0, 1.0
        )

        return signal.fillna(0.0)

    def wage_growth_signal(self, wages: pd.Series) -> pd.Series:
        """
        Wage pressure signal.

        Accelerating wages = inflation pressure = bullish for gold
        """
        wage_change = wages.pct_change(12)

        zscore_window = self.config.zscore_window
        rolling_mean = wage_change.rolling(zscore_window, min_periods=20).mean()
        rolling_std = wage_change.rolling(zscore_window, min_periods=20).std()
        rolling_std = rolling_std.replace(0, 1.0)
        zscore = (wage_change - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=wages.index)
        signal[zscore > 1.5] = 0.75
        signal[zscore < -1.5] = -0.25
        signal[(zscore >= -1.5) & (zscore <= 1.5)] = np.clip(
            zscore[(zscore >= -1.5) & (zscore <= 1.5)] * 0.3, -1.0, 1.0
        )

        return signal.fillna(0.0)

    def labor_force_signal(self, participation: pd.Series) -> pd.Series:
        """
        Labor force participation rate changes.

        Declining participation = weaker economy = bullish for gold
        """
        part_change = participation.diff(1)

        zscore_window = self.config.zscore_window
        rolling_mean = part_change.rolling(zscore_window, min_periods=20).mean()
        rolling_std = part_change.rolling(zscore_window, min_periods=20).std()
        rolling_std = rolling_std.replace(0, 1.0)
        zscore = (part_change - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=participation.index)
        signal[zscore < -1.5] = 0.5
        signal[zscore > 1.5] = -0.25
        signal[(zscore >= -1.5) & (zscore <= 1.5)] = np.clip(
            -zscore[(zscore >= -1.5) & (zscore <= 1.5)] * 0.2, -1.0, 1.0
        )

        return signal.fillna(0.0)

    # ========================================================================
    # Market Signals
    # ========================================================================

    def vix_spike_signal(self, vix: pd.Series) -> pd.Series:
        """
        VIX extremes signal.

        High VIX = fear/crisis = bullish for gold (flight to safety)
        Low VIX = complacency = bearish for gold
        """
        threshold = self.config.vix_spike_threshold

        zscore_window = self.config.zscore_window
        rolling_mean = vix.rolling(zscore_window, min_periods=20).mean()
        rolling_std = vix.rolling(zscore_window, min_periods=20).std()
        rolling_std = rolling_std.replace(0, 1.0)
        zscore = (vix - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=vix.index)
        signal[vix > threshold] = 1.0
        signal[vix < 12] = -0.5
        signal[(vix >= 12) & (vix <= threshold)] = np.clip(
            zscore[(vix >= 12) & (vix <= threshold)] * 0.2, -1.0, 1.0
        )

        return signal.fillna(0.0)

    def dollar_strength_signal(self, dxy: pd.Series) -> pd.Series:
        """
        DXY (Dollar Index) trends signal.

        Strong dollar = bearish for gold
        Weak dollar = bullish for gold
        """
        threshold = self.config.dollar_threshold

        dxy_change = dxy.pct_change(20)

        zscore_window = self.config.zscore_window
        rolling_mean = dxy_change.rolling(zscore_window, min_periods=20).mean()
        rolling_std = dxy_change.rolling(zscore_window, min_periods=20).std()
        rolling_std = rolling_std.replace(0, 1.0)
        zscore = (dxy_change - rolling_mean) / rolling_std

        signal = pd.Series(0.0, index=dxy.index)
        signal[dxy > threshold] = -0.75
        signal[dxy < 95] = 0.5
        signal[(dxy >= 95) & (dxy <= threshold)] = np.clip(
            -(dxy[(dxy >= 95) & (dxy <= threshold)] - 100) / 10.0, -1.0, 1.0
        )

        return signal.fillna(0.0)

    def risk_off_signal(
        self,
        vix: pd.Series,
        ten_year: pd.Series,
        dxy: pd.Series,
    ) -> pd.Series:
        """
        Risk-on/risk-off regime signal.

        Risk-off: High VIX, falling stocks, strong USD, flight to safety
        Risk-on: Low VIX, rising stocks, weak USD
        """
        vix_norm = (vix - vix.rolling(252, min_periods=20).mean()) / vix.rolling(
            252, min_periods=20
        ).std()
        dxy_norm = (dxy - dxy.rolling(252, min_periods=20).mean()) / dxy.rolling(
            252, min_periods=20
        ).std()

        risk_score = vix_norm * 0.5 + dxy_norm * 0.3 - ten_year.pct_change(20) * 0.2

        signal = np.clip(risk_score, -1.0, 1.0)

        return pd.Series(signal, index=vix.index).fillna(0.0)

    # ========================================================================
    # Signal Generation
    # ========================================================================

    def generate_all_signals(
        self,
        start_date: str,
        end_date: str,
    ) -> SignalPortfolio:
        """
        Generate all signals for the specified period.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            SignalPortfolio with all generated signals
        """
        data = self.load_data(start_date, end_date)

        if data.empty:
            logger.warning("No data loaded, returning empty signal portfolio")
            return SignalPortfolio()

        portfolio = SignalPortfolio()

        for idx in data.index:
            idx_date = idx.date() if isinstance(idx, (pd.Timestamp, datetime)) else idx
            signals_for_date = []

            # Interest Rate Signals
            if "DFII10" in data.columns and "DGS10" in data.columns:
                val = data.loc[idx]
                try:
                    ry_signal = self.real_yield_signal(val["DFII10"], val["DGS10"])
                    if idx in ry_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="real_yield",
                                value=float(ry_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if ry_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if ry_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(ry_signal.loc[idx])),
                                category=SignalCategory.INTEREST_RATE,
                                details={
                                    "tips": float(val.get("DFII10", 0)),
                                    "nominal": float(val.get("DGS10", 0)),
                                },
                            )
                        )
                except Exception as e:
                    logger.debug(f"real_yield signal error: {e}")

            if "FEDFUNDS" in data.columns:
                try:
                    val = data.loc[idx]
                    ff_signal = self.fed_funds_signal(val["FEDFUNDS"])
                    if idx in ff_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="fed_funds",
                                value=float(ff_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if ff_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if ff_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(ff_signal.loc[idx])),
                                category=SignalCategory.INTEREST_RATE,
                                details={"rate": float(val.get("FEDFUNDS", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"fed_funds signal error: {e}")

            if "DGS10" in data.columns and "DGS2" in data.columns:
                try:
                    val = data.loc[idx]
                    yc_signal = self.yield_curve_signal(val["DGS10"], val["DGS2"])
                    if idx in yc_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="yield_curve",
                                value=float(yc_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if yc_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if yc_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(yc_signal.loc[idx])),
                                category=SignalCategory.INTEREST_RATE,
                                details={"spread": float(val.get("DGS10", 0) - val.get("DGS2", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"yield_curve signal error: {e}")

            if "DGS10" in data.columns and "FEDFUNDS" in data.columns:
                try:
                    val = data.loc[idx]
                    tp_signal = self.term_premium_signal(val["DGS10"], val["FEDFUNDS"])
                    if idx in tp_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="term_premium",
                                value=float(tp_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if tp_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if tp_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(tp_signal.loc[idx])),
                                category=SignalCategory.INTEREST_RATE,
                                details={
                                    "premium": float(val.get("DGS10", 0) - val.get("FEDFUNDS", 0))
                                },
                            )
                        )
                except Exception as e:
                    logger.debug(f"term_premium signal error: {e}")

            # Money Supply Signals
            if "M2SL" in data.columns:
                try:
                    val = data.loc[idx]
                    m2_signal = self.m2_growth_signal(val["M2SL"])
                    if idx in m2_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="m2_growth",
                                value=float(m2_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if m2_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if m2_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(m2_signal.loc[idx])),
                                category=SignalCategory.MONEY_SUPPLY,
                                details={"m2": float(val.get("M2SL", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"m2_growth signal error: {e}")

            if "M2SL" in data.columns and "M2V" in data.columns:
                try:
                    val = data.loc[idx]
                    mv_signal = self.m2_velocity_signal(val["M2SL"], val["M2V"])
                    if idx in mv_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="m2_velocity",
                                value=float(mv_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if mv_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if mv_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(mv_signal.loc[idx])),
                                category=SignalCategory.MONEY_SUPPLY,
                                details={"velocity": float(val.get("M2V", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"m2_velocity signal error: {e}")

            if "M2SL" in data.columns:
                try:
                    val = data.loc[idx]
                    mp_signal = self.money_printing_signal(val["M2SL"])
                    if idx in mp_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="money_printing",
                                value=float(mp_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if mp_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if mp_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(mp_signal.loc[idx])),
                                category=SignalCategory.MONEY_SUPPLY,
                                details={},
                            )
                        )
                except Exception as e:
                    logger.debug(f"money_printing signal error: {e}")

            # Inflation Signals
            if "CPIAUCSL" in data.columns:
                try:
                    val = data.loc[idx]
                    ia_signal = self.inflation_acceleration_signal(val["CPIAUCSL"])
                    if idx in ia_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="inflation_acceleration",
                                value=float(ia_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if ia_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if ia_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(ia_signal.loc[idx])),
                                category=SignalCategory.INFLATION,
                                details={"cpi": float(val.get("CPIAUCSL", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"inflation_acceleration signal error: {e}")

            if "DGS10" in data.columns and "CPIAUCSL" in data.columns:
                try:
                    val = data.loc[idx]
                    ri_signal = self.real_inflation_signal(val["DGS10"], val["CPIAUCSL"])
                    if idx in ri_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="real_inflation",
                                value=float(ri_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if ri_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if ri_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(ri_signal.loc[idx])),
                                category=SignalCategory.INFLATION,
                                details={},
                            )
                        )
                except Exception as e:
                    logger.debug(f"real_inflation signal error: {e}")

            if "BEILAST" in data.columns:
                try:
                    val = data.loc[idx]
                    ie_signal = self.inflation_expectation_signal(val["BEILAST"])
                    if idx in ie_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="inflation_expectation",
                                value=float(ie_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if ie_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if ie_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(ie_signal.loc[idx])),
                                category=SignalCategory.INFLATION,
                                details={"breakeven": float(val.get("BEILAST", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"inflation_expectation signal error: {e}")

            # Employment Signals
            if "PAYEMS" in data.columns:
                try:
                    val = data.loc[idx]
                    emp_signal = self.employment_signal(val["PAYEMS"])
                    if idx in emp_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="employment",
                                value=float(emp_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if emp_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if emp_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(emp_signal.loc[idx])),
                                category=SignalCategory.EMPLOYMENT,
                                details={"payrolls": float(val.get("PAYEMS", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"employment signal error: {e}")

            if "AHISE" in data.columns:
                try:
                    val = data.loc[idx]
                    wg_signal = self.wage_growth_signal(val["AHISE"])
                    if idx in wg_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="wage_growth",
                                value=float(wg_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if wg_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if wg_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(wg_signal.loc[idx])),
                                category=SignalCategory.EMPLOYMENT,
                                details={"wages": float(val.get("AHISE", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"wage_growth signal error: {e}")

            if "LBSSA" in data.columns:
                try:
                    val = data.loc[idx]
                    lf_signal = self.labor_force_signal(val["LBSSA"])
                    if idx in lf_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="labor_force",
                                value=float(lf_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if lf_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if lf_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(lf_signal.loc[idx])),
                                category=SignalCategory.EMPLOYMENT,
                                details={"participation": float(val.get("LBSSA", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"labor_force signal error: {e}")

            # Market Signals
            if "VIXCLS" in data.columns:
                try:
                    val = data.loc[idx]
                    vix_signal = self.vix_spike_signal(val["VIXCLS"])
                    if idx in vix_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="vix_spike",
                                value=float(vix_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if vix_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if vix_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(vix_signal.loc[idx])),
                                category=SignalCategory.MARKET,
                                details={"vix": float(val.get("VIXCLS", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"vix_spike signal error: {e}")

            if "DTINYUS" in data.columns:
                try:
                    val = data.loc[idx]
                    dxy_signal = self.dollar_strength_signal(val["DTINYUS"])
                    if idx in dxy_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="dollar_strength",
                                value=float(dxy_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if dxy_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if dxy_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(dxy_signal.loc[idx])),
                                category=SignalCategory.MARKET,
                                details={"dxy": float(val.get("DTINYUS", 0))},
                            )
                        )
                except Exception as e:
                    logger.debug(f"dollar_strength signal error: {e}")

            if "VIXCLS" in data.columns and "DGS10" in data.columns and "DTINYUS" in data.columns:
                try:
                    val = data.loc[idx]
                    ro_signal = self.risk_off_signal(val["VIXCLS"], val["DGS10"], val["DTINYUS"])
                    if idx in ro_signal.index:
                        signals_for_date.append(
                            Signal(
                                date=idx_date,
                                name="risk_off",
                                value=float(ro_signal.loc[idx]),
                                direction=SignalDirection.BULLISH
                                if ro_signal.loc[idx] > 0
                                else SignalDirection.BEARISH
                                if ro_signal.loc[idx] < 0
                                else SignalDirection.NEUTRAL,
                                strength=abs(float(ro_signal.loc[idx])),
                                category=SignalCategory.MARKET,
                                details={},
                            )
                        )
                except Exception as e:
                    logger.debug(f"risk_off signal error: {e}")

            for signal in signals_for_date:
                portfolio.add_signal(signal)

        return portfolio

    def combine_signals(
        self,
        portfolio: SignalPortfolio,
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        Combine signals into composite signals by category.

        Args:
            portfolio: SignalPortfolio with signals
            weights: Optional weights for each category

        Returns:
            DataFrame with combined signals per category
        """
        if weights is None:
            weights = self.config.weights

        df = portfolio.to_dataframe()

        if df.empty:
            return pd.DataFrame()

        categories = df["category"].unique()
        combined = pd.DataFrame(index=df.index.unique())

        for cat in categories:
            cat_df = df[df["category"] == cat]
            if not cat_df.empty:
                combined[cat] = cat_df.groupby("date")["value"].mean()

        weights_series = pd.Series(weights)
        available_cats = [c for c in weights_series.index if c in combined.columns]

        if available_cats:
            combined["composite"] = sum(
                combined[cat] * weights_series[cat] for cat in available_cats
            ) / sum(weights_series[cat] for cat in available_cats)

        return combined.ffill().fillna(0)

    def normalize_signals(self, signals: pd.Series) -> pd.Series:
        """
        Normalize signals to -1 to 1 scale using rolling z-score.

        Args:
            signals: Raw signal series

        Returns:
            Normalized signals in -1 to 1 range
        """
        window = self.config.zscore_window

        rolling_mean = signals.rolling(window, min_periods=20).mean()
        rolling_std = signals.rolling(window, min_periods=20).std()
        rolling_std = rolling_std.replace(0, 1.0)

        zscore = (signals - rolling_mean) / rolling_std

        normalized = np.clip(zscore, -1.0, 1.0)

        return pd.Series(normalized, index=signals.index).fillna(0.0)

    # ========================================================================
    # XAUUSD-Specific Signals
    # ========================================================================

    def gold_macro_signal(
        self,
        portfolio: SignalPortfolio,
    ) -> pd.Series:
        """
        Combined macro signal for XAUUSD.

        Args:
            portfolio: SignalPortfolio with all signals

        Returns:
            Series with combined gold macro signal
        """
        combined = self.combine_signals(portfolio)

        if "composite" in combined.columns:
            return combined["composite"]

        return pd.Series(0.0)

    def gold_valuation_signal(
        self,
        data: pd.DataFrame,
    ) -> pd.Series:
        """
        Fair value estimate for gold based on fundamentals.

        Considers: real yields, inflation, dollar
        """
        signals = {}

        if "DFII10" in data.columns and "DGS10" in data.columns:
            real_yield = data["DGS10"] - data["DFII10"]
            signals["real_yield_fair"] = -real_yield / 2.0

        if "DTINYUS" in data.columns:
            dollar = data["DTINYUS"]
            signals["dollar_fair"] = -(dollar - 100) / 20.0

        if "CPIAUCSL" in data.columns:
            cpi_change = data["CPIAUCSL"].pct_change(12)
            signals["inflation_fair"] = cpi_change / 2.0

        if not signals:
            return pd.Series(0.0, index=data.index)

        combined = pd.DataFrame(signals).mean(axis=1)

        return np.clip(combined, -1.0, 1.0)

    def gold_momentum_signal(
        self,
        portfolio: SignalPortfolio,
    ) -> pd.Series:
        """
        Momentum signal from macro factors.

        Uses weighted combination of strongest category signals.
        """
        df = portfolio.to_dataframe()

        if df.empty:
            return pd.DataFrame()

        weights = {
            "inflation": 0.35,
            "interest_rate": 0.30,
            "money_supply": 0.20,
            "market": 0.15,
        }

        momentum = pd.Series(0.0, index=df.index.unique())

        for cat, weight in weights.items():
            cat_signals = df[df["category"] == cat]
            if not cat_signals.empty:
                cat_mean = cat_signals.groupby("date")["value"].mean()
                momentum = momentum.add(cat_mean * weight, fill_value=0)

        return momentum.fillna(0.0)


def create_signals_table() -> str:
    """
    SQL to create the macro_signals table in the database.

    Returns:
        SQL CREATE TABLE statement
    """
    return """
    CREATE TABLE IF NOT EXISTS macro_signals (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        name VARCHAR(100) NOT NULL,
        value DOUBLE PRECISION NOT NULL,
        direction VARCHAR(20) NOT NULL,
        strength DOUBLE PRECISION NOT NULL,
        category VARCHAR(50) NOT NULL,
        details JSONB,
        generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(date, name)
    );
    
    CREATE INDEX IF NOT EXISTS idx_macro_signals_date ON macro_signals(date);
    CREATE INDEX IF NOT EXISTS idx_macro_signals_category ON macro_signals(category);
    CREATE INDEX IF NOT EXISTS idx_macro_signals_name ON macro_signals(name);
    """


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    if len(sys.argv) > 1 and sys.argv[1] == "--create-table":
        print(create_signals_table())
    else:
        print("Macro Fundamental Signals Module")
        print("=" * 50)
        print("Usage:")
        print("  python fred_signals.py --create-table  # Print SQL to create table")
        print("")
        print("Example:")
        print("  from quantfund.strategies.fred_signals import MacroFundamentalSignals")
        print("  signals = MacroFundamentalSignals()")
        print("  portfolio = signals.generate_all_signals('2023-01-01', '2024-01-01')")
        print("  df = portfolio.to_dataframe()")
