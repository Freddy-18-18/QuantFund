"""
QuantFund Research Layer
========================
Institutional-grade alpha research, feature engineering,
walk-forward validation, and portfolio allocation.
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("quantfund-research")
except PackageNotFoundError:
    __version__ = "0.1.0-dev"
