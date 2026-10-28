"""Typed, validated configuration loaded from a JSON file (no hidden defaults in logic)."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Optional, Tuple

from .exceptions import ConfigError

MAX_SOCRATA_PAGE = 50000  # server-side cap of $limit
SOURCE_KINDS = ("socrata", "file")
POPULATION_KINDS = ("census", "file")
HTTP_METHODS = ("GET", "POST")
WINDOW_MODES = ("fixed", "moving")


@dataclass(frozen=True)
class SourceConfig:
    kind: str
    url: str
    method: str
    path: Optional[str]
    app_token_env: Optional[str]


@dataclass(frozen=True)
class WindowConfig:
    mode: str
    start: date
    end: date  # exclusive


@dataclass(frozen=True)
class PopulationConfig:
    kind: str
    url: str
    params: Dict[str, str]
    value_column: str
    zip_column: str
    path: Optional[str]
    nyc_zip_prefixes: Tuple[str, ...]
    api_key_env: Optional[str] = None


@dataclass(frozen=True)
class PathsConfig:
    raw: str
    curated: str
    state: str


@dataclass(frozen=True)
class Config:
    source: SourceConfig
    window: WindowConfig
    agencies: Tuple[str, ...]
    batch_size: int
    max_retries: int
    backoff_seconds: float
    timeout_seconds: float
    max_raw_records: Optional[int]
    min_raw_records: int
    quarantine_max_ratio: float
    min_rows_for_drift_check: int
    rate_per_residents: int
    population: PopulationConfig
    zip_prefix_borough: Dict[str, str]
    zip_placeholders: Tuple[str, ...]
    paths: PathsConfig
    complaint_types: Tuple[str, ...] = ()

    def snapshot(self):
        """JSON-serialisable view recorded in the run manifest."""
        return {
            "source": {"kind": self.source.kind, "url": self.source.url, "method": self.source.method},
            "window_mode": self.window.mode,
            "agencies": list(self.agencies),
            "complaint_types": list(self.complaint_types),
            "batch_size": self.batch_size,
            "max_retries": self.max_retries,
            "max_raw_records": self.max_raw_records,
            "min_raw_records": self.min_raw_records,
            "quarantine_max_ratio": self.quarantine_max_ratio,
            "rate_per_residents": self.rate_per_residents,
            "population_source": self.population.url or self.population.path,
        }


def _is_absolute_path(text):
    """Absolute on any OS: Windows treats '/abs/path' as relative, so check both flavours."""
    text = str(text)
    return (PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute()
            or text.startswith(("/", "\\")))


def _parse_date(value, label):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


def _section(data, key):
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"config section '{key}' is missing or not an object")
    return value


def _positive_int(value, label, allow_none=False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{label} must be a positive integer, got {value!r}")
    return value


def config_from_dict(data, allow_absolute_paths=False):
    """Build and validate a Config; every problem becomes a ConfigError."""
    try:
        src = _section(data, "source")
        kind = src.get("kind")
        method = str(src.get("method", "GET")).upper()
        if kind not in SOURCE_KINDS:
            raise ConfigError(f"source.kind must be one of {SOURCE_KINDS}, got {kind!r}")
        if method not in HTTP_METHODS:
            raise ConfigError(f"source.method must be one of {HTTP_METHODS}, got {method!r}")
        if kind == "socrata" and not src.get("url"):
            raise ConfigError("source.url is required for kind 'socrata'")
        if kind == "file" and not src.get("path"):
            raise ConfigError("source.path is required for kind 'file'")
        source = SourceConfig(kind, src.get("url") or "", method, src.get("path"), src.get("app_token_env"))

        win = _section(data, "window")
        mode = win.get("mode", "fixed")
        if mode not in WINDOW_MODES:
            raise ConfigError(f"window.mode must be one of {WINDOW_MODES}, got {mode!r}")
        start = _parse_date(win.get("start"), "window.start")
        if mode == "fixed" and not win.get("end"):
            raise ConfigError("window.end is required in 'fixed' mode")
        end = _parse_date(win["end"], "window.end") if win.get("end") else start
        if mode == "fixed" and start >= end:
            raise ConfigError(f"window.start {start} must be before window.end {end}")
        window = WindowConfig(mode, start, end)

        batch_size = _positive_int(data.get("batch_size"), "batch_size")
        if batch_size > MAX_SOCRATA_PAGE:
            raise ConfigError(f"batch_size must be <= {MAX_SOCRATA_PAGE} (server page cap)")
        max_retries = data.get("max_retries")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ConfigError(f"max_retries must be an integer >= 0, got {max_retries!r}")
        ratio = data.get("quarantine_max_ratio")
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0 <= ratio <= 1:
            raise ConfigError(f"quarantine_max_ratio must be within [0, 1], got {ratio!r}")
        min_raw = data.get("min_raw_records", 0)
        if not isinstance(min_raw, int) or min_raw < 0:
            raise ConfigError("min_raw_records must be an integer >= 0")

        pop = _section(data, "population")
        pkind = pop.get("kind")
        if pkind not in POPULATION_KINDS:
            raise ConfigError(f"population.kind must be one of {POPULATION_KINDS}, got {pkind!r}")
        if pkind == "file" and not pop.get("path"):
            raise ConfigError("population.path is required for kind 'file'")
        if pkind == "census" and not pop.get("url"):
            raise ConfigError("population.url is required for kind 'census'")
        population = PopulationConfig(
            kind=pkind,
            url=pop.get("url") or "",
            params=dict(pop.get("params") or {}),
            value_column=pop.get("value_column", ""),
            zip_column=pop.get("zip_column", ""),
            path=pop.get("path"),
            nyc_zip_prefixes=tuple(pop.get("nyc_zip_prefixes") or ()),
            api_key_env=pop.get("api_key_env"),
        )

        mapping = data.get("zip_prefix_borough")
        if not isinstance(mapping, dict) or not mapping:
            raise ConfigError("zip_prefix_borough must be a non-empty object")

        paths = _section(data, "paths")
        for key in ("raw", "curated", "state"):
            if not paths.get(key) or (_is_absolute_path(paths[key]) and not allow_absolute_paths):
                raise ConfigError(f"paths.{key} must be a non-empty relative path")

        return Config(
            source=source,
            window=window,
            agencies=tuple(_section(data, "scope").get("agencies") or ()),
            batch_size=batch_size,
            max_retries=max_retries,
            backoff_seconds=float(data.get("backoff_seconds", 1.0)),
            timeout_seconds=float(data.get("timeout_seconds", 60)),
            max_raw_records=_positive_int(data.get("max_raw_records"), "max_raw_records", allow_none=True),
            min_raw_records=min_raw,
            quarantine_max_ratio=float(ratio),
            min_rows_for_drift_check=_positive_int(data.get("min_rows_for_drift_check", 1000), "min_rows_for_drift_check"),
            rate_per_residents=_positive_int(data.get("rate_per_residents", 10000), "rate_per_residents"),
            population=population,
            zip_prefix_borough={str(k): str(v).upper() for k, v in mapping.items()},
            zip_placeholders=tuple(str(x).upper() for x in data.get("zip_placeholders", ())),
            paths=PathsConfig(paths["raw"], paths["curated"], paths["state"]),
            complaint_types=tuple(str(c).upper() for c in (_section(data, "scope").get("complaint_types") or ())),
        )
    except ConfigError:
        raise
    except (TypeError, ValueError, AttributeError) as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc


def load_config(path, allow_absolute_paths=False):
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file is not valid JSON: {path}: {exc}") from exc
    return config_from_dict(data, allow_absolute_paths)


class Window:
    """Half-open creation-date interval [start, end)."""

    def __init__(self, start, end):
        self.start = start
        self.end = end

    @property
    def start_dt(self):
        return datetime.combine(self.start, datetime.min.time())

    @property
    def end_dt(self):
        return datetime.combine(self.end, datetime.min.time())

    @property
    def slug(self):
        return f"{self.start.isoformat()}_{self.end.isoformat()}"

    def __repr__(self):
        return f"Window({self.start}..{self.end})"

    def __eq__(self, other):
        return isinstance(other, Window) and (self.start, self.end) == (other.start, other.end)
