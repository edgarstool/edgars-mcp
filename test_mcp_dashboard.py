import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parent / "update-edgars-mcp" / "mcp-dashboard.py"
MODULE_SPEC = importlib.util.spec_from_file_location("mcp_dashboard", MODULE_PATH)
mcp_dashboard = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(mcp_dashboard)


class RedirectingProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/mcp":
            body = b'<html><body>cf_access login</body></html>'
            self.send_response(302)
            self.send_header("Location", "https://team.example.cloudflareaccess.com/login")
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/prm":
            body = b'<html><body>cloudflareaccess.com login</body></html>'
            self.send_response(302)
            self.send_header("Location", "https://team.example.cloudflareaccess.com/login")
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, format, *args):
        return


class McpDashboardTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectingProbeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_http_get_does_not_follow_redirects(self):
        code, body, err = mcp_dashboard._http_get(f"{self.base}/prm", timeout=5)

        self.assertEqual(302, code)
        self.assertIn("cloudflareaccess.com", body)
        self.assertIsNone(err)

    def test_collect_status_requires_direct_prm_success(self):
        with patch.object(mcp_dashboard, "MCP_HEALTH_URL", f"{self.base}/health"):
            with patch.object(mcp_dashboard, "MCP_EXTERNAL_URL", f"{self.base}/mcp"):
                with patch.object(mcp_dashboard, "MCP_PRM_URL", f"{self.base}/prm"):
                    with patch.object(mcp_dashboard, "_port_listening", return_value=True):
                        with patch.object(mcp_dashboard, "_run", return_value=""):
                            status = mcp_dashboard.collect_status()

        self.assertTrue(status["local"]["ok"])
        self.assertTrue(status["external"]["reachable"])
        self.assertEqual(302, status["external"]["mcp_http"])
        self.assertEqual(302, status["external"]["prm_http"])
        self.assertFalse(status["external"]["oauth_ready"])


if __name__ == "__main__":
    unittest.main()
