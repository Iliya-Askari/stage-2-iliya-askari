import json
import tempfile
import unittest
from pathlib import Path

import requests

from nyc311_factory.config import Window
from nyc311_factory.exceptions import CheckpointError, NetworkError, SchemaDriftError
from nyc311_factory.http_client import HttpClient
from nyc311_factory.ingest import ingest
from nyc311_factory.sources import SocrataSource
from nyc311_factory.storage import RawStore
from nyc311_factory.synthetic import make_records
from datetime import date
from tests.helpers import FakeResponse, FakeSocrataSession, ScriptedSession

WINDOW = Window(date(2023, 1, 1), date(2024, 7, 1))
BATCH = 40


def build(records, tmp, fail_on_call=None, agencies=("HPD",)):
    session = FakeSocrataSession(records, fail_on_call=fail_on_call)
    client = HttpClient(session, max_retries=0, sleep=lambda s: None)
    source = SocrataSource(client, "http://api", "GET", WINDOW, agencies)
    return session, client, source, RawStore(Path(tmp) / "raw")


def stored_keys(store):
    return [r["unique_key"] for _, batch in store.iter_batches() for r in batch]


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.records = make_records(100, seed=3)

    def test_full_download_is_batched_and_complete(self):
        session, client, source, store = build(self.records, self.tmp.name)
        result = ingest(source, store, BATCH, client=client)
        self.assertTrue(result.completed)
        self.assertEqual(store.batch_numbers(), [1, 2, 3])
        self.assertEqual(len(session.calls), 3)  # ceil(100/40): short page ends the run, no extra probe
        self.assertEqual(result.state["http_requests"], 3)
        self.assertEqual(len(stored_keys(store)), 100)

    def test_resume_after_network_failure_continues_from_checkpoint_without_duplicates(self):
        session, client, source, store = build(self.records, self.tmp.name, fail_on_call=3)
        with self.assertRaises(NetworkError):
            ingest(source, store, BATCH, client=client)
        state = store.load_state()
        self.assertEqual((state["next_batch"], state["records"], state["completed"]), (3, 80, False))
        session2, client2, source2, _ = build(self.records, self.tmp.name)
        result = ingest(source2, store, BATCH, client=client2)
        self.assertEqual(len(session2.calls), 1)  # only the missing page was requested
        keys = stored_keys(store)
        self.assertEqual(keys, sorted(r["unique_key"] for r in self.records))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(result.state["http_requests"], 4)  # 3 attempts before the crash (one failed) + 1 after

    def test_pause_with_max_batches_then_resume_gives_same_files_as_uninterrupted(self):
        _, c1, s1, store1 = build(self.records, self.tmp.name + "/a")
        ingest(s1, store1, BATCH, client=c1)
        _, c2, s2, store2 = build(self.records, self.tmp.name + "/b")
        paused = ingest(s2, store2, BATCH, client=c2, max_batches=1)
        self.assertTrue(paused.paused)
        ingest(s2, store2, BATCH, client=c2)
        self.assertEqual(stored_keys(store1), stored_keys(store2))

    def test_rerun_after_completion_makes_no_requests(self):
        session, client, source, store = build(self.records, self.tmp.name)
        ingest(source, store, BATCH, client=client)
        calls = len(session.calls)
        ingest(source, store, BATCH, client=client)
        self.assertEqual(len(session.calls), calls)

    def test_checkpoint_for_other_scope_is_rejected(self):
        _, client, source, store = build(self.records, self.tmp.name)
        ingest(source, store, BATCH, client=client)
        _, _, other_source, _ = build(self.records, self.tmp.name, agencies=("DOT",))
        with self.assertRaises(CheckpointError):
            ingest(other_source, store, BATCH)

    def test_missing_batch_file_blocks_resume(self):
        _, client, source, store = build(self.records, self.tmp.name)
        ingest(source, store, BATCH, client=client, max_batches=2)
        (store.dir / "batch_00001.jsonl").unlink()
        with self.assertRaises(CheckpointError):
            ingest(source, store, BATCH, client=client)

    def test_schema_drift_required_column_removed(self):
        for r in self.records:
            r.pop("complaint_type")
        _, client, source, store = build(self.records, self.tmp.name)
        with self.assertRaises(SchemaDriftError):
            ingest(source, store, BATCH, client=client)
        self.assertEqual(store.batch_numbers(), [])  # nothing written from a drifted source

    def test_schema_drift_type_change(self):
        for r in self.records:
            r["created_date"] = 1672531200
        _, client, source, store = build(self.records, self.tmp.name)
        with self.assertRaises(SchemaDriftError):
            ingest(source, store, BATCH, client=client)

    def test_schema_drift_nullable_column_vanishes_over_whole_download(self):
        for r in self.records:
            r.pop("incident_zip")
        _, client, source, store = build(self.records, self.tmp.name)
        with self.assertRaises(SchemaDriftError):
            ingest(source, store, BATCH, client=client, min_rows_for_drift_check=50)

    def test_upstream_400_no_such_column_becomes_schema_drift(self):
        body = '{"code":"query.soql.no-such-column","message":"No such column: closed_date"}'
        client = HttpClient(ScriptedSession([FakeResponse(400, text=body)]), max_retries=0)
        source = SocrataSource(client, "http://api", "GET", WINDOW, ("HPD",))
        with self.assertRaises(SchemaDriftError):
            source.fetch_page(None, 10)

    def test_max_raw_records_truncates_and_completes(self):
        _, client, source, store = build(self.records, self.tmp.name)
        result = ingest(source, store, BATCH, client=client, max_raw_records=50)
        self.assertEqual(result.state["records"], 50)
        self.assertTrue(result.completed)

    def test_query_uses_keyset_cursor_and_window(self):
        _, client, source, _ = build(self.records, self.tmp.name)
        params = source.build_params("123", 10)
        self.assertIn("unique_key > '123'", params["$where"])
        self.assertIn("created_date < '2024-07-01T00:00:00'", params["$where"])
        self.assertEqual(params["$order"], "unique_key")


if __name__ == "__main__":
    unittest.main()


class ScopeTests(unittest.TestCase):
    def test_complaint_type_scope_is_in_query_and_changes_fingerprint(self):
        client = HttpClient(ScriptedSession([]), max_retries=0)
        plain = SocrataSource(client, "http://api", "GET", WINDOW, ("HPD",))
        scoped = SocrataSource(client, "http://api", "GET", WINDOW, ("HPD",), complaint_types=("HEAT/HOT WATER", "O'BRIEN"))
        where = scoped.build_params(None, 10)["$where"]
        self.assertIn("complaint_type in ('HEAT/HOT WATER','Heat/Hot Water','O''BRIEN','O''Brien')", where)
        self.assertNotIn("upper(", where)  # quotes escaped
        self.assertNotIn("complaint_type", plain.build_params(None, 10)["$where"])
        self.assertNotEqual(plain.fingerprint(), scoped.fingerprint())
