from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_olist_contract_covers_all_nine_source_domains():
    from nyc311_factory.olist import COLUMNS, FILES
    assert len(FILES) == len(COLUMNS) == 9
    assert set(FILES) == set(COLUMNS)
    assert set(FILES.values()) == {
        "olist_customers_dataset.csv", "olist_geolocation_dataset.csv", "olist_orders_dataset.csv",
        "olist_order_items_dataset.csv", "olist_order_payments_dataset.csv", "olist_order_reviews_dataset.csv",
        "olist_products_dataset.csv", "olist_sellers_dataset.csv", "product_category_name_translation.csv",
    }


def test_olist_loader_checks_all_inputs_before_connecting(tmp_path):
    from nyc311_factory.exceptions import ConfigError
    from nyc311_factory.olist import FILES, load_olist
    with pytest.raises(ConfigError, match="Missing Olist CSV files"):
        load_olist(data_dir=tmp_path,url="postgresql+psycopg://user:pass@localhost/db")
    assert len(FILES)==9


def test_ddl_uses_separate_schemas_and_preserves_constraints():
    ddl = (ROOT / "sql/001_olist_schema.sql").read_text(encoding="utf-8").lower()
    for schema in ("olist", "analytics", "factory"):
        assert f"create schema if not exists {schema}" in ddl
    for table in ("customers", "sellers", "products", "orders", "order_items", "payments", "reviews", "geolocation", "category_translation"):
        assert f"create table if not exists olist.{table}" in ddl
    assert "references olist.customers" in ddl
    assert "check(score between 1 and 5)" in ddl
    assert "drop database" not in ddl


def test_five_live_query_blocks_are_available():
    from nyc311_factory.dashboard import dashboard_sql
    for number in range(1, 6):
        sql = dashboard_sql(number)
        assert sql.lower().startswith(("select", "with"))
        assert "insert " not in sql.lower()
        assert "update " not in sql.lower()


def test_analyses_declare_business_rules_and_avoid_fanout():
    queries = (ROOT / "sql/002_dashboard_queries.sql").read_text(encoding="utf-8").lower()
    assert "count(distinct o.order_id)" in (ROOT / "sql/001_olist_schema.sql").read_text(encoding="utf-8").lower()
    assert "delivered_at is not null and estimated_delivery_at is not null" in queries
    assert "distinct i.seller_id,o.order_id" in queries
    assert "distinct i.seller_id,r.order_id,r.score" in queries
    assert "percentile_cont(0.5)" in queries


def test_function_and_idempotent_monthly_procedure_are_versioned():
    ddl = (ROOT / "sql/001_olist_schema.sql").read_text(encoding="utf-8").lower()
    assert "create or replace function analytics.late_rate" in ddl
    assert "nullif(eligible_count,0)" in ddl
    proc = ddl[ddl.index("create or replace procedure analytics.refresh_monthly_sales"):]
    assert "delete from analytics.monthly_sales_snapshot where month=p_month" in proc
    assert "insert into analytics.monthly_sales_snapshot" in proc


@pytest.mark.skipif(not __import__("os").environ.get("DATABASE_URL"), reason="DATABASE_URL not configured")
def test_postgres_function_and_procedure_idempotency():
    from sqlalchemy import create_engine, text
    from nyc311_factory.postgres import initialize_database
    url = __import__("os").environ["DATABASE_URL"]
    initialize_database(url=url)
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            assert conn.execute(text("SELECT analytics.late_rate(2,4)")).scalar() == 0.5
            conn.execute(text("CALL analytics.refresh_monthly_sales(DATE '2017-01-01')"))
            first = conn.execute(text("SELECT count(*) FROM analytics.monthly_sales_snapshot WHERE month=DATE '2017-01-01'")).scalar()
            conn.execute(text("CALL analytics.refresh_monthly_sales(DATE '2017-01-01')"))
            second = conn.execute(text("SELECT count(*) FROM analytics.monthly_sales_snapshot WHERE month=DATE '2017-01-01'")).scalar()
            assert first == second
    finally:
        engine.dispose()
