"""HTTP layer: GET and POST, bounded retries with exponential backoff, request accounting.

Retry policy (explicit, not accidental):
  * connection errors, timeouts, truncated bodies  -> retry
  * HTTP 429 and 5xx                               -> retry
  * body that is not valid JSON or has wrong shape  -> retry (treated as incomplete)
  * any other non-200 status (e.g. 400, 404)       -> fail immediately, never retried
After ``max_retries`` retries the failure becomes a NetworkError.
"""

import time

import requests

from .exceptions import ConfigError, HttpStatusError, MalformedResponseError, NetworkError

RETRYABLE_STATUS = frozenset({429})
SERVER_ERROR_MIN = 500
BACKOFF_CAP_SECONDS = 60.0
SUPPORTED_METHODS = ("GET", "POST")
BODY_SNIPPET_CHARS = 300


class _Retryable(Exception):
    pass


class HttpClient:
    def __init__(self, session=None, max_retries=3, backoff_seconds=1.0, timeout_seconds=60.0,
                 sleep=time.sleep, default_headers=None):
        self._session = session if session is not None else requests.Session()
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self.default_headers = dict(default_headers or {})
        self.total_requests = 0  # every attempt, including retries
        self.retries = 0

    def request(self, method, url, params=None, json_body=None, headers=None, expect=None):
        """Perform a request and return the decoded JSON payload.

        GET sends ``params`` in the query string; POST sends ``json_body`` as the JSON body.
        """
        method = method.upper()
        if method not in SUPPORTED_METHODS:
            raise ConfigError(f"unsupported HTTP method {method!r}; use one of {SUPPORTED_METHODS}")
        merged_headers = {**self.default_headers, **(headers or {})}
        attempt = 0
        while True:
            self.total_requests += 1
            try:
                return self._attempt(method, url, params, json_body, merged_headers, expect)
            except (requests.exceptions.RequestException, _Retryable) as exc:
                if attempt >= self.max_retries:
                    raise NetworkError(
                        f"{method} {url} failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
                attempt += 1
                self.retries += 1
                self._sleep(min(self.backoff_seconds * (2 ** (attempt - 1)), BACKOFF_CAP_SECONDS))

    def _attempt(self, method, url, params, json_body, headers, expect):
        kwargs = {"headers": headers, "timeout": self.timeout_seconds}
        if method == "GET":
            kwargs["params"] = params
        else:
            kwargs["json"] = json_body if json_body is not None else params
        response = self._session.request(method, url, **kwargs)
        status = response.status_code
        if status in RETRYABLE_STATUS or status >= SERVER_ERROR_MIN:
            raise _Retryable(f"HTTP {status}")
        if status != 200:
            body = (getattr(response, "text", "") or "")[:BODY_SNIPPET_CHARS]
            raise HttpStatusError(f"{method} {url} returned HTTP {status}: {body}", status, body)
        try:
            payload = response.json()
        except ValueError as exc:
            raise _Retryable(f"response body is not valid JSON (possibly truncated): {exc}") from exc
        if expect is not None and not isinstance(payload, expect):
            raise _Retryable(f"unexpected payload type {type(payload).__name__}")
        return payload


def ensure_list_of_dicts(payload, label):
    """Raise MalformedResponseError if a page is not a list of JSON objects."""
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise MalformedResponseError(f"{label}: expected a JSON list of objects")
    return payload
