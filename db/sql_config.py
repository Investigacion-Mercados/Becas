from __future__ import annotations

import os


SQL_SERVER = os.getenv("SQL_SERVER", "SGCN05")
SQL_DATABASE = os.getenv("SQL_DATABASE", "BDD_Proyectos")
SQL_SCHEMA = os.getenv("SQL_SCHEMA", "salesforce")
SQL_DRIVER = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")
SQL_TRUSTED_CONNECTION = os.getenv("SQL_TRUSTED_CONNECTION", "yes")

PROPENSITY_TABLES = {
    "evento": "ps_oportunidad_evento",
    "beneficio": "ps_oportunidad_beneficio",
    "modelo": "ps_oportunidad_modelo",
}


def qualified_table(table_name: str, schema: str | None = None) -> str:
    """Devuelve el nombre completamente calificado de una tabla."""
    schema_name = schema or SQL_SCHEMA
    return f"[{schema_name}].[{table_name}]"

