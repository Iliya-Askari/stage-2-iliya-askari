"""Deterministic writers: CSV formatting, aggregation and the wide analytical table."""

import csv
from datetime import datetime

FLOAT_FORMAT = ".6f"
RATE_FORMAT = ".4f"


def format_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, float):
        return format(value, FLOAT_FORMAT)
    return str(value)


class CsvWriter:
    def __init__(self, path, columns):
        self._handle = open(path, "w", encoding="utf-8", newline="")
        self._writer = csv.writer(self._handle, lineterminator="\n")
        self._columns = columns
        self._writer.writerow(columns)

    def write_row(self, row):
        self._writer.writerow([format_value(row[c]) for c in self._columns])

    def close(self):
        self._handle.close()


def write_dict_rows(path, columns, rows):
    writer = CsvWriter(path, columns)
    try:
        for row in rows:
            writer.write_row(row)
    finally:
        writer.close()


class Aggregator:
    """Counts complaints per (borough, complaint_type, month) while streaming."""

    def __init__(self):
        self.counts = {}

    def add(self, row):
        key = (row["borough"], row["complaint_type"], row["created_month"])
        self.counts[key] = self.counts.get(key, 0) + 1


def month_range(first, last):
    year, month = int(first[:4]), int(first[5:7])
    end_year, end_month = int(last[:4]), int(last[5:7])
    months = []
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def build_wide_table(counts, borough_population, rate_per):
    """Return (columns, rows): one row per borough x complaint_type, months spread across columns."""
    rate_prefix = f"rate_per_{rate_per}_"
    if not counts:
        return ["borough", "complaint_type", "borough_population", "total_count"], []
    seen_months = sorted({k[2] for k in counts})
    months = month_range(seen_months[0], seen_months[-1])
    combos = sorted({(k[0], k[1]) for k in counts})
    columns = (["borough", "complaint_type", "borough_population", "total_count"]
               + [f"count_{m}" for m in months] + [rate_prefix + m for m in months])
    rows = []
    for borough, ctype in combos:
        population = borough_population.get(borough)
        row = {"borough": borough, "complaint_type": ctype, "borough_population": population}
        total = 0
        for month in months:
            n = counts.get((borough, ctype, month), 0)
            total += n
            row[f"count_{month}"] = n
            row[rate_prefix + month] = (
                format(n / population * rate_per, RATE_FORMAT) if population else None)
        row["total_count"] = total
        rows.append(row)
    return columns, rows
