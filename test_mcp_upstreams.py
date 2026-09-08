"""Tests for default-off full-surface wrappers."""

import json
import os
import unittest
from unittest.mock import patch

import edgar_wrappers
import mcp_upstreams
import server_http
from mcp_upstreams import UpstreamSpec, prefix_tool_descriptor
from server_http import handle_tools_call, handle_tools_list


class WrapDefaultOffTests(unittest.TestCase):
    def test_wrap_catalog_is_always_listed(self):
        response = handle_tools_list(req_id=1, params={})
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("wrap_catalog", names)

    def test_native_surfaces_are_off_by_default(self):
        response = handle_tools_list(req_id=1, params={})
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertNotIn("hermes_agent", names)
        self.assertNotIn("openclaw_agent", names)
        self.assertNotIn("cloudflared_cli", names)
        self.assertNotIn("op_connect_status", names)
        self.assertNotIn("om__status", names)
        self.assertNotIn("descope__sdk_status", names)
        self.assertFalse(any(name.startswith("pw__") for name in names))
        self.assertFalse(any(name.startswith("win__") for name in names))
        self.assertFalse(any(name.startswith("dc__") for name in names))

    def test_existing_tools_are_not_removed(self):
        names = {tool["name"] for tool in server_http.TOOLS}
        for required in ("echo", "fs_list", "sys_run", "qmd_search", "qmd_get", "browser_screenshot"):
            self.assertIn(required, names)

    def test_notion_and_mmx_tools_are_removed(self):
        names = {tool["name"] for tool in server_http.TOOLS}
        self.assertNotIn("notion_search", names)
        self.assertNotIn("notion_get_page", names)
        self.assertFalse(any(name.startswith("mmx_") for name in names))
        listed = [tool["name"] for tool in handle_tools_list(req_id=1, params={})["result"]["tools"]]
        self.assertFalse(any(name.startswith("notion_") or name.startswith("mmx_") for name in listed))

    def test_wrap_catalog_call_reports_disabled_sources(self):
        response = handle_tools_call(req_id=7, params={"name": "wrap_catalog", "arguments": {}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual("off", payload["default"])
        self.assertFalse(payload["wrap_all"])
        ids = {source["id"] for source in payload["sources"]}
        for required in (
            "playwright",
            "windows",
            "desktop_commander",
            "cloudflared",
            "op_connect",
            "openmontage",
            "hermes",
            "openclaw",
            "descope",
        ):
            self.assertIn(required, ids)

    def test_prefix_keeps_every_upstream_tool(self):
        spec = UpstreamSpec(
            id="demo",
            prefix="demo__",
            title="Demo",
            env_flag="MCP_WRAP_DEMO",
            command="echo",
        )
        upstream = [
            {"name": "alpha", "description": "A"},
            {"name": "beta", "description": "B"},
            {"name": "gamma", "inputSchema": {"type": "object"}},
        ]
        prefixed = [prefix_tool_descriptor(spec, tool) for tool in upstream]
        self.assertEqual(["demo__alpha", "demo__beta", "demo__gamma"], [item["name"] for item in prefixed])

    def test_enabled_hermes_lists_full_cli_surface(self):
        with patch.dict(os.environ, {"MCP_WRAP_HERMES": "1"}, clear=False):
            names = [tool["name"] for tool in edgar_wrappers.list_wrap_tools()]
        for required in ("hermes_cli", "hermes_agent", "hermes_status", "hermes_version", "hermes_doctor"):
            self.assertIn(required, names)

    def test_enabled_openmontage_lists_source_tools_without_castrating(self):
        with patch.dict(os.environ, {"MCP_WRAP_OPENMONTAGE": "1"}, clear=False):
            names = [tool["name"] for tool in edgar_wrappers.list_wrap_tools()]
        om_tools = [name for name in names if name.startswith("om__") and name not in {"om__status", "om__list_pipelines", "om__read_pipeline", "om__execute", "om__dry_run", "om__registry_error"}]
        self.assertGreaterEqual(len(om_tools), 20)
        self.assertIn("om__execute", names)
        self.assertIn("om__list_pipelines", names)

    def test_enabled_openclaw_lists_full_cli_surface(self):
        with patch.dict(os.environ, {"MCP_WRAP_OPENCLAW": "1"}, clear=False):
            names = [tool["name"] for tool in edgar_wrappers.list_wrap_tools()]
        for required in ("openclaw_cli", "openclaw_agent", "openclaw_status", "openclaw_version", "openclaw_health"):
            self.assertIn(required, names)

    def test_enabled_cloudflared_keeps_start_stop_and_cli(self):
        with patch.dict(os.environ, {"MCP_WRAP_CLOUDFLARED": "1"}, clear=False):
            names = [tool["name"] for tool in edgar_wrappers.list_wrap_tools()]
        for required in (
            "cloudflared_cli",
            "cloudflared_status",
            "cloudflared_start",
            "cloudflared_stop",
            "cloudflared_restart",
            "cloudflared_verify",
            "cloudflared_add_service",
            "cloudflared_ddns_update",
        ):
            self.assertIn(required, names)

    def test_disabled_hermes_call_explains_how_to_enable(self):
        response = handle_tools_call(
            req_id=8,
            params={"name": "hermes_version", "arguments": {}},
        )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("MCP_WRAP_HERMES", response["result"]["content"][0]["text"])


class WrapLiveSafeTests(unittest.TestCase):
    def test_qmd_cli_still_resolves(self):
        self.assertTrue(server_http._qmd_available())

    def test_hermes_and_openclaw_binaries_exist(self):
        self.assertTrue(os.path.isfile(edgar_wrappers.hermes_cmd()), edgar_wrappers.hermes_cmd())
        self.assertTrue(os.path.isfile(edgar_wrappers.openclaw_cmd()), edgar_wrappers.openclaw_cmd())


if __name__ == "__main__":
    unittest.main()
