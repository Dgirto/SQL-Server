---
name: mssql
description: >
  Usa la librería ruvic_mssql_connector para consultar bases de datos
  Microsoft SQL Server en modo solo lectura - listar tablas (list_tables),
  leer datos (read_table), obtener estadísticas de tablas (table_stats) y
  analizar el plan ESTIMADO de ejecución de un query sin ejecutarlo
  (explain_query). Úsala cuando el usuario pida consultar, explorar o
  analizar una base de datos SQL Server.
triggers:
- sql server
- sqlserver
- mssql
- t-sql
- base de datos
- consultar tabla
- plan de ejecucion
---

# Conector SQL Server (ruvic_mssql_connector)

Librería Python de solo lectura para Microsoft SQL Server. Está **preinstalada en el runtime** cuando el conector está configurado (si no, instálala con `pip install git+https://github.com/Dgirto/conector-mssql.git#subdirectory=lib`).

## Regla crítica de credenciales

El código generado **NUNCA hardcodea credenciales**. Siempre se leen de variables de entorno, disponibles cuando el conector `mssql` está configurado:

| Variable | Contenido |
|----------|-----------|
| `RUVIC_MSSQL_HOST` | Host del servidor |
| `RUVIC_MSSQL_PORT` | Puerto (default 1433) |
| `RUVIC_MSSQL_DATABASE` | Nombre de la base de datos |
| `RUVIC_MSSQL_USERNAME` | Login de SQL Server |
| `RUVIC_MSSQL_PASSWORD` | Contraseña |
| `RUVIC_MSSQL_CONNECT_TIMEOUT` | (opcional) timeout en segundos |

Si estas variables NO existen, el conector no está configurado: no generes código que lo use; indica al usuario que lo configure en **Settings → Conectores**.

## Conexión (siempre igual)

```python
from ruvic_mssql_connector import MssqlClient

client = MssqlClient()  # lee RUVIC_MSSQL_* del entorno automáticamente
```

## Capacidad 1 — Listar tablas

```python
tables = client.list_tables(schema="dbo")
for t in tables:
    print(f"{t['schema']}.{t['table']}: ~{t['rows_estimate']} filas")
```

## Capacidad 2 — Leer una tabla

```python
rows = client.read_table("clientes", limit=50)
for row in rows:
    print(row)  # cada fila es un dict {columna: valor}
```

## Capacidad 3 — Estadísticas de una tabla

```python
stats = client.table_stats("ventas")
print(f"Filas: {stats['row_count']}, Tamaño: {stats['total_size']}")
for col in stats["columns"]:
    print(f"  {col['name']}: {col['type']} (nullable={col['nullable']})")
```

## Capacidad 4 — Plan ESTIMADO de ejecución de un query (sin ejecutarlo)

```python
plan = client.explain_query("SELECT * FROM ventas WHERE anio = 2026")
print(f"Costo estimado: {plan['total_cost']}")
print(f"Filas estimadas: {plan['estimated_rows']}")
```

`explain_query` usa `SET SHOWPLAN_XML ON`: en ese modo SQL Server solo compila y planifica el statement, **nunca lo ejecuta**. Solo acepta sentencias `SELECT`.

## Manejo de errores

```python
from ruvic_mssql_connector import (
    MssqlAuthError, MssqlDataError, MssqlNetworkError,
)

try:
    rows = client.read_table("pedidos")
except MssqlAuthError:
    print("Credenciales o permisos inválidos — revisa la configuración del conector")
except MssqlNetworkError:
    print("No se pudo alcanzar el servidor — revisa host/puerto/red")
except MssqlDataError as e:
    print(f"Error de datos: {e}")  # ej. la tabla no existe
```

## Buenas prácticas al generar código

1. Lee credenciales SOLO de las variables `RUVIC_MSSQL_*` (el constructor de `MssqlClient` ya lo hace).
2. Nunca imprimas `RUVIC_MSSQL_PASSWORD` en logs ni en la salida.
3. La librería es de SOLO LECTURA: no intentes INSERT/UPDATE/DELETE con ella.
4. Usa `limit` razonable en `read_table` (default 100) para no traer tablas enteras.
5. Para analizar rendimiento de un query usa `explain_query`, nunca lo ejecutes directamente.
6. El esquema por defecto es `dbo`; si el usuario menciona otro esquema, pásalo explícitamente.
