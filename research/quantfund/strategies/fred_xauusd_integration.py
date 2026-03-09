"""
FRED-XAUUSD Integration Module
===============================
Bridge between FRED macro signals and XAUUSD trading engine.

Features:
- Signal loading from database
- Signal processing for gold trading
- Trading signal generation with risk management
- Real-time signal provider
- Integration with existing signal_store

Usage:
    from quantfund.strategies.fred_xauusd_integration import FredXauusdIntegration

    integration = FredXauusdIntegration()
    signal = integration.generate_trading_signal()
    position = integration.calculate_position_size(signal)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TradingSignal(Enum):
    """Trading signal enumeration."""

    BUY = 1
    SELL = -1
    HOLD = 0


class MarketRegime(Enum):
    """Market regime enumeration for gold."""

    RATES_DRIVEN = "rates_driven"
    RISK_OFF = "risk_off"
    DOLLAR_DRIVEN = "dollar_driven"
    MOMENTUM = "momentum"
    NEUTRAL = "neutral"


@dataclass
class XauusdSignal:
    """XAUUSD trading signal output."""

    signal_date: date
    signal: TradingSignal
    strength: float
    confidence: float
    composite_value: float
    regime: MarketRegime
    position_size: float = 0.0
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    contributing_signals: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "signal_date": self.signal_date.isoformat()
            if isinstance(self.signal_date, date)
            else self.signal_date,
            "signal": self.signal.name,
            "strength": self.strength,
            "confidence": self.confidence,
            "composite_value": self.composite_value,
            "regime": self.regime.value,
            "position_size": self.position_size,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward_ratio": self.risk_reward_ratio,
            "metadata": self.metadata,
            "contributing_signals": self.contributing_signals,
            "generated_at": self.generated_at.isoformat()
            if isinstance(self.generated_at, datetime)
            else self.generated_at,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class SignalMetadata:
    """Metadata for signals."""

    signal_name: str
    source: str
    asset: str = "XAUUSD"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    total_signals: int = 0
    avg_strength: float = 0.0
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0


class FredXauusdIntegration:
    """
    Main integration module for FRED signals to XAUUSD trading.

    Provides signal loading, processing, and conversion to actionable
    trading signals for the XAUUSD trading engine.
    """

    DEFAULT_SIGNAL_WEIGHTS: Dict[str, float] = field(
        default_factory=lambda: {
            "real_yield": 0.20,
            "fed_funds": 0.10,
            "yield_curve": 0.08,
            "term_premium": 0.07,
            "m2_growth": 0.12,
            "m2_velocity": 0.05,
            "money_printing": 0.08,
            "inflation_acceleration": 0.10,
            "real_inflation": 0.08,
            "inflation_expectation": 0.07,
            "employment": 0.05,
            "wage_growth": 0.04,
            "labor_force": 0.02,
            "vix_spike": 0.05,
            "dollar_strength": 0.08,
            "risk_off": 0.08,
        }
    )

    def __init__(
        self,
        connection_string: Optional[str] = None,
        max_position_pct: float = 0.10,
        risk_per_trade_pct: float = 0.02,
    ):
        """
        Initialize FRED-XAUUSD integration.

        Args:
            connection_string: Database connection string
            max_position_pct: Maximum position size as percentage of capital
            risk_per_trade_pct: Risk per trade as percentage of capital
        """
        self._connection_string = connection_string
        self._signal_store = None
        self._fred_signals = None
        self._regime_detector = None
        self.max_position_pct = max_position_pct
        self.risk_per_trade_pct = risk_per_trade_pct

    @property
    def signal_store(self):
        """Get or create signal store."""
        if self._signal_store is None and self._connection_string:
            from quantfund.strategies.signal_store import SignalStore

            self._signal_store = SignalStore(self._connection_string)
        return self._signal_store

    @property
    def fred_signals(self):
        """Get or create FRED signals generator."""
        if self._fred_signals is None:
            from quantfund.strategies.fred_signals import MacroFundamentalSignals

            self._fred_signals = MacroFundamentalSignals()
        return self._fred_signals

    @property
    def regime_detector(self):
        """Get or create regime detector."""
        if self._regime_detector is None:
            from quantfund.assets.xauusd.regime.detector import GoldRegimeDetector

            self._regime_detector = GoldRegimeDetector()
        return self._regime_detector

    def load_signals_from_db(
        self,
        start_date: Optional[Union[str, date]] = None,
        end_date: Optional[Union[str, date]] = None,
        signal_names: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Load FRED signals from database.

        Args:
            start_date: Start date for signals
            end_date: End date for signals
            signal_names: Optional list of signal names to filter

        Returns:
            DataFrame of signals
        """
        if self.signal_store is None:
            logger.warning("Signal store not available")
            return pd.DataFrame()

        if isinstance(start_date, str):
            start_date = pd.to_datetime(start_date).date()
        if isinstance(end_date, str):
            end_date = pd.to_datetime(end_date).date()

        from quantfund.strategies.signal_store import SignalQuery

        query = SignalQuery(
            start_date=start_date,
            end_date=end_date,
            asset="XAUUSD",
        )

        signals = self.signal_store.get_signals(query)

        if signal_names and not signals.empty:
            signals = signals[signals["definition_name"].isin(signal_names)]

        return signals

    def load_latest_signals(
        self,
        days: int = 7,
    ) -> pd.DataFrame:
        """
        Get most recent signals.

        Args:
            days: Number of days to look back

        Returns:
            DataFrame of recent signals
        """
        if self.signal_store is None:
            logger.warning("Signal store not available")
            return pd.DataFrame()

        return self.signal_store.get_recent_signals(
            days=days,
            asset="XAUUSD",
        )

    def load_signals_by_date(
        self,
        signal_date: Union[str, date],
    ) -> pd.DataFrame:
        """
        Get signals for specific date.

        Args:
            signal_date: Date to load signals for

        Returns:
            DataFrame of signals for the date
        """
        if isinstance(signal_date, str):
            signal_date = pd.to_datetime(signal_date).date()

        return self.load_signals_from_db(
            start_date=signal_date,
            end_date=signal_date,
        )

    def load_signals_by_type(
        self,
        signal_type: str,
        start_date: Optional[Union[str, date]] = None,
        end_date: Optional[Union[str, date]] = None,
    ) -> pd.DataFrame:
        """
        Filter signals by type.

        Args:
            signal_type: Signal type to filter
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            DataFrame of filtered signals
        """
        if self.signal_store is None:
            logger.warning("Signal store not available")
            return pd.DataFrame()

        if isinstance(start_date, str):
            start_date = pd.to_datetime(start_date).date()
        if isinstance(end_date, str):
            end_date = pd.to_datetime(end_date).date()

        from quantfund.strategies.signal_store import SignalQuery, SignalType

        query = SignalQuery(
            signal_type=SignalType(signal_type),
            start_date=start_date,
            end_date=end_date,
            asset="XAUUSD",
        )

        return self.signal_store.get_signals(query)

    def process_signals_for_xauusd(
        self,
        signals: pd.DataFrame,
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        Process signals for gold trading.

        Args:
            signals: DataFrame of raw signals
            weights: Optional weights for signal combination

        Returns:
            Processed signals DataFrame
        """
        if signals.empty:
            return pd.DataFrame()

        if weights is None:
            weights = self.DEFAULT_SIGNAL_WEIGHTS

        processed = signals.copy()

        if "value" not in processed.columns:
            return pd.DataFrame()

        processed = processed.sort_values("signal_date")

        weight_series = processed["definition_name"].map(weights).fillna(0.5)

        processed["weighted_value"] = processed["value"] * weight_series
        processed["weight"] = weight_series

        return processed

    def aggregate_signals(
        self,
        signals: pd.DataFrame,
        method: str = "weighted",
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        Combine multiple signals into composite.

        Args:
            signals: DataFrame of signals
            method: Aggregation method ('mean', 'weighted', 'median')
            weights: Optional weights for each signal

        Returns:
            Aggregated signals DataFrame
        """
        if signals.empty:
            return pd.DataFrame()

        if weights is None:
            weights = self.DEFAULT_SIGNAL_WEIGHTS

        processed = self.process_signals_for_xauusd(signals, weights)

        if processed.empty:
            return pd.DataFrame()

        if method == "weighted":
            grouped = processed.groupby("signal_date")
            aggregated = grouped.agg(
                {
                    "weighted_value": "sum",
                    "weight": "sum",
                    "value": "count",
                }
            ).reset_index()
            aggregated["composite"] = aggregated["weighted_value"] / aggregated["weight"].replace(
                0, 1
            )
            aggregated = aggregated.rename(columns={"value": "signal_count"})
        elif method == "mean":
            grouped = processed.groupby("signal_date")
            aggregated = grouped["value"].mean().reset_index()
            aggregated.columns = ["signal_date", "composite"]
            aggregated["signal_count"] = grouped.size().values
        elif method == "median":
            grouped = processed.groupby("signal_date")
            aggregated = grouped["value"].median().reset_index()
            aggregated.columns = ["signal_date", "composite"]
            aggregated["signal_count"] = grouped.size().values
        else:
            raise ValueError(f"Unknown aggregation method: {method}")

        return aggregated

    def normalize_signals(
        self,
        signals: Union[pd.Series, pd.DataFrame],
        method: str = "clamp",
    ) -> Union[pd.Series, pd.DataFrame]:
        """
        Normalize signals to trading signals (-1, 0, 1).

        Args:
            signals: Signal series or DataFrame
            method: Normalization method ('clamp', 'zscore', 'rank')

        Returns:
            Normalized signals
        """
        if isinstance(signals, pd.DataFrame):
            result = signals.copy()
            if "composite" in result.columns:
                result["composite_normalized"] = self.normalize_signals(result["composite"], method)
            return result

        if signals.empty:
            return signals

        if method == "clamp":
            normalized = np.clip(signals, -1.0, 1.0)
        elif method == "zscore":
            mean = signals.mean()
            std = signals.std()
            if std > 0:
                zscore = (signals - mean) / std
                normalized = np.clip(zscore, -1.0, 1.0)
            else:
                normalized = signals * 0
        elif method == "rank":
            rank = signals.rank(pct=True)
            normalized = (rank - 0.5) * 2
        else:
            normalized = signals

        return normalized

    def gold_macro_bias(
        self,
        signals: pd.DataFrame,
    ) -> float:
        """
        Calculate overall macro bias for gold.

        Args:
            signals: DataFrame of signals

        Returns:
            Macro bias value (-1 to 1)
        """
        if signals.empty:
            return 0.0

        processed = self.process_signals_for_xauusd(signals)

        if processed.empty:
            return 0.0

        bias = (
            processed["weighted_value"].sum() / processed["weight"].sum()
            if processed["weight"].sum() > 0
            else 0.0
        )

        return float(np.clip(bias, -1.0, 1.0))

    def gold_signal_composite(
        self,
        signals: pd.DataFrame,
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.Series:
        """
        Create composite signal combining all factors.

        Args:
            signals: DataFrame of signals
            weights: Optional weights for each signal

        Returns:
            Composite signal series
        """
        if signals.empty:
            return pd.Series()

        aggregated = self.aggregate_signals(signals, method="weighted", weights=weights)

        if aggregated.empty:
            return pd.Series()

        return aggregated.set_index("signal_date")["composite"]

    def gold_regime_adjustment(
        self,
        composite_value: float,
        regime: MarketRegime,
    ) -> float:
        """
        Adjust signal based on market regime.

        Args:
            composite_value: Raw composite signal
            regime: Current market regime

        Returns:
            Regime-adjusted signal
        """
        regime_modifiers = {
            MarketRegime.RATES_DRIVEN: 1.0,
            MarketRegime.RISK_OFF: 1.2,
            MarketRegime.DOLLAR_DRIVEN: 0.9,
            MarketRegime.MOMENTUM: 1.1,
            MarketRegime.NEUTRAL: 0.8,
        }

        modifier = regime_modifiers.get(regime, 1.0)
        adjusted = composite_value * modifier

        return float(np.clip(adjusted, -1.0, 1.0))

    def generate_trading_signal(
        self,
        signals: Optional[pd.DataFrame] = None,
        signal_date: Optional[Union[str, date]] = None,
    ) -> XauusdSignal:
        """
        Generate actionable trading signal.

        Args:
            signals: Optional pre-loaded signals
            signal_date: Date for the signal

        Returns:
            XauusdSignal with trading recommendation
        """
        if signals is None:
            signals = self.load_latest_signals(days=30)

        if signals.empty:
            return XauusdSignal(
                signal_date=date.today()
                if signal_date is None
                else (
                    pd.to_datetime(signal_date).date()
                    if isinstance(signal_date, str)
                    else signal_date
                ),
                signal=TradingSignal.HOLD,
                strength=0.0,
                confidence=0.0,
                composite_value=0.0,
                regime=MarketRegime.NEUTRAL,
                metadata={"error": "No signals available"},
            )

        if signal_date is None:
            signal_date = signals["signal_date"].max()
        elif isinstance(signal_date, str):
            signal_date = pd.to_datetime(signal_date).date()

        signals_on_date = signals[signals["signal_date"] == signal_date]

        if signals_on_date.empty:
            latest_date = signals["signal_date"].max()
            signals_on_date = signals[signals["signal_date"] == latest_date]
            signal_date = latest_date

        composite = self.gold_signal_composite(signals_on_date)

        if composite.empty:
            composite_value = signals_on_date["value"].mean()
        else:
            composite_value = composite.iloc[-1] if len(composite) > 0 else 0.0

        regime = self._detect_regime(signals_on_date)

        adjusted_value = self.gold_regime_adjustment(composite_value, regime)

        normalized = self.normalize_signals(pd.Series([adjusted_value]), "clamp").iloc[0]

        signal = self._value_to_trading_signal(normalized)

        strength = min(abs(normalized), 1.0)
        confidence = self._calculate_confidence(signals_on_date)

        xauusd_signal = XauusdSignal(
            signal_date=signal_date,
            signal=signal,
            strength=strength,
            confidence=confidence,
            composite_value=adjusted_value,
            regime=regime,
            contributing_signals=signals_on_date["definition_name"].unique().tolist(),
            metadata={
                "raw_composite": composite_value,
                "normalized": normalized,
                "regime_modifier": self._get_regime_modifier(regime),
            },
        )

        return xauusd_signal

    def _detect_regime(self, signals: pd.DataFrame) -> MarketRegime:
        """
        Detect current market regime.

        Args:
            signals: DataFrame of signals

        Returns:
            MarketRegime enum value
        """
        if signals.empty:
            return MarketRegime.NEUTRAL

        signal_names = signals["definition_name"].unique().tolist()

        risk_off_signals = ["risk_off", "vix_spike"]
        dollar_signals = ["dollar_strength"]
        rate_signals = ["real_yield", "fed_funds", "yield_curve"]
        momentum_signals = ["momentum"]

        risk_off_score = sum(1 for s in signal_names if s in risk_off_signals)
        dollar_score = sum(1 for s in signal_names if s in dollar_signals)
        rate_score = sum(1 for s in signal_names if s in rate_signals)
        momentum_score = sum(1 for s in signal_names if s in momentum_signals)

        scores = {
            MarketRegime.RISK_OFF: risk_off_score,
            MarketRegime.DOLLAR_DRIVEN: dollar_score,
            MarketRegime.RATES_DRIVEN: rate_score,
            MarketRegime.MOMENTUM: momentum_score,
        }

        max_score = max(scores.values())

        if max_score == 0:
            return MarketRegime.NEUTRAL

        return max(scores, key=scores.get)

    def _get_regime_modifier(self, regime: MarketRegime) -> float:
        """Get regime modifier value."""
        modifiers = {
            MarketRegime.RATES_DRIVEN: 1.0,
            MarketRegime.RISK_OFF: 1.2,
            MarketRegime.DOLLAR_DRIVEN: 0.9,
            MarketRegime.MOMENTUM: 1.1,
            MarketRegime.NEUTRAL: 0.8,
        }
        return modifiers.get(regime, 1.0)

    def _value_to_trading_signal(self, value: float) -> TradingSignal:
        """Convert numeric value to trading signal."""
        if value > 0.2:
            return TradingSignal.BUY
        elif value < -0.2:
            return TradingSignal.SELL
        else:
            return TradingSignal.HOLD

    def _calculate_confidence(self, signals: pd.DataFrame) -> float:
        """Calculate signal confidence based on consensus."""
        if signals.empty:
            return 0.0

        if "direction" not in signals.columns:
            return 0.5

        directions = signals["direction"].value_counts()
        total = len(signals)

        if total == 0:
            return 0.0

        max_direction_pct = (directions.max() / total) if not directions.empty else 0.0

        avg_strength = signals.get("strength", pd.Series([0.5])).mean()

        confidence = max_direction_pct * 0.6 + avg_strength * 0.4

        return float(np.clip(confidence, 0.0, 1.0))

    def calculate_position_size(
        self,
        signal: XauusdSignal,
        capital: float = 100000.0,
    ) -> float:
        """
        Calculate position size based on signal strength.

        Args:
            signal: XauusdSignal
            capital: Trading capital

        Returns:
            Position size as fraction of capital
        """
        if signal.signal == TradingSignal.HOLD:
            return 0.0

        base_size = signal.strength * self.max_position_pct

        confidence_factor = signal.confidence

        adjusted_size = base_size * confidence_factor

        final_size = min(adjusted_size, self.max_position_pct)

        return float(np.clip(final_size, 0, self.max_position_pct))

    def apply_risk_filters(
        self,
        signal: XauusdSignal,
        portfolio_risk: float = 0.0,
        max_drawdown: float = 0.0,
    ) -> XauusdSignal:
        """
        Apply risk management filters.

        Args:
            signal: Input signal
            portfolio_risk: Current portfolio risk exposure
            max_drawdown: Current max drawdown

        Returns:
            Filtered signal with adjusted position
        """
        filtered = signal

        if portfolio_risk > 0.8:
            filtered.signal = TradingSignal.HOLD
            filtered.position_size = 0.0
            filtered.metadata["risk_filter"] = "portfolio_risk_exceeded"
            return filtered

        if max_drawdown > 0.20:
            reduced_size = filtered.position_size * 0.5
            filtered.position_size = reduced_size
            filtered.metadata["risk_filter"] = "max_drawdown_reduced"

        if signal.confidence < 0.3:
            reduced_size = filtered.position_size * 0.5
            filtered.position_size = reduced_size
            filtered.metadata["risk_filter"] = "low_confidence_reduced"

        return filtered

    def get_signal_for_engine(
        self,
        signal: Optional[XauusdSignal] = None,
    ) -> Dict[str, Any]:
        """
        Get formatted signal for trading engine.

        Args:
            signal: Optional pre-generated signal

        Returns:
            Dictionary formatted for trading engine
        """
        if signal is None:
            signal = self.generate_trading_signal()

        return {
            "action": signal.signal.name,
            "symbol": "XAUUSD",
            "signal_date": signal.signal_date.isoformat(),
            "strength": signal.strength,
            "confidence": signal.confidence,
            "position_pct": signal.position_size,
            "regime": signal.regime.value,
            "stop_loss_pct": self._get_stop_loss_pct(signal),
            "take_profit_pct": self._get_take_profit_pct(signal),
            "metadata": signal.metadata,
        }

    def _get_stop_loss_pct(self, signal: XauusdSignal) -> float:
        """Get stop loss percentage based on regime."""
        regime_stops = {
            MarketRegime.RATES_DRIVEN: 0.025,
            MarketRegime.RISK_OFF: 0.035,
            MarketRegime.DOLLAR_DRIVEN: 0.030,
            MarketRegime.MOMENTUM: 0.040,
            MarketRegime.NEUTRAL: 0.025,
        }
        return regime_stops.get(signal.regime, 0.025)

    def _get_take_profit_pct(self, signal: XauusdSignal) -> float:
        """Get take profit percentage based on regime."""
        regime_tps = {
            MarketRegime.RATES_DRIVEN: 0.050,
            MarketRegime.RISK_OFF: 0.075,
            MarketRegime.DOLLAR_DRIVEN: 0.060,
            MarketRegime.MOMENTUM: 0.100,
            MarketRegime.NEUTRAL: 0.050,
        }
        return regime_tps.get(signal.regime, 0.050)

    def convert_to_xauusd_signal(
        self,
        fred_signal: Dict[str, Any],
    ) -> XauusdSignal:
        """
        Convert FRED signal to XAUUSD format.

        Args:
            fred_signal: FRED signal dictionary

        Returns:
            XauusdSignal
        """
        signal_date = fred_signal.get("signal_date", date.today())
        if isinstance(signal_date, str):
            signal_date = pd.to_datetime(signal_date).date()

        value = fred_signal.get("value", 0.0)

        if isinstance(fred_signal.get("direction"), str):
            direction = fred_signal["direction"].upper()
            if direction == "BULLISH":
                trading_signal = TradingSignal.BUY if value > 0 else TradingSignal.SELL
            elif direction == "BEARISH":
                trading_signal = TradingSignal.SELL if value < 0 else TradingSignal.BUY
            else:
                trading_signal = TradingSignal.HOLD
        else:
            trading_signal = self._value_to_trading_signal(value)

        strength = fred_signal.get("strength", abs(value))
        confidence = fred_signal.get("confidence", 0.5)

        return XauusdSignal(
            signal_date=signal_date,
            signal=trading_signal,
            strength=strength,
            confidence=confidence,
            composite_value=value,
            regime=MarketRegime.NEUTRAL,
            metadata=fred_signal.get("metadata", {}),
        )


class SignalProvider:
    """
    Real-time signal provider for XAUUSD trading.

    Provides subscriptions to signal updates for integration
    with trading engines and Tauri commands.
    """

    def __init__(
        self,
        integration: Optional[FredXauusdIntegration] = None,
        update_interval_seconds: int = 300,
    ):
        """
        Initialize signal provider.

        Args:
            integration: FredXauusdIntegration instance
            update_interval_seconds: How often to check for new signals
        """
        self._integration = integration or FredXauusdIntegration()
        self._update_interval = update_interval_seconds
        self._subscribers: List[Callable[[XauusdSignal], None]] = []
        self._current_signal: Optional[XauusdSignal] = None
        self._last_update: Optional[datetime] = None

    def get_current_signal(self) -> XauusdSignal:
        """
        Get current trading signal.

        Returns:
            Current XauusdSignal
        """
        self._current_signal = self._integration.generate_trading_signal()
        self._last_update = datetime.now()

        if self._current_signal.position_size == 0:
            self._current_signal.position_size = self._integration.calculate_position_size(
                self._current_signal
            )

        return self._current_signal

    def subscribe_to_signals(
        self,
        callback: Callable[[XauusdSignal], None],
    ) -> None:
        """
        Subscribe to signal updates.

        Args:
            callback: Function to call on signal updates
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe_from_signals(
        self,
        callback: Callable[[XauusdSignal], None],
    ) -> None:
        """
        Unsubscribe from signal updates.

        Args:
            callback: Callback to remove
        """
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def notify_subscribers(self) -> None:
        """Notify all subscribers of current signal."""
        if self._current_signal is None:
            self.get_current_signal()

        for callback in self._subscribers:
            try:
                callback(self._current_signal)
            except Exception as e:
                logger.error(f"Error notifying subscriber: {e}")

    def get_signals_history(
        self,
        days: int = 30,
    ) -> pd.DataFrame:
        """
        Get historical signals.

        Args:
            days: Number of days of history

        Returns:
            DataFrame of historical signals
        """
        signals = self._integration.load_latest_signals(days=days)

        if signals.empty:
            return pd.DataFrame()

        result = []
        for signal_date in signals["signal_date"].unique():
            date_signals = signals[signals["signal_date"] == signal_date]
            trading_signal = self._integration.generate_trading_signal(
                signals=date_signals,
                signal_date=signal_date,
            )
            result.append(trading_signal.to_dict())

        return pd.DataFrame(result)

    def export_signals_json(
        self,
        signals: Optional[pd.DataFrame] = None,
        filepath: Optional[str] = None,
    ) -> str:
        """
        Export signals to JSON.

        Args:
            signals: DataFrame of signals
            filepath: Optional file path

        Returns:
            JSON string
        """
        if signals is None:
            signals = self.get_signals_history()

        if signals.empty:
            return "[]"

        json_data = signals.to_json(orient="records", date_format="iso")

        if filepath:
            with open(filepath, "w") as f:
                f.write(json_data)
            logger.info(f"Exported signals to {filepath}")

        return json_data


def create_integration(
    connection_string: Optional[str] = None,
) -> FredXauusdIntegration:
    """
    Factory function to create FredXauusdIntegration.

    Args:
        connection_string: Database connection string

    Returns:
        Configured FredXauusdIntegration instance
    """
    return FredXauusdIntegration(connection_string=connection_string)


def create_signal_provider(
    connection_string: Optional[str] = None,
) -> SignalProvider:
    """
    Factory function to create SignalProvider.

    Args:
        connection_string: Database connection string

    Returns:
        Configured SignalProvider instance
    """
    integration = create_integration(connection_string)
    return SignalProvider(integration=integration)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    print("FRED-XAUUSD Integration Module")
    print("=" * 50)
    print("Usage:")
    print("  from quantfund.strategies.fred_xauusd_integration import FredXauusdIntegration")
    print("")
    print("  integration = FredXauusdIntegration()")
    print("  signal = integration.generate_trading_signal()")
    print("  print(signal.to_json())")
