# Project Setup and Run Guide

This project contains the NYC 311 data pipeline and a PostgreSQL analytics layer for the Olist dataset. To run the full workflow on Windows, you need Python 3.11 or later, a local PostgreSQL server, an internet connection, and the nine Olist source CSV files.

## Project map: Challenge 1 and Challenge 2

### Challenge 1: NYC 311 data factory

These files implement the first challenge and provide the curated dataset used by the database challenge:

- `config/default.json`: main NYC 311 API, date range, agency, complaint types, and output settings.
- `config/demo.json`: smaller/demo configuration for the first-stage pipeline.
- `src/nyc311_factory/`: reusable Python package. `cli.py` exposes commands; `pipeline.py` coordinates fetching and curation; `ingest.py` and `http_client.py` fetch and page through API data; `cleaning.py`, `contract.py`, and `quality.py` validate and transform records; `storage.py`, `outputs.py`, and `manifest.py` write outputs and run metadata. The package also contains shared PostgreSQL loading modules used by Challenge 2.
- `docs/data_contract.md`: the rules and fields for the curated NYC 311 output.
- `data/raw/`, `data/state/`, and `data/curated/`: raw batches, restart/checkpoint state, and curated outputs/reports from Challenge 1. Generated raw data is intentionally not committed.
- `solution.ipynb`: Challenge 1 analysis notebook. `scripts/build_notebook.py` builds it; `scripts/measure_memory.py` and `scripts/verify_stage1.py` support Challenge 1 measurement and validation. `scripts/make_demo_data.py` creates demo data.
- `tests/test_cleaning.py`, `test_config.py`, `test_http_client.py`, `test_ingest.py`, and `test_pipeline.py`: tests for the Challenge 1 pipeline.
- `run_all.bat` and `run_all.sh`: older one-command launchers for Challenge 1 only. They do not run the PostgreSQL/DBA work in Challenge 2.

### Challenge 2: PostgreSQL DBA work

- `data/olist/`: the nine Olist source CSVs downloaded from Kaggle.
- `sql/001_olist_schema.sql`: schemas, tables, constraints, analytical views, function, snapshot table, and refresh procedure.
- `sql/002_dashboard_queries.sql`: the five dashboard queries.
- `sql/000_dashboard_baseline.sql`, `sql/003_performance_indexes.sql`, and `sql/004_drop_ineffective_index.sql`: baseline, candidate-index, and evaluated-index changes used by the benchmark.
- `src/nyc311_factory/olist.py`, `postgres.py`, and `dashboard.py`: load Olist data, publish Challenge 1 output to PostgreSQL, and execute live dashboard queries.
- `scripts/benchmark_postgres.py` and `notebooks/dba_benchmark.ipynb`: measure plans, query timing, snapshot comparison, index write cost, and storage.
- `tests/test_dba_artifacts.py`, `test_dba_postgres.py`, and `test_olist_reload.py`: Challenge 2 artifact and database tests.

The two challenges share the Python package and the `data/curated/case_level.csv` output. You normally do not need to launch individual Challenge 1 files when setting up Challenge 2.

## Step 1: Download the Olist data

1. Download the dataset from the [Kaggle page: Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce?resource=download). You may need to sign in to Kaggle.
2. Extract the downloaded ZIP file.
3. Copy these nine CSV files directly into the project's `data/olist/` directory. Do not put them inside an additional subfolder:

```text
data/olist/olist_customers_dataset.csv
data/olist/olist_sellers_dataset.csv
data/olist/olist_products_dataset.csv
data/olist/product_category_name_translation.csv
data/olist/olist_orders_dataset.csv
data/olist/olist_order_items_dataset.csv
data/olist/olist_order_payments_dataset.csv
data/olist/olist_order_reviews_dataset.csv
data/olist/olist_geolocation_dataset.csv
```

Each file must be at the exact path shown above. Do not leave only the ZIP file in `data/olist/`; the loader needs the extracted CSV files.

## Prerequisites

1. Install Python 3.11 or later and make sure `python` is available in PowerShell.
2. Install PostgreSQL 18 and start its service. If PostgreSQL is installed in the default location, add its `bin` directory to `PATH`:

```powershell
$env:Path += ";C:\Program Files\PostgreSQL\18\bin"
```

3. From the project root, create an empty database named `stage1`. The `createdb` command may prompt for the `postgres` user's password:

```powershell
createdb -h localhost -U postgres stage1
```

4. Set the database connection URL in the current PowerShell session. Replace `YOUR_PASSWORD` with your PostgreSQL password:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/stage1"
```

If the password contains URL-reserved characters such as `@`, `:`, `/`, or `#`, percent-encode them in the URL.

## Run the complete workflow with one file

Make sure PostgreSQL is running, the empty `stage1` database has been created, `DATABASE_URL` is set in the current PowerShell session, and the Olist CSVs are in place. From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_project_stage_2.ps1
```

This is the single launcher for Challenge 2. It creates the `.venv` virtual environment, installs the project and test dependencies, runs the NYC 311 pipeline as the required Challenge 1 data-producing step, creates and loads the PostgreSQL schema and both datasets, runs the tests, and executes the benchmark notebook. The NYC 311 pipeline needs internet access. The script does not install or start PostgreSQL; the server must already be running.

Do not separately run `run_all.bat`, `run_all.sh`, `solution.ipynb`, `scripts/build_notebook.py`, or `python -m nyc311_factory ... run` before launching this script. Those are Challenge 1 tools; the Challenge 2 launcher already invokes the pipeline it needs. Run only one launcher at a time. Do not start the benchmark separately while the launcher is still running it.

To run the pipeline and tests without executing the benchmark notebook:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_project_stage_2.ps1 -SkipBenchmark
```

The benchmark uses the same `DATABASE_URL` and changes some analytical settings and indexes. Run it against the database you have set aside for this project.

After it completes, review `reports/performance_results.json` for the measured results. It reports whether each of the five dashboard queries met the 200 ms median server-execution-time target and includes a separate live-view/index/snapshot comparison for the index-insensitive aggregation. The target is not considered verified until this benchmark has completed successfully on your populated database.

Dashboard queries and the benchmark use session-level `work_mem` of `64MB` by default to avoid the disk-based sorts seen in the initial query plans. Set `NYC311_WORK_MEM` in PowerShell before running either the dashboard or benchmark to use a different PostgreSQL value, for example `$env:NYC311_WORK_MEM = "32MB"`. This setting applies per database connection and is not a server-wide setting.

## Run the tests separately

After installing the dependencies and setting `DATABASE_URL`, run the tests from the repository root:

```powershell
python -m pytest -q
```

Without `DATABASE_URL`, PostgreSQL integration tests are skipped and only database-independent tests run. The full Olist reload test is optional and requires a separate test database whose name ends in `_test`. It must be separate from `stage1` because the test clears and reloads Olist data:

```powershell
createdb -h localhost -U postgres stage1_test
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/stage1_test"
python -m pytest -q
```

## Run individual stages

To run only the NYC 311 stage (fetch and curate the data):

```powershell
python -m nyc311_factory --config config/default.json -v run
```

To create the schema and load the stage-one and Olist data into PostgreSQL, first make sure the stage-one output and Olist CSV files are available:

```powershell
python -m nyc311_factory --config config/default.json db-load
```

The design rationale and verification status are documented in [report.md](report.md). DBA implementation details are in [docs/challenge2.md](docs/challenge2.md).
