from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .sql_config import (
    SQL_DATABASE,
    SQL_DRIVER,
    SQL_SCHEMA,
    SQL_SERVER,
    SQL_TRUSTED_CONNECTION,
    qualified_table,
)


def build_connection_url(
    server: str = SQL_SERVER,
    database: str = SQL_DATABASE,
    driver: str = SQL_DRIVER,
    trusted_connection: str = SQL_TRUSTED_CONNECTION,
) -> str:
    """Construye la URL de conexion a SQL Server con autenticacion Windows."""
    odbc_connect = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Trusted_Connection={trusted_connection};"
        "TrustServerCertificate=yes;"
    )
    return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_connect)}"


def create_sql_engine(
    server: str = SQL_SERVER,
    database: str = SQL_DATABASE,
    driver: str = SQL_DRIVER,
    trusted_connection: str = SQL_TRUSTED_CONNECTION,
) -> Engine:
    """Crea un engine reutilizable para consultas de solo lectura."""
    return create_engine(
        build_connection_url(
            server=server,
            database=database,
            driver=driver,
            trusted_connection=trusted_connection,
        ),
        pool_pre_ping=True,
        future=True,
    )


def read_sql_df(
    query: str,
    params: dict[str, Any] | None = None,
    engine: Engine | None = None,
) -> pd.DataFrame:
    """Ejecuta una consulta y devuelve un DataFrame."""
    current_engine = engine or create_sql_engine()
    with current_engine.connect() as connection:
        return pd.read_sql(text(query), connection, params=params or {})


def read_table_df(
    table_name: str,
    columns: list[str] | None = None,
    where_clause: str | None = None,
    params: dict[str, Any] | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    schema: str = SQL_SCHEMA,
    engine: Engine | None = None,
) -> pd.DataFrame:
    """Lee una tabla del schema configurado con un SELECT base."""
    selected_columns = ", ".join(columns) if columns else "*"
    query_parts = [f"SELECT {selected_columns} FROM {qualified_table(table_name, schema)}"]

    if where_clause:
        query_parts.append(f"WHERE {where_clause}")
    if order_by:
        query_parts.append(f"ORDER BY {order_by}")
    if limit is not None:
        query_parts[0] = (
            f"SELECT TOP ({limit}) {selected_columns} "
            f"FROM {qualified_table(table_name, schema)}"
        )

    query = "\n".join(query_parts)
    return read_sql_df(query=query, params=params, engine=engine)

