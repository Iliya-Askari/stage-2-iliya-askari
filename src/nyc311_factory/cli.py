"""Command line interface: ``nyc311 run|fetch|curate``. Exit codes come from the exception classes."""

import argparse
import logging
import sys
from dataclasses import replace
from datetime import date

from .config import WindowConfig, load_config
from .exceptions import ConfigError, FactoryError
from .pipeline import run_all, run_curate, run_fetch

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_INTERRUPTED = 130
DEFAULT_CONFIG = "config/default.json"


def build_parser():
    parser = argparse.ArgumentParser(prog="nyc311", description="NYC 311 data factory")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="path to the JSON config file")
    parser.add_argument("--mode", choices=["fixed", "moving"], help="override window.mode")
    parser.add_argument("--as-of", help="moving window end date (YYYY-MM-DD), default today")
    parser.add_argument("--max-batches", type=int, help="stop the download after N batches (resume later)")
    parser.add_argument("--refresh-population", action="store_true", help="re-download the population table")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("command", choices=["run", "fetch", "curate", "pg-load", "olist-load", "db-load", "db-init", "db-tune"], nargs="?", default="run")
    return parser


def _apply_overrides(cfg, args):
    if args.mode:
        cfg = replace(cfg, window=WindowConfig(args.mode, cfg.window.start, cfg.window.end))
    return cfg


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    try:
        cfg = _apply_overrides(load_config(args.config), args)
        try:
            as_of = date.fromisoformat(args.as_of) if args.as_of else None
        except ValueError as exc:
            raise ConfigError(f"--as-of must be YYYY-MM-DD: {exc}") from exc
        if args.command == "db-init":
            from .postgres import initialize_database
            initialize_database()
            print("PostgreSQL DDL applied from sql/001_olist_schema.sql")
        elif args.command == "db-tune":
            from .postgres import apply_sql_file
            apply_sql_file("sql/003_performance_indexes.sql")
            print("Candidate performance indexes applied from sql/003_performance_indexes.sql")
        elif args.command in ("pg-load", "db-load"):
            if args.command == "db-load":
                from .postgres import initialize_database
                initialize_database()
            from .postgres import load_curated_postgres
            count = load_curated_postgres(cfg.paths.curated)
            print(f"PostgreSQL load finished: rows={count} schema=factory table=stage1_cases")
            if args.command == "db-load":
                from .olist import load_olist
                result = load_olist()
                print(f"Olist PostgreSQL load finished: loaded={result['loaded']} rejected={result['rejected']} "
                      f"by_reason={result['rejected_by_reason']} quarantine={result['quarantine_path']} "
                      f"manifest={result['manifest_path']}")
        elif args.command == "olist-load":
            from .olist import load_olist
            result = load_olist()
            print(f"Olist PostgreSQL load finished: loaded={result['loaded']} rejected={result['rejected']} "
                  f"by_reason={result['rejected_by_reason']} quarantine={result['quarantine_path']} "
                  f"manifest={result['manifest_path']}")
        elif args.command == "fetch":
            summary = run_fetch(cfg, as_of=as_of, max_batches=args.max_batches,
                                refresh_population=args.refresh_population)
            print(f"fetch finished: records={summary['records']} completed={summary['completed']}")
        elif args.command == "curate":
            result, _ = run_curate(cfg, as_of=as_of)
            print(f"curate finished: raw={result.raw_total} valid={result.valid_total} "
                  f"quarantined={result.quarantined_total}")
        else:
            summary, result, _ = run_all(cfg, as_of=as_of, max_batches=args.max_batches,
                                         refresh_population=args.refresh_population)
            if result is None:
                print("download paused (max-batches reached); run again to resume")
            else:
                print(f"done: raw={result.raw_total} valid={result.valid_total} "
                      f"quarantined={result.quarantined_total}")
        return EXIT_OK
    except FactoryError as exc:
        print(f"ERROR [{type(exc).__name__}]: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("interrupted; progress is saved, rerun to resume", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
