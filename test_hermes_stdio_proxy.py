"""Unit tests for the Hermes stdio proxy preflight."""

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import hermes_stdio_proxy


class FakeHTTPResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload if payload is not None else {
            "jsonrpc": "2.0",
            "id": "hermes-preflight",
            "result": {"serverInfo": {"name": "edgars mcp"}},
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class HermesPreflightTests(unittest.TestCase):
    def test_preflight_requires_mcp_api_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(
                hermes_stdio_proxy.HermesPreflightError,
                "No MCP auth is available",
            ):
                hermes_stdio_proxy.run_preflight()

    def test_preflight_rejects_partial_cf_access_service_token(self):
        with patch.dict("os.environ", {"MCP_CF_ACCESS_CLIENT_ID": "client-id.access"}, clear=True):
            with self.assertRaisesRegex(
                hermes_stdio_proxy.HermesPreflightError,
                "Cloudflare Access service token is incomplete",
            ):
                hermes_stdio_proxy.run_preflight()

    def test_preflight_sends_mcp_api_token_to_initialize(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["timeout"] = timeout
            captured["authorization"] = request.get_header("Authorization")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeHTTPResponse()

        with patch.dict("os.environ", {"MCP_API_TOKEN": "  secret-token  "}, clear=True):
            with patch("urllib.request.urlopen", fake_urlopen):
                hermes_stdio_proxy.run_preflight()

        self.assertEqual("Bearer secret-token", captured["authorization"])
        self.assertEqual(hermes_stdio_proxy.PREFLIGHT_TIMEOUT_SECONDS, captured["timeout"])
        self.assertEqual("initialize", captured["payload"]["method"])

    def test_preflight_sends_cf_access_service_token_headers_when_configured(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["timeout"] = timeout
            captured["client_id"] = request.get_header("Cf-Access-Client-Id")
            captured["client_secret"] = request.get_header("Cf-Access-Client-Secret")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeHTTPResponse()

        with patch.dict(
            "os.environ",
            {
                "MCP_CF_ACCESS_CLIENT_ID": "client-id.access",
                "MCP_CF_ACCESS_CLIENT_SECRET": "client-secret",
            },
            clear=True,
        ):
            with patch("urllib.request.urlopen", fake_urlopen):
                hermes_stdio_proxy.run_preflight()

        self.assertEqual("client-id.access", captured["client_id"])
        self.assertEqual("client-secret", captured["client_secret"])
        self.assertEqual("initialize", captured["payload"]["method"])

    def test_preflight_fails_fast_with_single_reason_when_token_rejected(self):
        error = urllib.error.HTTPError(
            hermes_stdio_proxy.MCP_URL,
            401,
            "Unauthorized",
            hdrs={},
            fp=io.BytesIO(b"token rejected"),
        )

        with patch.dict("os.environ", {"MCP_API_TOKEN": "secret-token"}, clear=True):
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaisesRegex(
                    hermes_stdio_proxy.HermesPreflightError,
                    "MCP_API_TOKEN was rejected",
                ):
                    hermes_stdio_proxy.run_preflight()

    def test_preflight_service_token_401_mentions_cloudflare_access(self):
        error = urllib.error.HTTPError(
            hermes_stdio_proxy.MCP_URL,
            401,
            "Unauthorized",
            hdrs={},
            fp=io.BytesIO(b"access denied"),
        )

        with patch.dict(
            "os.environ",
            {
                "MCP_CF_ACCESS_CLIENT_ID": "client-id.access",
                "MCP_CF_ACCESS_CLIENT_SECRET": "client-secret",
            },
            clear=True,
        ):
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaisesRegex(
                    hermes_stdio_proxy.HermesPreflightError,
                    "Cloudflare Access service token was rejected",
                ):
                    hermes_stdio_proxy.run_preflight()

    def test_main_exits_before_reading_stdin_when_preflight_fails(self):
        with patch(
            "hermes_stdio_proxy.run_preflight",
            side_effect=hermes_stdio_proxy.HermesPreflightError("one reason"),
        ):
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    hermes_stdio_proxy.main()

        self.assertEqual(1, raised.exception.code)
        self.assertIn("Startup aborted: one reason", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
