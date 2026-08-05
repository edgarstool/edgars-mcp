"""Focused tests for the integrated Honcho MCP tool proxy."""

import unittest
from unittest.mock import patch

from edgars_mcp import http_server


def config(**overrides):
    values = {
        "mcp_api_token": "test-token",
        "base_url": "https://mcp.example.test",
    }
    values.update(overrides)
    return http_server.EdgarsMcpServerConfig(**values)


class HonchoToolProxyTests(unittest.TestCase):
    def setUp(self):
        with http_server.HONCHO_TOOLS_CACHE_LOCK:
            http_server.HONCHO_TOOLS_CACHE.update({"expires_at": 0.0, "identity": "", "tools": []})

    def test_no_key_keeps_exactly_78_base_tools(self):
        response = http_server.handle_tools_list(1, {}, config())
        self.assertEqual(78, len(http_server.TOOLS))
        self.assertEqual(78, len(response["result"]["tools"]))

    def test_configured_upstream_descriptors_get_honcho_prefix(self):
        upstream = {"result": {"tools": [{
            "name": "search_memory",
            "description": "Search memory",
            "inputSchema": {"type": "object", "properties": {}},
        }]}}
        with patch.object(http_server, "call_honcho_mcp_json_rpc", return_value=upstream):
            response = http_server.handle_tools_list(1, {}, config(honcho_api_key="key"))
        descriptor = response["result"]["tools"][-1]
        self.assertEqual("honcho__search_memory", descriptor["name"])
        self.assertEqual("search_memory", descriptor["_meta"]["edgars_mcp_proxy"]["upstream_name"])

    def test_tools_call_routes_to_upstream_name(self):
        result = {"content": [{"type": "text", "text": "remembered"}]}
        with patch.object(http_server, "call_honcho_mcp_json_rpc", return_value={"result": result}) as call:
            response = http_server.handle_tools_call(
                42, {"name": "honcho__search_memory", "arguments": {"query": "Edgar"}},
                config(honcho_api_key="key"),
            )
        self.assertEqual(result, response["result"])
        self.assertEqual("tools/call", call.call_args.args[1])
        self.assertEqual({"name": "search_memory", "arguments": {"query": "Edgar"}}, call.call_args.args[2])
        self.assertEqual(42, call.call_args.kwargs["req_id"])

    def test_upstream_failure_returns_base_tools_and_negative_caches(self):
        with patch.object(http_server, "call_honcho_mcp_json_rpc", side_effect=RuntimeError("offline")) as call:
            first = http_server.handle_tools_list(1, {}, config(honcho_api_key="key"))
            second = http_server.handle_tools_list(2, {}, config(honcho_api_key="key"))
        self.assertEqual(78, len(first["result"]["tools"]))
        self.assertEqual(78, len(second["result"]["tools"]))
        call.assert_called_once()

    def test_cache_is_not_reused_across_changed_identity(self):
        payloads = [
            {"result": {"tools": [{"name": "first", "inputSchema": {"type": "object"}}]}},
            {"result": {"tools": [{"name": "second", "inputSchema": {"type": "object"}}]}},
        ]
        with patch.object(http_server, "call_honcho_mcp_json_rpc", side_effect=payloads) as call:
            first = http_server.fetch_honcho_tool_descriptors(
                config(honcho_api_key="key", honcho_workspace_id="workspace-one")
            )
            second = http_server.fetch_honcho_tool_descriptors(
                config(honcho_api_key="key", honcho_workspace_id="workspace-two")
            )
        self.assertEqual("honcho__first", first[0]["name"])
        self.assertEqual("honcho__second", second[0]["name"])
        self.assertEqual(2, call.call_count)


if __name__ == "__main__":
    unittest.main()
