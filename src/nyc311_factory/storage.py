"""Raw batch store: JSONL batches plus an atomic checkpoint file inside one directory."""

import json
import os
import re
from pathlib import Path

from .exceptions import CheckpointError
from .io_utils import atomic_write_text, canonical_json, pretty_json

STATE_FILE = "_checkpoint.json"
BATCH_PATTERN = re.compile(r"^batch_(\d{5})\.jsonl$")
BATCH_NAME = "batch_{:05d}.jsonl"


def new_state(fingerprint):
    return {
        "fingerprint": fingerprint,
        "cursor": None,
        "next_batch": 1,
        "records": 0,
        "http_requests": 0,
        "retries": 0,
        "completed": False,
        "column_presence": {},
    }


class RawStore:
    def __init__(self, directory):
        self.dir = Path(directory)

    def load_state(self, fingerprint=None):
        path = self.dir / STATE_FILE
        if not path.exists():
            return new_state(fingerprint)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CheckpointError(f"checkpoint {path} is corrupt: {exc}") from exc
        if fingerprint is not None and state.get("fingerprint") != fingerprint:
            raise CheckpointError(
                f"{self.dir} was created with a different query/scope. "
                "Delete that directory or restore the previous configuration."
            )
        return state

    def save_state(self, state):
        atomic_write_text(self.dir / STATE_FILE, pretty_json(state))

    def write_batch(self, number, records):
        text = "".join(canonical_json(r) + "\n" for r in records)
        atomic_write_text(self.dir / BATCH_NAME.format(number), text)

    def batch_numbers(self):
        if not self.dir.exists():
            return []
        found = []
        for name in os.listdir(self.dir):
            match = BATCH_PATTERN.match(name)
            if match:
                found.append(int(match.group(1)))
        return sorted(found)

    def iter_batches(self):
        """Yield (batch_number, list_of_records) in order, one batch in memory at a time."""
        for number in self.batch_numbers():
            path = self.dir / BATCH_NAME.format(number)
            with open(path, encoding="utf-8") as handle:
                yield number, [json.loads(line) for line in handle if line.strip()]

    def verify_complete_prefix(self, next_batch):
        """Batches 1..next_batch-1 must all exist; otherwise resuming would silently lose data."""
        present = set(self.batch_numbers())
        missing = [n for n in range(1, next_batch) if n not in present]
        if missing:
            raise CheckpointError(f"checkpoint expects batches {missing[:5]} in {self.dir} but they are missing")
