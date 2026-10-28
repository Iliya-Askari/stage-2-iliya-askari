# Design Rationale and Project Defense

## 1. Executive summary

This project combines a repeatable NYC 311 data pipeline with a PostgreSQL analytics layer for the Olist marketplace dataset. The design favors explicit data contracts, restartable ingestion, traceable data quality decisions, and database constraints that make invalid states harder to store. It keeps raw inputs, curated outputs, operational loading, and analytical queries distinct so that each stage can be inspected and rerun.

The implementation follows the project requirements and technical direction I provided. I used OpenAI Codex to generate and revise most of the implementation, tests, SQL, and supporting documentation. I directed the scope and priorities, evaluated proposed trade-offs, requested changes, and reviewed the resulting artifacts. This is an AI-assisted implementation; I do not present every line of code as independently authored by me. I am responsible for explaining the design and for distinguishing verified results from work that still needs to be run.

## 2. Problem definition

The first stage collects a bounded set of NYC 311 complaints, enriches them with Census population data, validates them against a data contract, and produces reusable curated outputs. The second stage adds PostgreSQL schemas for the curated factory data and Olist marketplace data, validates and loads the source CSVs, and provides five analytical queries plus database-side support for refreshable aggregates and performance comparisons.

The main engineering concerns are reproducibility, partial failures during ingestion, source quality, preservation of identifiers and monetary values, referential integrity, and clear definitions for analytical metrics. The design choices below address those concerns while keeping the project operable as a small local pipeline.

## 3. Why the project is structured this way

### 3.1 Separate pipeline stages behind a Python package

The NYC 311 workflow is implemented as the `nyc311_factory` package under `src/nyc311_factory`, with separate modules for configuration, fetching, curation, validation, storage, and PostgreSQL loading. This keeps network access and transformation logic out of the command-line entry point and gives each stage a focused interface.

The package structure was chosen so that later stages can reuse the canonical curated output without copying or reimplementing the stage-one transformations. It also makes unit testing possible without requiring a live API for every test. Configuration is stored outside the implementation, allowing date ranges and source settings to change without editing pipeline code.

### 3.2 Preserve raw inputs and make downloads restartable

The fetcher uses keyset pagination on `unique_key` and persists each batch before advancing its checkpoint. This was selected over offset pagination because offsets can shift when records are inserted while a long download is in progress, and because a saved cursor is a simple restart point after a network interruption. Batch output is written atomically so an interruption does not leave a partially written batch presented as complete.

The bounded stage-one scope is HPD complaints from 2023-01-01 through 2024-07-01 for three selected complaint types. The recorded API counts were 364,303 for HEAT/HOT WATER, 173,333 for UNSANITARY CONDITION, and 95,276 for PLUMBING, summing to 632,912. A fixed limit on the first N records was rejected because the API ordering would bias the result toward earlier records rather than produce a representative scope. The trade-off is that the result does not cover all HPD complaints or all complaint types.

### 3.3 Make data-quality decisions visible

Curated data follows an explicit contract. Invalid records are quarantined with reason codes rather than silently discarded. Values are normalized only where the analytical contract calls for it: complaint type casing is unified, invalid ZIP values are treated as missing, and an unknown borough may be inferred from ZIP mapping. Raw source data remains available for audit and reprocessing.

This approach favors recoverability and explainability over making every source row look complete. In the recorded stage-one run, 215 of 632,912 rows were quarantined for `CLOSED_BEFORE_CREATED` (about 0.034%). The configured 0.5% threshold is a guard against unusually high rejection rates; it allows observed low-level anomalies while halting on likely source or schema changes. The rejected records are still a limitation: the source does not establish whether each timestamp inversion is a genuine data error or a clock-entry issue.

### 3.4 Use database schemas to express ownership and constraints

The PostgreSQL layer separates `olist`, `factory`, and `analytics` schemas. This makes data ownership clear and prevents source tables, stage-one outputs, and derived analytical objects from becoming one undifferentiated namespace. The stage-one destination is part of the existing package so its output contract has one implementation and one load path.

Tables use primary keys and foreign keys where the source supports a reliable business key. Checks enforce domain rules such as nonnegative amounts and dimensions, valid review scores, positive item numbers, and sensible timestamp order. Geolocation does not receive an invented unique key because repeated ZIP prefixes and coordinates are legitimate in that source. Customer unique IDs are also not treated as a customer-table key because the source represents repeat customers across multiple customer records.

Identifiers and ZIP prefixes remain text to preserve leading zeroes and avoid accidental numeric interpretation. Monetary values use `numeric(12,2)` and are parsed through `Decimal`, avoiding binary floating-point rounding for currency. Source timestamps do not include a timezone, so they are stored as `timestamp without time zone`; assigning a timezone would imply information that the CSV does not provide.

### 3.5 Validate before inserting and quarantine rejected source rows

The Olist loader converts and validates records before loading them, checks duplicates and foreign-key relationships, and records rejected source rows in JSONL quarantine with reasons. The replacement load is transactional so a failed load does not leave a partly refreshed set of tables. This is more work than relying on a permissive bulk import, but it makes the accepted and rejected records auditable and protects referential integrity.

Nullable product and seller references on order items reflect the source and loading policy; the order relationship itself remains required. This avoids discarding an otherwise useful order item solely because its optional catalog reference is absent. The loader still reports such data quality issues rather than silently changing identifiers.

### 3.6 Put analytical definitions in SQL and document metric limits

The five dashboard queries are maintained in SQL and exposed through a small Python read interface. SQL keeps joins, aggregation, and filtering close to the database, where the data resides, and makes the analytical definitions reviewable without tracing application code.

The metrics state their scope explicitly. For example, item price is treated as merchandise GMV, not recognized net revenue, because there is no refund or reversal ledger. Delivery calculations exclude records missing required dates. Satisfaction comparisons are descriptive associations, not causal claims. Orders that use multiple payment/installment combinations may contribute to more than one group, so those group totals cannot be summed as unique marketplace revenue.

### 3.7 Use a snapshot only as a refreshable optimization

The monthly sales snapshot is derived from a live aggregate view and refreshed transactionally by month. The refresh validates month boundaries and takes an advisory transaction lock for that month. This allows safe repeated refreshes without making the snapshot a separate, hand-maintained source of truth. The dashboard can use either the live view or snapshot; the benchmark is designed to compare their results before selecting the faster option.

Indexes are evaluated against query plans, measured reads, write overhead, and storage. This avoids treating every plausible index as beneficial: an index can speed a read while increasing insert cost and disk usage. No performance conclusion should be treated as measured until the benchmark has been run against a populated database.

## 4. Evidence and verification status

The stage-one manifest previously recorded 632,912 fetched records and 632,603 population matches. The project report also records an earlier 49-test offline run and a comparison between the fetched row count and the sum of the selected API category counts. These are historical results from that recorded run, not results newly produced for this report. Reproducibility checks for exact memory use, repeated-run output hashes, and the precise normalization count were not available in the report materials and are not claimed here.

The DBA implementation includes PostgreSQL integration tests, an Olist reload/idempotency test gated on a separate disposable test database, and a benchmark notebook. Those checks require a local PostgreSQL service, source data, and a configured connection. The current workspace has not run the database load, PostgreSQL integration tests, or benchmark; therefore this report makes no claim about their runtime behavior, measured query improvement, or real Olist load counts. The supplied challenge delivery guide was also not present in the repository, so compliance against that guide could not be independently assessed.

## 5. Limitations and risks

- The NYC 311 API is mutable. A record added behind a saved keyset cursor may be missed, and records already downloaded may later change status. The raw cache makes curation repeatable for a fixed input, but does not make the live source immutable.
- ZIP-prefix mapping to borough is an approximation. Census ACS 2022 population estimates remain fixed across the selected 18-month complaint period.
- Recent complaint periods contain right-censored cases: open cases have not had the same time to resolve as older cases. Comparisons should account for this.
- Olist source files and a working PostgreSQL database are prerequisites for end-to-end verification. Database integration tests should use a separate disposable database where destructive reload tests are enabled.
- Benchmark outcomes depend on the local PostgreSQL version, data volume, indexes, and machine. No index or snapshot speedup is asserted without a recorded run.

## 6. How I would defend the main trade-offs

If asked why the system is not a single script that downloads and transforms everything in memory, I would point to restartability and the ability to inspect raw, curated, and quarantined records independently. If asked why the database enforces constraints when the loader already validates data, I would explain that loader checks provide useful rejection reports while database constraints protect the stored state from other writers and future code paths. If asked why the results are scoped to three complaint types, I would explain that the scope was chosen from API counts and avoids a biased first-N cutoff, while acknowledging that it excludes other complaint categories.

For the DBA work, I would distinguish implemented design from verified behavior. The schemas, loader, queries, constraints, refresh procedure, and tests provide a concrete implementation to review. A successful local database load, a full test run, and benchmark output are still required before claiming operational validation or performance gains.

## 7. AI usage and my role

I used OpenAI Codex as the primary implementation assistant. Codex generated and revised most of the Python modules, SQL, tests, scripts, and report wording under my direction. I supplied the project requirements and constraints, chose the requested scope and workflow, asked for explanations of design options, reviewed the proposed changes, and steered revisions when behavior or documentation needed to change. I used the resulting work as an implementation to inspect and defend; I do not claim that I manually authored every line or independently executed the unrun DBA checks.

The responsibility for the submitted work remains mine. I should be able to explain the decisions in this report, identify which evidence is historical versus newly verified, and run the outstanding database checks before presenting them as completed results. AI assistance does not replace that responsibility.
