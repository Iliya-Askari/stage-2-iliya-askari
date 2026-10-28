# DBA Challenge 2 — implementation and evidence report

## Audit of stage one and supplied materials

Stage one is the `nyc311_factory` package under `src/nyc311_factory`. Its canonical cleaned output is `data/curated/case_level.csv`, with 18 columns defined in `contract.py`; sibling outputs are a wide aggregate, quarantine, quality report and `run_manifest.json`. The committed manifest describes an earlier run with 632,912 source records and 632,603 population matches. These are historical stage-one manifest figures, not a new run. `data/olist/` contains the nine source CSVs. The official `00_Guide_Delivery` file is absent from the repository and supplied mission text, so its requirements could not be checked.

## Database design and data policy

The database has separate `olist` (marketplace data), `factory` (stage-one output) and `analytics` (views and snapshots) schemas.

| Table | Keys and checks | Type/conversion rationale |
|---|---|---|
| `olist.customers` | `customer_id` PK; unique-customer identifier is not unique because it represents grouping | IDs/city text, ZIP `char(5)`, state `char(2)` |
| `olist.sellers` | `seller_id` PK | Same identifier/location choices |
| `olist.products` | `product_id` PK; physical dimensions/counts nonnegative | Category text; integer dimensions and counts |
| `olist.category_translation` | raw category PK; English label required | Text preserves source Portuguese and translation |
| `olist.orders` | `order_id` PK; customer FK; delivery cannot predate purchase | CSV timestamps have no UTC offset, so `timestamp without time zone` preserves source wall clock without inventing a zone |
| `olist.order_items` | `(order_id,item_number)` PK; order FK; product/seller FKs nullable; item number positive; prices nonnegative | `numeric(12,2)` preserves money exactly; integer item number |
| `olist.payments` | `(order_id,sequence)` PK; order FK; positive sequence; nonnegative installment/value | `numeric(12,2)` amount; small integer sequence/installments |
| `olist.reviews` | `(review_id,order_id)` PK; order FK; score 1–5 | Comments are retained as text; duplicate pairs keep first row and quarantine later rows |
| `olist.geolocation` | No unique key asserted because ZIP coordinates repeat; coordinate bounds checked | `double precision`; ZIP string preserves leading zeroes |
| `factory.stage1_cases` | `unique_key` PK; nullability follows stage-one contract | Derived from `CASE_COLUMNS`, chunked from canonical curated CSV |

Source blanks become SQL NULL. IDs and ZIP prefixes remain strings. Amounts are converted through `Decimal`; timestamps remain naive as in the CSV. Invalid dates/numerics, nonintegral integer fields, invalid ZIPs/coordinates, negative amounts/measures, duplicate business keys, and broken foreign keys are rejected before insert. The original CSV fields of rejected rows are reread and written to JSONL quarantine. FK constraints remain enabled. The loader reports rejection counts by dataset and reason; no counts are claimed until it is run.

## Analytical definitions

The five statements are in `sql/002_dashboard_queries.sql`; `nyc311_factory.dashboard.read_dashboard()` executes a live SELECT through SQLAlchemy on each call.

1. **Basket/revenue:** item `price` is merchandise GMV and freight is excluded. No status filter is applied because there is no refund/reversal ledger; this is item value recorded, not recognized net revenue. Category-month orders are distinct orders containing that category; average is that category's sales divided by those orders. Orders with missing purchase month cannot enter a monthly grouping. Use English translation, otherwise raw category, then `unknown`. The loader refreshes a monthly database snapshot transactionally from the live multi-table view. Dashboard Q1 routes through `analytics.v_dashboard_sales`: it defaults to the live view, and the benchmark switches it to whichever of view or snapshot measures faster after confirming result equality.
2. **Delivery:** eligible orders require purchase, delivered and estimated timestamps; purchase month is used. Late means delivered after estimate. Missing state is `??`. Missing date orders are excluded from numerator and denominator.
3. **Satisfaction:** compare late/on-time using the same date comparison. Average multiple scores per order first. Orders without scored reviews are omitted. This is descriptive association, not causal evidence.
4. **Seller performance:** item price is seller merchandise revenue. Preparation is purchase to carrier handoff, averaged once per seller/order when timestamps exist and are nonnegative. Review scores are averaged per order, then associated with each seller participating in the order and weighted once per seller/order. Top 20 are ranked by revenue.
5. **Payment/installments:** one order per payment-type/installment combination after same-combination rows are summed. Order value is item price plus freight; mean and median are returned. Orders split across combinations appear in each relevant group, so group values must not be summed as unique marketplace revenue. NULL and zero installments remain distinct.

`analytics.v_order_delivery` is a single-purpose view; `analytics.v_item_sales` is multi-table. `analytics.late_rate()` works in SELECT and returns NULL for zero denominator. `analytics.refresh_monthly_sales(date)` refreshes a month in the caller's transaction, validates month start, and takes a per-month advisory transaction lock. Sequential repeats are idempotent; transaction rollback protects prior state on error.

## Setup and execution

Install Python 3.11+ and PostgreSQL, then from the repository root:

```powershell
python -m venv .venv
. .venv/Scripts/Activate.ps1
python -m pip install -e ".[test]"
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DB"
nyc311 db-load
```

With Docker Desktop, the full local path can be started with one script: copy `.env.example` to `.env`, change the password, then run `./scripts/run_dba.ps1`. It starts PostgreSQL 16, installs the package, loads both datasets, runs tests and executes the benchmark notebook. It expects stage one's curated output to already exist. The optional full Olist idempotency test requires a separate disposable database whose name ends in `_test`; set `TEST_DATABASE_URL` only for that database.

With Docker Desktop, the full local path can be started with one script: copy `.env.example` to `.env`, change the password, then run `./scripts/run_dba.ps1`. It starts PostgreSQL 16, installs the package, loads both datasets, runs tests and executes the benchmark notebook. It expects stage one's curated output to already exist. The optional full Olist idempotency test requires a separate disposable database whose name ends in `_test`; set `TEST_DATABASE_URL` only for that database.

`db-load` applies `sql/001_olist_schema.sql`, loads `data/curated/case_level.csv` using the stage-one package destination, and transactionally replaces Olist tables from `data/olist/`. It writes rejected source records to `data/state/olist_quarantine.jsonl`. The existing stage-one curated output must be present; rebuilding it can require network/Census access.

For a live read:

```python
from nyc311_factory.dashboard import read_dashboard
sales_by_month = read_dashboard(1)
```

Tests: `python -m pytest -q`. PostgreSQL integration tests use unique fixture rows in transactions and roll them back; without `DATABASE_URL` they are skipped. Full Olist reload/idempotency testing is separately gated by `TEST_DATABASE_URL`, whose database name must end in `_test`. For performance, run `notebooks/dba_benchmark.ipynb` or `python scripts/benchmark_postgres.py`. The runner captures baseline plans from `sql/000_dashboard_baseline.sql`, applies candidate indexes from `sql/003_performance_indexes.sql`, refreshes and compares the live aggregate view with its database snapshot, then sets Q1's source to the faster equal-result option and measures the five final dashboard statements. It also compares temporary insert cost with/without a seller index, reports index/table sizes and ratios, then drops the tested low-selectivity customer-state index via `sql/004_drop_ineffective_index.sql`. It writes `reports/performance_results.json`; that artifact is only available after successful execution.

## Verification and acceptance

The current environment could not run Python: `.venv` points to a removed interpreter and neither `python` nor `py` finds an installation. PostgreSQL clients/server were not available on PATH. Therefore SQL, loader, tests, notebook, and performance measurements have not been executed. No timing, plan, FK count, load count, or test result is claimed. `00_Guide_Delivery` is missing.

| Acceptance group | Status | Evidence / blocker |
|---|---|---|
| Stage-one audit and preservation | PARTIAL | Existing package/output contract inspected; destination added to same package. |
| One path for DDL + stage-one + Olist loads | PARTIAL | `nyc311 db-load` connects the steps; not run, and PostgreSQL database must exist. |
| Nine Olist tables, types, keys and checks | PARTIAL | DDL and explicit loader validation present; PostgreSQL behavior unverified. |
| Olist loading and FK quarantine statistics | PARTIAL | Loader and JSONL report implemented; real counts require execution. |
| Five live analytical reads | PARTIAL | SQL and SQLAlchemy live read present; not executed. |
| Before/after budgets, plans, index use/write/size | PARTIAL | Repeatable benchmark runner/notebook present; no benchmark artifact yet. |
| Views/function/procedure/snapshot/idempotency | PARTIAL | DDL and DB integration tests present; not run. |
| Six-plus data tests and stage-one suite | PARTIAL | Static checks and six PostgreSQL integration tests added; not run. |
| Ten-minute notebook ceiling | PARTIAL | Notebook is ready, runtime unverified. |
| Eight meaningful Git commits | PASS | Eight scoped commits were created; commit subjects are reported with final Git status. |
| Official delivery guide | FAIL | Not supplied. |

**Overall: `PARTIAL`.** The implementation now covers the code paths for the major requirements, but it is not a verified operational delivery until the complete load, test suite and benchmark run successfully. Use the generated quarantine, load summary and performance artifact for real counts and results rather than inferring them from source files.
