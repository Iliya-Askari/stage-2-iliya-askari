"""The explicit data contract: source columns, curated columns, allowed values, reason codes."""

from dataclasses import dataclass
from typing import Optional, Tuple

# ---- upstream (raw) columns -------------------------------------------------
SOURCE_COLUMNS = (
    "unique_key", "created_date", "closed_date", "agency", "complaint_type",
    "descriptor", "status", "incident_zip", "borough",
)
REQUIRED_SOURCE_COLUMNS = ("unique_key", "created_date", "agency", "complaint_type", "status")
NULLABLE_SOURCE_COLUMNS = tuple(c for c in SOURCE_COLUMNS if c not in REQUIRED_SOURCE_COLUMNS)

# ---- value domains ----------------------------------------------------------
BOROUGHS = ("BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND")
BOROUGH_UNKNOWN = "UNSPECIFIED"
BOROUGH_PLACEHOLDERS = ("UNSPECIFIED", "UNKNOWN", "N/A")
DESCRIPTOR_UNKNOWN = "UNSPECIFIED"
CLOSED_STATUS = "CLOSED"
ZIP_LENGTH = 5
UNIQUE_KEY_MAX_LENGTH = 32
SECONDS_PER_HOUR = 3600
HOURS_PER_DAY = 24


class Reason:
    """Quarantine reason codes (stable identifiers, used in manifest and files)."""

    BAD_TYPE = "BAD_TYPE"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    BAD_UNIQUE_KEY = "BAD_UNIQUE_KEY"
    INVALID_CREATED_DATE = "INVALID_CREATED_DATE"
    INVALID_CLOSED_DATE = "INVALID_CLOSED_DATE"
    OUT_OF_WINDOW = "OUT_OF_WINDOW"
    AGENCY_OUT_OF_SCOPE = "AGENCY_OUT_OF_SCOPE"
    COMPLAINT_TYPE_OUT_OF_SCOPE = "COMPLAINT_TYPE_OUT_OF_SCOPE"
    CLOSED_BEFORE_CREATED = "CLOSED_BEFORE_CREATED"
    CLOSED_WITHOUT_DATE = "CLOSED_WITHOUT_DATE"
    BAD_BOROUGH = "BAD_BOROUGH"
    DUPLICATE_KEY = "DUPLICATE_KEY"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    dtype: str  # string | datetime | int | float
    nullable: bool
    unique: bool = False
    allowed: Optional[Tuple[str, ...]] = None
    note: str = ""


CASE_COLUMNS = (
    ColumnSpec("unique_key", "string", False, unique=True, note="record identity"),
    ColumnSpec("created_date", "datetime", False, note="inside the configured window"),
    ColumnSpec("closed_date", "datetime", True, note="null = still open; never before created_date"),
    ColumnSpec("agency", "string", False, note="restricted to configured scope"),
    ColumnSpec("complaint_type", "string", False),
    ColumnSpec("descriptor", "string", False, note="null filled with UNSPECIFIED"),
    ColumnSpec("status", "string", False),
    ColumnSpec("incident_zip", "string", True, note="5 digits; placeholders -> null"),
    ColumnSpec("borough", "string", False, allowed=BOROUGHS + (BOROUGH_UNKNOWN,),
               note="imputed from ZIP when missing"),
    ColumnSpec("zip_borough", "string", True, note="borough implied by ZIP prefix"),
    ColumnSpec("borough_mismatch", "int", False, allowed=("0", "1"), note="1 if 311 borough != ZIP borough"),
    ColumnSpec("population_zip", "int", True, note="reference population of the ZIP"),
    ColumnSpec("created_month", "string", False, note="YYYY-MM"),
    ColumnSpec("created_hour", "int", False),
    ColumnSpec("created_dow", "int", False, note="0=Monday"),
    ColumnSpec("is_closed", "int", False, allowed=("0", "1")),
    ColumnSpec("resolution_hours", "float", True, note=">= 0; null when open"),
    ColumnSpec("resolution_days", "float", True, note="resolution_hours / 24"),
)
CASE_COLUMN_NAMES = tuple(c.name for c in CASE_COLUMNS)
