"""Stage orchestration: fetch (raw) -> curate (validate/clean/join/aggregate) -> manifest."""

import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .config import Window
from .curate import (CASE_FILE, QUALITY_FILE, QUARANTINE_FILE, WIDE_FILE, curate, publish)
from .exceptions import ConfigError, IngestIncompleteError
from .http_client import HttpClient
from .ingest import ingest
from .io_utils import atomic_write_text, pretty_json
from .manifest import MANIFEST_FILE, build_manifest, utc_now, write_manifest
from .population import Population, ensure_population, load_population_csv
from .sources import APP_TOKEN_HEADER, build_source
from .storage import RawStore

LOG = logging.getLogger("nyc311")
RAW_PREFIX = "311_"
RAW_DIR_PATTERN = re.compile(r"^311_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$")
LAST_RUN_FILE = "last_run.json"
USER_AGENT = "nyc311-factory/1.0 (university data-engineering project)"
OUTPUT_NAMES = (CASE_FILE, WIDE_FILE, QUARANTINE_FILE, QUALITY_FILE)


def make_client(cfg, session=None, sleep=time.sleep):
    headers = {"User-Agent": USER_AGENT}
    token_env = cfg.source.app_token_env
    if token_env and os.environ.get(token_env):
        headers[APP_TOKEN_HEADER] = os.environ[token_env]
    return HttpClient(session=session, max_retries=cfg.max_retries, backoff_seconds=cfg.backoff_seconds,
                      timeout_seconds=cfg.timeout_seconds, sleep=sleep, default_headers=headers)


def _last_run_path(cfg):
    return Path(cfg.paths.state) / LAST_RUN_FILE


def read_last_run(cfg):
    path = _last_run_path(cfg)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is corrupt: {exc}") from exc


def resolve_window(cfg, as_of=None):
    """Fixed mode: the configured window. Moving mode: last run's end .. today (None if up to date)."""
    if cfg.window.mode == "fixed":
        return Window(cfg.window.start, cfg.window.end)
    last = read_last_run(cfg)
    start = date.fromisoformat(last["window_end"]) if last else cfg.window.start
    end = as_of or datetime.now(timezone.utc).date()
    if start >= end:
        return None
    return Window(start, end)


def raw_dir_for(cfg, window):
    return Path(cfg.paths.raw) / f"{RAW_PREFIX}{window.slug}"


def raw_windows_for_curation(cfg, as_of=None):
    """(directory, Window) pairs that feed the curated outputs, in deterministic order."""
    raw_root = Path(cfg.paths.raw)
    if cfg.window.mode == "fixed":
        window = Window(cfg.window.start, cfg.window.end)
        return [(raw_dir_for(cfg, window), window)]
    pairs = []
    if raw_root.exists():
        for name in sorted(os.listdir(raw_root)):
            match = RAW_DIR_PATTERN.match(name)
            if match:
                pairs.append((raw_root / name, Window(date.fromisoformat(match.group(1)),
                                                      date.fromisoformat(match.group(2)))))
    if not pairs:
        raise IngestIncompleteError("no raw windows found; run 'fetch' first")
    return pairs


def run_fetch(cfg, client=None, as_of=None, max_batches=None, refresh_population=False):
    client = client or make_client(cfg)
    window = resolve_window(cfg, as_of)
    summary = {"window": window, "completed": True, "records": 0}
    if window is None:
        LOG.info("moving window: nothing new since last run")
    else:
        source = build_source(cfg, client, window)
        store = RawStore(raw_dir_for(cfg, window))
        result = ingest(source, store, cfg.batch_size, client=client, max_batches=max_batches,
                        max_raw_records=cfg.max_raw_records,
                        min_rows_for_drift_check=cfg.min_rows_for_drift_check)
        summary.update(completed=result.completed, records=result.state["records"])
        LOG.info("fetch %s: %d records, completed=%s, http_requests=%d",
                 window, result.state["records"], result.completed, result.state["http_requests"])
    ensure_population(cfg, client, refresh=refresh_population)
    return summary


def run_curate(cfg, client=None, as_of=None, started_at=None):
    started_at = started_at or utc_now()
    client = client or make_client(cfg)
    population_path, population_meta = ensure_population(cfg, client)
    population = Population(load_population_csv(population_path), cfg.zip_prefix_borough)
    pairs = raw_windows_for_curation(cfg, as_of)
    states = []
    for directory, _ in pairs:
        state = RawStore(directory).load_state()
        if not state["completed"]:
            raise IngestIncompleteError(f"{directory} is incomplete; resume with 'fetch'")
        states.append(state)
    result = curate(cfg, pairs, population)
    manifest = build_manifest(cfg, result, result.windows, states, population_meta, started_at, utc_now())
    atomic_write_text(Path(result.tmp_dir) / MANIFEST_FILE, pretty_json(manifest))
    publish(result.tmp_dir, cfg.paths.curated, OUTPUT_NAMES + (MANIFEST_FILE,))
    atomic_write_text(_last_run_path(cfg), pretty_json(
        {"window_end": max(w.end for w in result.windows).isoformat(), "finished_at": manifest["run"]["finished_at"]}))
    LOG.info("curate: raw=%d valid=%d quarantined=%d", result.raw_total, result.valid_total, result.quarantined_total)
    return result, manifest


def run_all(cfg, client=None, as_of=None, max_batches=None, refresh_population=False):
    started_at = utc_now()
    client = client or make_client(cfg)
    summary = run_fetch(cfg, client, as_of, max_batches, refresh_population)
    if not summary["completed"]:
        return summary, None, None
    result, manifest = run_curate(cfg, client, as_of, started_at)
    return summary, result, manifest
