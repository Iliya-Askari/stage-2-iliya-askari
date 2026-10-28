import unittest

import requests

from nyc311_factory.exceptions import ConfigError, HttpStatusError, NetworkError
from nyc311_factory.http_client import HttpClient
from tests.helpers import FakeResponse, ScriptedSession


def make_client(script, retries=2, sleeps=None):
    session = ScriptedSession(script)
    sleeps = sleeps if sleeps is not None else []
    return HttpClient(session, max_retries=retries, backoff_seconds=1.0, sleep=sleeps.append), session, sleeps


class HttpClientTests(unittest.TestCase):
    def test_get_sends_params_in_query(self):
        client, session, _ = make_client([FakeResponse(200, [{"a": 1}])])
        self.assertEqual(client.request("GET", "http://x", params={"q": "1"}, expect=list), [{"a": 1}])
        method, _, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(kwargs["params"], {"q": "1"})
        self.assertNotIn("json", kwargs)

    def test_post_sends_json_body(self):
        client, session, _ = make_client([FakeResponse(200, [])])
        client.request("POST", "http://x", json_body={"query": "select"}, expect=list)
        method, _, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(kwargs["json"], {"query": "select"})
        self.assertNotIn("params", kwargs)

    def test_retries_server_error_with_exponential_backoff(self):
        client, session, sleeps = make_client([FakeResponse(503), FakeResponse(429), FakeResponse(200, [1])], retries=3)
        self.assertEqual(client.request("GET", "http://x"), [1])
        self.assertEqual(sleeps, [1.0, 2.0])
        self.assertEqual((client.total_requests, client.retries), (3, 2))

    def test_gives_up_after_max_retries_with_network_error(self):
        err = requests.exceptions.ConnectionError("down")
        client, session, _ = make_client([err, err, err], retries=2)
        with self.assertRaises(NetworkError):
            client.request("GET", "http://x")
        self.assertEqual(client.total_requests, 3)

    def test_client_error_is_not_retried(self):
        client, session, sleeps = make_client([FakeResponse(404, text="nope")])
        with self.assertRaises(HttpStatusError) as ctx:
            client.request("GET", "http://x")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeps, [])

    def test_truncated_json_is_retried_then_fails(self):
        client, _, _ = make_client([FakeResponse(200, bad_json=True)] * 3, retries=2)
        with self.assertRaises(NetworkError):
            client.request("GET", "http://x")

    def test_wrong_payload_shape_is_retried(self):
        client, _, _ = make_client([FakeResponse(200, {"error": "x"}), FakeResponse(200, [])])
        self.assertEqual(client.request("GET", "http://x", expect=list), [])
        self.assertEqual(client.retries, 1)

    def test_unsupported_method_is_a_config_error(self):
        client, _, _ = make_client([])
        with self.assertRaises(ConfigError):
            client.request("DELETE", "http://x")


if __name__ == "__main__":
    unittest.main()
