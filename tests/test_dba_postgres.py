"""Isolated PostgreSQL integration checks; every fixture insert is rolled back."""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text


pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not configured")


@pytest.fixture
def db_case():
    from nyc311_factory.postgres import initialize_database
    url=os.environ["DATABASE_URL"]
    initialize_database(url=url)
    engine=create_engine(url,future=True)
    conn=engine.connect()
    transaction=conn.begin()
    token=uuid.uuid4().hex
    ids={key: token+"_"+key for key in ("customer","seller","product","order","review")}
    conn.execute(text("INSERT INTO olist.customers(customer_id,customer_unique_id,state) VALUES(:id,:uid,'ZZ')"),
                 {"id":ids["customer"],"uid":ids["customer"]})
    conn.execute(text("INSERT INTO olist.sellers(seller_id,state) VALUES(:id,'ZZ')"),{"id":ids["seller"]})
    conn.execute(text("INSERT INTO olist.category_translation VALUES(:raw,:english)"),
                 {"raw":token,"english":"test_category_"+token})
    conn.execute(text("INSERT INTO olist.products(product_id,category_name) VALUES(:id,:category)"),
                 {"id":ids["product"],"category":token})
    conn.execute(text("""INSERT INTO olist.orders(order_id,customer_id,status,purchase_at,carrier_at,
       delivered_at,estimated_delivery_at) VALUES(:id,:customer,'delivered',TIMESTAMPTZ '2035-01-10 00:00+00',
       TIMESTAMPTZ '2035-01-10 12:00+00',TIMESTAMPTZ '2035-01-12 00:00+00',TIMESTAMPTZ '2035-01-11 00:00+00')"""),
       {"id":ids["order"],"customer":ids["customer"]})
    conn.execute(text("""INSERT INTO olist.order_items(order_id,item_number,product_id,seller_id,price,freight_value)
       VALUES(:order,1,:product,:seller,10.00,2.00)"""),
       {"order":ids["order"],"product":ids["product"],"seller":ids["seller"]})
    conn.execute(text("INSERT INTO olist.payments(order_id,sequence,payment_type,installments,value) VALUES(:order,1,'credit_card',2,12.00)"),
                 {"order":ids["order"]})
    conn.execute(text("INSERT INTO olist.reviews(review_id,order_id,score) VALUES(:review,:order,4)"),
                 {"review":ids["review"],"order":ids["order"]})
    conn.execute(text("UPDATE analytics.dashboard_config SET source='view' WHERE analysis_name='monthly_sales'"))
    conn.execute(text("UPDATE analytics.dashboard_config SET source='view' WHERE analysis_name='monthly_sales'"))
    try:
        yield conn,ids,token
    finally:
        transaction.rollback()
        conn.close()
        engine.dispose()


def test_fk_rejects_unknown_customer(db_case):
    conn,_,token=db_case
    nested=conn.begin_nested()
    with pytest.raises(Exception):
        conn.execute(text("INSERT INTO olist.orders(order_id,customer_id,status) VALUES(:id,:missing,'new')"),
                     {"id":token+"_orphan","missing":token+"_absent"})
    nested.rollback()


def test_score_check_rejects_out_of_range(db_case):
    conn,ids,token=db_case
    nested=conn.begin_nested()
    with pytest.raises(Exception):
        conn.execute(text("INSERT INTO olist.reviews(review_id,order_id,score) VALUES(:id,:order,6)"),
                     {"id":token+"_invalid_review","order":ids["order"]})
    nested.rollback()


def test_late_rate_function_handles_fraction_and_zero(db_case):
    conn,_,_=db_case
    assert conn.execute(text("SELECT analytics.late_rate(1,4)")).scalar_one() == 0.25
    assert conn.execute(text("SELECT analytics.late_rate(0,0)")).scalar_one() is None


def test_q1_live_analytics_counts_controlled_order_once(db_case):
    from nyc311_factory.dashboard import dashboard_sql
    conn,ids,token=db_case
    result=conn.execute(text(dashboard_sql(1))).mappings().all()
    rows=[r for r in result if r["category"] == "test_category_"+token and str(r["month"]) == "2035-01-01"]
    assert len(rows)==1
    assert rows[0]["sales_value"] == 10
    assert rows[0]["orders"] == 1


def test_delivery_query_uses_purchase_month_and_excludes_incomplete_dates(db_case):
    from nyc311_factory.dashboard import dashboard_sql
    conn,_,_=db_case
    rows=conn.execute(text(dashboard_sql(2))).mappings().all()
    assert any(str(r["order_month"])=="2035-01-01" and r["state"]=="ZZ" and
               r["eligible_orders"]>=1 and r["late_orders"]>=1 for r in rows)


def test_monthly_procedure_is_repeatable_and_transactional(db_case):
    conn,_,_=db_case
    month="2035-01-01"
    conn.execute(text("CALL analytics.refresh_monthly_sales(CAST(:month AS date))"),{"month":month})
    first=conn.execute(text("SELECT count(*) FROM analytics.monthly_sales_snapshot WHERE month=:month"),{"month":month}).scalar_one()
    conn.execute(text("CALL analytics.refresh_monthly_sales(CAST(:month AS date))"),{"month":month})
    second=conn.execute(text("SELECT count(*) FROM analytics.monthly_sales_snapshot WHERE month=:month"),{"month":month}).scalar_one()
    assert first==second and first>=1


def test_procedure_rejects_non_month_start_without_changing_snapshot(db_case):
    conn,_,_=db_case
    conn.execute(text("CALL analytics.refresh_monthly_sales(DATE '2035-01-01')"))
    before=conn.execute(text("SELECT count(*) FROM analytics.monthly_sales_snapshot WHERE month=DATE '2035-01-01'")).scalar_one()
    nested=conn.begin_nested()
    with pytest.raises(Exception):
        conn.execute(text("CALL analytics.refresh_monthly_sales(DATE '2035-01-02')"))
    nested.rollback()
    after=conn.execute(text("SELECT count(*) FROM analytics.monthly_sales_snapshot WHERE month=DATE '2035-01-01'")).scalar_one()
    assert before==after


def test_procedure_rejects_non_month_start_without_changing_snapshot(db_case):
    conn,_,_=db_case
    conn.execute(text("CALL analytics.refresh_monthly_sales(DATE '2035-01-01')"))
    before=conn.execute(text("SELECT count(*) FROM analytics.monthly_sales_snapshot WHERE month=DATE '2035-01-01'")).scalar_one()
    nested=conn.begin_nested()
    with pytest.raises(Exception):
        conn.execute(text("CALL analytics.refresh_monthly_sales(DATE '2035-01-02')"))
    nested.rollback()
    after=conn.execute(text("SELECT count(*) FROM analytics.monthly_sales_snapshot WHERE month=DATE '2035-01-01'")).scalar_one()
    assert before==after
