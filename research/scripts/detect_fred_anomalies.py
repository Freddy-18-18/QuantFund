#!/usr/bin/env python3
"""
Daily FRED Anomaly Detection Job
=================================

Complete anomaly detection pipeline for FRED economic time series.
Runs statistical and ML-based detectors, generates alerts, and saves results.

Usage:
    python detect_fred_anomalies.py --all --verbose
    python detect_fred_anomalies.py --series GDP,UNRATE --detectors zscore,stl
    python detect_fred_anomalies.py --all --semantic --alerts --severity medium

Cron Setup (add to crontab):
    # Run daily at 6 AM
    0 6 * * * cd /path/to/QuantFund && python research/scripts/detect_fred_anomalies.py --all --alerts >> logs/anomaly_detection.log 2>&1

    # Run hourly for specific high-priority series
    0 * * * * cd /path/to/QuantFund && python research/scripts/detect_fred_anomalies.py --series GDP,UNRATE,CPIAUCSL --alerts >> logs/anomaly_detection.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from quantfund.data.fred_anomaly import (
    FredAnomalyDetector,
    Anomaly,
    AnomalyReport,
    AnomalySeverity,
    ThresholdConfig,
)
from quantfund.data.fred_semantic_anomaly import (
    SemanticAnomalyDetector,
    AnomalyClassification,
    ClassificationType,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("anomaly_detection")


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_string(cls, s: str) -> "Severity":
        return cls(s.lower())


@dataclass
class Alert:
    """Alert notification for critical anomalies."""

    id: str
    series_id: str
    date: date
    severity: str
    score: float
    method: str
    message: str
    classification: Optional[str] = None
    explanation: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "series_id": self.series_id,
            "date": self.date.isoformat() if isinstance(self.date, date) else str(self.date),
            "severity": self.severity,
            "score": self.score,
            "method": self.method,
            "message": self.message,
            "classification": self.classification,
            "explanation": self.explanation,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class DetectionSummary:
    """Summary statistics for detection run."""

    total_series_processed: int = 0
    total_anomalies: int = 0
    anomalies_by_severity: Dict[str, int] = field(default_factory=dict)
    anomalies_by_series: Dict[str, int] = field(default_factory=dict)
    trends: Dict[str, str] = field(default_factory=dict)
    processing_time_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_series_processed": self.total_series_processed,
            "total_anomalies": self.total_anomalies,
            "anomalies_by_severity": self.anomalies_by_severity,
            "anomalies_by_series": self.anomalies_by_series,
            "trends": self.trends,
            "processing_time_seconds": self.processing_time_seconds,
            "errors": self.errors,
        }


class AlertManager:
    """Manages alert generation and notification."""

    def __init__(
        self,
        output_dir: Optional[str] = None,
        email_config: Optional[Dict[str, str]] = None,
        log_file: Optional[str] = None,
    ):
        self.output_dir = Path(output_dir) if output_dir else Path("data/alerts")
        self.email_config = email_config
        self.log_file = log_file or "logs/alerts.log"
        self.alerts: List[Alert] = []

        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_alert(
        self,
        anomaly: Anomaly,
        classification: Optional[AnomalyClassification] = None,
    ) -> Alert:
        alert_id = f"ALERT-{anomaly.series_id}-{anomaly.date.strftime('%Y%m%d')}-{anomaly.method}"

        message = (
            f"[{anomaly.severity.value.upper()}] Anomaly detected in {anomaly.series_id} "
            f"on {anomaly.date}: score={anomaly.score:.2f} ({anomaly.method})"
        )

        alert = Alert(
            id=alert_id,
            series_id=anomaly.series_id,
            date=anomaly.date,
            severity=anomaly.severity.value,
            score=anomaly.score,
            method=anomaly.method,
            message=message,
            classification=classification.classification.value if classification else None,
            explanation=classification.explanation if classification else None,
        )

        self.alerts.append(alert)
        return alert

    def generate_dashboard_payload(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.now().isoformat(),
            "alert_count": len(self.alerts),
            "alerts_by_severity": self._count_by_severity(),
            "critical_alerts": [a.to_dict() for a in self.alerts if a.severity == "critical"],
            "recent_alerts": [a.to_dict() for a in self.alerts[:10]],
        }

    def _count_by_severity(self) -> Dict[str, int]:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for alert in self.alerts:
            if alert.severity in counts:
                counts[alert.severity] += 1
        return counts

    def save_alerts(self) -> int:
        if not self.alerts:
            return 0

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        alerts_file = self.output_dir / f"alerts_{timestamp}.json"

        with open(alerts_file, "w") as f:
            json.dump(
                {"alerts": [a.to_dict() for a in self.alerts]},
                f,
                indent=2,
            )

        logger.info(f"Saved {len(self.alerts)} alerts to {alerts_file}")

        if self.log_file:
            self._log_to_file()

        return len(self.alerts)

    def _log_to_file(self) -> None:
        log_path = Path(self.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, "a") as f:
            for alert in self.alerts:
                f.write(
                    f"{alert.created_at.isoformat()} | {alert.severity.upper():8} | {alert.message}\n"
                )

    def send_email_alerts(self) -> int:
        if not self.email_config or not self.alerts:
            return 0

        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            critical_alerts = [a for a in self.alerts if a.severity in ("critical", "high")]
            if not critical_alerts:
                return 0

            msg = MIMEMultipart()
            msg["From"] = self.email_config.get("from", "alerts@example.com")
            msg["To"] = self.email_config["to"]
            msg["Subject"] = (
                f"[FRED Anomaly Alert] {len(critical_alerts)} critical anomalies detected"
            )

            body = "Critical Anomaly Alerts:\n\n"
            for alert in critical_alerts[:20]:
                body += f"- {alert.message}\n"
                if alert.explanation:
                    body += f"  {alert.explanation[:200]}\n"
                body += "\n"

            msg.attach(MIMEText(body, "plain"))

            server = smtplib.SMTP(
                self.email_config.get("smtp_host", "localhost"),
                self.email_config.get("smtp_port", 587),
            )
            if self.email_config.get("username"):
                server.starttls()
                server.login(
                    self.email_config["username"],
                    self.email_config["password"],
                )
            server.send_message(msg)
            server.quit()

            logger.info(f"Sent {len(critical_alerts)} email alerts")
            return len(critical_alerts)

        except Exception as e:
            logger.error(f"Failed to send email alerts: {e}")
            return 0


class FredAnomalyJob:
    """Main job orchestrator for daily anomaly detection."""

    def __init__(
        self,
        db_connection: Optional[str] = None,
        data_retention_days: int = 365,
        min_severity: Severity = Severity.LOW,
        parallel: bool = False,
        workers: int = 4,
        verbose: bool = False,
        dry_run: bool = False,
    ):
        self.db_connection = db_connection or os.environ.get(
            "FRED_DB_CONNECTION",
            "postgresql://postgres:postgres@localhost:5432/freddata",
        )
        self.data_retention_days = data_retention_days
        self.min_severity = min_severity
        self.parallel = parallel
        self.workers = workers
        self.verbose = verbose
        self.dry_run = dry_run

        if verbose:
            logger.setLevel(logging.DEBUG)

        self.detector = FredAnomalyDetector(db_connection=self.db_connection)
        self.semantic_detector = SemanticAnomalyDetector(db_connection=self.db_connection)
        self.alert_manager = AlertManager()

        self.min_severity_order = [
            Severity.LOW,
            Severity.MEDIUM,
            Severity.HIGH,
            Severity.CRITICAL,
        ]

    def _get_severity_order(self, severity: str) -> int:
        mapping = {
            "low": 0,
            "medium": 1,
            "high": 2,
            "critical": 3,
        }
        return mapping.get(severity, 0)

    def _filter_by_severity(self, anomalies: List[Anomaly]) -> List[Anomaly]:
        min_order = self._get_severity_order(self.min_severity.value)
        return [a for a in anomalies if self._get_severity_order(a.severity.value) >= min_order]

    def load_series_list(self, series_ids: Optional[List[str]] = None) -> List[str]:
        if series_ids:
            return series_ids

        try:
            import psycopg2

            conn = psycopg2.connect(self.db_connection)
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT series_id FROM fred_series ORDER BY series_id")
            series_list = [row[0] for row in cur.fetchall()]
            cur.close()
            conn.close()

            return series_list
        except Exception as e:
            logger.warning(f"Could not fetch series from database: {e}")
            return self._get_default_series()

    def _get_default_series(self) -> List[str]:
        return [
            "GDP",
            "UNRATE",
            "CPIAUCSL",
            "PCEPI",
            "FEDFUNDS",
            "DGS10",
            "M2SL",
            "HOUST",
            "PAYEMS",
            "RETAIL",
        ]

    def load_series_data(
        self,
        series_id: str,
        start_date: Optional[date] = None,
    ) -> Optional[pd.DataFrame]:
        end_date = date.today()
        start_date = start_date or (end_date - timedelta(days=self.data_retention_days))

        try:
            import psycopg2

            conn = psycopg2.connect(self.db_connection)
            query = """
                SELECT date, value 
                FROM fred_data 
                WHERE series_id = %s AND date >= %s AND date <= %s
                ORDER BY date
            """
            df = pd.read_sql_query(query, conn, params=(series_id, start_date, end_date))
            conn.close()

            if df.empty:
                logger.warning(f"No data found for {series_id}")
                return None

            df["date"] = pd.to_datetime(df["date"])
            return df

        except Exception as e:
            logger.error(f"Failed to load data for {series_id}: {e}")
            return None

    def process_series(
        self,
        series_id: str,
        detectors: Optional[List[str]] = None,
        run_semantic: bool = False,
    ) -> Tuple[str, List[Anomaly], List[Anomaly], List[AnomalyClassification]]:
        logger.info(f"Processing series: {series_id}")

        df = self.load_series_data(series_id)
        if df is None or len(df) < 20:
            logger.warning(f"Insufficient data for {series_id}")
            return series_id, [], [], []

        try:
            if detectors:
                report = self.detector.run_all_detectors(df, series_id, detectors)
            else:
                report = self.detector.run_all_detectors(df, series_id)

            raw_anomalies = report.anomalies

            filtered_anomalies = self._filter_by_severity(raw_anomalies)

            consensus = self.detector.consensus_scoring(filtered_anomalies)
            consensus = self._filter_by_severity(consensus)

            classified = []
            if run_semantic and consensus:
                for anomaly in consensus:
                    try:
                        classification = self.semantic_detector.classify_anomaly(
                            anomaly_date=anomaly.date,
                            series_id=series_id,
                            anomaly_score=anomaly.score,
                        )
                        classified.append(classification)
                    except Exception as e:
                        logger.debug(f"Classification failed for {series_id}: {e}")

            logger.info(
                f"{series_id}: {len(filtered_anomalies)} raw, {len(consensus)} consensus anomalies"
            )

            return series_id, filtered_anomalies, consensus, classified

        except Exception as e:
            logger.error(f"Error processing {series_id}: {e}")
            return series_id, [], [], []

    def run_pipeline(
        self,
        series_ids: Optional[List[str]] = None,
        detectors: Optional[List[str]] = None,
        consensus_only: bool = False,
        run_semantic: bool = False,
        generate_alerts: bool = False,
    ) -> DetectionSummary:
        start_time = datetime.now()

        summary = DetectionSummary()

        if series_ids:
            all_series = series_ids
        else:
            all_series = self.load_series_list()

        summary.total_series_processed = len(all_series)

        all_anomalies: List[Anomaly] = []
        all_classified: List[Tuple[Anomaly, AnomalyClassification]] = []

        if self.parallel and len(all_series) > 1:
            logger.info(f"Running parallel processing with {self.workers} workers")

            with ProcessPoolExecutor(max_workers=self.workers) as executor:
                futures = {
                    executor.submit(
                        self._process_series_wrapper,
                        sid,
                        detectors,
                        consensus_only,
                        run_semantic,
                    ): sid
                    for sid in all_series
                }

                for future in as_completed(futures):
                    sid = futures[future]
                    try:
                        result = future.result()
                        if result:
                            sid, raw, cons, classified = result
                            all_anomalies.extend(raw)
                            all_classified.extend(
                                (a, c) for a, c in zip(cons, classified) if c is not None
                            )
                    except Exception as e:
                        logger.error(f"Worker failed for {sid}: {e}")
                        summary.errors.append(f"{sid}: {str(e)}")
        else:
            for sid in all_series:
                try:
                    result = self._process_series_wrapper(
                        sid, detectors, consensus_only, run_semantic
                    )
                    if result:
                        sid, raw, cons, classified = result
                        all_anomalies.extend(raw)
                        all_classified.extend(
                            (a, c) for a, c in zip(cons, classified) if c is not None
                        )
                except Exception as e:
                    logger.error(f"Processing failed for {sid}: {e}")
                    summary.errors.append(f"{sid}: {str(e)}")

        for anomaly in all_anomalies:
            severity = anomaly.severity.value
            summary.anomalies_by_severity[severity] = (
                summary.anomalies_by_severity.get(severity, 0) + 1
            )

            if anomaly.series_id:
                summary.anomalies_by_series[anomaly.series_id] = (
                    summary.anomalies_by_series.get(anomaly.series_id, 0) + 1
                )

        summary.trends = self._analyze_trends(all_anomalies)
        summary.total_anomalies = len(all_anomalies)

        if generate_alerts:
            self._generate_alerts(all_anomalies, all_classified)

        if not self.dry_run and all_anomalies:
            self._save_results(all_anomalies)

        processing_time = (datetime.now() - start_time).total_seconds()
        summary.processing_time_seconds = processing_time

        return summary

    def _process_series_wrapper(
        self,
        series_id: str,
        detectors: Optional[List[str]],
        consensus_only: bool,
        run_semantic: bool,
    ) -> Optional[Tuple[str, List[Anomaly], List[Anomaly], List[AnomalyClassification]]]:
        return self.process_series(
            series_id,
            detectors=detectors,
            run_semantic=run_semantic,
        )

    def _analyze_trends(self, anomalies: List[Anomaly]) -> Dict[str, str]:
        trends = {}

        by_series: Dict[str, List[Anomaly]] = {}
        for a in anomalies:
            if a.series_id:
                if a.series_id not in by_series:
                    by_series[a.series_id] = []
                by_series[a.series_id].append(a)

        for series_id, series_anomalies in by_series.items():
            if len(series_anomalies) < 2:
                continue

            sorted_anomalies = sorted(series_anomalies, key=lambda x: x.date)
            recent = sorted_anomalies[-5:]

            scores = [a.score for a in recent]
            if all(s > 0 for s in scores):
                trends[series_id] = "increasing"
            elif all(s < 0 for s in scores):
                trends[series_id] = "decreasing"
            else:
                trends[series_id] = "mixed"

        return trends

    def _generate_alerts(
        self,
        anomalies: List[Anomaly],
        classified: List[Tuple[Anomaly, AnomalyClassification]],
    ) -> None:
        critical = [a for a in anomalies if a.severity == AnomalySeverity.CRITICAL]
        high = [a for a in anomalies if a.severity == AnomalySeverity.HIGH]

        alert_anomalies = critical + high[:10]

        classified_dict = {c[0].date: c[1] for c in classified}

        for anomaly in alert_anomalies:
            classification = classified_dict.get(anomaly.date)
            self.alert_manager.create_alert(anomaly, classification)

        self.alert_manager.save_alerts()

    def _save_results(self, anomalies: List[Anomaly]) -> int:
        if not anomalies:
            return 0

        try:
            return self.detector.save_to_database(anomalies)
        except Exception as e:
            logger.error(f"Failed to save results: {e}")
            return 0

    def print_summary(self, summary: DetectionSummary) -> None:
        print("\n" + "=" * 60)
        print("ANOMALY DETECTION SUMMARY")
        print("=" * 60)
        print(f"Series Processed:    {summary.total_series_processed}")
        print(f"Total Anomalies:    {summary.total_anomalies}")
        print(f"Processing Time:    {summary.processing_time_seconds:.2f}s")
        print()

        print("By Severity:")
        for severity in ["critical", "high", "medium", "low"]:
            count = summary.anomalies_by_severity.get(severity, 0)
            print(f"  {severity.upper():8}: {count}")
        print()

        if summary.anomalies_by_series:
            print("Top Series by Anomaly Count:")
            sorted_series = sorted(
                summary.anomalies_by_series.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]
            for series_id, count in sorted_series:
                print(f"  {series_id:12}: {count}")
            print()

        if summary.trends:
            print("Trend Analysis:")
            for series_id, trend in summary.trends.items():
                print(f"  {series_id:12}: {trend}")
            print()

        if summary.errors:
            print("Errors:")
            for error in summary.errors[:5]:
                print(f"  - {error}")
            print()

        print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Daily FRED Anomaly Detection Job",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --all --verbose
  %(prog)s --series GDP,UNRATE --detectors zscore,stl
  %(prog)s --all --consensus-only
  %(prog)s --all --semantic --alerts --severity medium
  %(prog)s --all --parallel --workers 8
  %(prog)s --series GDP --dry-run
        """,
    )

    parser.add_argument(
        "--series",
        type=str,
        help="Comma-separated list of series IDs to process",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all series in database",
    )

    parser.add_argument(
        "--detectors",
        type=str,
        help="Comma-separated list of detectors to run (zscore, stl, cusum, chow_test, "
        "binary_segmentation, arima_outlier, isolation_forest, autoencoder, one_class_svm, multivariate_pca)",
    )

    parser.add_argument(
        "--consensus-only",
        action="store_true",
        help="Only run consensus scoring (skip individual detectors)",
    )

    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Include semantic analysis (release dates, events)",
    )

    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Enable parallel processing",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )

    parser.add_argument(
        "--alerts",
        action="store_true",
        help="Generate alerts for critical anomalies",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed logging",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview results without saving to database",
    )

    parser.add_argument(
        "--severity",
        type=str,
        choices=["low", "medium", "high", "critical"],
        default="low",
        help="Minimum severity to save (default: low)",
    )

    parser.add_argument(
        "--db-connection",
        type=str,
        help="Database connection string",
    )

    parser.add_argument(
        "--retention-days",
        type=int,
        default=365,
        help="Days of historical data to analyze (default: 365)",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.series and not args.all:
        logger.error("Please specify --series or --all")
        return 1

    series_ids = None
    if args.series:
        series_ids = [s.strip() for s in args.series.split(",")]

    detectors = None
    if args.detectors:
        detectors = [d.strip() for d in args.detectors.split(",")]

    job = FredAnomalyJob(
        db_connection=args.db_connection,
        data_retention_days=args.retention_days,
        min_severity=Severity.from_string(args.severity),
        parallel=args.parallel,
        workers=args.workers,
        verbose=args.verbose,
        dry_run=args.dry_run,
    )

    logger.info("Starting anomaly detection job")
    logger.info(f"Series: {series_ids or 'all'}")
    logger.info(f"Detectors: {detectors or 'all'}")
    logger.info(f"Semantic: {args.semantic}")
    logger.info(f"Alerts: {args.alerts}")

    summary = job.run_pipeline(
        series_ids=series_ids,
        detectors=detectors,
        consensus_only=args.consensus_only,
        run_semantic=args.semantic,
        generate_alerts=args.alerts,
    )

    job.print_summary(summary)

    if args.dry_run:
        logger.info("Dry run - results not saved")

    logger.info("Anomaly detection job completed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
