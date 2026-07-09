# Conector SQL Server (CON-018)

Conector Ruvic de solo lectura para Microsoft SQL Server. Permite listar
tablas, leer datos con límite, obtener estadísticas de tablas y analizar el
plan ESTIMADO de ejecución de un query sin ejecutarlo.

## Instalación

```bash
pip install git+https://github.com/Dgirto/SQL-Server.git#subdirectory=lib
```

Python 3.10+. Dependencia única: `pymssql>=2.3,<3.0` (empaqueta FreeTDS, no
requiere instalar drivers ODBC de Microsoft por separado en el runtime).

## Prerrequisito importante: autenticación en modo mixto

SQL Server, por defecto, solo permite **Windows Authentication**. Este
conector usa **SQL Authentication** (usuario/contraseña), así que el
servidor debe tener habilitado el **modo de autenticación mixto**
(SQL Server and Windows Authentication mode) — si no, el login con
usuario/contraseña fallará aunque las credenciales sean correctas.

## Permisos requeridos en el servidor

Crea un login y usuario dedicados de solo lectura:

```sql
CREATE LOGIN ruvic_reader WITH PASSWORD = 'CAMBIA_ESTA_CONTRASEÑA';

USE tu_base_de_datos;
CREATE USER ruvic_reader FOR LOGIN ruvic_reader;
GRANT SELECT ON SCHEMA::dbo TO ruvic_reader;
GRANT SHOWPLAN TO ruvic_reader;
```

- `SELECT` sobre el/los esquemas a exponer: necesario para `db.read` y
  `db.stats` (las vistas de catálogo `sys.tables`/`sys.columns`/etc. son
  visibles para cualquier login con algún permiso sobre el objeto).
- `SHOWPLAN`: necesario para `db.explain` (permite compilar y ver el plan
  de un query sin ejecutarlo, sin dar permiso de escritura).
- No se otorgan permisos de escritura ni administración.

## Variables de entorno (`RUVIC_MSSQL_*`)

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `RUVIC_MSSQL_HOST` | Sí | Host del servidor |
| `RUVIC_MSSQL_PORT` | No (default `1433`) | Puerto |
| `RUVIC_MSSQL_DATABASE` | Sí | Base de datos a consultar |
| `RUVIC_MSSQL_USERNAME` | Sí | Login de SQL Server |
| `RUVIC_MSSQL_PASSWORD` | Sí | Contraseña |
| `RUVIC_MSSQL_CONNECT_TIMEOUT` | No (default `10`) | Timeout de conexión en segundos |

## Pruebas locales

Con SQL Server ya instalado (modo mixto habilitado, TCP/IP habilitado en
SQL Server Configuration Manager):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ./lib

export RUVIC_MSSQL_HOST=localhost
export RUVIC_MSSQL_PORT=1433
export RUVIC_MSSQL_DATABASE=demo
export RUVIC_MSSQL_USERNAME=ruvic_reader
export RUVIC_MSSQL_PASSWORD=CambiaEstaClave123!

python test_connection.py
python validate_local.py
```

Prueba también los casos de error (contraseña incorrecta, host inalcanzable,
tabla inexistente, esquema sin permiso) y verifica que los mensajes sean
claros.

## Notas de integración

- `read_table` usa `SELECT TOP (n) * FROM [schema].[table]` con `n` ya
  validado y acotado (1–10000) en Python antes de interpolarse — no hay
  binding de parámetro para `TOP` porque no todas las versiones/drivers lo
  aceptan de forma consistente, pero el valor nunca proviene de texto libre
  del usuario sin pasar por `int()` y `min()/max()`.
- `explain_query` usa `SET SHOWPLAN_XML ON` — SQL Server compila y
  planifica el statement sin ejecutarlo. Solo acepta `SELECT` (rechaza
  `;` múltiples y cualquier otro tipo de sentencia).
- pymssql/FreeTDS no exponen un código de error limpio (`errno`) como otros
  drivers: la clasificación de errores (`MssqlAuthError` /
  `MssqlNetworkError` / `MssqlDataError`) se hace por patrones de texto en
  el mensaje del driver. Si el mensaje real de tu versión de SQL Server no
  calza con ninguno de los patrones conocidos, cae a un `MssqlDataError`
  genérico (nunca se propaga la excepción cruda).
