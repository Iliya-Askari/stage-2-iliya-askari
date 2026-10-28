"""Record sources. A source returns one page at a time and an opaque cursor for the next one.

Adding a new source (a file, a database) means implementing ``fetch_page``/``fingerprint``;
validation, quarantine and manifest code never touch HTTP.
"""

import json
import os
from itertools import islice

from .contract import SOURCE_COLUMNS
from .exceptions import ConfigError, HttpStatusError, SchemaDriftError
from .http_client import ensure_list_of_dicts
from .io_utils import sha256_text

NO_SUCH_COLUMN_MARKERS = ("no-such-column", "no such column", "query.soql.no-such-column")
APP_TOKEN_HEADER = "X-App-Token"


def case_variants(values):
    """Spellings to request: the API mixes 'WATER LEAK' and 'Water Leak', and SoQL '=' is case-sensitive.

    Listing the variants avoids calling upper() inside $where, which some gateways reject.
    """
    out = []
    for value in values:
        for variant in (value.upper(), value.title()):
            if variant not in out:
                out.append(variant)
    return out


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class SocrataSource:
    """Keyset-paginated reader for a Socrata resource endpoint (ordered by unique_key)."""

    def __init__(self, client, url, method, window, agencies, complaint_types=()):
        self.client = client
        self.url = url
        self.method = method
        self.window = window
        self.agencies = tuple(agencies)
        self.complaint_types = tuple(c.upper() for c in complaint_types)

    def fingerprint(self):
        return sha256_text("|".join([
            self.url, self.window.slug, ",".join(self.agencies), ",".join(self.complaint_types),
            ",".join(SOURCE_COLUMNS),
        ]))

    def build_params(self, cursor, limit):
        where = (
            f"created_date >= {_quote(self.window.start_dt.isoformat())} "
            f"AND created_date < {_quote(self.window.end_dt.isoformat())}"
        )
        if self.agencies:
            where += " AND agency in (" + ",".join(_quote(a) for a in self.agencies) + ")"
        if self.complaint_types:
            variants = case_variants(self.complaint_types)
            where += " AND complaint_type in (" + ",".join(_quote(c) for c in variants) + ")"
        if cursor is not None:
            where += f" AND unique_key > {_quote(cursor)}"
        return {
            "$select": ",".join(SOURCE_COLUMNS),
            "$where": where,
            "$order": "unique_key",
            "$limit": str(limit),
        }

    def fetch_page(self, cursor, limit):
        params = self.build_params(cursor, limit)
        try:
            payload = self.client.request(
                self.method, self.url,
                params=params if self.method == "GET" else None,
                json_body=params if self.method == "POST" else None,
                expect=list,
            )
        except HttpStatusError as exc:
            if exc.status_code == 400 and any(m in exc.body.lower() for m in NO_SUCH_COLUMN_MARKERS):
                raise SchemaDriftError(f"upstream rejected a contract column: {exc.body}") from exc
            raise
        records = ensure_list_of_dicts(payload, "socrata page")
        next_cursor = records[-1].get("unique_key") if records else cursor
        return records, next_cursor


class FileSource:
    """JSON-lines file source (used for offline demos/tests and future file inputs)."""

    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            raise ConfigError(f"source file not found: {path}")

    def fingerprint(self):
        return sha256_text("file|" + os.path.basename(self.path))

    def fetch_page(self, cursor, limit):
        offset = int(cursor or 0)
        with open(self.path, encoding="utf-8") as handle:
            lines = list(islice((ln for ln in handle if ln.strip()), offset, offset + limit))
        records = ensure_list_of_dicts([json.loads(ln) for ln in lines], "file page")
        return records, offset + len(records)


def build_source(cfg, client, window):
    if cfg.source.kind == "socrata":
        return SocrataSource(client, cfg.source.url, cfg.source.method, window, cfg.agencies, cfg.complaint_types)
    return FileSource(cfg.source.path)
