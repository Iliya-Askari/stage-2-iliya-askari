"""Detection of upstream schema/type changes (fail loudly instead of creating empty columns)."""

from .contract import NULLABLE_SOURCE_COLUMNS, REQUIRED_SOURCE_COLUMNS, SOURCE_COLUMNS
from .exceptions import SchemaDriftError

NON_STRING_RATIO_LIMIT = 0.5


def update_presence(presence, records):
    """Accumulate, per column, how many records contain a non-null value."""
    for column in SOURCE_COLUMNS:
        presence[column] = presence.get(column, 0) + sum(1 for r in records if r.get(column) is not None)


def check_batch(records):
    """Per-batch checks: required columns must exist and values must keep their (string) type."""
    if not records:
        return
    total = len(records)
    for column in REQUIRED_SOURCE_COLUMNS:
        present = sum(1 for r in records if r.get(column) is not None)
        if present == 0:
            raise SchemaDriftError(f"required column '{column}' is absent from all {total} records of a batch")
    for column in SOURCE_COLUMNS:
        values = [r[column] for r in records if r.get(column) is not None]
        if not values:
            continue
        non_string = sum(1 for v in values if not isinstance(v, str))
        if non_string / len(values) > NON_STRING_RATIO_LIMIT:
            raise SchemaDriftError(
                f"column '{column}' changed type: {non_string}/{len(values)} values are not strings"
            )


def check_final(presence, total_records, min_rows):
    """Whole-download check for nullable columns (the API omits nulls, so one batch proves nothing)."""
    if total_records < min_rows:
        return
    for column in NULLABLE_SOURCE_COLUMNS:
        if presence.get(column, 0) == 0:
            raise SchemaDriftError(f"column '{column}' never appeared in {total_records} records")
