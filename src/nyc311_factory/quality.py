"""Generated (not hand-written) per-column data-quality profile."""

from datetime import datetime

UNIQUE_CAP = 200000
PCT_DECIMALS = 4


class ColumnProfile:
    def __init__(self, spec):
        self.spec = spec
        self.rows = 0
        self.nulls = 0
        self.values = set()
        self.capped = False
        self.low = None
        self.high = None

    def add(self, value):
        self.rows += 1
        if value is None:
            self.nulls += 1
            return
        if not self.capped:
            self.values.add(value)
            if len(self.values) > UNIQUE_CAP:
                self.capped = True
                self.values = set()
        if self.low is None or value < self.low:
            self.low = value
        if self.high is None or value > self.high:
            self.high = value


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, float):
        return format(value, ".6f")
    return str(value)


class DatasetProfiler:
    def __init__(self, specs):
        self.profiles = [ColumnProfile(s) for s in specs]

    def add_row(self, row):
        for profile in self.profiles:
            profile.add(row[profile.spec.name])

    def report_rows(self):
        out = []
        for p in self.profiles:
            pct = 100.0 * p.nulls / p.rows if p.rows else 0.0
            unique = f">={UNIQUE_CAP}" if p.capped else str(len(p.values))
            out.append({
                "column": p.spec.name, "dtype": p.spec.dtype, "rows": p.rows,
                "null_pct": f"{pct:.{PCT_DECIMALS}f}", "n_unique": unique,
                "min": _fmt(p.low), "max": _fmt(p.high),
            })
        return out
