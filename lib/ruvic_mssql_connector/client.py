"""Cliente de solo lectura para Microsoft SQL Server.

Capacidades:
- list_tables():      listar tablas de la base de datos.
- read_table():       leer filas de una tabla con límite.
- table_stats():      estadísticas de una tabla (filas, tamaño, columnas).
- explain_query():    plan ESTIMADO de ejecución de un query SIN ejecutarlo.

Las credenciales SIEMPRE provienen de variables de entorno RUVIC_MSSQL_*
(ver config.MssqlConfig.from_env). Prohibido hardcodearlas.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import pymssql

from .config import MssqlConfig
from .exceptions import (
    MssqlAuthError,
    MssqlConnectorError,
    MssqlDataError,
    MssqlNetworkError,
)
from .logging_utils import get_logger

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_SHOWPLAN_NS = {"sp": "http://schemas.microsoft.com/sqlserver/2004/07/showplan"}

# pymssql/FreeTDS no exponen un errno limpio como otros drivers: el número de
# error de SQL Server viaja embebido en el texto del mensaje. Se clasifica por
# patrones conocidos y cualquier caso no reconocido cae a un mensaje genérico
# (nunca se relanza la excepción cruda del driver).
_LOGIN_FAILED_PATTERNS = ("login failed", "password", "adodb.connection")
_MISSING_DB_PATTERNS = ("cannot open database", "database", "has not been recovered")
_PERMISSION_PATTERNS = (
    "permission was denied",
    "select permission",
    "showplan permission",
    "requires the",
)
_MISSING_OBJECT_PATTERNS = ("invalid object name",)


def _human_size(kilobytes: int | None) -> str:
    """Convierte KB (unidad nativa de sys.allocation_units) a algo legible."""
    if not kilobytes:
        return "0 KB"
    size = float(kilobytes)
    for unit in ("KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _validate_identifier(name: str, kind: str) -> None:
    """Valida nombres de tabla/esquema para evitar inyección SQL."""
    if not _IDENTIFIER_RE.match(name):
        raise MssqlDataError(
            f"Nombre de {kind} inválido: {name!r}. "
            "Solo se permiten letras, números y guion bajo."
        )


def _wrap_driver_error(exc: Exception, not_found_message: str) -> MssqlConnectorError:
    """Traduce un error del driver (pymssql/FreeTDS) a una excepción propia,
    sin dejar escapar nunca el tipo o mensaje crudo del driver."""
    message = str(exc).lower()
    if any(p in message for p in _PERMISSION_PATTERNS):
        return MssqlAuthError(
            "El login no tiene permiso suficiente para esa operación "
            "(se requiere SELECT sobre la tabla, o SHOWPLAN para explain_query)."
        )
    if any(p in message for p in _MISSING_OBJECT_PATTERNS):
        return MssqlDataError(not_found_message)
    if any(p in message for p in _LOGIN_FAILED_PATTERNS):
        return MssqlAuthError(
            "Autenticación fallida: usuario o contraseña inválidos."
        )
    if any(p in message for p in _MISSING_DB_PATTERNS):
        return MssqlDataError(not_found_message)
    return MssqlDataError(f"Error de datos: {exc}")


def _parse_showplan(raw_xml: str) -> dict[str, Any]:
    """Extrae costo y filas estimadas del XML de SHOWPLAN_XML."""
    root = ET.fromstring(raw_xml)
    stmt = root.find(".//sp:StmtSimple", _SHOWPLAN_NS)
    if stmt is None:
        stmt = root.find(".//sp:StmtCond", _SHOWPLAN_NS)
    total_cost = None
    estimated_rows = None
    if stmt is not None:
        cost_attr = stmt.get("StatementSubTreeCost")
        rows_attr = stmt.get("StatementEstRows")
        total_cost = float(cost_attr) if cost_attr is not None else None
        estimated_rows = float(rows_attr) if rows_attr is not None else None
    return {
        "total_cost": total_cost,
        "estimated_rows": estimated_rows,
        "plan_xml": raw_xml,
    }


class MssqlClient:
    """Cliente de solo lectura para Microsoft SQL Server.

    Args:
        config: configuración de conexión. Si se omite, se lee de las
            variables de entorno RUVIC_MSSQL_* (comportamiento estándar
            en el runtime de la plataforma).

    Ejemplo:
        >>> client = MssqlClient()          # lee RUVIC_MSSQL_* del entorno
        >>> client.list_tables()
        [{'schema': 'dbo', 'table': 'clientes', 'rows_estimate': 1520}]
    """

    def __init__(self, config: MssqlConfig | None = None) -> None:
        self.config = config or MssqlConfig.from_env()
        self._logger = get_logger()

    # ------------------------------------------------------------------ #
    # Conexión
    # ------------------------------------------------------------------ #

    def _connect(self):
        try:
            conn = pymssql.connect(
                server=self.config.host,
                port=str(self.config.port),
                database=self.config.database,
                user=self.config.username,
                password=self.config.password,
                login_timeout=self.config.connect_timeout,
                timeout=self.config.connect_timeout,
            )
        except pymssql.Error as exc:
            message = str(exc).lower()
            if any(p in message for p in _LOGIN_FAILED_PATTERNS):
                raise MssqlAuthError(
                    "Autenticación fallida: usuario o contraseña inválidos, "
                    "o el login no tiene acceso a la base de datos."
                ) from exc
            if any(p in message for p in _MISSING_DB_PATTERNS):
                raise MssqlDataError(
                    f"La base de datos {self.config.database!r} no existe "
                    "o el login no tiene acceso a ella."
                ) from exc
            raise MssqlNetworkError(
                f"No se pudo conectar a {self.config.host}:{self.config.port} "
                f"(timeout {self.config.connect_timeout}s). Verifica host, puerto "
                "y acceso de red."
            ) from exc
        return conn

    def ping(self) -> bool:
        """Verifica la conexión ejecutando SELECT 1.

        Returns:
            True si la conexión funciona.

        Raises:
            MssqlAuthError / MssqlNetworkError / MssqlDataError según el fallo.
        """
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
        finally:
            conn.close()
        self._logger.info("Ping exitoso a %s:%s", self.config.host, self.config.port)
        return True

    # ------------------------------------------------------------------ #
    # Capacidad 1: listar tablas
    # ------------------------------------------------------------------ #

    def list_tables(self, schema: str = "dbo") -> list[dict[str, Any]]:
        """Lista las tablas de un esquema con su conteo estimado de filas.

        Args:
            schema: esquema a inspeccionar (default "dbo").

        Returns:
            Lista de dicts: {"schema", "table", "rows_estimate"}.

        Ejemplo:
            >>> client.list_tables()
            [{'schema': 'dbo', 'table': 'ventas', 'rows_estimate': 89123}]
        """
        _validate_identifier(schema, "esquema")
        query = """
            SELECT s.name AS schema_name,
                   t.name AS table_name,
                   SUM(p.rows) AS rows_estimate
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)
            WHERE s.name = %s
            GROUP BY s.name, t.name
            ORDER BY t.name
        """
        conn = self._connect()
        try:
            cur = conn.cursor()
            try:
                cur.execute(query, (schema,))
                rows = [
                    {"schema": row[0], "table": row[1], "rows_estimate": row[2]}
                    for row in cur.fetchall()
                ]
            except pymssql.Error as exc:
                raise _wrap_driver_error(
                    exc, f'El esquema "{schema}" no existe.'
                ) from exc
            cur.close()
        finally:
            conn.close()
        self._logger.info("Se listaron %d tablas del esquema %s", len(rows), schema)
        return rows

    # ------------------------------------------------------------------ #
    # Capacidad 2: leer una tabla
    # ------------------------------------------------------------------ #

    def read_table(
        self,
        table: str,
        schema: str = "dbo",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Lee filas de una tabla como lista de diccionarios.

        Args:
            table: nombre de la tabla.
            schema: esquema (default "dbo").
            limit: máximo de filas a retornar (default 100, máximo 10000).

        Returns:
            Lista de dicts, una entrada por fila.

        Ejemplo:
            >>> client.read_table("clientes", limit=5)
            [{'id': 1, 'nombre': 'ACME', ...}, ...]
        """
        _validate_identifier(table, "tabla")
        _validate_identifier(schema, "esquema")
        limit = max(1, min(int(limit), 10_000))
        query = f"SELECT TOP ({limit}) * FROM [{schema}].[{table}]"
        conn = self._connect()
        try:
            cur = conn.cursor(as_dict=True)
            try:
                cur.execute(query)
                rows = cur.fetchall()
            except pymssql.Error as exc:
                raise _wrap_driver_error(
                    exc, f'La tabla "{schema}"."{table}" no existe.'
                ) from exc
            cur.close()
        finally:
            conn.close()
        self._logger.info(
            'Leídas %d filas de "%s"."%s" (limit=%d)', len(rows), schema, table, limit
        )
        return rows

    # ------------------------------------------------------------------ #
    # Capacidad 3: estadísticas de una tabla
    # ------------------------------------------------------------------ #

    def table_stats(self, table: str, schema: str = "dbo") -> dict[str, Any]:
        """Obtiene estadísticas de una tabla.

        Args:
            table: nombre de la tabla.
            schema: esquema (default "dbo").

        Returns:
            Dict con: row_count (exacto), total_size (legible, ej. "12.0 MB"),
            y columns (lista de {"name", "type", "nullable"}).

        Ejemplo:
            >>> client.table_stats("ventas")
            {'row_count': 89123, 'total_size': '12.0 MB', 'columns': [...]}
        """
        _validate_identifier(table, "tabla")
        _validate_identifier(schema, "esquema")
        qualified = f"[{schema}].[{table}]"
        columns_query = """
            SELECT c.name AS col_name,
                   ty.name AS type_name,
                   c.is_nullable
            FROM sys.columns c
            JOIN sys.types ty ON c.user_type_id = ty.user_type_id
            JOIN sys.tables t ON c.object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = %s AND t.name = %s
            ORDER BY c.column_id
        """
        size_query = """
            SELECT SUM(a.total_pages) * 8 AS total_kb
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            JOIN sys.indexes i ON t.object_id = i.object_id
            JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
            JOIN sys.allocation_units a ON p.partition_id = a.container_id
            WHERE s.name = %s AND t.name = %s
        """
        # sys.columns oculta las columnas si el login no tiene NINGÚN permiso
        # sobre el objeto (igual trato que "no existe"), así que no se puede
        # distinguir aquí "no existe" de "sin permiso" — el mensaje cubre
        # ambos casos para no afirmar algo falso.
        not_found = (
            f"La tabla {qualified} no existe o el login no tiene ningún "
            "permiso sobre ella (falta GRANT SELECT)."
        )
        conn = self._connect()
        try:
            cur = conn.cursor()
            try:
                cur.execute(columns_query, (schema, table))
                columns = [
                    {"name": row[0], "type": row[1], "nullable": bool(row[2])}
                    for row in cur.fetchall()
                ]
                if not columns:
                    raise MssqlDataError(not_found)

                cur.execute(size_query, (schema, table))
                size_row = cur.fetchone()
                total_kb = size_row[0] if size_row else 0

                cur.execute(f"SELECT COUNT(*) FROM {qualified}")
                row_count = cur.fetchone()[0]
            except pymssql.Error as exc:
                raise _wrap_driver_error(exc, not_found) from exc
            cur.close()
        finally:
            conn.close()
        return {
            "schema": schema,
            "table": table,
            "row_count": row_count,
            "total_size": _human_size(total_kb),
            "columns": columns,
        }

    # ------------------------------------------------------------------ #
    # Capacidad 4: plan ESTIMADO de un query (NUNCA lo ejecuta)
    # ------------------------------------------------------------------ #

    def explain_query(self, query: str) -> dict[str, Any]:
        """Describe el plan ESTIMADO de ejecución de un query SIN ejecutarlo.

        Usa SET SHOWPLAN_XML ON: en ese modo, SQL Server solo compila y
        planifica el statement siguiente, nunca lo ejecuta.

        Args:
            query: consulta SQL a analizar (solo se permite un statement,
                y debe ser un SELECT).

        Returns:
            Dict con: total_cost estimado, estimated_rows y el XML completo
            del plan (plan_xml).

        Ejemplo:
            >>> client.explain_query("SELECT * FROM ventas WHERE anio = 2026")
            {'total_cost': 0.0328, 'estimated_rows': 8912.0, 'plan_xml': '...'}
        """
        statement = query.strip().rstrip(";")
        if ";" in statement:
            raise MssqlDataError(
                "Solo se permite analizar un statement a la vez (sin ';')."
            )
        if not statement.lower().lstrip().startswith("select"):
            raise MssqlDataError(
                "explain_query solo acepta sentencias SELECT."
            )
        conn = self._connect()
        try:
            cur = conn.cursor()
            try:
                cur.execute("SET SHOWPLAN_XML ON")
                cur.execute(statement)
                row = cur.fetchone()
                raw_xml = row[0] if row else None
            except pymssql.Error as exc:
                raise _wrap_driver_error(
                    exc, f"Query inválido, no se pudo planificar: {exc}"
                ) from exc
            finally:
                try:
                    cur.execute("SET SHOWPLAN_XML OFF")
                except pymssql.Error:
                    pass
            cur.close()
        finally:
            conn.close()

        if not raw_xml:
            raise MssqlDataError("El servidor no devolvió un plan de ejecución.")
        return _parse_showplan(raw_xml)
