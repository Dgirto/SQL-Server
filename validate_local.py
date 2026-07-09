"""Validacion local del conector mssql: ejercita las 4 capacidades.

Uso:
    python validate_local.py

Requiere las variables RUVIC_MSSQL_* exportadas en el entorno.
"""

from ruvic_mssql_connector import MssqlClient, setup_logging

setup_logging("INFO")
client = MssqlClient()

print("== 1. Tablas ==")
for t in client.list_tables():
    print(f"  {t['schema']}.{t['table']} (~{t['rows_estimate']} filas)")

print("== 2. Datos de clientes ==")
for row in client.read_table("clientes", limit=10):
    print(f"  {row}")

print("== 3. Estadisticas ==")
stats = client.table_stats("clientes")
print(f"  filas={stats['row_count']} tamano={stats['total_size']}")
print(f"  columnas={[c['name'] for c in stats['columns']]}")

print("== 4. Plan estimado ==")
plan = client.explain_query("SELECT * FROM clientes WHERE ciudad = 'Bogota'")
print(f"  costo={plan['total_cost']} filas_estimadas={plan['estimated_rows']}")
