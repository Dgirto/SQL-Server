"""Conector Ruvic de solo lectura para Microsoft SQL Server."""

from .client import MssqlClient
from .config import ENV_PREFIX, MssqlConfig
from .exceptions import (
    MssqlAuthError,
    MssqlConnectorError,
    MssqlDataError,
    MssqlNetworkError,
)
from .logging_utils import setup_logging

__all__ = [
    "ENV_PREFIX",
    "MssqlAuthError",
    "MssqlClient",
    "MssqlConfig",
    "MssqlConnectorError",
    "MssqlDataError",
    "MssqlNetworkError",
    "setup_logging",
]

__version__ = "1.0.0"
