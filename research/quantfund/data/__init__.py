"""
Data Module for QuantFund
==========================

This module provides data access and processing capabilities for:
- OHLCV bar data with pipeline processing
- FRED (Federal Reserve Economic Data) client and utilities
- World Bank data client
- FRED data quality control and validation
- FRED data transformation and feature engineering
- FRED statistical anomaly detection
- FRED semantic anomaly detection (cross-references with economic events)

Main Components:
----------------
- Pipeline: OHLCVBar, DataCatalog, OHLCVLoader, PointInTimeWindow, ResampleFreq
- FRED Client: FredClient, get_fred_client
- FRED Quality: FredQualityController, detect_missing_values, zscore_outliers, generate_quality_report
- FRED Transform: FredTransformer
- FRED Features: FredFeatureEngine, FeatureConfig
- FRED Anomaly: FredAnomalyDetector, ZScoreDetector, STLDetector, etc.
- FRED Semantic Anomaly: SemanticAnomalyDetector, KnownEvent, AnomalyClassification
- World Bank: WorldBankClient, INDICATORS, COUNTRIES
"""

from .pipeline import (
    OHLCVBar,
    DataCatalog,
    OHLCVLoader,
    PointInTimeWindow,
    ResampleFreq,
)

from .fred_client import FredClient, get_fred_client
from .worldbank_client import WorldBankClient, INDICATORS, COUNTRIES

from .fred_quality import (
    FredQualityController,
    detect_missing_values,
    zscore_outliers,
    generate_quality_report,
    check_data_consistency,
    detect_duplicates,
    validate_value_ranges,
    mad_outliers,
    iqr_outliers,
    isolation_forest_outliers,
    detect_all_outliers,
    linear_interpolate,
    forward_fill,
    backward_fill,
    impute_all,
    save_anomalies_to_db,
    AnomalySeverity,
    Frequency,
    MissingValueGap,
    DataQualityResult,
    OutlierResult,
    CombinedOutlierResult,
    ImputationResult,
    QualityReport,
    DatabaseConnection as FredQualityDatabaseConnection,
)

from .fred_transform import FredTransformer, create_fred_transformer

from .fred_features import (
    FredFeatureEngine,
    FeatureConfig,
    create_feature_engine,
    FeatureResult,
    DatabaseConnection as FredFeaturesDatabaseConnection,
    XAUUSD_RELATED_SERIES,
)

from .fred_anomaly import (
    FredAnomalyDetector,
    ZScoreDetector,
    STLDetector,
    CusumDetector,
    ChowTestDetector,
    BinarySegmentationDetector,
    ArimaOutlierDetector,
    IsolationForestDetector,
    AutoencoderDetector,
    OneClassSVMDetector,
    MultivariateDetector,
    Anomaly,
    AnomalyReport,
    AnomalySeverity,
    ThresholdConfig,
    create_anomaly_detector,
)

from .fred_semantic_anomaly import (
    SemanticAnomalyDetector,
    EventType,
    ClassificationType,
    ReleaseImportance,
    KnownEvent,
    AnomalyClassification,
    get_semantic_detector,
)

__all__ = [
    # Pipeline
    "OHLCVBar",
    "DataCatalog",
    "OHLCVLoader",
    "PointInTimeWindow",
    "ResampleFreq",
    # FRED Client
    "FredClient",
    "get_fred_client",
    # FRED Quality
    "FredQualityController",
    "detect_missing_values",
    "zscore_outliers",
    "generate_quality_report",
    "check_data_consistency",
    "detect_duplicates",
    "validate_value_ranges",
    "mad_outliers",
    "iqr_outliers",
    "isolation_forest_outliers",
    "detect_all_outliers",
    "linear_interpolate",
    "forward_fill",
    "backward_fill",
    "impute_all",
    "save_anomalies_to_db",
    "AnomalySeverity",
    "Frequency",
    "MissingValueGap",
    "DataQualityResult",
    "OutlierResult",
    "CombinedOutlierResult",
    "ImputationResult",
    "QualityReport",
    "FredQualityDatabaseConnection",
    # FRED Transform
    "FredTransformer",
    "create_fred_transformer",
    # FRED Features
    "FredFeatureEngine",
    "FeatureConfig",
    "create_feature_engine",
    "FeatureResult",
    "FredFeaturesDatabaseConnection",
    "XAUUSD_RELATED_SERIES",
    # World Bank
    "WorldBankClient",
    "INDICATORS",
    "COUNTRIES",
    # FRED Anomaly Detection
    "FredAnomalyDetector",
    "ZScoreDetector",
    "STLDetector",
    "CusumDetector",
    "ChowTestDetector",
    "BinarySegmentationDetector",
    "ArimaOutlierDetector",
    "IsolationForestDetector",
    "AutoencoderDetector",
    "OneClassSVMDetector",
    "MultivariateDetector",
    "Anomaly",
    "AnomalyReport",
    "AnomalySeverity",
    "ThresholdConfig",
    "create_anomaly_detector",
    # FRED Semantic Anomaly Detection
    "SemanticAnomalyDetector",
    "EventType",
    "ClassificationType",
    "ReleaseImportance",
    "KnownEvent",
    "AnomalyClassification",
    "get_semantic_detector",
]
