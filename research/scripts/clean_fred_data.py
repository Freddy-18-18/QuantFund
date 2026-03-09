#!/usr/bin/env python3
"""
FRED Data Cleaning Pipeline Script
===================================

Comprehensive data cleaning pipeline for FRED economic time series:
- Quality checks (missing values, duplicates, consistency)
- Outlier detection using multiple methods
- Data imputation
- Feature generation

Usage:
    python clean_fred_data.py --all --verbose
    python clean_fred_data.py --series GDP,CPIAUCSL --features-only
    python clean_fred_data.py --all --parallel --workers 8

Options:
    --series       Process specific series (comma-separated)
    --all          Process all series in database
    --quality-only Only run quality checks
    --outliers-only Only detect outliers
    --impute-only  Only run imputation
    --features-only Only generate features
    --parallel     Enable parallel processing
    --workers      Number of parallel workers (default: 4)
    --verbose      Detailed logging
    --dry-run      Preview without saving
    --report-path  Path to save JSON report
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from quantfund.data.fred_quality import (
    FredQualityController,
    DatabaseConnection as QualityDBConnection,
    DataQualityResult,
    CombinedOutlierResult,
    ImputationResult,
    Frequency,
)
from quantfund.data.fred_transform import FredTransformer
from quantfund.data.fred_features import FredFeatureEngine, FeatureConfig


@dataclass
class SeriesProcessingResult:
    """Result of processing a single series."""

    series_id: str
    success: bool
    error: Optional[str] = None
    quality_check_passed: bool = False
    outliers_detected: int = 0
    missing_values_handled: int = 0
    features_generated: int = 0
    processing_time_seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)


@dataclass
class PipelineSummary:
    """Summary of the entire pipeline run."""

    total_series: int = 0
    successful: int = 0
    failed: int = 0
    total_outliers: int = 0
    total_missing_imputed: int = 0
    total_features: int = 0
    total_processing_time: float = 0.0
    failed_series: List[Dict[str, str]] = field(default_factory=list)
    series_results: List[Dict[str, Any]] = field(default_factory=list)


class FredDataCleaner:
    """Main class for FRED data cleaning pipeline."""

    def __init__(
        self,
        db_connection: Optional[str] = None,
        verbose: bool = False,
        dry_run: bool = False,
    ):
        self.verbose = verbose
        self.dry_run = dry_run

        conn_str = db_connection or os.environ.get(
            "DATABASE_URL", "postgresql://localhost/quantfund"
        )

        self.quality_db = QualityDBConnection(conn_str)
        self.quality_controller = FredQualityController(self.quality_db)
        self.transformer = FredTransformer(db_connection=conn_str)
        self.feature_engine = FredFeatureEngine(db_connection=conn_str)

        self._setup_logging()

    def _setup_logging(self) -> None:
        """Configure logging."""
        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger = logging.getLogger(__name__)

    def get_all_series(self) -> List[str]:
        """Get all series IDs from database."""
        query = "SELECT series_id FROM fred_series ORDER BY series_id"
        results = self.quality_db.execute_query(query)
        if not results:
            return []
        return [r[0] for r in results]

    def get_series_data(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get series data from database."""
        return self.quality_controller.get_series_data(series_id, start_date, end_date)

    def run_quality_checks(
        self,
        series_id: str,
        save_to_db: bool = True,
    ) -> Tuple[DataQualityResult, Optional[str]]:
        """Run quality checks for a series."""
        try:
            report = self.quality_controller.generate_quality_report(
                series_id=series_id,
                save_to_db=save_to_db and not self.dry_run,
                apply_imputation=False,
            )
            return report.data_quality, None
        except Exception as e:
            return None, str(e)

    def run_outlier_detection(
        self,
        series_id: str,
        save_to_db: bool = True,
    ) -> Tuple[CombinedOutlierResult, Optional[str]]:
        """Run outlier detection for a series."""
        try:
            df = self.get_series_data(series_id)
            if df.empty:
                return None, "No data available"

            from quantfund.data.fred_quality import OutlierDetector

            outliers = OutlierDetector.detect_all_outliers(df, series_id)

            if save_to_db and not self.dry_run and outliers.consensus_count > 0:
                from quantfund.data.fred_quality import AnomalyDatabase

                AnomalyDatabase.save_anomalies_to_db(
                    self.quality_db, series_id, outliers, overwrite=True
                )

            return outliers, None
        except Exception as e:
            return None, str(e)

    def run_imputation(
        self,
        series_id: str,
    ) -> Tuple[pd.DataFrame, int, Optional[str]]:
        """Run imputation for a series."""
        try:
            df = self.get_series_data(series_id)
            if df.empty:
                return df, 0, "No data available"

            from quantfund.data.fred_quality import DataImputer, FrequencyDetector

            frequency = FrequencyDetector.detect(df)

            imputation_result = DataImputer.impute_all(df, frequency)

            return (
                imputation_result.data_after,
                imputation_result.imputed_count,
                None,
            )
        except Exception as e:
            return pd.DataFrame(), 0, str(e)

    def run_feature_generation(
        self,
        series_id: str,
        save_to_db: bool = True,
    ) -> Tuple[pd.DataFrame, int, Optional[str]]:
        """Generate features for a series."""
        try:
            features = self.feature_engine.compute_all_features(series_id)

            if features.empty:
                return features, 0, None

            feature_count = len([c for c in features.columns if c != "date"])

            if save_to_db and not self.dry_run:
                self.feature_engine.save_to_feature_store(series_id, features)

            return features, feature_count, None
        except Exception as e:
            return pd.DataFrame(), 0, str(e)

    def process_series(
        self,
        series_id: str,
        run_quality: bool = True,
        run_outliers: bool = True,
        run_imputation: bool = True,
        run_features: bool = True,
    ) -> SeriesProcessingResult:
        """Process a single series through the pipeline."""
        start_time = time.time()
        result = SeriesProcessingResult(series_id=series_id, success=False)

        try:
            if run_quality:
                quality_result, error = self.run_quality_checks(series_id)
                if error:
                    result.warnings.append(f"Quality check error: {error}")
                else:
                    result.quality_check_passed = quality_result.is_valid

            if run_outliers:
                outliers, error = self.run_outlier_detection(series_id)
                if error:
                    result.warnings.append(f"Outlier detection error: {error}")
                elif outliers:
                    result.outliers_detected = outliers.consensus_count

            if run_imputation:
                df, imputed_count, error = self.run_imputation(series_id)
                if error:
                    result.warnings.append(f"Imputation error: {error}")
                else:
                    result.missing_values_handled = imputed_count

            if run_features:
                features, feature_count, error = self.run_feature_generation(series_id)
                if error:
                    result.warnings.append(f"Feature generation error: {error}")
                else:
                    result.features_generated = feature_count

            result.success = True

        except Exception as e:
            result.error = str(e)
            self.logger.error(f"Error processing {series_id}: {e}")

        result.processing_time_seconds = time.time() - start_time
        return result

    def process_series_list(
        self,
        series_ids: List[str],
        run_quality: bool = True,
        run_outliers: bool = True,
        run_imputation: bool = True,
        run_features: bool = True,
    ) -> PipelineSummary:
        """Process multiple series sequentially."""
        summary = PipelineSummary(total_series=len(series_ids))

        self.logger.info(f"Processing {len(series_ids)} series...")

        for i, series_id in enumerate(series_ids, 1):
            if self.verbose:
                self.logger.info(f"Processing {series_id} ({i}/{len(series_ids)})")

            result = self.process_series(
                series_id=series_id,
                run_quality=run_quality,
                run_outliers=run_outliers,
                run_imputation=run_imputation,
                run_features=run_features,
            )

            summary.series_results.append(asdict(result))

            if result.success:
                summary.successful += 1
                summary.total_outliers += result.outliers_detected
                summary.total_missing_imputed += result.missing_values_handled
                summary.total_features += result.features_generated
            else:
                summary.failed += 1
                summary.failed_series.append(
                    {
                        "series_id": series_id,
                        "error": result.error or "Unknown error",
                    }
                )

            if self.verbose and result.warnings:
                for warning in result.warnings:
                    self.logger.warning(f"  {series_id}: {warning}")

        summary.total_processing_time = sum(
            r["processing_time_seconds"] for r in summary.series_results
        )

        return summary

    def process_series_parallel(
        self,
        series_ids: List[str],
        max_workers: int = 4,
        run_quality: bool = True,
        run_outliers: bool = True,
        run_imputation: bool = True,
        run_features: bool = True,
    ) -> PipelineSummary:
        """Process multiple series in parallel."""
        summary = PipelineSummary(total_series=len(series_ids))

        self.logger.info(f"Processing {len(series_ids)} series with {max_workers} workers...")

        def process_single(series_id: str) -> SeriesProcessingResult:
            cleaner = FredDataCleaner(
                db_connection=self.quality_db.connection_string,
                verbose=False,
                dry_run=self.dry_run,
            )
            return cleaner.process_series(
                series_id=series_id,
                run_quality=run_quality,
                run_outliers=run_outliers,
                run_imputation=run_imputation,
                run_features=run_features,
            )

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_single, sid): sid for sid in series_ids}

            completed = 0
            for future in as_completed(futures):
                completed += 1
                result = future.result()
                summary.series_results.append(asdict(result))

                if result.success:
                    summary.successful += 1
                    summary.total_outliers += result.outliers_detected
                    summary.total_missing_imputed += result.missing_values_handled
                    summary.total_features += result.features_generated
                else:
                    summary.failed += 1
                    summary.failed_series.append(
                        {
                            "series_id": result.series_id,
                            "error": result.error or "Unknown error",
                        }
                    )

                if self.verbose:
                    status = "OK" if result.success else "FAIL"
                    self.logger.info(
                        f"[{completed}/{len(series_ids)}] {result.series_id}: {status}"
                    )

        summary.total_processing_time = sum(
            r["processing_time_seconds"] for r in summary.series_results
        )

        return summary


def print_summary(summary: PipelineSummary, verbose: bool = False) -> None:
    """Print pipeline summary."""
    print("\n" + "=" * 60)
    print("FRED DATA CLEANING PIPELINE - SUMMARY REPORT")
    print("=" * 60)

    print(f"\nTotal Series Processed: {summary.total_series}")
    print(f"  Successful: {summary.successful}")
    print(f"  Failed: {summary.failed}")

    print(f"\nOutliers Detected: {summary.total_outliers}")
    print(f"Missing Values Imputed: {summary.total_missing_imputed}")
    print(f"Features Generated: {summary.total_features}")

    print(f"\nTotal Processing Time: {summary.total_processing_time:.2f}s")
    if summary.total_series > 0:
        avg_time = summary.total_processing_time / summary.total_series
        print(f"Average Time per Series: {avg_time:.2f}s")

    if summary.failed_series:
        print("\n" + "-" * 40)
        print("FAILED SERIES:")
        print("-" * 40)
        for failed in summary.failed_series:
            print(f"  - {failed['series_id']}: {failed['error']}")

    if verbose and summary.series_results:
        print("\n" + "-" * 40)
        print("SERIES DETAILS:")
        print("-" * 40)
        for result in summary.series_results[:10]:
            print(f"\n{result['series_id']}:")
            print(f"  Success: {result['success']}")
            print(f"  Outliers: {result['outliers_detected']}")
            print(f"  Imputed: {result['missing_values_handled']}")
            print(f"  Features: {result['features_generated']}")
            print(f"  Time: {result['processing_time_seconds']:.2f}s")
            if result["warnings"]:
                print(f"  Warnings: {result['warnings']}")

    print("\n" + "=" * 60)


def save_report(summary: PipelineSummary, path: str) -> None:
    """Save detailed report to JSON file."""
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_series": summary.total_series,
        "successful": summary.successful,
        "failed": summary.failed,
        "total_outliers": summary.total_outliers,
        "total_missing_imputed": summary.total_missing_imputed,
        "total_features": summary.total_features,
        "total_processing_time_seconds": summary.total_processing_time,
        "failed_series": summary.failed_series,
        "series_results": summary.series_results,
    }

    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nDetailed report saved to: {path}")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="FRED Data Cleaning Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --all --verbose
  %(prog)s --series GDP,CPIAUCSL --features-only
  %(prog)s --all --parallel --workers 8
  %(prog)s --series UNRATE --quality-only --verbose
        """,
    )

    parser.add_argument(
        "--series",
        type=str,
        help="Process specific series (comma-separated)",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all series in database",
    )

    parser.add_argument(
        "--quality-only",
        action="store_true",
        help="Only run quality checks",
    )

    parser.add_argument(
        "--outliers-only",
        action="store_true",
        help="Only detect outliers",
    )

    parser.add_argument(
        "--impute-only",
        action="store_true",
        help="Only run imputation",
    )

    parser.add_argument(
        "--features-only",
        action="store_true",
        help="Only generate features",
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
        "--verbose",
        action="store_true",
        help="Detailed logging",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without saving",
    )

    parser.add_argument(
        "--report-path",
        type=str,
        help="Path to save JSON report",
    )

    parser.add_argument(
        "--db-url",
        type=str,
        help="Database connection URL (overrides DATABASE_URL env var)",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    if not args.series and not args.all:
        print("Error: Must specify either --series or --all")
        return 1

    if args.dry_run:
        print("DRY RUN MODE - No changes will be saved to database")

    cleaner = FredDataCleaner(
        db_connection=args.db_url,
        verbose=args.verbose,
        dry_run=args.dry_run,
    )

    if args.series:
        series_ids = [s.strip() for s in args.series.split(",")]
    else:
        series_ids = cleaner.get_all_series()
        if not series_ids:
            print("Error: No series found in database")
            return 1
        print(f"Found {len(series_ids)} series in database")

    run_quality = not (args.outliers_only or args.impute_only or args.features_only)
    run_outliers = not (args.quality_only or args.impute_only or args.features_only)
    run_imputation = not (args.quality_only or args.outliers_only or args.features_only)
    run_features = not (args.quality_only or args.outliers_only or args.impute_only)

    if args.verbose:
        print("\nPipeline Steps:")
        if run_quality:
            print("  [1] Quality Checks")
        if run_outliers:
            print("  [2] Outlier Detection")
        if run_imputation:
            print("  [3] Imputation")
        if run_features:
            print("  [4] Feature Generation")
        print()

    try:
        if args.parallel and len(series_ids) > 1:
            summary = cleaner.process_series_parallel(
                series_ids=series_ids,
                max_workers=args.workers,
                run_quality=run_quality,
                run_outliers=run_outliers,
                run_imputation=run_imputation,
                run_features=run_features,
            )
        else:
            summary = cleaner.process_series_list(
                series_ids=series_ids,
                run_quality=run_quality,
                run_outliers=run_outliers,
                run_imputation=run_imputation,
                run_features=run_features,
            )

        print_summary(summary, verbose=args.verbose)

        if args.report_path:
            save_report(summary, args.report_path)

        return 0 if summary.failed == 0 else 1

    except KeyboardInterrupt:
        print("\n\nPipeline interrupted by user")
        return 130
    except Exception as e:
        print(f"\nError: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
