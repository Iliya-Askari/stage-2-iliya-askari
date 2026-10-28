# Data contract and cleaning policy

Final dataset `case_level.csv` (one row per complaint). Source columns are fetched with an explicit `$select`.

| column | type | nullable | domain / rule |
|---|---|---|---|
| unique_key | string | no | **unique**, length <= 32 |
| created_date | datetime | no | inside [window.start, window.end) |
| closed_date | datetime | yes | null = open; never earlier than created_date |
| agency | string | no | inside configured scope |
| complaint_type | string | no | whitespace-normalised |
| descriptor | string | no | null -> `UNSPECIFIED` |
| status | string | no | `Closed` requires closed_date |
| incident_zip | string | yes | 5 digits; `00000`, `N/A`, `A/N`, garbage -> null; ZIP+4 truncated |
| borough | string | no | BRONX/BROOKLYN/MANHATTAN/QUEENS/STATEN ISLAND/UNSPECIFIED |
| zip_borough, borough_mismatch, population_zip | derived | see code | ZIP-prefix borough, 311-vs-ZIP disagreement flag, census population |
| created_month, created_hour, created_dow | derived | no | |
| is_closed, resolution_hours, resolution_days | derived | hours/days null when open | >= 0 (0 allowed) |

## Quarantine reason codes
BAD_TYPE, MISSING_REQUIRED, BAD_UNIQUE_KEY, INVALID_CREATED_DATE, INVALID_CLOSED_DATE, OUT_OF_WINDOW, AGENCY_OUT_OF_SCOPE,
CLOSED_BEFORE_CREATED, CLOSED_WITHOUT_DATE, BAD_BOROUGH, DUPLICATE_KEY.
Every quarantined record is written to `quarantine.jsonl` with `reason_code`, `reason_detail` and the untouched raw record.
If quarantined/raw exceeds `quarantine_max_ratio`, the run fails (exit 6) and no curated output is published.

## Definitions
* **Invalid record**: violates a row of the table above that is not "recoverable" (recoverable = cleaned in place, counted in `cleaning_stats`).
* **Duplicate**: same `unique_key` among otherwise valid records; the first occurrence in the deterministic order (batch order, then position) is kept, later ones are quarantined as DUPLICATE_KEY.
