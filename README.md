# Project Setup and Run Guide

This project contains the NYC 311 data pipeline and a PostgreSQL analytics layer for the Olist dataset. To run the full workflow on Windows, you need Python 3.11 or later, a local PostgreSQL server, an internet connection, and the nine Olist source CSV files.

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
powershell -ExecutionPolicy Bypass -File .\run_project.ps1
```

The script creates the `.venv` virtual environment, installs the project and test dependencies, runs the NYC 311 pipeline, creates and loads the PostgreSQL schema and data, runs the tests, and executes the benchmark notebook. The NYC 311 pipeline needs internet access. The script does not install or start PostgreSQL; the server must already be running.

To run the pipeline and tests without executing the benchmark notebook:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_project.ps1 -SkipBenchmark
```

The benchmark uses the same `DATABASE_URL` and changes some analytical settings and indexes. Run it against the database you have set aside for this project.

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
