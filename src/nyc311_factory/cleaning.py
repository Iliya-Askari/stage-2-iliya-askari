"""Record-level validation, cleaning and derivation (pure functions + one stateful processor).

Policies (also documented in docs/data_contract.md and report.md):
  * contract violations           -> quarantine with a reason code, never silently dropped
  * dirty-but-recoverable values  -> cleaned in place (ZIP placeholders -> null, borough imputed)
  * duplicate = same unique_key among valid records; first one in deterministic order wins
"""

import re
from datetime import datetime

from .contract import (BOROUGH_PLACEHOLDERS, BOROUGH_UNKNOWN, BOROUGHS, CLOSED_STATUS, DESCRIPTOR_UNKNOWN,
                       HOURS_PER_DAY, REQUIRED_SOURCE_COLUMNS, SECONDS_PER_HOUR, SOURCE_COLUMNS,
                       UNIQUE_KEY_MAX_LENGTH, ZIP_LENGTH, Reason)

ZIP_PATTERN = re.compile(r"^(\d{5})(?:-\d{4})?$")
WHITESPACE = re.compile(r"\s+")
HOURS_DECIMALS = 4
DAYS_DECIMALS = 6


class Rejected(Exception):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def normalize_text(value):
    """Strip and collapse whitespace; empty -> None."""
    if value is None:
        return None
    text = WHITESPACE.sub(" ", value).strip()
    return text or None


def clean_zip(value, placeholders):
    """Return (zip5 or None, was_nullified)."""
    text = normalize_text(value)
    if text is None:
        return None, False
    if text.upper() in placeholders:
        return None, True
    match = ZIP_PATTERN.match(text)
    if not match or match.group(1) == "0" * ZIP_LENGTH:
        return None, True
    return match.group(1), False


def parse_datetime(value):
    return datetime.fromisoformat(value)


class RecordProcessor:
    def __init__(self, cfg, population):
        self.cfg = cfg
        self.population = population
        self.agencies = set(cfg.agencies)
        self.complaint_types = {c.upper() for c in cfg.complaint_types}
        self.placeholders = set(cfg.zip_placeholders)
        self.seen_keys = set()
        self.stats = {
            "zip_nullified": 0, "zip_missing": 0, "borough_imputed_from_zip": 0,
            "borough_unresolved": 0, "zip_not_in_population": 0, "borough_zip_mismatch": 0,
            "descriptor_filled": 0, "complaint_type_case_normalized": 0, "open_cases": 0, "zero_duration_cases": 0,
        }

    def process(self, raw, window):
        """Return (row, None, None) or (None, reason_code, detail)."""
        try:
            row = self._process(raw, window)
        except Rejected as exc:
            return None, exc.code, exc.detail
        return row, None, None

    def _process(self, raw, window):
        values = {}
        for column in SOURCE_COLUMNS:
            value = raw.get(column)
            if value is not None and not isinstance(value, str):
                raise Rejected(Reason.BAD_TYPE, f"{column} has type {type(value).__name__}")
            values[column] = normalize_text(value)
        for column in REQUIRED_SOURCE_COLUMNS:
            if values[column] is None:
                raise Rejected(Reason.MISSING_REQUIRED, f"{column} is missing")
        original_type = values["complaint_type"]
        values["complaint_type"] = original_type.upper()  # the API mixes 'Water Leak' and 'WATER LEAK'
        if values["complaint_type"] != original_type:
            self.stats["complaint_type_case_normalized"] += 1
        key = values["unique_key"]
        if len(key) > UNIQUE_KEY_MAX_LENGTH:
            raise Rejected(Reason.BAD_UNIQUE_KEY, "unique_key too long")
        try:
            created = parse_datetime(values["created_date"])
        except ValueError:
            raise Rejected(Reason.INVALID_CREATED_DATE, values["created_date"])
        closed = None
        if values["closed_date"] is not None:
            try:
                closed = parse_datetime(values["closed_date"])
            except ValueError:
                raise Rejected(Reason.INVALID_CLOSED_DATE, values["closed_date"])
        if not window.start_dt <= created < window.end_dt:
            raise Rejected(Reason.OUT_OF_WINDOW, values["created_date"])
        if self.agencies and values["agency"] not in self.agencies:
            raise Rejected(Reason.AGENCY_OUT_OF_SCOPE, values["agency"])
        if self.complaint_types and values["complaint_type"] not in self.complaint_types:
            raise Rejected(Reason.COMPLAINT_TYPE_OUT_OF_SCOPE, values["complaint_type"])
        if closed is not None and closed < created:
            raise Rejected(Reason.CLOSED_BEFORE_CREATED, f"{values['created_date']} > {values['closed_date']}")
        if closed is None and values["status"].upper() == CLOSED_STATUS:
            raise Rejected(Reason.CLOSED_WITHOUT_DATE, "status is Closed but closed_date is empty")
        borough_raw = values["borough"].upper() if values["borough"] else None
        if borough_raw in BOROUGH_PLACEHOLDERS:
            borough_raw = None
        if borough_raw is not None and borough_raw not in BOROUGHS:
            raise Rejected(Reason.BAD_BOROUGH, values["borough"])
        if key in self.seen_keys:
            raise Rejected(Reason.DUPLICATE_KEY, key)
        self.seen_keys.add(key)
        return self._build_row(values, created, closed, borough_raw)

    def _build_row(self, values, created, closed, borough_raw):
        zip_code, nullified = clean_zip(values["incident_zip"], self.placeholders)
        if nullified:
            self.stats["zip_nullified"] += 1
        elif zip_code is None:
            self.stats["zip_missing"] += 1
        zip_borough = self.population.borough_of_zip(zip_code)
        borough = borough_raw
        if borough is None:
            if zip_borough:
                borough = zip_borough
                self.stats["borough_imputed_from_zip"] += 1
            else:
                borough = BOROUGH_UNKNOWN
                self.stats["borough_unresolved"] += 1
        mismatch = int(borough_raw is not None and zip_borough is not None and borough_raw != zip_borough)
        self.stats["borough_zip_mismatch"] += mismatch
        population = self.population.zip_to_pop.get(zip_code) if zip_code else None
        if zip_code and population is None:
            self.stats["zip_not_in_population"] += 1
        descriptor = values["descriptor"]
        if descriptor is None:
            descriptor = DESCRIPTOR_UNKNOWN
            self.stats["descriptor_filled"] += 1
        hours = days = None
        if closed is not None:
            hours = round((closed - created).total_seconds() / SECONDS_PER_HOUR, HOURS_DECIMALS)
            days = round(hours / HOURS_PER_DAY, DAYS_DECIMALS)
            if hours == 0:
                self.stats["zero_duration_cases"] += 1
        else:
            self.stats["open_cases"] += 1
        return {
            "unique_key": values["unique_key"], "created_date": created, "closed_date": closed,
            "agency": values["agency"], "complaint_type": values["complaint_type"],
            "descriptor": descriptor, "status": values["status"], "incident_zip": zip_code,
            "borough": borough, "zip_borough": zip_borough, "borough_mismatch": mismatch,
            "population_zip": population, "created_month": created.strftime("%Y-%m"),
            "created_hour": created.hour, "created_dow": created.weekday(),
            "is_closed": int(closed is not None), "resolution_hours": hours, "resolution_days": days,
        }
