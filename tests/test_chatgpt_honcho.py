import json
import threading
import urllib.error
import urllib.request
import unittest
from unittest.mock import patch

from edgars_mcp import http_server
from edgars_mcp.chatgpt_honcho import (
    CHATGPT_HONCHO_PATH,
    ChatgptHonchoConfig,
    HonchoStagingClient,
    build_resource_metadata,
    build_tools,
    dispatch,
)


class ChatgptHonchoUnitTests(unittest.TestCase):
    def setUp(self):
        self.config = ChatgptHonchoConfig(
            enabled=True,
            resource_url="https://mcp.edgars.tools/chatgpt-honcho",
            issuer="https://5h2aw6.logto.app/oidc",
            userinfo_url="https://5h2aw6.logto.app/oidc/me",
            upstream_url="http://127.0.0.1:18000",
            workspace_id="edg313-chatgpt-dev",
            observer_id="chatgpt",
            observed_id="edgar",
        )

    def test_resource_metadata_points_only_to_logto(self):
        meta = build_resource_metadata(self.config)
        self.assertEqual(self.config.resource_url, meta["resource"])
        self.assertEqual([self.config.issuer], meta["authorization_servers"])
        self.assertIn("offline_access", meta["scopes_supported"])

    def test_tool_list_is_memory_only(self):
        self.assertEqual(
            ["recall_edgar_memory", "remember_edgar_memory"],
            [tool["name"] for tool in build_tools()],
        )

    def test_ensure_workspace_creates_observer_and_observed_peers(self):
        calls = []

        class FakeClient(HonchoStagingClient):
            def _request(self, method, path, payload=None):
                calls.append((method, path, payload))
                return 201, {}

        FakeClient(self.config).ensure_workspace()
        peer_ids = [payload["id"] for method, path, payload in calls if path.endswith("/peers")]
        self.assertEqual(["chatgpt", "edgar"], peer_ids)

    def test_remember_requires_confirm(self):
        client = unittest.mock.Mock(spec=HonchoStagingClient)
        response = dispatch({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
            "name":"remember_edgar_memory","arguments":{"content":"x","confirm":False}
        }}, client)
        self.assertTrue(response["result"]["isError"])
        client.remember.assert_not_called()

    def test_remember_and_recall_dispatch_to_staging_client(self):
        client = unittest.mock.Mock(spec=HonchoStagingClient)
        client.remember.return_value = {"id":"c1","content":"EDG313 marker"}
        client.recall.return_value = [{"id":"c1","content":"EDG313 marker"}]
        saved = dispatch({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
            "name":"remember_edgar_memory","arguments":{"content":"EDG313 marker","confirm":True}
        }}, client)
        found = dispatch({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
            "name":"recall_edgar_memory","arguments":{"query":"EDG313 marker"}
        }}, client)
        self.assertFalse(saved["result"].get("isError", False))
        self.assertFalse(found["result"].get("isError", False))
        client.remember.assert_called_once_with("EDG313 marker")
        client.recall.assert_called_once_with("EDG313 marker", top_k=5)


class ChatgptHonchoHttpTests(unittest.TestCase):
    def _start(self):
        cfg = http_server.EdgarsMcpServerConfig(
            mcp_api_token="existing-token",
            base_url="https://mcp.edgars.tools",
            chatgpt_honcho_enabled=True,
            chatgpt_honcho_issuer="https://5h2aw6.logto.app/oidc",
            chatgpt_honcho_userinfo_url="https://5h2aw6.logto.app/oidc/me",
            chatgpt_honcho_upstream_url="http://127.0.0.1:18000",
            chatgpt_honcho_workspace_id="edg313-chatgpt-dev",
        )
        server = http_server.ThreadingHTTPServer(("127.0.0.1",0), http_server.MCPHTTPHandler, config=cfg)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_address[1]}"

    def test_path_metadata_is_public_and_logto_backed(self):
        server, thread, base = self._start()
        try:
            with urllib.request.urlopen(base+"/.well-known/oauth-protected-resource/chatgpt-honcho", timeout=5) as r:
                data=json.load(r)
            self.assertEqual("https://mcp.edgars.tools/chatgpt-honcho", data["resource"])
            self.assertEqual(["https://5h2aw6.logto.app/oidc"], data["authorization_servers"])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_path_requires_real_logto_bearer(self):
        server, thread, base = self._start()
        try:
            body=json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}).encode()
            req=urllib.request.Request(base+CHATGPT_HONCHO_PATH,data=body,headers={"Content-Type":"application/json"},method="POST")
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(401, raised.exception.code)
            self.assertIn("oauth-protected-resource/chatgpt-honcho", raised.exception.headers["WWW-Authenticate"])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_valid_logto_token_lists_only_two_tools(self):
        server, thread, base = self._start()
        try:
            body=json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}).encode()
            req=urllib.request.Request(base+CHATGPT_HONCHO_PATH,data=body,headers={
                "Content-Type":"application/json","Authorization":"Bearer logto-test-token"
            },method="POST")
            with patch("edgars_mcp.http_server.verify_chatgpt_honcho_logto_token", return_value={"sub":"u1","email":"edgar@edgars.tools"}):
                with urllib.request.urlopen(req, timeout=5) as r:
                    data=json.load(r)
            self.assertEqual(["recall_edgar_memory","remember_edgar_memory"], [t["name"] for t in data["result"]["tools"]])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
