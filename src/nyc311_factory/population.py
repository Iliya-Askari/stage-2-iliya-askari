"""Independent reference source: population per ZIP code tabulation area (US Census ACS)."""

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .exceptions import PopulationError
from .io_utils import atomic_write_text, pretty_json, sha256_file

POPULATION_CSV = "population_zcta.csv"
POPULATION_META = "population_meta.json"
ZIP_WIDTH = 5


class Population:
    """ZIP -> population plus ZIP-prefix -> borough mapping."""

    def __init__(self, zip_to_pop, prefix_to_borough):
        self.zip_to_pop = dict(zip_to_pop)
        self.prefix_to_borough = dict(prefix_to_borough)

    def borough_of_zip(self, zip_code):
        if not zip_code:
            return None
        return self.prefix_to_borough.get(zip_code[:3])

    def borough_totals(self):
        totals = {}
        for zip_code, pop in self.zip_to_pop.items():
            borough = self.borough_of_zip(zip_code)
            if borough:
                totals[borough] = totals.get(borough, 0) + pop
        return totals


def parse_census_payload(payload, value_column, zip_column, prefixes):
    """Turn the Census list-of-lists response into {zip: population}.

    Negative values are Census sentinel codes for "no estimate"; those ZIPs are skipped and counted.
    """
    if not isinstance(payload, list) or len(payload) < 2 or not all(isinstance(r, list) for r in payload):
        raise PopulationError("census payload must be a header row followed by data rows")
    header = payload[0]
    if value_column not in header or zip_column not in header:
        raise PopulationError(f"census payload lacks columns {value_column!r}/{zip_column!r}: header={header}")
    vi, zi = header.index(value_column), header.index(zip_column)
    result, skipped = {}, 0
    for row in payload[1:]:
        try:
            zip_code = str(row[zi]).zfill(ZIP_WIDTH)
            value = int(row[vi])
        except (TypeError, ValueError, IndexError):
            skipped += 1
            continue
        if prefixes and zip_code[:3] not in prefixes:
            continue
        if value < 0:
            skipped += 1
            continue
        if zip_code in result:
            raise PopulationError(f"duplicate ZIP {zip_code} in population source")
        result[zip_code] = value
    if not result:
        raise PopulationError("population source produced no NYC ZIP rows")
    return result, skipped


def write_population_csv(path, zip_to_pop):
    lines = ["zip,population"] + [f"{z},{zip_to_pop[z]}" for z in sorted(zip_to_pop)]
    atomic_write_text(path, "\n".join(lines) + "\n")


def load_population_csv(path):
    zip_to_pop = {}
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                zip_code = row["zip"].strip().zfill(ZIP_WIDTH)
                if zip_code in zip_to_pop:
                    raise PopulationError(f"duplicate ZIP {zip_code} in {path}")
                zip_to_pop[zip_code] = int(row["population"])
    except (OSError, KeyError, ValueError) as exc:
        raise PopulationError(f"cannot read population file {path}: {exc}") from exc
    if not zip_to_pop:
        raise PopulationError(f"population file {path} is empty")
    return zip_to_pop


def ensure_population(cfg, client, refresh=False):
    """Fetch (once) and cache the reference table; later runs reuse the cached file."""
    pcfg = cfg.population
    if pcfg.kind == "file":
        path = Path(pcfg.path)
        meta = {"source": f"file:{pcfg.path}", "retrieved_at": None, "http_requests": 0}
        meta.update(sha256=sha256_file(path), rows=len(load_population_csv(path)))
        return path, meta
    directory = Path(cfg.paths.raw) / "population"
    csv_path, meta_path = directory / POPULATION_CSV, directory / POPULATION_META
    if csv_path.exists() and meta_path.exists() and not refresh:
        return csv_path, json.loads(meta_path.read_text(encoding="utf-8"))
    before = client.total_requests
    params = dict(pcfg.params)
    api_key = os.environ.get(pcfg.api_key_env) if pcfg.api_key_env else None
    if api_key:
        params["key"] = api_key  # secret: sent, but never written to the meta/manifest
    payload = client.request("GET", pcfg.url, params=params, expect=list)
    zip_to_pop, skipped = parse_census_payload(
        payload, pcfg.value_column, pcfg.zip_column, set(pcfg.nyc_zip_prefixes))
    write_population_csv(csv_path, zip_to_pop)
    meta = {
        "source": pcfg.url, "params": pcfg.params,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": len(zip_to_pop), "skipped_no_estimate": skipped,
        "sha256": sha256_file(csv_path), "http_requests": client.total_requests - before,
    }
    atomic_write_text(meta_path, pretty_json(meta))
    return csv_path, meta
