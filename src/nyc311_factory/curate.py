"""Streaming validation + cleaning + join + aggregation over raw batches.

Memory: one raw batch at a time; only the set of seen unique_keys and the (tiny) aggregate
counters live for the whole run. Outputs are built in ``<curated>/_tmp`` and published atomically
only if every check passes, so an interrupted/failed run never leaves partial results.
"""

import json
import os
import shutil
from pathlib import Path

from .config import Window
from .contract import CASE_COLUMN_NAMES, CASE_COLUMNS
from .cleaning import RecordProcessor
from .exceptions import IngestIncompleteError, InsufficientDataError, QuarantineThresholdError
from .io_utils import canonical_json, sha256_file
from .outputs import Aggregator, CsvWriter, build_wide_table, write_dict_rows
from .quality import DatasetProfiler
from .storage import RawStore

TMP_DIR = "_tmp"
CASE_FILE = "case_level.csv"
WIDE_FILE = "wide_borough_type_month.csv"
QUARANTINE_FILE = "quarantine.jsonl"
QUALITY_FILE = "data_quality_report.csv"
FAILED_QUARANTINE_FILE = "quarantine_failed_run.jsonl"
QUALITY_COLUMNS = ("column", "dtype", "rows", "null_pct", "n_unique", "min", "max")


class CurateResult:
    def __init__(self):
        self.raw_total = 0
        self.valid_total = 0
        self.quarantine_by_reason = {}
        self.cleaning_stats = {}
        self.join = {}
        self.tmp_dir = None
        self.hashes = {}
        self.windows = []

    @property
    def quarantined_total(self):
        return sum(self.quarantine_by_reason.values())


def _check_ratio(result, max_ratio, final=False):
    if result.raw_total and result.quarantined_total / result.raw_total > max_ratio:
        ratio = result.quarantined_total / result.raw_total
        raise QuarantineThresholdError(
            f"quarantine ratio {ratio:.4%} exceeds limit {max_ratio:.4%} "
            f"({result.quarantined_total}/{result.raw_total}); reasons={result.quarantine_by_reason}")


def curate(cfg, raw_dirs_with_windows, population):
    curated = Path(cfg.paths.curated)
    tmp = curated / TMP_DIR
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    result = CurateResult()
    result.tmp_dir = tmp
    result.windows = [w for _, w in raw_dirs_with_windows]
    processor = RecordProcessor(cfg, population)
    case_writer = CsvWriter(tmp / CASE_FILE, CASE_COLUMN_NAMES)
    quarantine = open(tmp / QUARANTINE_FILE, "w", encoding="utf-8", newline="\n")
    profiler = DatasetProfiler(CASE_COLUMNS)
    aggregator = Aggregator()
    matched = 0
    try:
        for raw_dir, window in raw_dirs_with_windows:
            store = RawStore(raw_dir)
            if not store.load_state()["completed"]:
                raise IngestIncompleteError(f"raw download in {raw_dir} is not complete; run 'fetch' first")
            for _, records in store.iter_batches():
                for raw in records:
                    result.raw_total += 1
                    row, code, detail = processor.process(raw, window)
                    if row is None:
                        result.quarantine_by_reason[code] = result.quarantine_by_reason.get(code, 0) + 1
                        quarantine.write(canonical_json(
                            {"reason_code": code, "reason_detail": detail, "record": raw}) + "\n")
                        continue
                    result.valid_total += 1
                    matched += int(row["population_zip"] is not None)
                    case_writer.write_row(row)
                    profiler.add_row(row)
                    aggregator.add(row)
                _check_ratio(result, cfg.quarantine_max_ratio)
        _check_ratio(result, cfg.quarantine_max_ratio, final=True)
        if result.raw_total < cfg.min_raw_records:
            raise InsufficientDataError(
                f"only {result.raw_total} raw records, configured minimum is {cfg.min_raw_records}")
    except BaseException as exc:
        case_writer.close()
        quarantine.close()
        if isinstance(exc, QuarantineThresholdError):
            os.replace(tmp / QUARANTINE_FILE, curated / FAILED_QUARANTINE_FILE)
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    case_writer.close()
    quarantine.close()
    result.cleaning_stats = dict(sorted(processor.stats.items()))
    result.join = {
        "rows_before_join": result.valid_total, "rows_after_join": result.valid_total,
        "matched_population": matched, "unmatched_population": result.valid_total - matched,
        "population_zip_rows": len(population.zip_to_pop),
        "note": "many-to-one lookup on a unique ZIP key: row count must not change",
    }
    columns, rows = build_wide_table(aggregator.counts, population.borough_totals(), cfg.rate_per_residents)
    write_dict_rows(tmp / WIDE_FILE, columns, rows)
    write_dict_rows(tmp / QUALITY_FILE, QUALITY_COLUMNS, profiler.report_rows())
    for name in (CASE_FILE, WIDE_FILE, QUARANTINE_FILE, QUALITY_FILE):
        result.hashes[name] = sha256_file(tmp / name)
    result.quality_rows = profiler.report_rows()
    return result


def publish(tmp_dir, curated_dir, names):
    """Atomically move finished files from the temp directory into place."""
    for name in names:
        os.replace(Path(tmp_dir) / name, Path(curated_dir) / name)
    shutil.rmtree(tmp_dir, ignore_errors=True)
