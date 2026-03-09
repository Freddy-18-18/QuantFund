"""
Semantic Anomaly Detection Module
==================================

Cross-references statistical anomalies with FRED release dates and known
economic events to distinguish between "real" anomalies and expected
data releases.

Usage:
    from quantfund.data.fred_semantic_anomaly import SemanticAnomalyDetector

    detector = SemanticAnomalyDetector(fred_client=client)

    # Classify an anomaly
    result = detector.classify_anomaly(
        anomaly_date=date(2024, 3, 15),
        series_id="UNRATE",
        anomaly_score=3.5
    )

    # Get explanation
    explanation = detector.explain_anomaly(result)

Classes:
    - SemanticAnomalyDetector: Main detector for semantic anomaly classification
    - KnownEvent: Dataclass for economic events
    - AnomalyClassification: Classification result

Event Types:
    - Fed meetings (FOMC)
    - CPI release dates
    - Employment reports (NFP)
    - GDP releases
    - Central bank announcements
    - Geopolitical events
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class EventType(Enum):
    FOMC = "fomc"
    CPI = "cpi"
    NFP = "nfp"
    GDP = "gdp"
    CENTRAL_BANK = "central_bank"
    GEOPOLITICAL = "geopolitical"
    EARNINGS = "earnings"
    TREASURY = "treasury"
    OTHER = "other"


class ClassificationType(Enum):
    EXPECTED = "expected"
    SUSPICIOUS = "suspicious"
    GENUINE = "genuine"


class ReleaseImportance(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class KnownEvent:
    name: str
    date: date
    event_type: EventType
    importance: ReleaseImportance
    description: str = ""
    affected_series: List[str] = field(default_factory=list)
    typical_impact: float = 0.0
    volatility_boost: float = 1.0


@dataclass
class AnomalyClassification:
    date: date
    series_id: str
    anomaly_score: float
    classification: ClassificationType
    confidence: float
    explanation: str
    related_events: List[KnownEvent] = field(default_factory=list)
    release_context: Optional[Dict[str, Any]] = None
    factors: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "series_id": self.series_id,
            "anomaly_score": self.anomaly_score,
            "classification": self.classification.value,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "related_events": [
                {
                    "name": e.name,
                    "date": e.date.isoformat(),
                    "type": e.event_type.value,
                    "importance": e.importance.value,
                }
                for e in self.related_events
            ],
            "release_context": self.release_context,
            "factors": self.factors,
        }


@dataclass
class ReleaseInfo:
    release_id: int
    name: str
    release_date: date
    importance: ReleaseImportance
    series_released: List[str] = field(default_factory=list)
    press_release: bool = False


SERIES_RELEASE_MAPPING = {
    "UNRATE": {"release_id": 62, "importance": ReleaseImportance.HIGH},
    "UNEMPLOY": {"release_id": 62, "importance": ReleaseImportance.HIGH},
    "PAYEMS": {"release_id": 62, "importance": ReleaseImportance.HIGH},
    "CPIAUCSL": {"release_id": 53, "importance": ReleaseImportance.HIGH},
    "CPILFESL": {"release_id": 53, "importance": ReleaseImportance.MEDIUM},
    "GDP": {"release_id": 83, "importance": ReleaseImportance.HIGH},
    "GDPC1": {"release_id": 83, "importance": ReleaseImportance.HIGH},
    "PCEPI": {"release_id": 171, "importance": ReleaseImportance.HIGH},
    "FEDFUNDS": {"release_id": 134, "importance": ReleaseImportance.HIGH},
    "DFF": {"release_id": 134, "importance": ReleaseImportance.HIGH},
    "DGS10": {"release_id": 134, "importance": ReleaseImportance.HIGH},
    "DGS2": {"release_id": 134, "importance": ReleaseImportance.MEDIUM},
    "M2SL": {"release_id": 241, "importance": ReleaseImportance.MEDIUM},
    "M2V": {"release_id": 241, "importance": ReleaseImportance.MEDIUM},
    "HOUST": {"release_id": 44, "importance": ReleaseImportance.MEDIUM},
    "HOUSING": {"release_id": 44, "importance": ReleaseImportance.MEDIUM},
    " retail": {"release_id": 51, "importance": ReleaseImportance.HIGH},
    "RETAIL": {"release_id": 51, "importance": ReleaseImportance.HIGH},
}


KNOWN_EVENTS_CALENDAR = [
    KnownEvent(
        name="FOMC Meeting",
        date=date(2024, 1, 30),
        event_type=EventType.FOMC,
        importance=ReleaseImportance.HIGH,
        description="Federal Reserve interest rate decision",
        affected_series=["FEDFUNDS", "DFF", "DGS10", "DGS2"],
        typical_impact=0.5,
        volatility_boost=2.0,
    ),
    KnownEvent(
        name="FOMC Meeting",
        date=date(2024, 3, 19),
        event_type=EventType.FOMC,
        importance=ReleaseImportance.HIGH,
        description="Federal Reserve interest rate decision",
        affected_series=["FEDFUNDS", "DFF", "DGS10", "DGS2"],
        typical_impact=0.5,
        volatility_boost=2.0,
    ),
    KnownEvent(
        name="FOMC Meeting",
        date=date(2024, 4, 30),
        event_type=EventType.FOMC,
        importance=ReleaseImportance.HIGH,
        description="Federal Reserve interest rate decision",
        affected_series=["FEDFUNDS", "DFF", "DGS10", "DGS2"],
        typical_impact=0.5,
        volatility_boost=2.0,
    ),
    KnownEvent(
        name="FOMC Meeting",
        date=date(2024, 6, 11),
        event_type=EventType.FOMC,
        importance=ReleaseImportance.HIGH,
        description="Federal Reserve interest rate decision",
        affected_series=["FEDFUNDS", "DFF", "DGS10", "DGS2"],
        typical_impact=0.5,
        volatility_boost=2.0,
    ),
    KnownEvent(
        name="FOMC Meeting",
        date=date(2024, 7, 30),
        event_type=EventType.FOMC,
        importance=ReleaseImportance.HIGH,
        description="Federal Reserve interest rate decision",
        affected_series=["FEDFUNDS", "DFF", "DGS10", "DGS2"],
        typical_impact=0.5,
        volatility_boost=2.0,
    ),
    KnownEvent(
        name="FOMC Meeting",
        date=date(2024, 9, 17),
        event_type=EventType.FOMC,
        importance=ReleaseImportance.HIGH,
        description="Federal Reserve interest rate decision",
        affected_series=["FEDFUNDS", "DFF", "DGS10", "DGS2"],
        typical_impact=0.5,
        volatility_boost=2.0,
    ),
    KnownEvent(
        name="FOMC Meeting",
        date=date(2024, 11, 6),
        event_type=EventType.FOMC,
        importance=ReleaseImportance.HIGH,
        description="Federal Reserve interest rate decision",
        affected_series=["FEDFUNDS", "DFF", "DGS10", "DGS2"],
        typical_impact=0.5,
        volatility_boost=2.0,
    ),
    KnownEvent(
        name="CPI Release",
        date=date(2024, 1, 11),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Consumer Price Index release",
        affected_series=["CPIAUCSL", "CPILFESL"],
        typical_impact=0.3,
        volatility_boost=1.8,
    ),
    KnownEvent(
        name="CPI Release",
        date=date(2024, 2, 13),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Consumer Price Index release",
        affected_series=["CPIAUCSL", "CPILFESL"],
        typical_impact=0.3,
        volatility_boost=1.8,
    ),
    KnownEvent(
        name="CPI Release",
        date=date(2024, 3, 12),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Consumer Price Index release",
        affected_series=["CPIAUCSL", "CPILFESL"],
        typical_impact=0.3,
        volatility_boost=1.8,
    ),
    KnownEvent(
        name="CPI Release",
        date=date(2024, 4, 10),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Consumer Price Index release",
        affected_series=["CPIAUCSL", "CPILFESL"],
        typical_impact=0.3,
        volatility_boost=1.8,
    ),
    KnownEvent(
        name="CPI Release",
        date=date(2024, 5, 15),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Consumer Price Index release",
        affected_series=["CPIAUCSL", "CPILFESL"],
        typical_impact=0.3,
        volatility_boost=1.8,
    ),
    KnownEvent(
        name="CPI Release",
        date=date(2024, 6, 12),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Consumer Price Index release",
        affected_series=["CPIAUCSL", "CPILFESL"],
        typical_impact=0.3,
        volatility_boost=1.8,
    ),
    KnownEvent(
        name="Employment Report (NFP)",
        date=date(2024, 1, 5),
        event_type=EventType.NFP,
        importance=ReleaseImportance.HIGH,
        description="Non-Farm Payrolls release",
        affected_series=["UNRATE", "UNEMPLOY", "PAYEMS"],
        typical_impact=0.4,
        volatility_boost=2.2,
    ),
    KnownEvent(
        name="Employment Report (NFP)",
        date=date(2024, 2, 2),
        event_type=EventType.NFP,
        importance=ReleaseImportance.HIGH,
        description="Non-Farm Payrolls release",
        affected_series=["UNRATE", "UNEMPLOY", "PAYEMS"],
        typical_impact=0.4,
        volatility_boost=2.2,
    ),
    KnownEvent(
        name="Employment Report (NFP)",
        date=date(2024, 3, 8),
        event_type=EventType.NFP,
        importance=ReleaseImportance.HIGH,
        description="Non-Farm Payrolls release",
        affected_series=["UNRATE", "UNEMPLOY", "PAYEMS"],
        typical_impact=0.4,
        volatility_boost=2.2,
    ),
    KnownEvent(
        name="Employment Report (NFP)",
        date=date(2024, 4, 5),
        event_type=EventType.NFP,
        importance=ReleaseImportance.HIGH,
        description="Non-Farm Payrolls release",
        affected_series=["UNRATE", "UNEMPLOY", "PAYEMS"],
        typical_impact=0.4,
        volatility_boost=2.2,
    ),
    KnownEvent(
        name="Employment Report (NFP)",
        date=date(2024, 5, 3),
        event_type=EventType.NFP,
        importance=ReleaseImportance.HIGH,
        description="Non-Farm Payrolls release",
        affected_series=["UNRATE", "UNEMPLOY", "PAYEMS"],
        typical_impact=0.4,
        volatility_boost=2.2,
    ),
    KnownEvent(
        name="Employment Report (NFP)",
        date=date(2024, 6, 7),
        event_type=EventType.NFP,
        importance=ReleaseImportance.HIGH,
        description="Non-Farm Payrolls release",
        affected_series=["UNRATE", "UNEMPLOY", "PAYEMS"],
        typical_impact=0.4,
        volatility_boost=2.2,
    ),
    KnownEvent(
        name="GDP Advance",
        date=date(2024, 1, 25),
        event_type=EventType.GDP,
        importance=ReleaseImportance.HIGH,
        description="GDP Advance estimate",
        affected_series=["GDP", "GDPC1"],
        typical_impact=0.5,
        volatility_boost=1.5,
    ),
    KnownEvent(
        name="GDP Advance",
        date=date(2024, 4, 25),
        event_type=EventType.GDP,
        importance=ReleaseImportance.HIGH,
        description="GDP Advance estimate",
        affected_series=["GDP", "GDPC1"],
        typical_impact=0.5,
        volatility_boost=1.5,
    ),
    KnownEvent(
        name="GDP Advance",
        date=date(2024, 7, 25),
        event_type=EventType.GDP,
        importance=ReleaseImportance.HIGH,
        description="GDP Advance estimate",
        affected_series=["GDP", "GDPC1"],
        typical_impact=0.5,
        volatility_boost=1.5,
    ),
    KnownEvent(
        name="GDP Advance",
        date=date(2024, 10, 30),
        event_type=EventType.GDP,
        importance=ReleaseImportance.HIGH,
        description="GDP Advance estimate",
        affected_series=["GDP", "GDPC1"],
        typical_impact=0.5,
        volatility_boost=1.5,
    ),
    KnownEvent(
        name="ECB Rate Decision",
        date=date(2024, 1, 25),
        event_type=EventType.CENTRAL_BANK,
        importance=ReleaseImportance.HIGH,
        description="European Central Bank rate decision",
        affected_series=["DEXCHUS", "DEXUSEU"],
        typical_impact=0.3,
        volatility_boost=1.6,
    ),
    KnownEvent(
        name="BOJ Rate Decision",
        date=date(2024, 1, 23),
        event_type=EventType.CENTRAL_BANK,
        importance=ReleaseImportance.MEDIUM,
        description="Bank of Japan rate decision",
        affected_series=["DEXJPUS"],
        typical_impact=0.4,
        volatility_boost=1.7,
    ),
    KnownEvent(
        name="PCE Release",
        date=date(2024, 1, 26),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Personal Consumption Expenditures price index",
        affected_series=["PCEPI"],
        typical_impact=0.3,
        volatility_boost=1.6,
    ),
    KnownEvent(
        name="PCE Release",
        date=date(2024, 2, 29),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Personal Consumption Expenditures price index",
        affected_series=["PCEPI"],
        typical_impact=0.3,
        volatility_boost=1.6,
    ),
    KnownEvent(
        name="PCE Release",
        date=date(2024, 3, 27),
        event_type=EventType.CPI,
        importance=ReleaseImportance.HIGH,
        description="Personal Consumption Expenditures price index",
        affected_series=["PCEPI"],
        typical_impact=0.3,
        volatility_boost=1.6,
    ),
    KnownEvent(
        name="Treasury Auction",
        date=date(2024, 2, 26),
        event_type=EventType.TREASURY,
        importance=ReleaseImportance.MEDIUM,
        description="10-Year Treasury Note Auction",
        affected_series=["DGS10"],
        typical_impact=0.2,
        volatility_boost=1.4,
    ),
    KnownEvent(
        name="Treasury Auction",
        date=date(2024, 3, 25),
        event_type=EventType.TREASURY,
        importance=ReleaseImportance.MEDIUM,
        description="10-Year Treasury Note Auction",
        affected_series=["DGS10"],
        typical_impact=0.2,
        volatility_boost=1.4,
    ),
]


class SemanticAnomalyDetector:
    def __init__(
        self,
        fred_client: Optional[Any] = None,
        db_connection: Optional[str] = None,
        events_calendar: Optional[List[KnownEvent]] = None,
    ):
        self.fred_client = fred_client
        self.db_connection = db_connection or os.environ.get(
            "FRED_DB_CONNECTION",
            "postgresql://postgres:postgres@localhost:5432/freddata",
        )
        self.events_calendar = events_calendar or KNOWN_EVENTS_CALENDAR.copy()
        self._release_cache: Dict[date, List[ReleaseInfo]] = {}
        self._series_release_mapping = SERIES_RELEASE_MAPPING.copy()

    def load_calendar(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        event_types: Optional[List[EventType]] = None,
    ) -> List[KnownEvent]:
        filtered_events = self.events_calendar

        if start_date:
            filtered_events = [e for e in filtered_events if e.date >= start_date]
        if end_date:
            filtered_events = [e for e in filtered_events if e.date <= end_date]
        if event_types:
            filtered_events = [e for e in filtered_events if e.event_type in event_types]

        return filtered_events

    def add_event(self, event: KnownEvent) -> None:
        self.events_calendar.append(event)

    def fetch_release_dates(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[ReleaseInfo]:
        if self.fred_client is None:
            logger.warning("FRED client not available, using cached release dates")
            return self._get_cached_releases(series_id, start_date, end_date)

        release_info = self._series_release_mapping.get(series_id.upper())
        if not release_info:
            return []

        release_id = release_info["importance"]
        try:
            raw_dates = self.fred_client.get_release_dates(release_id)
            releases = []

            for rd in raw_dates:
                release_date = datetime.strptime(rd["date"], "%Y-%m-%d").date()
                if start_date and release_date < start_date:
                    continue
                if end_date and release_date > end_date:
                    continue

                releases.append(
                    ReleaseInfo(
                        release_id=release_id,
                        name=rd.get("release_name", ""),
                        release_date=release_date,
                        importance=release_info.get("importance", ReleaseImportance.MEDIUM),
                    )
                )

            return releases
        except Exception as e:
            logger.error(f"Failed to fetch release dates: {e}")
            return self._get_cached_releases(series_id, start_date, end_date)

    def _get_cached_releases(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[ReleaseInfo]:
        release_info = self._series_release_mapping.get(series_id.upper())
        if not release_info:
            return []

        all_releases = []
        for event in self.events_calendar:
            if event.affected_series:
                if any(
                    series_id.upper() in aff.upper() or aff.upper() in series_id.upper()
                    for aff in event.affected_series
                ):
                    all_releases.append(
                        ReleaseInfo(
                            release_id=release_info.get("release_id", 0),
                            name=event.name,
                            release_date=event.date,
                            importance=event.importance,
                        )
                    )

        filtered = all_releases
        if start_date:
            filtered = [r for r in filtered if r.release_date >= start_date]
        if end_date:
            filtered = [r for r in filtered if r.release_date <= end_date]

        return filtered

    def is_release_date(
        self,
        check_date: date,
        series_id: Optional[str] = None,
        window_days: int = 1,
    ) -> bool:
        if series_id:
            releases = self._get_cached_releases(series_id)
            for release in releases:
                if abs((release.release_date - check_date).days) <= window_days:
                    return True
            return False

        for event in self.events_calendar:
            if abs((event.date - check_date).days) <= window_days:
                return True

        return False

    def get_release_impact(
        self,
        release_date: date,
        series_id: str,
    ) -> Dict[str, Any]:
        events = self.check_event_impact(release_date, series_id)

        if not events:
            return {
                "has_release": False,
                "importance": ReleaseImportance.LOW.value,
                "volatility_boost": 1.0,
                "typical_impact": 0.0,
            }

        max_importance = max(e.importance for e in events)
        max_volatility = max(e.volatility_boost for e in events)
        avg_impact = np.mean([e.typical_impact for e in events])

        return {
            "has_release": True,
            "importance": max_importance.value,
            "volatility_boost": max_volatility,
            "typical_impact": avg_impact,
            "events": [e.name for e in events],
        }

    def check_event_impact(
        self,
        check_date: date,
        series_id: Optional[str] = None,
        window_days: int = 2,
    ) -> List[KnownEvent]:
        matching_events = []

        for event in self.events_calendar:
            days_diff = abs((event.date - check_date).days)
            if days_diff <= window_days:
                if series_id:
                    if any(
                        series_id.upper() in aff.upper() or aff.upper() in series_id.upper()
                        for aff in event.affected_series
                    ):
                        matching_events.append(event)
                else:
                    matching_events.append(event)

        return matching_events

    def classify_anomaly(
        self,
        anomaly_date: date,
        series_id: str,
        anomaly_score: float,
        historical_values: Optional[pd.Series] = None,
    ) -> AnomalyClassification:
        is_release = self.is_release_date(anomaly_date, series_id)
        release_impact = self.get_release_impact(anomaly_date, series_id)
        related_events = self.check_event_impact(anomaly_date, series_id)

        confidence = self.calculate_confidence(
            anomaly_score, is_release, release_impact, related_events
        )

        if is_release and release_impact["has_release"]:
            if release_impact["importance"] == ReleaseImportance.HIGH.value:
                classification = ClassificationType.EXPECTED
                explanation = self._generate_expected_explanation(
                    anomaly_date, series_id, anomaly_score, related_events, release_impact
                )
            elif release_impact["importance"] == ReleaseImportance.MEDIUM.value:
                if anomaly_score > 4.0:
                    classification = ClassificationType.GENUINE
                    explanation = self._generate_genuine_explanation(
                        anomaly_date, series_id, anomaly_score
                    )
                else:
                    classification = ClassificationType.EXPECTED
                    explanation = self._generate_expected_explanation(
                        anomaly_date, series_id, anomaly_score, related_events, release_impact
                    )
            else:
                if anomaly_score > 3.5:
                    classification = ClassificationType.SUSPICIOUS
                    explanation = self._generate_suspicious_explanation(
                        anomaly_date, series_id, anomaly_score, related_events
                    )
                else:
                    classification = ClassificationType.EXPECTED
                    explanation = self._generate_expected_explanation(
                        anomaly_date, series_id, anomaly_score, related_events, release_impact
                    )
        else:
            if anomaly_score >= 4.5:
                classification = ClassificationType.GENUINE
                explanation = self._generate_genuine_explanation(
                    anomaly_date, series_id, anomaly_score
                )
            elif anomaly_score >= 3.0 and related_events:
                classification = ClassificationType.SUSPICIOUS
                explanation = self._generate_suspicious_explanation(
                    anomaly_date, series_id, anomaly_score, related_events
                )
            elif anomaly_score >= 3.5:
                classification = ClassificationType.GENUINE
                explanation = self._generate_genuine_explanation(
                    anomaly_date, series_id, anomaly_score
                )
            else:
                classification = ClassificationType.SUSPICIOUS
                explanation = self._generate_suspicious_explanation(
                    anomaly_date, series_id, anomaly_score, related_events
                )

        factors = {
            "release_match": 1.0 if is_release else 0.0,
            "event_count": float(len(related_events)),
            "importance_score": self._importance_to_score(
                release_impact.get("importance", ReleaseImportance.LOW.value)
            ),
            "volatility_boost": release_impact.get("volatility_boost", 1.0),
        }

        return AnomalyClassification(
            date=anomaly_date,
            series_id=series_id,
            anomaly_score=anomaly_score,
            classification=classification,
            confidence=confidence,
            explanation=explanation,
            related_events=related_events,
            release_context=release_impact,
            factors=factors,
        )

    def _importance_to_score(self, importance: str) -> float:
        mapping = {
            ReleaseImportance.HIGH.value: 1.0,
            ReleaseImportance.MEDIUM.value: 0.6,
            ReleaseImportance.LOW.value: 0.3,
        }
        return mapping.get(importance, 0.0)

    def calculate_confidence(
        self,
        anomaly_score: float,
        is_release: bool,
        release_impact: Dict[str, Any],
        related_events: List[KnownEvent],
    ) -> float:
        base_confidence = min(1.0, anomaly_score / 5.0)

        if is_release and release_impact.get("has_release"):
            release_match_bonus = 0.2
        else:
            release_match_bonus = 0.0

        event_count = len(related_events)
        if event_count >= 2:
            event_bonus = 0.15
        elif event_count == 1:
            event_bonus = 0.1
        else:
            event_bonus = 0.0

        if anomaly_score >= 4.5:
            score_bonus = 0.1
        elif anomaly_score >= 3.5:
            score_bonus = 0.05
        else:
            score_bonus = 0.0

        confidence = min(1.0, base_confidence + release_match_bonus + event_bonus + score_bonus)

        return round(confidence, 2)

    def _generate_expected_explanation(
        self,
        anomaly_date: date,
        series_id: str,
        anomaly_score: float,
        related_events: List[KnownEvent],
        release_impact: Dict[str, Any],
    ) -> str:
        event_names = (
            ", ".join([e.name for e in related_events]) if related_events else "FRED data release"
        )

        explanation = (
            f"The anomaly detected on {anomaly_date.isoformat()} for {series_id} "
            f"is classified as EXPECTED. This date coincides with {event_names}, "
            f"which typically causes significant data movement."
        )

        if release_impact.get("typical_impact"):
            explanation += (
                f" The typical impact is {release_impact['typical_impact']:.1f}%, "
                f"which aligns with the observed anomaly score of {anomaly_score:.2f}."
            )

        return explanation

    def _generate_suspicious_explanation(
        self,
        anomaly_date: date,
        series_id: str,
        anomaly_score: float,
        related_events: List[KnownEvent],
    ) -> str:
        event_info = ""
        if related_events:
            event_names = ", ".join([e.name for e in related_events])
            event_info = (
                f" There is a known event ({event_names}) on or near this date, "
                f"but the magnitude of the anomaly ({anomaly_score:.2f}) exceeds typical expectations."
            )

        explanation = (
            f"The anomaly detected on {anomaly_date.isoformat()} for {series_id} "
            f"is classified as SUSPICIOUS.{event_info} "
            f"This could indicate either an unusual data release or a genuine market event "
            f"that warrants further investigation."
        )

        return explanation

    def _generate_genuine_explanation(
        self,
        anomaly_date: date,
        series_id: str,
        anomaly_score: float,
    ) -> str:
        explanation = (
            f"The anomaly detected on {anomaly_date.isoformat()} for {series_id} "
            f"is classified as GENUINE with high confidence. "
            f"No major FRED releases or known economic events coincide with this date, "
            f"yet the anomaly score of {anomaly_score:.2f} indicates a significant deviation "
            f"from expected values. This represents a true outlier that may reflect "
            f"genuine economic phenomena or data quality issues requiring attention."
        )

        return explanation

    def explain_anomaly(self, classification: AnomalyClassification) -> str:
        return classification.explanation

    def save_classified_anomalies(
        self,
        classifications: List[AnomalyClassification],
    ) -> int:
        if not classifications:
            return 0

        try:
            import psycopg2

            conn = psycopg2.connect(self.db_connection)
            cur = conn.cursor()

            count = 0
            for cls in classifications:
                try:
                    cur.execute(
                        """
                        INSERT INTO classified_anomalies 
                        (series_id, date, anomaly_score, classification, confidence, 
                         explanation, related_events, release_context, factors, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (series_id, date) DO UPDATE SET
                            anomaly_score = EXCLUDED.anomaly_score,
                            classification = EXCLUDED.classification,
                            confidence = EXCLUDED.confidence,
                            explanation = EXCLUDED.explanation,
                            related_events = EXCLUDED.related_events,
                            release_context = EXCLUDED.release_context,
                            factors = EXCLUDED.factors,
                            updated_at = NOW()
                        """,
                        (
                            cls.series_id,
                            cls.date,
                            cls.anomaly_score,
                            cls.classification.value,
                            cls.confidence,
                            cls.explanation,
                            str([e.name for e in cls.related_events]),
                            str(cls.release_context),
                            str(cls.factors),
                        ),
                    )
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to insert classification: {e}")
                    continue

            conn.commit()
            cur.close()
            conn.close()

            logger.info(f"Saved {count} classified anomalies")
            return count

        except ImportError:
            logger.warning("psycopg2 not available, skipping database save")
            return 0
        except Exception as e:
            logger.error(f"Database save failed: {e}")
            return 0

    def get_anomaly_explanations(
        self,
        series_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        classification: Optional[ClassificationType] = None,
    ) -> List[Dict[str, Any]]:
        try:
            import psycopg2
            import json

            conn = psycopg2.connect(self.db_connection)
            cur = conn.cursor()

            sql = "SELECT * FROM classified_anomalies WHERE 1=1"
            params = []

            if series_id:
                sql += " AND series_id = %s"
                params.append(series_id)
            if start_date:
                sql += " AND date >= %s"
                params.append(start_date)
            if end_date:
                sql += " AND date <= %s"
                params.append(end_date)
            if classification:
                sql += " AND classification = %s"
                params.append(classification.value)

            sql += " ORDER BY date DESC"

            cur.execute(sql, params)
            rows = cur.fetchall()

            columns = [desc[0] for desc in cur.description]
            results = []

            for row in rows:
                record = dict(zip(columns, row))
                if "related_events" in record and record["related_events"]:
                    try:
                        record["related_events"] = json.loads(
                            record["related_events"].replace("'", '"')
                        )
                    except Exception:
                        pass
                if "release_context" in record and record["release_context"]:
                    try:
                        record["release_context"] = json.loads(
                            record["release_context"].replace("'", '"')
                        )
                    except Exception:
                        pass
                if "factors" in record and record["factors"]:
                    try:
                        record["factors"] = json.loads(record["factors"].replace("'", '"'))
                    except Exception:
                        pass
                results.append(record)

            cur.close()
            conn.close()

            return results

        except ImportError:
            logger.warning("psycopg2 not available")
            return []
        except Exception as e:
            logger.error(f"Failed to retrieve explanations: {e}")
            return []

    def batch_classify(
        self,
        anomalies: List[Dict[str, Any]],
    ) -> List[AnomalyClassification]:
        results = []

        for anomaly in anomalies:
            result = self.classify_anomaly(
                anomaly_date=anomaly.get("date"),
                series_id=anomaly.get("series_id"),
                anomaly_score=anomaly.get("score", anomaly.get("anomaly_score", 0)),
                historical_values=anomaly.get("historical_values"),
            )
            results.append(result)

        return results

    def get_upcoming_releases(
        self,
        days_ahead: int = 30,
        series_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        events = self.load_calendar(start_date=today, end_date=end_date)

        if series_id:
            events = [
                e
                for e in events
                if any(
                    series_id.upper() in aff.upper() or aff.upper() in series_id.upper()
                    for aff in e.affected_series
                )
            ]

        return [
            {
                "name": e.name,
                "date": e.date.isoformat(),
                "type": e.event_type.value,
                "importance": e.importance.value,
                "affected_series": e.affected_series,
                "days_until": (e.date - today).days,
            }
            for e in sorted(events, key=lambda x: x.date)
        ]


def get_semantic_detector(fred_client: Optional[Any] = None) -> SemanticAnomalyDetector:
    return SemanticAnomalyDetector(fred_client=fred_client)
