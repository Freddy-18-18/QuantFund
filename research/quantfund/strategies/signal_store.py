"""
Signal Store Module
===================
Central repository for trading signals with SQLAlchemy and PostgreSQL support.

Features:
- Signal storage and retrieval
- Feature store integration
- Signal aggregation and consensus
- Signal registry for type management
- Import/export utilities
- Signal validation

Usage:
    from quantfund.strategies.signal_store import SignalStore

    store = SignalStore("postgresql://localhost/quantfund")
    store.create_tables()

    # Save a signal
    store.save_signal(signal_data)

    # Query signals
    signals = store.get_signals_by_date_range(start_date, end_date)
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

try:
    from sqlalchemy import (
        JSON,
        BigInteger,
        Boolean,
        Column,
        Date,
        DateTime,
        Enum as SAEnum,
        Float,
        ForeignKey,
        Integer,
        String,
        Text,
        create_engine,
        text,
    )
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    Engine = None
    Session = None

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    """Signal type enumeration."""

    FUNDAMENTAL = "fundamental"
    TECHNICAL = "technical"
    ML = "ml"
    SENTIMENT = "sentiment"
    MACRO = "macro"
    VOLATILITY = "volatility"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    CROSS_ASSET = "cross_asset"
    CUSTOM = "custom"


class SignalDirection(str, Enum):
    """Signal direction enumeration."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalStrength(str, Enum):
    """Signal strength classification."""

    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


class Base(DeclarativeBase if HAS_SQLALCHEMY else object):
    """SQLAlchemy declarative base."""

    pass


if HAS_SQLALCHEMY:

    class SignalDefinition(Base):
        """Signal type definitions table."""

        __tablename__ = "signal_definitions"

        id = Column(Integer, primary_key=True, autoincrement=True)
        name = Column(String(100), unique=True, nullable=False, index=True)
        description = Column(Text, nullable=True)
        signal_type = Column(SAEnum(SignalType), nullable=False, index=True)
        asset_class = Column(String(50), nullable=True, index=True)
        parameters = Column(JSONB, nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)
        updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        is_active = Column(Boolean, default=True)

        values = relationship("SignalValue", back_populates="definition", lazy="dynamic")

    class SignalValue(Base):
        """Individual signal values table."""

        __tablename__ = "signal_values"

        id = Column(BigInteger, primary_key=True, autoincrement=True)
        definition_id = Column(
            Integer, ForeignKey("signal_definitions.id"), nullable=False, index=True
        )
        asset = Column(String(50), nullable=False, index=True)
        signal_date = Column(Date, nullable=False, index=True)
        value = Column(Float, nullable=False)
        direction = Column(SAEnum(SignalDirection), nullable=False)
        strength = Column(Float, nullable=False, default=0.5)
        confidence = Column(Float, nullable=True)
        metadata = Column(JSONB, nullable=True)
        features_used = Column(JSONB, nullable=True)
        model_version = Column(String(50), nullable=True)
        generated_at = Column(DateTime, default=datetime.utcnow, index=True)
        created_at = Column(DateTime, default=datetime.utcnow)

        definition = relationship("SignalDefinition", back_populates="values")

        __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)

    class SignalModel(Base):
        """Trained model metadata table."""

        __tablename__ = "signal_models"

        id = Column(Integer, primary_key=True, autoincrement=True)
        name = Column(String(100), unique=True, nullable=False, index=True)
        model_type = Column(String(50), nullable=False)
        signal_type = Column(SAEnum(SignalType), nullable=False, index=True)
        version = Column(String(50), nullable=False)
        description = Column(Text, nullable=True)
        hyperparameters = Column(JSONB, nullable=True)
        features = Column(JSONB, nullable=True)
        performance_metrics = Column(JSONB, nullable=True)
        trained_from = Column(Date, nullable=True)
        trained_to = Column(Date, nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)
        updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        is_active = Column(Boolean, default=True)

    class SignalPerformance(Base):
        """Signal performance tracking table."""

        __tablename__ = "signal_performance"

        id = Column(BigInteger, primary_key=True, autoincrement=True)
        signal_value_id = Column(
            BigInteger, ForeignKey("signal_value.id"), nullable=False, index=True
        )
        prediction = Column(Float, nullable=False)
        actual = Column(Float, nullable=True)
        pnl = Column(Float, nullable=True)
        returns = Column(Float, nullable=True)
        hit_rate = Column(Float, nullable=True)
        evaluation_date = Column(Date, nullable=False, index=True)
        horizon_days = Column(Integer, nullable=True)
        metadata = Column(JSONB, nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)

    class FeatureStore(Base):
        """Feature store for signal generation."""

        __tablename__ = "signal_features"

        id = Column(BigInteger, primary_key=True, autoincrement=True)
        asset = Column(String(50), nullable=False, index=True)
        feature_name = Column(String(100), nullable=False, index=True)
        feature_value = Column(Float, nullable=True)
        observation_date = Column(Date, nullable=False, index=True)
        feature_type = Column(String(50), nullable=True)
        metadata = Column(JSONB, nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)

        __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)


@dataclass
class SignalData:
    """Signal data structure."""

    definition_name: str
    asset: str
    signal_date: date
    value: float
    direction: SignalDirection
    strength: float = 0.5
    confidence: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    features_used: Optional[List[str]] = None
    model_version: Optional[str] = None


@dataclass
class SignalQuery:
    """Signal query parameters."""

    definition_name: Optional[str] = None
    signal_type: Optional[SignalType] = None
    asset: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    min_strength: Optional[float] = None
    max_strength: Optional[float] = None
    direction: Optional[SignalDirection] = None
    limit: Optional[int] = None


@dataclass
class AggregatedSignal:
    """Aggregated signal result."""

    asset: str
    signal_date: date
    aggregated_value: float
    direction: SignalDirection
    strength: float
    contributing_signals: List[str] = field(default_factory=list)
    weights: Dict[str, float] = field(default_factory=dict)
    consensus_score: float = 0.0


class SignalValidator:
    """Validator for signal data."""

    @staticmethod
    def validate_signal(signal: SignalData) -> tuple[bool, List[str]]:
        """
        Validate signal data.

        Args:
            signal: Signal data to validate

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        if not signal.definition_name:
            errors.append("Signal definition name is required")

        if not signal.asset:
            errors.append("Asset is required")

        if signal.signal_date is None:
            errors.append("Signal date is required")

        if not isinstance(signal.value, (int, float)):
            errors.append("Signal value must be a number")

        if signal.value < -1 or signal.value > 1:
            errors.append("Signal value must be between -1 and 1")

        if signal.strength < 0 or signal.strength > 1:
            errors.append("Strength must be between 0 and 1")

        if signal.confidence is not None:
            if signal.confidence < 0 or signal.confidence > 1:
                errors.append("Confidence must be between 0 and 1")

        if signal.direction not in SignalDirection:
            errors.append(f"Invalid direction: {signal.direction}")

        return len(errors) == 0, errors

    @staticmethod
    def validate_batch(signals: List[SignalData]) -> Dict[str, Any]:
        """
        Validate a batch of signals.

        Args:
            signals: List of signals to validate

        Returns:
            Validation report dictionary
        """
        valid_signals = []
        invalid_signals = []

        for signal in signals:
            is_valid, errors = SignalValidator.validate_signal(signal)
            if is_valid:
                valid_signals.append(signal)
            else:
                invalid_signals.append({"signal": signal, "errors": errors})

        return {
            "total": len(signals),
            "valid": len(valid_signals),
            "invalid": len(invalid_signals),
            "valid_signals": valid_signals,
            "invalid_signals": invalid_signals,
        }


class SignalStore:
    """
    Central repository for trading signals.

    Provides comprehensive signal storage, retrieval, aggregation,
    and management capabilities with PostgreSQL support.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        echo: bool = False,
    ):
        """
        Initialize the SignalStore.

        Args:
            connection_string: Database connection string
            echo: Whether to echo SQL statements
        """
        if not HAS_SQLALCHEMY:
            raise ImportError(
                "SQLAlchemy is required for SignalStore. Install with: pip install sqlalchemy"
            )

        self._connection_string = connection_string
        self._engine: Optional[Engine] = None
        self._session_factory = None

        if connection_string:
            self._init_engine(connection_string, echo)

    def _init_engine(self, connection_string: str, echo: bool = False) -> None:
        """Initialize database engine."""
        if connection_string.endswith(".db") or ":memory:" in connection_string:
            connection_string = f"sqlite:///{connection_string}"

        self._engine = create_engine(connection_string, echo=echo)
        self._session_factory = sessionmaker(bind=self._engine)

    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._engine is not None

    def create_tables(self, drop_existing: bool = False) -> None:
        """
        Create all signal store tables.

        Args:
            drop_existing: Whether to drop existing tables
        """
        if self._engine is None:
            raise RuntimeError("Database engine not initialized")

        if drop_existing:
            Base.metadata.drop_all(self._engine)

        Base.metadata.create_all(self._engine)
        logger.info("Signal store tables created successfully")

    def get_schema_sql(self) -> str:
        """Get SQL schema creation script."""
        return """
-- Signal Definitions
CREATE TABLE IF NOT EXISTS signal_definitions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    signal_type VARCHAR(50) NOT NULL,
    asset_class VARCHAR(50),
    parameters JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_signal_definitions_name ON signal_definitions(name);
CREATE INDEX IF NOT EXISTS idx_signal_definitions_type ON signal_definitions(signal_type);
CREATE INDEX IF NOT EXISTS idx_signal_definitions_asset_class ON signal_definitions(asset_class);

-- Signal Values
CREATE TABLE IF NOT EXISTS signal_values (
    id BIGSERIAL PRIMARY KEY,
    definition_id INTEGER REFERENCES signal_definitions(id),
    asset VARCHAR(50) NOT NULL,
    signal_date DATE NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    direction VARCHAR(20) NOT NULL,
    strength DOUBLE PRECISION DEFAULT 0.5,
    confidence DOUBLE PRECISION,
    metadata JSONB,
    features_used JSONB,
    model_version VARCHAR(50),
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signal_values_definition ON signal_values(definition_id);
CREATE INDEX IF NOT EXISTS idx_signal_values_asset ON signal_values(asset);
CREATE INDEX IF NOT EXISTS idx_signal_values_date ON signal_values(signal_date);
CREATE INDEX IF NOT EXISTS idx_signal_values_generated ON signal_values(generated_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_values_unique ON signal_values(definition_id, asset, signal_date);

-- Signal Models
CREATE TABLE IF NOT EXISTS signal_models (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    model_type VARCHAR(50) NOT NULL,
    signal_type VARCHAR(50) NOT NULL,
    version VARCHAR(50) NOT NULL,
    description TEXT,
    hyperparameters JSONB,
    features JSONB,
    performance_metrics JSONB,
    trained_from DATE,
    trained_to DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_signal_models_name ON signal_models(name);
CREATE INDEX IF NOT EXISTS idx_signal_models_type ON signal_models(signal_type);

-- Signal Performance
CREATE TABLE IF NOT EXISTS signal_performance (
    id BIGSERIAL PRIMARY KEY,
    signal_value_id BIGINT REFERENCES signal_values(id),
    prediction DOUBLE PRECISION NOT NULL,
    actual DOUBLE PRECISION,
    pnl DOUBLE PRECISION,
    returns DOUBLE PRECISION,
    hit_rate DOUBLE PRECISION,
    evaluation_date DATE NOT NULL,
    horizon_days INTEGER,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signal_performance_signal ON signal_performance(signal_value_id);
CREATE INDEX IF NOT EXISTS idx_signal_performance_eval_date ON signal_performance(evaluation_date);

-- Signal Features
CREATE TABLE IF NOT EXISTS signal_features (
    id BIGSERIAL PRIMARY KEY,
    asset VARCHAR(50) NOT NULL,
    feature_name VARCHAR(100) NOT NULL,
    feature_value DOUBLE PRECISION,
    observation_date DATE NOT NULL,
    feature_type VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signal_features_asset ON signal_features(asset);
CREATE INDEX IF NOT EXISTS idx_signal_features_name ON signal_features(feature_name);
CREATE INDEX IF NOT EXISTS idx_signal_features_date ON signal_features(observation_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_features_unique ON signal_features(asset, feature_name, observation_date);
"""

    def execute_schema(self) -> None:
        """Execute schema creation script."""
        if self._engine is None:
            raise RuntimeError("Database engine not initialized")

        schema_sql = self.get_schema_sql()

        with self._engine.connect() as conn:
            for statement in schema_sql.split(";"):
                statement = statement.strip()
                if statement:
                    try:
                        conn.execute(text(statement))
                    except Exception as e:
                        warnings.warn(f"Schema creation warning: {e}")
            conn.commit()

        logger.info("Signal store schema created successfully")

    def _get_session(self) -> Session:
        """Get a new database session."""
        if self._session_factory is None:
            raise RuntimeError("Database not initialized")
        return self._session_factory()

    def register_signal_type(
        self,
        name: str,
        signal_type: SignalType,
        description: Optional[str] = None,
        asset_class: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Register a new signal type.

        Args:
            name: Signal definition name
            signal_type: Signal type enum
            description: Optional description
            asset_class: Optional asset class
            parameters: Optional parameters

        Returns:
            Signal definition ID
        """
        with self._get_session() as session:
            existing = session.query(SignalDefinition).filter(SignalDefinition.name == name).first()

            if existing:
                logger.warning(f"Signal type '{name}' already exists, updating")
                existing.description = description
                existing.signal_type = signal_type
                existing.asset_class = asset_class
                existing.parameters = parameters
                existing.updated_at = datetime.utcnow()
                session.commit()
                return existing.id

            definition = SignalDefinition(
                name=name,
                signal_type=signal_type,
                description=description,
                asset_class=asset_class,
                parameters=parameters,
            )
            session.add(definition)
            session.commit()
            logger.info(f"Registered signal type: {name}")
            return definition.id

    def list_signal_types(self, active_only: bool = True) -> pd.DataFrame:
        """
        List available signal types.

        Args:
            active_only: Whether to return only active signal types

        Returns:
            DataFrame of signal definitions
        """
        with self._get_session() as session:
            query = session.query(SignalDefinition)

            if active_only:
                query = query.filter(SignalDefinition.is_active == True)

            results = query.order_by(SignalDefinition.name).all()

            if not results:
                return pd.DataFrame()

            data = [
                {
                    "id": r.id,
                    "name": r.name,
                    "signal_type": r.signal_type.value if r.signal_type else None,
                    "asset_class": r.asset_class,
                    "description": r.description,
                    "is_active": r.is_active,
                    "created_at": r.created_at,
                }
                for r in results
            ]

            return pd.DataFrame(data)

    def get_signal_metadata(self, definition_name: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata about a signal definition.

        Args:
            definition_name: Name of the signal definition

        Returns:
            Metadata dictionary or None
        """
        with self._get_session() as session:
            definition = (
                session.query(SignalDefinition)
                .filter(SignalDefinition.name == definition_name)
                .first()
            )

            if not definition:
                return None

            return {
                "id": definition.id,
                "name": definition.name,
                "signal_type": definition.signal_type.value if definition.signal_type else None,
                "asset_class": definition.asset_class,
                "description": definition.description,
                "parameters": definition.parameters,
                "is_active": definition.is_active,
                "created_at": definition.created_at.isoformat() if definition.created_at else None,
                "updated_at": definition.updated_at.isoformat() if definition.updated_at else None,
            }

    def save_signal(self, signal: SignalData) -> int:
        """
        Save an individual signal to the database.

        Args:
            signal: Signal data to save

        Returns:
            Signal value ID
        """
        is_valid, errors = SignalValidator.validate_signal(signal)
        if not is_valid:
            raise ValueError(f"Invalid signal: {errors}")

        with self._get_session() as session:
            definition = (
                session.query(SignalDefinition)
                .filter(SignalDefinition.name == signal.definition_name)
                .first()
            )

            if not definition:
                raise ValueError(
                    f"Signal definition '{signal.definition_name}' not found. "
                    "Register it first using register_signal_type()."
                )

            signal_value = SignalValue(
                definition_id=definition.id,
                asset=signal.asset,
                signal_date=signal.signal_date,
                value=signal.value,
                direction=signal.direction,
                strength=signal.strength,
                confidence=signal.confidence,
                metadata=signal.metadata,
                features_used=signal.features_used,
                model_version=signal.model_version,
            )
            session.add(signal_value)
            session.commit()

            logger.info(
                f"Saved signal: {signal.definition_name} for {signal.asset} on {signal.signal_date}"
            )
            return signal_value.id

    def save_signals(self, signals: List[SignalData], batch_size: int = 1000) -> int:
        """
        Batch save signals to the database.

        Args:
            signals: List of signals to save
            batch_size: Number of signals per batch

        Returns:
            Number of signals saved
        """
        if not signals:
            return 0

        validation = SignalValidator.validate_batch(signals)
        if validation["invalid"] > 0:
            logger.warning(f"Skipping {validation['invalid']} invalid signals")

        valid_signals = validation["valid_signals"]
        if not valid_signals:
            return 0

        saved_count = 0

        with self._get_session() as session:
            definition_map = {}
            for signal in valid_signals:
                if signal.definition_name not in definition_map:
                    definition = (
                        session.query(SignalDefinition)
                        .filter(SignalDefinition.name == signal.definition_name)
                        .first()
                    )
                    definition_map[signal.definition_name] = definition

            for i in range(0, len(valid_signals), batch_size):
                batch = valid_signals[i : i + batch_size]

                for signal in batch:
                    definition = definition_map.get(signal.definition_name)
                    if not definition:
                        continue

                    signal_value = SignalValue(
                        definition_id=definition.id,
                        asset=signal.asset,
                        signal_date=signal.signal_date,
                        value=signal.value,
                        direction=signal.direction,
                        strength=signal.strength,
                        confidence=signal.confidence,
                        metadata=signal.metadata,
                        features_used=signal.features_used,
                        model_version=signal.model_version,
                    )
                    session.add(signal_value)
                    saved_count += 1

                session.commit()

        logger.info(f"Saved {saved_count} signals to database")
        return saved_count

    def get_signal(
        self,
        definition_name: str,
        asset: str,
        signal_date: date,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single signal by date and type.

        Args:
            definition_name: Signal definition name
            asset: Asset identifier
            signal_date: Signal date

        Returns:
            Signal data dictionary or None
        """
        with self._get_session() as session:
            definition = (
                session.query(SignalDefinition)
                .filter(SignalDefinition.name == definition_name)
                .first()
            )

            if not definition:
                return None

            signal_value = (
                session.query(SignalValue)
                .filter(
                    SignalValue.definition_id == definition.id,
                    SignalValue.asset == asset,
                    SignalValue.signal_date == signal_date,
                )
                .first()
            )

            if not signal_value:
                return None

            return {
                "id": signal_value.id,
                "definition_name": definition.name,
                "asset": signal_value.asset,
                "signal_date": signal_value.signal_date,
                "value": signal_value.value,
                "direction": signal_value.direction.value if signal_value.direction else None,
                "strength": signal_value.strength,
                "confidence": signal_value.confidence,
                "metadata": signal_value.metadata,
                "features_used": signal_value.features_used,
                "model_version": signal_value.model_version,
                "generated_at": signal_value.generated_at.isoformat()
                if signal_value.generated_at
                else None,
            }

    def get_signals(
        self,
        query: Optional[SignalQuery] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """
        Retrieve signals with filters.

        Args:
            query: Signal query parameters
            **kwargs: Additional filter parameters

        Returns:
            DataFrame of signals
        """
        if query is None:
            query = SignalQuery(**kwargs)

        with self._get_session() as session:
            base_query = session.query(SignalValue, SignalDefinition).join(
                SignalDefinition, SignalValue.definition_id == SignalDefinition.id
            )

            if query.definition_name:
                base_query = base_query.filter(SignalDefinition.name == query.definition_name)

            if query.signal_type:
                base_query = base_query.filter(SignalDefinition.signal_type == query.signal_type)

            if query.asset:
                base_query = base_query.filter(SignalValue.asset == query.asset)

            if query.start_date:
                base_query = base_query.filter(SignalValue.signal_date >= query.start_date)

            if query.end_date:
                base_query = base_query.filter(SignalValue.signal_date <= query.end_date)

            if query.min_strength is not None:
                base_query = base_query.filter(SignalValue.strength >= query.min_strength)

            if query.max_strength is not None:
                base_query = base_query.filter(SignalValue.strength <= query.max_strength)

            if query.direction:
                base_query = base_query.filter(SignalValue.direction == query.direction)

            base_query = base_query.order_by(SignalValue.signal_date.desc())

            if query.limit:
                base_query = base_query.limit(query.limit)

            results = base_query.all()

            if not results:
                return pd.DataFrame()

            data = []
            for signal_value, definition in results:
                data.append(
                    {
                        "id": signal_value.id,
                        "definition_name": definition.name,
                        "signal_type": definition.signal_type.value
                        if definition.signal_type
                        else None,
                        "asset": signal_value.asset,
                        "signal_date": signal_value.signal_date,
                        "value": signal_value.value,
                        "direction": signal_value.direction.value
                        if signal_value.direction
                        else None,
                        "strength": signal_value.strength,
                        "confidence": signal_value.confidence,
                        "metadata": signal_value.metadata,
                        "features_used": signal_value.features_used,
                        "model_version": signal_value.model_version,
                        "generated_at": signal_value.generated_at,
                    }
                )

            return pd.DataFrame(data)

    def get_signals_by_date_range(
        self,
        start_date: Union[str, date],
        end_date: Union[str, date],
        definition_name: Optional[str] = None,
        asset: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get signals within a date range.

        Args:
            start_date: Start date
            end_date: End date
            definition_name: Optional signal definition filter
            asset: Optional asset filter

        Returns:
            DataFrame of signals
        """
        start = pd.to_datetime(start_date).date() if isinstance(start_date, str) else start_date
        end = pd.to_datetime(end_date).date() if isinstance(end_date, str) else end_date

        query = SignalQuery(
            start_date=start,
            end_date=end,
            definition_name=definition_name,
            asset=asset,
        )

        return self.get_signals(query)

    def get_signals_by_type(
        self,
        signal_type: SignalType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        asset: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get signals by type (fundamental, ml, etc.).

        Args:
            signal_type: Signal type
            start_date: Optional start date
            end_date: Optional end date
            asset: Optional asset filter

        Returns:
            DataFrame of signals
        """
        query = SignalQuery(
            signal_type=signal_type,
            start_date=start_date,
            end_date=end_date,
            asset=asset,
        )

        return self.get_signals(query)

    def get_signals_by_asset(
        self,
        asset: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        definition_name: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get signals for a specific asset.

        Args:
            asset: Asset identifier
            start_date: Optional start date
            end_date: Optional end date
            definition_name: Optional signal definition filter

        Returns:
            DataFrame of signals
        """
        query = SignalQuery(
            asset=asset,
            start_date=start_date,
            end_date=end_date,
            definition_name=definition_name,
        )

        return self.get_signals(query)

    def get_recent_signals(
        self,
        days: int = 7,
        definition_name: Optional[str] = None,
        asset: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get most recent signals.

        Args:
            days: Number of days to look back
            definition_name: Optional signal definition filter
            asset: Optional asset filter

        Returns:
            DataFrame of recent signals
        """
        from datetime import timedelta

        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        query = SignalQuery(
            start_date=start_date,
            end_date=end_date,
            definition_name=definition_name,
            asset=asset,
            limit=1000,
        )

        return self.get_signals(query)

    def aggregate_signals(
        self,
        signals: pd.DataFrame,
        method: str = "mean",
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        Combine signals from multiple sources.

        Args:
            signals: DataFrame of signals
            method: Aggregation method ('mean', 'weighted', 'median')
            weights: Optional weights for each signal

        Returns:
            Aggregated signals DataFrame
        """
        if signals.empty:
            return pd.DataFrame()

        grouped = signals.groupby(["asset", "signal_date"])

        if method == "mean":
            aggregated = grouped["value"].mean().reset_index()
        elif method == "median":
            aggregated = grouped["value"].median().reset_index()
        elif method == "weighted":
            if not weights:
                raise ValueError("Weights required for weighted aggregation")

            weighted_values = []
            for asset, date_group in grouped:
                weighted_sum = 0.0
                weight_sum = 0.0

                for _, row in date_group.iterrows():
                    signal_name = row.get("definition_name", "default")
                    weight = weights.get(signal_name, 1.0)
                    weighted_sum += row["value"] * weight
                    weight_sum += weight

                avg_value = weighted_sum / weight_sum if weight_sum > 0 else 0.0
                weighted_values.append(
                    {"asset": asset[0], "signal_date": asset[1], "value": avg_value}
                )

            aggregated = pd.DataFrame(weighted_values)
        else:
            raise ValueError(f"Unknown aggregation method: {method}")

        return aggregated

    def signal_weighted_average(
        self,
        signals: pd.DataFrame,
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        Calculate weighted average of signals.

        Args:
            signals: DataFrame of signals with 'definition_name', 'asset', 'signal_date', 'value'
            weights: Dictionary of {definition_name: weight}

        Returns:
            DataFrame with weighted averages
        """
        if signals.empty:
            return pd.DataFrame()

        if weights is None:
            weights = {name: 1.0 for name in signals["definition_name"].unique()}

        signals = signals.copy()
        signals["weight"] = signals["definition_name"].map(weights).fillna(1.0)

        grouped = signals.groupby(["asset", "signal_date"])

        def weighted_avg(group):
            return np.average(group["value"], weights=group["weight"])

        result = grouped.apply(weighted_avg).reset_index()
        result.columns = ["asset", "signal_date", "weighted_value"]

        return result

    def signal_consensus(
        self,
        signals: pd.DataFrame,
        threshold: float = 0.3,
    ) -> pd.DataFrame:
        """
        Calculate consensus signal from multiple models.

        Uses directional agreement and strength to determine consensus.

        Args:
            signals: DataFrame of signals
            threshold: Minimum proportion of agreement for consensus

        Returns:
            DataFrame with consensus signals
        """
        if signals.empty:
            return pd.DataFrame()

        results = []

        grouped = signals.groupby(["asset", "signal_date"])

        for (asset, signal_date), group in grouped:
            bullish_count = (group["direction"] == "bullish").sum()
            bearish_count = (group["direction"] == "bearish").sum()
            total = len(group)

            if total == 0:
                continue

            if bullish_count > bearish_count:
                direction = SignalDirection.BULLISH
                consensus_score = bullish_count / total
            elif bearish_count > bullish_count:
                direction = SignalDirection.BEARISH
                consensus_score = bearish_count / total
            else:
                direction = SignalDirection.NEUTRAL
                consensus_score = 0.5

            if consensus_score < threshold:
                direction = SignalDirection.NEUTRAL

            avg_value = group["value"].mean()
            avg_strength = group["strength"].mean()

            results.append(
                {
                    "asset": asset,
                    "signal_date": signal_date,
                    "value": avg_value,
                    "direction": direction.value,
                    "strength": avg_strength,
                    "consensus_score": consensus_score,
                    "contributing_signals": group["definition_name"].tolist(),
                    "bullish_count": bullish_count,
                    "bearish_count": bearish_count,
                    "total_signals": total,
                }
            )

        return pd.DataFrame(results)

    def load_features_for_signal(
        self,
        asset: str,
        feature_names: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Load features for signal generation.

        Args:
            asset: Asset identifier
            feature_names: Optional list of feature names to load
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            DataFrame of features
        """
        if self._engine is None:
            raise RuntimeError("Database not initialized")

        query = "SELECT * FROM signal_features WHERE asset = :asset"
        params: Dict[str, Any] = {"asset": asset}

        if feature_names:
            placeholders = ", ".join([f":feat_{i}" for i in range(len(feature_names))])
            query += f" AND feature_name IN ({placeholders})"
            for i, name in enumerate(feature_names):
                params[f"feat_{i}"] = name

        if start_date:
            query += " AND observation_date >= :start_date"
            params["start_date"] = start_date

        if end_date:
            query += " AND observation_date <= :end_date"
            params["end_date"] = end_date

        query += " ORDER BY observation_date, feature_name"

        with self._engine.connect() as conn:
            result = conn.execute(text(query), params)
            rows = result.fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=result.keys())

        pivot_df = df.pivot_table(
            index="observation_date",
            columns="feature_name",
            values="feature_value",
            aggfunc="first",
        ).reset_index()

        pivot_df.columns = ["date" if c == "observation_date" else c for c in pivot_df.columns]

        return pivot_df

    def save_features_to_store(
        self,
        asset: str,
        features: pd.DataFrame,
        feature_type: Optional[str] = None,
    ) -> int:
        """
        Save computed features to the feature store.

        Args:
            asset: Asset identifier
            features: DataFrame with 'date' and feature columns
            feature_type: Optional feature type classification

        Returns:
            Number of features saved
        """
        if self._engine is None:
            raise RuntimeError("Database not initialized")

        feature_columns = [c for c in features.columns if c != "date"]

        records = []
        for _, row in features.iterrows():
            date_val = row["date"]
            for feature in feature_columns:
                records.append(
                    {
                        "asset": asset,
                        "feature_name": feature,
                        "feature_value": row[feature],
                        "observation_date": pd.to_datetime(date_val),
                        "feature_type": feature_type,
                    }
                )

        if not records:
            return 0

        insert_sql = """
        INSERT INTO signal_features 
        (asset, feature_name, feature_value, observation_date, feature_type)
        VALUES (:asset, :feature_name, :feature_value, :observation_date, :feature_type)
        """

        with self._engine.connect() as conn:
            conn.execute(text(insert_sql), records)
            conn.commit()

        logger.info(f"Saved {len(records)} features for {asset}")
        return len(records)

    def get_latest_features(
        self,
        asset: str,
        feature_names: Optional[List[str]] = None,
        n_latest: int = 1,
    ) -> pd.DataFrame:
        """
        Get latest feature values.

        Args:
            asset: Asset identifier
            feature_names: Optional list of feature names
            n_latest: Number of latest observations to return

        Returns:
            DataFrame of latest features
        """
        if self._engine is None:
            raise RuntimeError("Database not initialized")

        query = """
        SELECT DISTINCT ON (feature_name) 
            asset, feature_name, feature_value, observation_date
        FROM signal_features
        WHERE asset = :asset
        """
        params: Dict[str, Any] = {"asset": asset}

        if feature_names:
            placeholders = ", ".join([f":feat_{i}" for i in range(len(feature_names))])
            query += f" AND feature_name IN ({placeholders})"
            for i, name in enumerate(feature_names):
                params[f"feat_{i}"] = name

        query += " ORDER BY feature_name, observation_date DESC"

        with self._engine.connect() as conn:
            result = conn.execute(text(query), params)
            rows = result.fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=result.keys())

        if n_latest > 1:
            recent_dates = df["observation_date"].unique()[:n_latest]
            df = df[df["observation_date"].isin(recent_dates)]

        pivot_df = df.pivot_table(
            index="observation_date",
            columns="feature_name",
            values="feature_value",
            aggfunc="first",
        ).reset_index()

        pivot_df.columns = ["date" if c == "observation_date" else c for c in pivot_df.columns]

        return pivot_df

    def export_signals(
        self,
        query: SignalQuery,
        format: str = "csv",
        filepath: Optional[str] = None,
    ) -> Union[str, pd.DataFrame]:
        """
        Export signals to CSV or JSON.

        Args:
            query: Signal query parameters
            format: Export format ('csv' or 'json')
            filepath: Optional file path to save to

        Returns:
            Exported data as string or DataFrame
        """
        signals = self.get_signals(query)

        if signals.empty:
            return "" if format == "csv" else "[]"

        if format == "csv":
            csv_data = signals.to_csv(index=False)

            if filepath:
                with open(filepath, "w") as f:
                    f.write(csv_data)
                logger.info(f"Exported signals to {filepath}")

            return csv_data

        elif format == "json":
            json_data = signals.to_json(orient="records", date_format="iso")

            if filepath:
                with open(filepath, "w") as f:
                    f.write(json_data)
                logger.info(f"Exported signals to {filepath}")

            return json_data

        else:
            raise ValueError(f"Unsupported format: {format}")

    def import_signals(
        self,
        data: Union[str, pd.DataFrame],
        source: str = "csv",
    ) -> int:
        """
        Import signals from CSV or JSON.

        Args:
            data: File path or DataFrame
            source: Source format ('csv' or 'json')

        Returns:
            Number of signals imported
        """
        if isinstance(data, str):
            if source == "csv":
                df = pd.read_csv(data)
            elif source == "json":
                df = pd.read_json(data)
            else:
                raise ValueError(f"Unsupported source: {source}")
        else:
            df = data

        signals = []
        for _, row in df.iterrows():
            signal = SignalData(
                definition_name=row.get("definition_name", row.get("definition_name")),
                asset=row["asset"],
                signal_date=pd.to_datetime(row["signal_date"]).date(),
                value=row["value"],
                direction=SignalDirection(row["direction"]),
                strength=row.get("strength", 0.5),
                confidence=row.get("confidence"),
                metadata=row.get("metadata"),
                features_used=row.get("features_used"),
                model_version=row.get("model_version"),
            )
            signals.append(signal)

        return self.save_signals(signals)

    def validate_signal(self, signal: SignalData) -> tuple[bool, List[str]]:
        """
        Validate signal format.

        Args:
            signal: Signal to validate

        Returns:
            Tuple of (is_valid, error_messages)
        """
        return SignalValidator.validate_signal(signal)

    def close(self) -> None:
        """Close database connection."""
        if self._engine:
            self._engine.dispose()
            logger.info("Signal store connection closed")


def create_signal_store(
    connection_string: Optional[str] = None,
    create_schema: bool = True,
) -> SignalStore:
    """
    Factory function to create a SignalStore.

    Args:
        connection_string: Database connection string
        create_schema: Whether to create schema on initialization

    Returns:
        Configured SignalStore instance
    """
    store = SignalStore(connection_string)

    if create_schema and store.is_connected:
        try:
            store.create_tables()
        except Exception as e:
            warnings.warn(f"Could not create tables: {e}")

    return store
