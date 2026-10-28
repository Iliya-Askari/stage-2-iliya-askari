"""Run manifest assembly."""

import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .io_utils import atomic_write_text, pretty_json

MANIFEST_FILE = "run_manifest.json"
MAX_PAGE_ROWS = 50000
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now():
    return datetime.now(timezone.utc)


def git_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             timeout=10, cwd=Path(__file__).resolve().parent)
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def request_budget(raw_records, batch_size, http_requests, retries, population_requests):
    """Report actual requests and why fewer were impossible."""
    page = min(batch_size, MAX_PAGE_ROWS)
    minimum_data_pages = max(1, math.ceil(raw_records / page)) if raw_records else 1
    minimum = minimum_data_pages + population_requests
    return {
        "total_http_requests": http_requests + population_requests,
        "retry_attempts_included": retries,
        "minimum_possible_requests": minimum,
        "rationale": (
            f"The server caps one response at {MAX_PAGE_ROWS} rows, so {raw_records} raw records need at least "
            f"ceil({raw_records}/{page}) = {minimum_data_pages} data requests, plus {population_requests} request "
            "for the population table. Keyset pagination needs no extra count/probe request: a short page "
            "signals the end. Anything above the minimum is retries or resumed runs."),
    }


def build_manifest(cfg, result, windows, ingest_states, population_meta, started_at, finished_at):
    raw_records = sum(s["records"] for s in ingest_states)
    http_requests = sum(s["http_requests"] for s in ingest_states)
    retries = sum(s["retries"] for s in ingest_states)
    return {
        "code_version": {"package": __version__, "git_commit": git_commit()},
        "run": {"started_at": started_at.strftime(TIME_FORMAT), "finished_at": finished_at.strftime(TIME_FORMAT)},
        "window": {
            "mode": cfg.window.mode,
            "start": min(w.start for w in windows).isoformat(),
            "end_exclusive": max(w.end for w in windows).isoformat(),
            "scope_agencies": list(cfg.agencies),
            "scope_complaint_types": list(cfg.complaint_types),
        },
        "config": cfg.snapshot(),
        "records": {
            "raw": result.raw_total, "raw_downloaded_total": raw_records,
            "valid": result.valid_total, "quarantined": result.quarantined_total,
            "quarantine_by_reason": dict(sorted(result.quarantine_by_reason.items())),
        },
        "cleaning_stats": result.cleaning_stats,
        "join": result.join,
        "population_source": population_meta,
        "http": request_budget(raw_records, cfg.batch_size, http_requests, retries,
                               population_meta.get("http_requests", 0)),
        "output_hashes_sha256": dict(sorted(result.hashes.items())),
        "determinism_note": "run.* timestamps and git_commit are excluded from hashing; hashes cover data outputs.",
    }


def write_manifest(path, manifest):
    atomic_write_text(path, pretty_json(manifest))
