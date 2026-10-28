"""Offline fakes shared by the tests (no network anywhere)."""

import json
import re
import tempfile
from dataclasses import replace
from pathlib import Path

import requests

from nyc311_factory.config import config_from_dict
from nyc311_factory.synthetic import make_records, write_jsonl, write_population_csv

BASE_CONFIG = {
    "source": {"kind": "file", "url": "", "method": "GET", "path": "x.jsonl", "app_token_env": None},
    "window": {"mode": "fixed", "start": "2023-01-01", "end": "2024-07-01"},
    "scope": {"agencies": ["HPD"]},
    "batch_size": 100, "max_retries": 2, "backoff_seconds": 0.0, "timeout_seconds": 5,
    "max_raw_records": None, "min_raw_records": 0, "quarantine_max_ratio": 0.5,
    "min_rows_for_drift_check": 50, "rate_per_residents": 10000,
    "population": {"kind": "file", "url": "", "params": {}, "value_column": "", "zip_column": "",
                   "path": "pop.csv", "nyc_zip_prefixes": []},
    "zip_prefix_borough": {"100": "MANHATTAN", "104": "BRONX", "112": "BROOKLYN", "113": "QUEENS", "103": "STATEN ISLAND"},
    "zip_placeholders": ["00000", "N/A", "A/N"],
    "paths": {"raw": "raw", "curated": "curated", "state": "state"},
}


class FakeResponse:
    def __init__(self, status=200, payload=None, text="", bad_json=False):
        self.status_code = status
        self._payload = payload
        self.text = text
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("truncated")
        return self._payload


class ScriptedSession:
    """Returns/raises scripted items in order; records every call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeSocrataSession:
    """Serves records ordered by unique_key honouring the keyset cursor and $limit."""

    def __init__(self, records, fail_on_call=None, error=None):
        self.records = sorted(records, key=lambda r: r["unique_key"])
        self.calls = []
        self.fail_on_call = fail_on_call
        self.error = error or requests.exceptions.ConnectionError("boom")

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise self.error
        params = kwargs.get("params") or kwargs.get("json")
        match = re.search(r"unique_key > '([^']*)'", params["$where"])
        rows = [r for r in self.records if not match or r["unique_key"] > match.group(1)]
        return FakeResponse(200, rows[: int(params["$limit"])])


def make_config(root, **overrides):
    data = json.loads(json.dumps(BASE_CONFIG))
    root = Path(root)
    data["paths"] = {"raw": str(root / "raw"), "curated": str(root / "curated"), "state": str(root / "state")}
    cfg = config_from_dict({**data, **{k: v for k, v in overrides.items() if k in data}}, allow_absolute_paths=True)
    extra = {k: v for k, v in overrides.items() if k not in data}
    return replace(cfg, **extra) if extra else cfg


def prepare_file_inputs(root, n=300, defect_rate=0.0, seed=1, duplicates=0):
    """Write synthetic input + population into root and return a config pointing at them."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    records = make_records(n, defect_rate=defect_rate, seed=seed)
    records.sort(key=lambda r: r["unique_key"])
    records += records[:duplicates]
    write_jsonl(root / "in.jsonl", records)
    write_population_csv(root / "pop.csv")
    data = json.loads(json.dumps(BASE_CONFIG))
    data["source"]["path"] = str(root / "in.jsonl")
    data["population"]["path"] = str(root / "pop.csv")
    data["paths"] = {"raw": str(root / "raw"), "curated": str(root / "curated"), "state": str(root / "state")}
    data["zip_prefix_borough"].update({"100": "MANHATTAN", "104": "BRONX", "112": "BROOKLYN",
                                       "113": "QUEENS", "103": "STATEN ISLAND", "110": "QUEENS", "111": "QUEENS"})
    return data, records


def tempdir():
    return tempfile.TemporaryDirectory()
