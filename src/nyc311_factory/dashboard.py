"""Live dashboard reads; each call executes SQL against PostgreSQL via SQLAlchemy."""
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from .exceptions import ConfigError


def dashboard_sql(query_number, sql_path="sql/002_dashboard_queries.sql"):
    if query_number not in range(1, 6):
        raise ValueError("query_number must be from 1 to 5")
    path = Path(sql_path)
    if not path.is_file():
        raise ConfigError(f"dashboard SQL file not found: {path}")
    blocks = path.read_text(encoding="utf-8").split("-- Q")
    try:
        block = next(part for part in blocks if part.startswith(f"{query_number}:"))
    except StopIteration as exc:
        raise ConfigError(f"query {query_number} was not found in {path}") from exc
    lines=block.splitlines()[1:]  # discard the numbered query heading
    while lines and lines[0].lstrip().startswith("--"):
        lines=lines[1:]
    statement="\n".join(lines).split(";",1)[0].strip()
    if not statement:
        raise ConfigError(f"query {query_number} has no SQL statement in {path}")
    return statement


def read_dashboard(query_number, params=None, url=None, sql_path="sql/002_dashboard_queries.sql"):
    """Run one parameterized live dashboard SELECT and return its current rows."""
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("Set DATABASE_URL to a PostgreSQL SQLAlchemy URL")
    engine = create_engine(url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as connection:
            return pd.read_sql_query(text(dashboard_sql(query_number, sql_path)), connection, params=params or {})
    finally:
        engine.dispose()
