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
        self.assertNotIn("om__status", names)
        self.assertNotIn("descope__sdk_status", names)
        self.assertNotIn("fleet_dispatch", names)
        self.assertFalse(any(name.startswith("pw__") for name in names))
        self.assertFalse(any(name.startswith("win__") for name in names))
        self.assertFalse(any(name.startswith("dc__") for name in names))
        self.assertFalse(any(name.startswith("kapture__") for name in names))

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
            "kapture",
            "cloudflared",
            "openmontage",
            "hermes",
            "openclaw",
            "descope",
            "fleet",
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
        if not edgar_wrappers.OPENMONTAGE_DIR.is_dir():
            self.skipTest("OpenMontage Windows checkout is not present on this host")
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

    def test_enabled_fleet_lists_bounded_surface(self):
        with patch.dict(os.environ, {"MCP_WRAP_FLEET": "1"}, clear=False):
            tools = edgar_wrappers.list_wrap_tools()
        by_name = {tool["name"]: tool for tool in tools}
        self.assertTrue({"fleet_health", "fleet_benchmark", "fleet_route", "fleet_dispatch"} <= set(by_name))
        route = by_name["fleet_route"]
        self.assertEqual(
            ["general", "website-audit", "event", "lightweight"],
            route["inputSchema"]["properties"]["task_type"]["enum"],
        )
        dispatch = by_name["fleet_dispatch"]
        self.assertIn("target", dispatch["inputSchema"]["properties"])
        self.assertIn("auto", dispatch["inputSchema"]["properties"]["target"]["enum"])
        self.assertIn("task_type", dispatch["inputSchema"]["properties"])
        self.assertIn("message", dispatch["inputSchema"]["properties"])
        self.assertNotIn("command", dispatch["inputSchema"]["properties"])
        self.assertNotIn("args", dispatch["inputSchema"]["properties"])
        self.assertNotIn("shell", dispatch["inputSchema"]["properties"])
        self.assertNotIn("argv", dispatch["inputSchema"]["properties"])

    def test_fleet_route_and_auto_dispatch_use_fixed_arguments_without_leaking_argv(self):
        runner_response = edgar_wrappers._json(
            {
                "argv": ["powershell.exe", "-File", "G:/hidden/edgar-fleet.ps1"],
                "exit_code": 0,
                "output": '{"selected_target":"azure"}',
            }
        )
        with patch.object(edgar_wrappers, "_run", return_value=runner_response) as run:
            route_response = edgar_wrappers._handle_fleet(
                "fleet_route",
                {"task_type": "event"},
            )
            dispatch_response = edgar_wrappers._handle_fleet(
                "fleet_dispatch",
                {
                    "target": "auto",
                    "task_type": "website-audit",
                    "message": "bounded website-audit canary",
                },
            )

        route_argv = run.call_args_list[0].args[0]
        dispatch_argv = run.call_args_list[1].args[0]
        self.assertEqual("route", route_argv[route_argv.index("-Action") + 1])
        self.assertEqual("event", route_argv[route_argv.index("-TaskType") + 1])
        self.assertNotIn("-Message", route_argv)
        self.assertEqual("auto", dispatch_argv[dispatch_argv.index("-Target") + 1])
        self.assertEqual("dispatch", dispatch_argv[dispatch_argv.index("-Action") + 1])
        self.assertEqual("website-audit", dispatch_argv[dispatch_argv.index("-TaskType") + 1])
        self.assertEqual("bounded website-audit canary", dispatch_argv[dispatch_argv.index("-Message") + 1])
        for response in (route_response, dispatch_response):
            self.assertFalse(response["isError"])
            self.assertNotIn("argv", response["structuredContent"])
            self.assertEqual({"selected_target": "azure"}, response["structuredContent"]["result"])

    def test_fleet_rejects_auto_for_non_dispatch_and_unknown_task_type(self):
        auto_health = edgar_wrappers._handle_fleet("fleet_health", {"target": "auto"})
        bad_task_type = edgar_wrappers._handle_fleet(
            "fleet_dispatch",
            {"target": "auto", "task_type": "unbounded", "message": "canary"},
        )
        self.assertTrue(auto_health["isError"])
        self.assertIn("only supported", auto_health["content"][0]["text"])
        self.assertTrue(bad_task_type["isError"])
        self.assertIn("invalid fleet task_type", bad_task_type["content"][0]["text"])

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
