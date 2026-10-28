"""Batched, resumable, idempotent download of raw records into a RawStore."""

from . import schema
from .exceptions import CheckpointError


class IngestResult:
    def __init__(self, state, paused):
        self.state = state
        self.paused = paused

    @property
    def completed(self):
        return bool(self.state["completed"])


def ingest(source, store, batch_size, client=None, max_batches=None, max_raw_records=None,
           min_rows_for_drift_check=1000):
    """Download until the source is exhausted.

    Resume logic: the checkpoint stores the cursor *after* the last fully written batch.
    A batch file is written atomically BEFORE the checkpoint is advanced, so a crash can only
    leave a batch that will be re-fetched and rewritten with identical content (idempotent).
    """
    state = store.load_state(source.fingerprint())
    if state["completed"]:
        return IngestResult(state, paused=False)
    store.verify_complete_prefix(state["next_batch"])
    start_requests = client.total_requests if client else 0
    start_retries = client.retries if client else 0
    base_requests = state["http_requests"]
    base_retries = state["retries"]
    batches_done = 0

    def sync_counters():
        if client:
            state["http_requests"] = base_requests + client.total_requests - start_requests
            state["retries"] = base_retries + client.retries - start_retries

    try:
        while True:
            if max_batches is not None and batches_done >= max_batches:
                sync_counters()
                store.save_state(state)
                return IngestResult(state, paused=True)
            records, next_cursor = source.fetch_page(state["cursor"], batch_size)
            sync_counters()
            exhausted = len(records) < batch_size
            if max_raw_records is not None:
                remaining = max_raw_records - state["records"]
                if len(records) >= remaining:
                    records = records[:remaining]
                    exhausted = True
            if records:
                schema.check_batch(records)
                schema.update_presence(state["column_presence"], records)
                store.write_batch(state["next_batch"], records)
                state["records"] += len(records)
                state["next_batch"] += 1
                state["cursor"] = next_cursor
                batches_done += 1
            if exhausted:
                schema.check_final(state["column_presence"], state["records"], min_rows_for_drift_check)
                state["completed"] = True
                store.save_state(state)
                return IngestResult(state, paused=False)
            store.save_state(state)
    except BaseException:
        sync_counters()
        try:
            store.save_state(state)
        except OSError:
            pass
        raise
