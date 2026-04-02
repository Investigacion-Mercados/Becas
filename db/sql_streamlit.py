from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from .sql_connection import create_sql_engine, read_sql_df, read_table_df


@st.cache_resource(show_spinner=False)
def get_sql_engine():
    """Retorna un engine cacheado a nivel de app Streamlit."""
    return create_sql_engine()


@st.cache_data(show_spinner=False, ttl=600)
def read_sql_cached(
    query: str,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Ejecuta una consulta cacheada para Streamlit."""
    return read_sql_df(query=query, params=params, engine=get_sql_engine())


@st.cache_data(show_spinner=False, ttl=600)
def read_table_cached(
    table_name: str,
    columns: list[str] | None = None,
    where_clause: str | None = None,
    params: dict[str, Any] | None = None,
    order_by: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Lee una tabla cacheada para Streamlit."""
    return read_table_df(
        table_name=table_name,
        columns=columns,
        where_clause=where_clause,
        params=params,
        order_by=order_by,
        limit=limit,
        engine=get_sql_engine(),
    )

