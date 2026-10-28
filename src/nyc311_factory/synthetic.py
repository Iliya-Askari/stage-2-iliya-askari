"""Deterministic synthetic NYC-311-like data for offline demos and tests (NOT real data)."""

import json
import random
from datetime import datetime, timedelta

BOROUGH_ZIPS = {
    "MANHATTAN": ["10001", "10002", "10027"],
    "BRONX": ["10451", "10458"],
    "BROOKLYN": ["11201", "11215", "11226"],
    "QUEENS": ["11354", "11375"],
    "STATEN ISLAND": ["10301", "10314"],
}
COMPLAINT_TYPES = ["HEAT/HOT WATER", "PLUMBING", "PAINT/PLASTER", "UNSANITARY CONDITION", "DOOR/WINDOW"]
BOROUGH_SCALE = {"MANHATTAN": 1.0, "BRONX": 1.6, "BROOKLYN": 1.3, "QUEENS": 1.1, "STATEN ISLAND": 0.8}
SECONDS_PER_DAY = 86400
DIRTY_ZIPS = ["00000", "N/A", " 10001 ", "10001-1234", "A/N", "ABCDE"]


def make_population_rows():
    rows = []
    base = 20000
    for borough in sorted(BOROUGH_ZIPS):
        for i, zip_code in enumerate(BOROUGH_ZIPS[borough]):
            rows.append((zip_code, base + 7000 * i))
    return rows


def make_records(n, start="2023-01-01", days=546, seed=42, defect_rate=0.0, agency="HPD"):
    """Return n records. defect_rate>0 injects invalid/dirty records (about that fraction)."""
    rng = random.Random(seed)
    start_dt = datetime.fromisoformat(start)
    records = []
    for i in range(n):
        borough = rng.choice(sorted(BOROUGH_ZIPS))
        zip_code = rng.choice(BOROUGH_ZIPS[borough])
        created = start_dt + timedelta(seconds=rng.randrange(days * SECONDS_PER_DAY))
        hours = rng.lognormvariate(3.0, 1.1) * BOROUGH_SCALE[borough]
        closed = created + timedelta(hours=hours) if rng.random() < 0.9 else None
        rec = {
            "unique_key": f"{10000000 + i:08d}",
            "created_date": created.strftime("%Y-%m-%dT%H:%M:%S.000"),
            "agency": agency,
            "complaint_type": rng.choice(COMPLAINT_TYPES),
            "descriptor": rng.choice(["ENTIRE BUILDING", "APARTMENT ONLY", None]),
            "status": "Closed" if closed else "Open",
            "incident_zip": zip_code,
            "borough": borough,
        }
        if closed:
            rec["closed_date"] = closed.strftime("%Y-%m-%dT%H:%M:%S.000")
        if rng.random() < 0.03:
            rec["borough"] = "Unspecified"
        if defect_rate and rng.random() < defect_rate:
            _inject_defect(rec, rng, created)
        records.append({k: v for k, v in rec.items() if v is not None})
    return records


def _inject_defect(rec, rng, created):
    kind = rng.choice(["closed_before", "bad_date", "missing_type", "dirty_zip", "bad_borough"])
    if kind == "closed_before":
        rec["closed_date"] = (created - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000")
        rec["status"] = "Closed"
    elif kind == "bad_date":
        rec["created_date"] = "not-a-date"
    elif kind == "missing_type":
        rec["complaint_type"] = None
    elif kind == "dirty_zip":
        rec["incident_zip"] = rng.choice(DIRTY_ZIPS)
    else:
        rec["borough"] = "ATLANTIS"


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for rec in records:
            handle.write(json.dumps(rec, sort_keys=True) + "\n")


def write_population_csv(path):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("zip,population\n")
        for zip_code, pop in make_population_rows():
            handle.write(f"{zip_code},{pop}\n")
