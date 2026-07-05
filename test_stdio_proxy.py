import json
import unittest
import urllib.error
from io import BytesIO
from unittest import mock

import stdio_proxy


class StdioProxyPreflightTests(unittest.TestCase):
    def test_missing_token_aborts(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(stdio_proxy.PreflightError):
                stdio_proxy.run_preflight()

    def test_partial_cf_access_service_token_aborts(self):
        with mock.patch.dict("os.environ", {"MCP_CF_ACCESS_CLIENT_ID": "client-id"}, clear=True):
            with self.assertRaisesRegex(stdio_proxy.PreflightError, "Cloudflare Access service token is incomplete"):
                stdio_proxy.run_preflight()

    def test_unreachable_endpoint_aborts(self):
        with mock.patch.dict("os.environ", {"MCP_API_TOKEN": "x"}, clear=True):
            with mock.patch("stdio_proxy.urllib.request.urlopen") as urlopen:
                urlopen.side_effect = urllib.error.URLError("connection refused")
                with self.assertRaises(stdio_proxy.PreflightError):
                    stdio_proxy.run_preflight()

    def test_preflight_timeout_value_used(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["timeout"] = timeout
            body = json.dumps({"jsonrpc": "2.0", "id": "stdio-preflight", "result": {}}).encode()
            class FakeResp:
                status = 200
                def __enter__(self_inner): return self_inner
                def __exit__(self_inner, *args): pass
                def read(self_inner): return body
            return FakeResp()

        with mock.patch.dict("os.environ", {"MCP_API_TOKEN": "x"}, clear=True):
            with mock.patch("stdio_proxy.urllib.request.urlopen", side_effect=fake_urlopen):
                stdio_proxy.run_preflight()
        self.assertEqual(stdio_proxy.PREFLIGHT_TIMEOUT_SECONDS, captured["timeout"])

    def test_service_token_headers_are_sent_when_configured(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["timeout"] = timeout
            captured["client_id"] = req.headers.get("Cf-access-client-id")
            captured["client_secret"] = req.headers.get("Cf-access-client-secret")
            body = json.dumps({"jsonrpc": "2.0", "id": "stdio-preflight", "result": {}}).encode()
            class FakeResp:
                status = 200
                def __enter__(self_inner): return self_inner
                def __exit__(self_inner, *args): pass
                def read(self_inner): return body
            return FakeResp()

        with mock.patch.dict(
            "os.environ",
            {
                "MCP_CF_ACCESS_CLIENT_ID": "client-id.access",
                "MCP_CF_ACCESS_CLIENT_SECRET": "client-secret",
            },
            clear=True,
        ):
            with mock.patch("stdio_proxy.urllib.request.urlopen", side_effect=fake_urlopen):
                stdio_proxy.run_preflight()

        self.assertEqual("client-id.access", captured["client_id"])
        self.assertEqual("client-secret", captured["client_secret"])

    def test_service_token_401_mentions_cloudflare_access_instead_of_bearer(self):
        error = urllib.error.HTTPError(
            stdio_proxy.MCP_URL,
            401,
            "Unauthorized",
            hdrs={},
            fp=BytesIO(b"access denied"),
        )

        with mock.patch.dict(
            "os.environ",
            {
                "MCP_CF_ACCESS_CLIENT_ID": "client-id.access",
                "MCP_CF_ACCESS_CLIENT_SECRET": "client-secret",
            },
            clear=True,
        ):
            with mock.patch("stdio_proxy.urllib.request.urlopen", side_effect=error):
                with self.assertRaisesRegex(stdio_proxy.PreflightError, "Cloudflare Access service token was rejected"):
                    stdio_proxy.run_preflight()


if __name__ == "__main__":
    unittest.main()

