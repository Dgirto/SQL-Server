"""Excepciones propias del conector SQL Server.

Separan los tres tipos de fallo que el usuario debe distinguir:
autenticación, red/servidor y datos. Nunca exponemos excepciones
crípticas del driver subyacente.
"""


class MssqlConnectorError(Exception):
    """Error base del conector."""


class MssqlAuthError(MssqlConnectorError):
    """Credenciales inválidas o permisos insuficientes."""


class MssqlNetworkError(MssqlConnectorError):
    """No se pudo alcanzar el servidor (host/puerto/red/timeout)."""


class MssqlDataError(MssqlConnectorError):
    """La operación es válida pero el objeto no existe o el query es inválido."""
