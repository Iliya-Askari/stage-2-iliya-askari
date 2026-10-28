"""Full Olist replacement test. Requires an explicitly disposable test database."""
import os
from pathlib import Path
from pathlib import Path

import pytest


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
def test_olist_reload_is_idempotent_in_dedicated_database(tmp_path):
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from nyc311_factory.olist import load_olist
    from nyc311_factory.postgres import initialize_database

    if not all((Path("data/olist")/name).is_file() for name in (
        "olist_customers_dataset.csv","olist_geolocation_dataset.csv","olist_orders_dataset.csv",
        "olist_order_items_dataset.csv","olist_order_payments_dataset.csv","olist_order_reviews_dataset.csv",
        "olist_products_dataset.csv","olist_sellers_dataset.csv","product_category_name_translation.csv")):
        pytest.skip("Olist source CSVs are not present")

    if not all((Path("data/olist")/name).is_file() for name in (
        "olist_customers_dataset.csv","olist_geolocation_dataset.csv","olist_orders_dataset.csv",
        "olist_order_items_dataset.csv","olist_order_payments_dataset.csv","olist_order_reviews_dataset.csv",
        "olist_products_dataset.csv","olist_sellers_dataset.csv","product_category_name_translation.csv")):
        pytest.skip("Olist source CSVs are not present")

    test_url=os.environ["TEST_DATABASE_URL"]
    parsed=make_url(test_url)
    primary=make_url(os.environ["DATABASE_URL"]) if os.environ.get("DATABASE_URL") else None
    if not parsed.database or not parsed.database.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end in _test (disposable test database only)")
    if primary and (parsed.host,parsed.port,parsed.database)==(primary.host,primary.port,primary.database):
        pytest.fail("TEST_DATABASE_URL must point to a separate database")
    initialize_database(url=test_url)
    first=load_olist(url=test_url,quarantine_path=tmp_path/"first.jsonl")
    engine=create_engine(test_url,future=True)
    try:
        with engine.connect() as conn:
            counts1={table:conn.execute(text(f"SELECT count(*) FROM olist.{table}")).scalar_one()
                     for table in first["loaded"]}
        second=load_olist(url=test_url,quarantine_path=tmp_path/"second.jsonl")
        with engine.connect() as conn:
            counts2={table:conn.execute(text(f"SELECT count(*) FROM olist.{table}")).scalar_one()
                     for table in second["loaded"]}
        assert counts1==counts2==first["loaded"]==second["loaded"]
        assert first["rejected_by_reason"]==second["rejected_by_reason"]
    finally:
        engine.dispose()
