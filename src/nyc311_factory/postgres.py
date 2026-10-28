"""PostgreSQL destination for the curated stage-one dataset.

The destination is deliberately part of the factory package: ``nyc311 pg-load``
publishes its canonical case_level.csv, with replace-in-one-transaction semantics.
"""
import os
from pathlib import Path

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, MetaData, Table, Column, String, create_engine, text

from .contract import CASE_COLUMNS
from .exceptions import ConfigError


def _engine(url=None):
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("Set DATABASE_URL to a PostgreSQL SQLAlchemy URL")
    return create_engine(url, pool_pre_ping=True, future=True)


def load_curated_postgres(curated_dir, url=None, chunksize=1000):
    """Replace factory.stage1_cases from canonical curated output atomically."""
    import pandas as pd

    csv_path = Path(curated_dir) / "case_level.csv"
    if not csv_path.is_file():
        raise ConfigError(f"curated stage-one output not found: {csv_path}")
    engine = _engine(url)
    sql_types = {"string": String, "datetime": DateTime, "int": BigInteger, "float": Float}
    metadata = MetaData(schema="factory")
    columns=[]
    checks=[]
    for spec in CASE_COLUMNS:
        if spec.name=="unique_key":
            column_type=String(32)
        elif spec.name=="incident_zip":
            column_type=String(5)
        else:
            column_type=sql_types[spec.dtype]()
        columns.append(Column(spec.name,column_type,nullable=spec.nullable,primary_key=spec.name=="unique_key"))
        if spec.allowed:
            allowed=", ".join(v if spec.dtype=="int" else "'"+v.replace("'","''")+"'" for v in spec.allowed)
            checks.append(CheckConstraint(f'"{spec.name}" IN ({allowed})',name=f"ck_stage1_{spec.name}_domain"))
    checks.extend([
        CheckConstraint("closed_date IS NULL OR closed_date >= created_date",name="ck_stage1_closed_after_created"),
        CheckConstraint("LOWER(status) <> 'closed' OR closed_date IS NOT NULL",name="ck_stage1_closed_status_has_date"),
        CheckConstraint("resolution_hours IS NULL OR resolution_hours >= 0",name="ck_stage1_resolution_hours_nonnegative"),
        CheckConstraint("resolution_days IS NULL OR resolution_days >= 0",name="ck_stage1_resolution_days_nonnegative"),
        CheckConstraint("incident_zip IS NULL OR incident_zip ~ '^[0-9]{5}$'",name="ck_stage1_incident_zip_format"),
        CheckConstraint("population_zip IS NULL OR population_zip > 0",name="ck_stage1_population_positive"),
    ])
    table = Table("stage1_cases", metadata, *columns, *checks)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS factory"))
            metadata.create_all(conn)
            conn.execute(table.delete())
            count = 0
            for frame in pd.read_csv(csv_path, chunksize=chunksize, dtype={
                spec.name: "string" for spec in CASE_COLUMNS if spec.dtype == "string"
            }, parse_dates=[spec.name for spec in CASE_COLUMNS if spec.dtype == "datetime"]):
                frame = frame.astype({s.name: "Int64" for s in CASE_COLUMNS if s.dtype == "int"})
                frame = frame.astype({s.name: "Float64" for s in CASE_COLUMNS if s.dtype == "float"})
                frame.to_sql("stage1_cases", conn, schema="factory", if_exists="append",
                             index=False, chunksize=chunksize, method="multi")
                count += len(frame)
        return count
    finally:
        engine.dispose()


def apply_sql_file(sql_path, url=None):
    """Apply versioned DDL in one database transaction (never drops user objects)."""
    path = Path(sql_path)
    if not path.is_file():
        raise ConfigError(f"SQL schema file not found: {path}")
    engine = _engine(url)
    try:
        with engine.begin() as conn:
            import sqlparse
            for statement in sqlparse.split(path.read_text(encoding="utf-8")):
                if statement.strip():
                    conn.exec_driver_sql(statement)
    finally:
        engine.dispose()


def initialize_database(sql_path="sql/001_olist_schema.sql", url=None):
    """Apply versioned initial DDL without dropping existing user objects."""
    return apply_sql_file(sql_path, url)
