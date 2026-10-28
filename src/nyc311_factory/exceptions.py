"""Project-specific exception hierarchy.

Every exception carries the process exit code the CLI should use, so that a
network failure, a data-validation failure and a configuration failure are
distinguishable by shell scripts and CI.
"""


class FactoryError(Exception):
    """Base class of all expected, project-level failures."""

    exit_code = 1


class ConfigError(FactoryError):
    """Configuration is missing, malformed or inconsistent."""

    exit_code = 2


class CheckpointError(ConfigError):
    """Saved ingestion state does not match the current configuration/files."""


class NetworkError(FactoryError):
    """A remote request failed permanently (after retries)."""

    exit_code = 3


class HttpStatusError(NetworkError):
    """A non-retryable HTTP status was returned."""

    def __init__(self, message, status_code=None, body=""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class MalformedResponseError(NetworkError):
    """The response body was incomplete or had an unexpected shape."""


class SchemaDriftError(FactoryError):
    """The upstream source no longer matches the expected schema."""

    exit_code = 4


class ValidationError(FactoryError):
    """Data failed the contract in a way that stops the run."""

    exit_code = 5


class PopulationError(ValidationError):
    """The population reference table is unusable."""


class QuarantineThresholdError(ValidationError):
    """Too many records were quarantined; the data is suspicious."""

    exit_code = 6


class InsufficientDataError(FactoryError):
    """Fewer raw records than the configured minimum were obtained."""

    exit_code = 7


class IngestIncompleteError(FactoryError):
    """Curation was requested while the raw download is still partial."""

    exit_code = 8
