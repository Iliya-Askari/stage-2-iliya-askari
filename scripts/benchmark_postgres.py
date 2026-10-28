"""Repeatable live PostgreSQL benchmark for the five dashboard reads.

Captures EXPLAIN ANALYZE JSON and server-side execution times before/after the
candidate-index migration. It only creates and drops a specifically named
low-selectivity candidate index and temporary benchmark tables.
"""
import argparse
import json
import os
import statistics
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from nyc311_factory.dashboard import dashboard_sql
from nyc311_factory.postgres import apply_sql_file


def _measure(url, query, runs):
    engine = create_engine(url, pool_pre_ping=True, future=True)
    try:
        plans, elapsed = [], []
        with engine.connect() as conn:
            conn.execute(text("SET track_io_timing = on"))
            conn.execute(text("SELECT 1"))
            for _ in range(runs + 1):  # first is warmup; report remaining executions
                started = time.perf_counter()
                raw = conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query)).scalar_one()
                wall_ms = (time.perf_counter() - started) * 1000
                document = raw[0] if isinstance(raw, list) else raw
                if isinstance(document, str):
                    document = json.loads(document)
                plan = document.get("Plan", {})
                if len(plans) > 0:
                    elapsed.append(float(document.get("Execution Time", wall_ms)))
                def index_names(node):
                    found=[]
                    if node.get("Index Name"): found.append(node["Index Name"])
                    for child in node.get("Plans", []): found.extend(index_names(child))
                    return found
                plans.append({"planning_ms": document.get("Planning Time"),
                              "execution_ms": document.get("Execution Time"),
                              "total_cost": plan.get("Total Cost"), "plan_rows": plan.get("Plan Rows"),
                              "actual_rows": plan.get("Actual Rows"), "shared_hit_blocks": plan.get("Shared Hit Blocks"),
                              "shared_read_blocks": plan.get("Shared Read Blocks"),
                              "indexes_used": index_names(plan), "plan": document})
        reported = plans[1:]
        values = elapsed
        return {"runs": runs, "median_execution_ms": statistics.median(values),
                "min_execution_ms": min(values), "max_execution_ms": max(values),
                "plans": reported}
    finally:
        engine.dispose()


def _write_index_experiment(url, runs):
    engine = create_engine(url, pool_pre_ping=True, future=True)
    try:
        plain, indexed = [], []
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TEMP TABLE perf_items_plain AS SELECT order_id,item_number,product_id,seller_id,price,freight_value FROM olist.order_items WITH NO DATA")
            conn.exec_driver_sql("CREATE TEMP TABLE perf_items_indexed AS SELECT order_id,item_number,product_id,seller_id,price,freight_value FROM olist.order_items WITH NO DATA")
            conn.exec_driver_sql("CREATE INDEX perf_items_seller_idx ON perf_items_indexed(seller_id)")
            for iteration in range(runs):
                pairs=(("perf_items_plain",plain),("perf_items_indexed",indexed))
                if iteration % 2:
                    pairs=tuple(reversed(pairs))
                for table, values in pairs:
                    conn.exec_driver_sql(f"TRUNCATE {table}")
                    t0 = time.perf_counter()
                    conn.exec_driver_sql(f"INSERT INTO {table} SELECT order_id,item_number,product_id,seller_id,price,freight_value FROM olist.order_items LIMIT 5000")
                    values.append((time.perf_counter()-t0)*1000)
            count = conn.exec_driver_sql("SELECT count(*) FROM perf_items_plain").scalar_one()
        return {"rows_per_sample": count,
                "plain_median_ms": statistics.median(plain),
                "indexed_median_ms": statistics.median(indexed),
                "plain_samples_ms": plain, "indexed_samples_ms": indexed,
                "note": "Temporary-table insert benchmark; source SELECT is included in measured time."}
    finally:
        engine.dispose()


def _index_inventory(url):
    engine=create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            rows=conn.execute(text("""SELECT ix.schemaname,ix.tablename,ix.indexname,st.idx_scan,
                 pg_size_pretty(pg_relation_size(st.indexrelid)) AS size, pg_relation_size(st.indexrelid) AS bytes,
                 pg_relation_size(st.relid) AS table_bytes,
                 round(pg_relation_size(st.indexrelid)::numeric/NULLIF(pg_relation_size(st.relid),0),4) AS index_table_ratio
                 FROM pg_indexes ix JOIN pg_stat_user_indexes st
                   ON st.schemaname=ix.schemaname AND st.relname=ix.tablename AND st.indexrelname=ix.indexname
                 WHERE ix.schemaname='olist' ORDER BY ix.tablename,ix.indexname""")).mappings().all()
            table_bytes=conn.execute(text("SELECT relname,pg_relation_size(oid) AS bytes FROM pg_class WHERE relnamespace='olist'::regnamespace AND relkind='r'")).mappings().all()
        return {"indexes":[dict(r) for r in rows],"tables":[dict(r) for r in table_bytes]}
    finally: engine.dispose()


def _refresh_all_snapshots(url):
    engine=create_engine(url,future=True)
    try:
        with engine.begin() as conn:
            months=conn.execute(text("""SELECT DISTINCT date_trunc('month',purchase_at)::date
                FROM olist.orders WHERE purchase_at IS NOT NULL ORDER BY 1""")).scalars().all()
            conn.execute(text("DELETE FROM analytics.monthly_sales_snapshot"))
            for month in months:
                conn.execute(text("CALL analytics.refresh_monthly_sales(CAST(:month AS date))"),{"month":month})
        return len(months)
    finally: engine.dispose()


def _snapshot_comparison(url,runs):
    view_sql="SELECT * FROM analytics.v_item_sales ORDER BY month,category"
    snapshot_sql="SELECT month,category,sales_value,orders,revenue_per_order FROM analytics.monthly_sales_snapshot ORDER BY month,category"
    engine=create_engine(url,future=True)
    try:
        with engine.connect() as conn:
            different=conn.execute(text("""SELECT count(*) FROM (
                (SELECT month,category,sales_value,orders,revenue_per_order FROM analytics.v_item_sales
                 EXCEPT SELECT month,category,sales_value,orders,revenue_per_order FROM analytics.monthly_sales_snapshot)
                UNION ALL
                (SELECT month,category,sales_value,orders,revenue_per_order FROM analytics.monthly_sales_snapshot
                 EXCEPT SELECT month,category,sales_value,orders,revenue_per_order FROM analytics.v_item_sales)
            ) differences""")).scalar_one()
        if different:
            raise RuntimeError(f"Snapshot differs from live view in {different} rows")
    finally: engine.dispose()
    view_result=_measure(url,view_sql,runs)
    snapshot_result=_measure(url,snapshot_sql,runs)
    choice="snapshot" if snapshot_result["median_execution_ms"] < view_result["median_execution_ms"] else "view"
    return {"rows_match":different==0,"view":view_result,"snapshot":snapshot_result,
            "measured_recommendation":choice}


def run(runs=7, url=None, output="reports/performance_results.json"):
    if runs < 1:
        raise ValueError("runs must be at least one")
    started=time.perf_counter()
    url=url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL before running the benchmark")
    queries_before={str(i):dashboard_sql(i,"sql/000_dashboard_baseline.sql") for i in range(1,6)}
    queries_after={str(i):dashboard_sql(i,"sql/002_dashboard_queries.sql") for i in range(1,6)}
    result={"measurement":"PostgreSQL EXPLAIN ANALYZE Execution Time; one warm-up excluded; server-side ms",
            "runs_per_query":runs,"before_indexes":{},"after_indexes":{}}
    apply_sql_file("sql/000_drop_candidate_indexes.sql",url=url)
    for key,query in queries_before.items(): result["before_indexes"][key]=_measure(url,query,runs)
    apply_sql_file("sql/003_performance_indexes.sql",url=url)
    result["snapshot_months_refreshed"]=_refresh_all_snapshots(url)
    result["view_vs_snapshot"]=_snapshot_comparison(url,runs)
    engine=create_engine(url,future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE analytics.dashboard_config SET source=:source,updated_at=now() WHERE analysis_name='monthly_sales'"),
                         {"source":result["view_vs_snapshot"]["measured_recommendation"]})
    finally:
        engine.dispose()
    result["dashboard_source_choice"]=result["view_vs_snapshot"]["measured_recommendation"]
    for key,query in queries_after.items(): result["after_indexes"][key]=_measure(url,query,runs)
    result["budget_ms_per_query"]=200
    result["budget_met"]={key: result["after_indexes"][key]["median_execution_ms"] < 200
                          for key in result["after_indexes"]}
    result["index_write_cost"]=_write_index_experiment(url,runs)
    result["index_inventory"]=_index_inventory(url)
    # This index was deliberately included to test an unselective attribute.
    candidate_used=any("ix_customers_state_candidate" in plan.get("indexes_used",[])
                       for query in result["after_indexes"].values() for plan in query["plans"])
    apply_sql_file("sql/004_drop_ineffective_index.sql",url=url)
    result["removed_index"]={"name":"olist.ix_customers_state_candidate",
        "observed_in_dashboard_plans":candidate_used,
        "reason":"no query filters on state; retained only for candidate evaluation and removed after plan review"}
    result["benchmark_runtime_seconds"]=round(time.perf_counter()-started,3)
    path=Path(output); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--runs",type=int,default=7)
    parser.add_argument("--output",default="reports/performance_results.json")
    args=parser.parse_args()
    result=run(args.runs,output=args.output)
    for key in result["before_indexes"]:
        before=result["before_indexes"][key]["median_execution_ms"]
        after=result["after_indexes"][key]["median_execution_ms"]
        status="PASS" if after < 200 else "FAIL"
        print(f"Q{key}: before={before:.3f} ms after={after:.3f} ms target<200ms {status}")
    print(f"Index write samples: {result['index_write_cost']}")
