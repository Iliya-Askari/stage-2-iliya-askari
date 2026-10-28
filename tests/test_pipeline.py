import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from nyc311_factory import cli
from nyc311_factory.config import WindowConfig, config_from_dict
from nyc311_factory.curate import FAILED_QUARANTINE_FILE
from nyc311_factory.exceptions import InsufficientDataError, QuarantineThresholdError
from nyc311_factory.outputs import build_wide_table, month_range
from nyc311_factory.pipeline import read_last_run, resolve_window, run_all, run_curate, run_fetch
from nyc311_factory.population import parse_census_payload
from nyc311_factory.exceptions import PopulationError
from tests.helpers import prepare_file_inputs


def cfg_for(root, **kw):
    data, _ = prepare_file_inputs(root, **kw)
    return config_from_dict(data, allow_absolute_paths=True), data


def read_manifest(cfg):
    return json.loads((Path(cfg.paths.curated) / "run_manifest.json").read_text())


def hashes(cfg):
    return read_manifest(cfg)["output_hashes_sha256"]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_counts_are_consistent_and_quarantine_has_reason_codes(self):
        cfg, _ = cfg_for(self.root, n=400, defect_rate=0.1, duplicates=5)
        _, result, manifest = run_all(cfg)
        rec = manifest["records"]
        self.assertEqual(rec["raw"], 405)
        self.assertEqual(rec["raw"], rec["valid"] + rec["quarantined"])
        self.assertEqual(sum(rec["quarantine_by_reason"].values()), rec["quarantined"])
        self.assertTrue(1 <= rec["quarantine_by_reason"]["DUPLICATE_KEY"] <= 5)  # a defective original is quarantined for its defect first
        lines = (Path(cfg.paths.curated) / "quarantine.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), rec["quarantined"])
        self.assertTrue(all("reason_code" in json.loads(l) for l in lines))

    def test_quarantine_over_threshold_fails_and_publishes_no_outputs(self):
        cfg, _ = cfg_for(self.root, n=200, defect_rate=0.5)
        cfg = replace(cfg, quarantine_max_ratio=0.05)
        with self.assertRaises(QuarantineThresholdError):
            run_all(cfg)
        curated = Path(cfg.paths.curated)
        self.assertFalse((curated / "case_level.csv").exists())
        self.assertFalse((curated / "run_manifest.json").exists())
        self.assertTrue((curated / FAILED_QUARANTINE_FILE).exists())
        self.assertFalse((curated / "_tmp").exists())

    def test_min_raw_records_is_enforced(self):
        cfg, _ = cfg_for(self.root, n=50)
        with self.assertRaises(InsufficientDataError):
            run_all(replace(cfg, min_raw_records=1000))

    def test_independent_runs_from_scratch_have_identical_hashes(self):
        cfg_a, _ = cfg_for(self.root / "a", n=300, defect_rate=0.05, seed=7)
        cfg_b, _ = cfg_for(self.root / "b", n=300, defect_rate=0.05, seed=7)
        run_all(cfg_a)
        run_all(cfg_b)
        self.assertEqual(hashes(cfg_a), hashes(cfg_b))

    def test_second_run_same_folder_is_idempotent(self):
        cfg, _ = cfg_for(self.root, n=300, defect_rate=0.05, duplicates=3)
        run_all(cfg)
        first = hashes(cfg)
        run_all(cfg)
        self.assertEqual(first, hashes(cfg))
        keys = [l.split(",")[0] for l in (Path(cfg.paths.curated) / "case_level.csv").read_text().splitlines()[1:]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_interrupted_download_resumes_and_matches_clean_run(self):
        cfg_a, _ = cfg_for(self.root / "a", n=350, defect_rate=0.05, seed=9)
        cfg_b, _ = cfg_for(self.root / "b", n=350, defect_rate=0.05, seed=9)
        run_all(cfg_a)
        summary, result, _ = run_all(cfg_b, max_batches=1)
        self.assertFalse(summary["completed"])
        self.assertIsNone(result)
        self.assertFalse((Path(cfg_b.paths.curated) / "case_level.csv").exists())
        run_all(cfg_b)
        self.assertEqual(hashes(cfg_a), hashes(cfg_b))

    def test_join_keeps_row_count_and_reports_unmatched(self):
        cfg, _ = cfg_for(self.root, n=300, defect_rate=0.1)
        _, _, manifest = run_all(cfg)
        join = manifest["join"]
        self.assertEqual(join["rows_before_join"], join["rows_after_join"])
        self.assertEqual(join["rows_before_join"], manifest["records"]["valid"])
        self.assertEqual(join["matched_population"] + join["unmatched_population"], join["rows_after_join"])

    def test_manifest_contains_required_fields(self):
        cfg, _ = cfg_for(self.root, n=120)
        _, _, manifest = run_all(cfg)
        for key in ("code_version", "run", "window", "records", "http", "output_hashes_sha256", "join"):
            self.assertIn(key, manifest)
        self.assertEqual(manifest["window"]["start"], "2023-01-01")
        self.assertEqual(set(manifest["output_hashes_sha256"]),
                         {"case_level.csv", "data_quality_report.csv", "quarantine.jsonl", "wide_borough_type_month.csv"})

    def test_wide_table_zero_fills_and_computes_rate(self):
        counts = {("BRONX", "NOISE", "2023-01"): 3, ("BRONX", "NOISE", "2023-03"): 1}
        columns, rows = build_wide_table(counts, {"BRONX": 20000}, 10000)
        self.assertEqual(month_range("2023-01", "2023-03"), ["2023-01", "2023-02", "2023-03"])
        self.assertEqual(rows[0]["count_2023-02"], 0)
        self.assertEqual(rows[0]["total_count"], 4)
        self.assertEqual(rows[0]["rate_per_10000_2023-01"], "1.5000")
        _, rows = build_wide_table(counts, {}, 10000)
        self.assertIsNone(rows[0]["rate_per_10000_2023-01"])  # unknown population -> no rate, not a fake zero

    def test_moving_window_starts_at_last_run_end(self):
        cfg, _ = cfg_for(self.root, n=100)
        run_all(cfg)  # fixed run writes last_run state
        self.assertEqual(read_last_run(cfg)["window_end"], "2024-07-01")
        moving = replace(cfg, window=WindowConfig("moving", cfg.window.start, cfg.window.end))
        window = resolve_window(moving, as_of=date(2024, 9, 1))
        self.assertEqual((window.start, window.end), (date(2024, 7, 1), date(2024, 9, 1)))
        self.assertIsNone(resolve_window(moving, as_of=date(2024, 7, 1)))

    def test_census_payload_parsing_and_validation(self):
        payload = [["B01003_001E", "zip code tabulation area"], ["1000", "10001"], ["-666666666", "10002"], ["5", "99999"]]
        pops, skipped = parse_census_payload(payload, "B01003_001E", "zip code tabulation area", {"100"})
        self.assertEqual((pops, skipped), ({"10001": 1000}, 1))
        with self.assertRaises(PopulationError):
            parse_census_payload([["x"], ["1"]], "B01003_001E", "zip code tabulation area", {"100"})

    def test_cli_maps_errors_to_distinct_exit_codes(self):
        self.assertEqual(cli.main(["--config", str(self.root / "missing.json")]), 2)
        bad = self.root / "bad.json"
        bad.write_text("{not json")
        self.assertEqual(cli.main(["--config", str(bad)]), 2)
        data, _ = prepare_file_inputs(self.root, n=50)
        data["paths"] = {"raw": "raw", "curated": "curated", "state": "state"}  # CLI requires relative paths
        cfgfile = self.root / "ok.json"
        cfgfile.write_text(json.dumps(data))
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        self.assertEqual(cli.main(["--config", str(cfgfile), "curate"]), 8)  # not downloaded yet -> incomplete


if __name__ == "__main__":
    unittest.main()


class PopulationKeyTests(unittest.TestCase):
    def test_census_key_is_sent_but_not_stored_in_meta(self):
        from nyc311_factory.http_client import HttpClient
        from nyc311_factory.population import ensure_population
        from tests.helpers import FakeResponse, ScriptedSession, make_config
        payload = [["B01003_001E", "zip code tabulation area"], ["1000", "10001"]]
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            pop = replace(cfg.population, kind="census", url="http://census", value_column="B01003_001E",
                          zip_column="zip code tabulation area", nyc_zip_prefixes=("100",), api_key_env="TEST_CENSUS_KEY")
            cfg = replace(cfg, population=pop)
            session = ScriptedSession([FakeResponse(200, payload)])
            os.environ["TEST_CENSUS_KEY"] = "SECRET123"
            self.addCleanup(os.environ.pop, "TEST_CENSUS_KEY", None)
            _, meta = ensure_population(cfg, HttpClient(session, max_retries=0))
            self.assertEqual(session.calls[0][2]["params"]["key"], "SECRET123")
            self.assertNotIn("SECRET123", json.dumps(meta))
