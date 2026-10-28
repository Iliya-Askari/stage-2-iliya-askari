"""Create synthetic demo inputs (offline). Usage: python scripts/make_demo_data.py"""

from pathlib import Path

from nyc311_factory.synthetic import make_records, write_jsonl, write_population_csv

OUT = Path("data/demo_input")
DEMO_RECORDS = 20000
DEMO_DEFECT_RATE = 0.03
DEMO_DUPLICATES = 25

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    records = make_records(DEMO_RECORDS, defect_rate=DEMO_DEFECT_RATE)
    records.sort(key=lambda r: r["unique_key"])
    records += records[:DEMO_DUPLICATES]  # exact duplicate keys, quarantined as DUPLICATE_KEY
    write_jsonl(OUT / "synthetic_311.jsonl", records)
    write_population_csv(OUT / "synthetic_population.csv")
    print(f"wrote {len(records)} synthetic records to {OUT}")
