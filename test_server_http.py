"""Unit tests and smoke checks for server_http helpers."""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import server_http
from server_http import (
    JOBS,
    JOBS_LOCK,
    DISCORD_WEBHOOK_EVENTS,
    DISCORD_WEBHOOK_EVENTS_LOCK,
    HandcraftServerConfig,
    MCPHTTPHandler,
    ThreadingHTTPServer,
    TOOLS,
    cleanup_expired_jobs,
    create_job,
    handle_discord_webhook_payload,
    handle_agent_job_cleanup,
    handle_agent_job_list,
    handle_claude_code_agent,
    handle_tools_call,
    handle_tools_list,
    handle_tracktw_package_status,
    list_jobs,
    update_job,
    validate_http_startup_config,
    validate_mcp_api_token,
)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def tool_text(response):
    return response["result"]["content"][0]["text"]


def tool_is_error(response):
    return response["result"].get("isError") is True


class ServerHttpJobApiTests(unittest.TestCase):
    def setUp(self):
        with JOBS_LOCK:
            JOBS.clear()

    def test_list_jobs_sorted_and_limited(self):
        first = create_job("gemini_agent", "task-1", "C:/tmp")
        second = create_job("codex_agent", "task-2", "C:/tmp")
        third = create_job("claude_code_agent", "task-3", "C:/tmp")

        update_job(first, created_at=100.0, updated_at=100.0, status="queued")
        update_job(second, created_at=200.0, updated_at=200.0, status="running")
        update_job(third, created_at=300.0, updated_at=300.0, status="succeeded")

        jobs = list_jobs(limit=2)
        self.assertEqual(2, len(jobs))
        self.assertEqual(third, jobs[0]["job_id"])
        self.assertEqual(second, jobs[1]["job_id"])

    def test_cleanup_expired_jobs_only_removes_expired(self):
        expired = create_job("gemini_agent", "expired", "C:/tmp")
        alive = create_job("codex_agent", "alive", "C:/tmp")

        update_job(expired, expires_at=1.0)
        update_job(alive, expires_at=9999999999.0)

        removed = cleanup_expired_jobs()
        self.assertEqual(1, removed)

        with JOBS_LOCK:
            self.assertNotIn(expired, JOBS)
            self.assertIn(alive, JOBS)

    def test_agent_job_list_handler_with_status_filter(self):
        create_job("gemini_agent", "queued", "C:/tmp")
        done = create_job("codex_agent", "done", "C:/tmp")
        update_job(done, status="succeeded", created_at=500.0, updated_at=500.0)

        response = handle_agent_job_list(req_id=1, arguments={"status": "succeeded", "limit": 10})
        text = response["result"]["content"][0]["text"]

        self.assertIn("Found 1 job(s)", text)
        self.assertIn("status=succeeded", text)

    def test_agent_job_cleanup_handler_reports_count(self):
        expired = create_job("gemini_agent", "expired", "C:/tmp")
        update_job(expired, expires_at=1.0)

        response = handle_agent_job_cleanup(req_id=1, arguments={})
        text = response["result"]["content"][0]["text"]
        self.assertIn("Expired jobs removed: 1", text)


class HttpStartupConfigTests(unittest.TestCase):
    def test_main_starts_when_mcp_api_token_is_configured(self):
        created_servers = []

        class FakeServer:
            def __init__(self, server_address, handler_class, config):
                self.server_address = server_address
                self.handler_class = handler_class
                self.config = config
                self.served = False
                self.closed = False
                created_servers.append(self)

            def serve_forever(self):
                self.served = True

            def server_close(self):
                self.closed = True

        with patch.dict(
            "os.environ",
            {
                "MCP_API_TOKEN": "  secret-token  ",
                "MCP_BASE_URL": "  https://mcp.example.test  ",
            },
            clear=True,
        ), patch("server_http.ThreadingHTTPServer", FakeServer):
            server_http.main()

        self.assertEqual(1, len(created_servers))
        server = created_servers[0]
        self.assertEqual(("0.0.0.0", server_http.PORT), server.server_address)
        self.assertIs(server_http.MCPHTTPHandler, server.handler_class)
        self.assertEqual("secret-token", server.config.mcp_api_token)
        self.assertEqual("https://mcp.example.test", server.config.base_url)
        self.assertTrue(server.served)
        self.assertTrue(server.closed)

    def test_main_fails_fast_when_mcp_api_token_is_missing_or_blank(self):
        cases = {
            "unset": {},
            "empty": {"MCP_API_TOKEN": ""},
            "whitespace": {"MCP_API_TOKEN": "   \t\r\n"},
        }

        for label, environment in cases.items():
            with self.subTest(label=label):
                with patch.dict("os.environ", environment, clear=True), patch(
                    "server_http.ThreadingHTTPServer"
                ) as server_class:
                    with self.assertRaises(SystemExit) as raised:
                        server_http.main()

                self.assertEqual(1, raised.exception.code)
                server_class.assert_not_called()

    def test_mcp_api_token_requires_present_value(self):
        for raw_token in (None, "", "   ", "\t\r\n"):
            with self.subTest(raw_token=raw_token):
                with self.assertRaisesRegex(RuntimeError, "MCP_API_TOKEN must be set"):
                    validate_mcp_api_token(raw_token)

    def test_mcp_api_token_trims_configured_value(self):
        self.assertEqual("secret-token", validate_mcp_api_token("  secret-token  "))

    def test_base_url_defaults_to_edgars_tools(self):
        self.assertEqual("https://mcp.edgars.tools", server_http.validate_base_url(None))
        self.assertEqual("https://mcp.edgars.tools", server_http.validate_base_url(""))
        self.assertEqual("https://custom.example", server_http.validate_base_url("  https://custom.example  "))

    def test_http_startup_config_reads_environment_into_config_object(self):
        with patch.dict(
            "os.environ",
            {
                "MCP_API_TOKEN": "  secret-token  ",
                "MCP_BASE_URL": "  https://mcp.example.test  ",
            },
        ):
            config = validate_http_startup_config()

        self.assertEqual(
            HandcraftServerConfig(
                mcp_api_token="secret-token",
                base_url="https://mcp.example.test",
            ),
            config,
        )

    def test_http_servers_keep_separate_auth_config(self):
        first_config = HandcraftServerConfig(mcp_api_token="first-token", base_url="https://first.example")
        second_config = HandcraftServerConfig(mcp_api_token="second-token", base_url="https://second.example")
        first_server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHTTPHandler, config=first_config)
        second_server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHTTPHandler, config=second_config)
        try:
            self.assertEqual("first-token", first_server.config.mcp_api_token)
            self.assertEqual("second-token", second_server.config.mcp_api_token)
            self.assertEqual("https://first.example", first_server.config.base_url)
            self.assertEqual("https://second.example", second_server.config.base_url)
        finally:
            first_server.server_close()
            second_server.server_close()

    def test_health_endpoint_reports_explicit_runtime_status(self):
        config = HandcraftServerConfig(
            mcp_api_token="secret-token",
            base_url="https://mcp.example.test",
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHTTPHandler, config=config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(200, response.status)
            self.assertTrue(payload["ok"])
            self.assertEqual("/mcp", payload["local"]["mcp_path"])
            self.assertEqual("/health", payload["local"]["health_path"])
            self.assertEqual("https://mcp.example.test/mcp", payload["public"]["mcp_url"])
            self.assertTrue(payload["auth"]["mcp_api_token_configured"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class OAuthFlowTests(unittest.TestCase):
    def setUp(self):
        with server_http.OAUTH_CODES_LOCK:
            server_http.OAUTH_CODES.clear()
        with server_http.OAUTH_CLIENTS_LOCK:
            server_http.OAUTH_CLIENTS.clear()
        with server_http.OAUTH_TOKENS_LOCK:
            server_http.OAUTH_ACCESS_TOKENS.clear()

    def _start_server(self):
        config = HandcraftServerConfig(
            mcp_api_token="secret-token",
            base_url="https://mcp.example.test",
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHTTPHandler, config=config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_address[1]}"

    def test_oauth_metadata_advertises_pkce_public_client_flow(self):
        server, thread, base = self._start_server()
        try:
            with urllib.request.urlopen(f"{base}/.well-known/oauth-authorization-server", timeout=5) as response:
                metadata = json.loads(response.read().decode("utf-8"))

            self.assertEqual(["authorization_code"], metadata["grant_types_supported"])
            self.assertEqual(["S256"], metadata["code_challenge_methods_supported"])
            self.assertIn("client_secret_post", metadata["token_endpoint_auth_methods_supported"])
            self.assertIn("client_secret_basic", metadata["token_endpoint_auth_methods_supported"])
            self.assertIn("none", metadata["token_endpoint_auth_methods_supported"])
            self.assertEqual(f"https://mcp.example.test/authorize", metadata["authorization_endpoint"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_resource_metadata_advertises_oauth_resource(self):
        server, thread, base = self._start_server()
        try:
            with urllib.request.urlopen(f"{base}/.well-known/oauth-protected-resource", timeout=5) as response:
                metadata = json.loads(response.read().decode("utf-8"))

            self.assertEqual("https://mcp.example.test", metadata["resource"])
            self.assertEqual(["https://mcp.example.test"], metadata["authorization_servers"])
            self.assertEqual(["mcp"], metadata["scopes_supported"])
            self.assertIn("client_secret_post", metadata["token_endpoint_auth_methods_supported"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_resource_metadata_supports_mcp_path_alias_for_tunnel_client(self):
        server, thread, base = self._start_server()
        try:
            with urllib.request.urlopen(f"{base}/.well-known/oauth-protected-resource/mcp", timeout=5) as response:
                metadata = json.loads(response.read().decode("utf-8"))

            self.assertEqual("https://mcp.example.test/mcp", metadata["resource"])
            self.assertEqual(["https://mcp.example.test"], metadata["authorization_servers"])
            self.assertEqual(["mcp"], metadata["scopes_supported"])
            self.assertEqual("https://mcp.example.test/mcp", metadata["resource_documentation"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_mcp_unauthorized_advertises_resource_metadata(self):
        server, thread, base = self._start_server()
        try:
            body = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{base}/mcp",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(req, timeout=5)

            self.assertEqual(401, raised.exception.code)
            authenticate = raised.exception.headers["WWW-Authenticate"]
            self.assertIn("Bearer", authenticate)
            self.assertIn('resource_metadata="https://mcp.example.test/.well-known/oauth-protected-resource"', authenticate)
            self.assertIn('scope="mcp"', authenticate)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_register_rejects_missing_redirect_uris(self):
        server, thread, base = self._start_server()
        try:
            body = json.dumps({"client_name": "bad-client"}).encode("utf-8")
            req = urllib.request.Request(
                f"{base}/register",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(req, timeout=5)

            self.assertEqual(400, raised.exception.code)
            payload = json.loads(raised.exception.read().decode("utf-8"))
            self.assertEqual("invalid_client_metadata", payload["error"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_authorization_code_pkce_flow_issues_usable_bearer_token(self):
        server, thread, base = self._start_server()
        try:
            redirect_uri = "https://chat.openai.com/aip/oauth/callback"
            register_body = json.dumps({
                "client_name": "ChatGPT",
                "redirect_uris": [redirect_uri],
            }).encode("utf-8")
            register_req = urllib.request.Request(
                f"{base}/register",
                data=register_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(register_req, timeout=5) as response:
                registered = json.loads(response.read().decode("utf-8"))
            client_id = registered["client_id"]
            client_secret = registered["client_secret"]

            verifier = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
            challenge = server_http.pkce_s256_challenge(verifier)
            authorize_query = urllib.parse.urlencode({
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": "mcp",
                "resource": "https://mcp.example.test",
                "state": "state-1",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            })
            opener = urllib.request.build_opener(NoRedirectHandler)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(f"{base}/authorize?{authorize_query}", timeout=5)
            self.assertEqual(302, raised.exception.code)
            location = raised.exception.headers["Location"]
            redirected = urllib.parse.urlparse(location)
            redirected_query = urllib.parse.parse_qs(redirected.query)
            self.assertEqual(["state-1"], redirected_query["state"])
            code = redirected_query["code"][0]

            token_body = urllib.parse.urlencode({
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": verifier,
                "resource": "https://mcp.example.test",
                "client_secret": client_secret,
            }).encode("utf-8")
            token_req = urllib.request.Request(
                f"{base}/token",
                data=token_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(token_req, timeout=5) as response:
                token_payload = json.loads(response.read().decode("utf-8"))

            access_token = token_payload["access_token"]
            self.assertNotEqual("secret-token", access_token)
            self.assertEqual("Bearer", token_payload["token_type"])
            self.assertEqual("mcp", token_payload["scope"])

            tools_body = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }).encode("utf-8")
            tools_req = urllib.request.Request(
                f"{base}/mcp",
                data=tools_body,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(tools_req, timeout=5) as response:
                tools_payload = json.loads(response.read().decode("utf-8"))

            tool_names = [tool["name"] for tool in tools_payload["result"]["tools"]]
            self.assertIn("fs_disk_info", tool_names)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_authorization_code_confidential_client_flow_allows_missing_pkce(self):
        server, thread, base = self._start_server()
        try:
            redirect_uri = "https://chatgpt.com/connector/oauth/callback-test"
            register_body = json.dumps({
                "client_name": "ChatGPT",
                "redirect_uris": [redirect_uri],
            }).encode("utf-8")
            register_req = urllib.request.Request(
                f"{base}/register",
                data=register_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(register_req, timeout=5) as response:
                registered = json.loads(response.read().decode("utf-8"))
            client_id = registered["client_id"]
            client_secret = registered["client_secret"]

            authorize_query = urllib.parse.urlencode({
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": "mcp",
                "resource": "https://mcp.example.test/mcp",
                "state": "state-2",
            })
            opener = urllib.request.build_opener(NoRedirectHandler)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(f"{base}/authorize?{authorize_query}", timeout=5)
            self.assertEqual(302, raised.exception.code)
            location = raised.exception.headers["Location"]
            redirected_query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
            self.assertEqual(["state-2"], redirected_query["state"])
            code = redirected_query["code"][0]

            token_body = urllib.parse.urlencode({
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code": code,
                "resource": "https://mcp.example.test/mcp",
                "client_secret": client_secret,
            }).encode("utf-8")
            token_req = urllib.request.Request(
                f"{base}/token",
                data=token_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(token_req, timeout=5) as response:
                token_payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual("Bearer", token_payload["token_type"])
            self.assertEqual("mcp", token_payload["scope"])
            self.assertTrue(token_payload["access_token"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_tools_list_has_chatgpt_app_required_metadata(self):
        response = handle_tools_list(req_id=1, params={})
        listed_tools = response["result"]["tools"]

        self.assertGreater(len(listed_tools), 0)
        for tool in listed_tools:
            with self.subTest(tool=tool["name"]):
                self.assertIsInstance(tool.get("title"), str)
                self.assertTrue(tool["title"])
                annotations = tool.get("annotations")
                self.assertIsInstance(annotations, dict)
                self.assertIn("readOnlyHint", annotations)
                self.assertIn("openWorldHint", annotations)
                self.assertIn("destructiveHint", annotations)
                self.assertEqual([{"type": "oauth2", "scopes": ["mcp"]}], tool.get("securitySchemes"))
                self.assertEqual(tool["securitySchemes"], tool.get("_meta", {}).get("securitySchemes"))
                output_schema = tool.get("outputSchema")
                self.assertIsInstance(output_schema, dict)
                self.assertEqual("object", output_schema.get("type"))


class CacheTraceRotationScriptTests(unittest.TestCase):
    def test_cache_trace_rotation_archives_then_reopens_log(self):
        script_path = Path(__file__).parent / "scripts" / "Rotate-CacheTrace.ps1"

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmpdir:
            tmp_path = Path(tmpdir)
            log_path = tmp_path / "logs" / "cache-trace.jsonl"
            archive_dir = tmp_path / "logs" / "archive" / "cache-trace"
            log_path.parent.mkdir(parents=True)
            log_path.write_text('{"event":"before"}\n', encoding="utf-8")

            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                    "-LogPath",
                    str(log_path),
                    "-ArchiveDir",
                    str(archive_dir),
                    "-MaxSizeMB",
                    "0.000001",
                    "-MaxAgeDays",
                    "0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            result = json.loads(completed.stdout)
            archives = list(archive_dir.glob("cache-trace-*.jsonl"))
            checkpoints = list(archive_dir.glob("cache-trace-*.checkpoint.json"))

            self.assertTrue(result["rotated"])
            self.assertEqual("size", result["reason"])
            self.assertEqual("", log_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(archives))
            self.assertEqual('{"event":"before"}\n', archives[0].read_text(encoding="utf-8"))
            self.assertEqual(1, len(checkpoints))

            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write('{"event":"after-rotation"}\n')

            self.assertEqual('{"event":"after-rotation"}\n', log_path.read_text(encoding="utf-8"))


class DiscordWebhookTests(unittest.TestCase):
    def setUp(self):
        with DISCORD_WEBHOOK_EVENTS_LOCK:
            DISCORD_WEBHOOK_EVENTS.clear()

    def test_discord_ping_returns_pong(self):
        status, response = handle_discord_webhook_payload({"type": 1})

        self.assertEqual(200, status)
        self.assertEqual({"type": 1}, response)

    def test_discord_message_payload_is_stored(self):
        status, response = handle_discord_webhook_payload({
            "id": "msg-1",
            "channel_id": "channel-1",
            "guild_id": "guild-1",
            "author": {"username": "edgar"},
            "content": "hello webhook",
        })

        self.assertEqual(200, status)
        self.assertTrue(response["ok"])
        self.assertEqual("discord", response["source"])
        self.assertEqual("msg-1", response["event_id"])

        with DISCORD_WEBHOOK_EVENTS_LOCK:
            self.assertEqual(1, len(DISCORD_WEBHOOK_EVENTS))
            self.assertEqual("hello webhook", DISCORD_WEBHOOK_EVENTS[0]["content"])

    def test_discord_payload_must_be_object(self):
        status, response = handle_discord_webhook_payload(["not", "an", "object"])

        self.assertEqual(400, status)
        self.assertFalse(response["ok"])


class TrackTWTests(unittest.TestCase):
    def test_tracktw_schema_is_registered(self):
        listed_tools = handle_tools_list(req_id=1, params={})["result"]["tools"]
        names = {tool["name"] for tool in listed_tools}

        self.assertIn("tracktw_carriers", names)
        self.assertIn("tracktw_package_status", names)

    def test_tracktw_package_status_formats_timeline_and_eta(self):
        tracking_data = {
            "tracking_number": "ABC123",
            "package_history": [
                {"time": 1714543200, "status": "已收件"},
                {"time": 1714629600, "status": "司機配送中", "checkpoint_status": "配送中"},
            ],
        }

        with patch.object(server_http, "_tracktw_find_carrier", return_value={"id": "blackcat", "name": "黑貓宅急便"}), \
             patch.object(server_http, "_tracktw_import_package", return_value="pkg-1"), \
             patch.object(server_http, "_tracktw_track_package", return_value=tracking_data):
            response = handle_tracktw_package_status(
                req_id=1,
                arguments={"carrier_name": "黑貓", "tracking_number": "abc123"},
            )

        self.assertFalse(tool_is_error(response))
        text = tool_text(response)
        self.assertIn("目前階段：配送中", text)
        self.assertIn("目前 checkpoint：配送中", text)
        self.assertIn("current_event_time：2024-05-02 14:00", text)
        self.assertIn("預估到貨：今天或明天", text)
        self.assertIn("貨態時間軸（from_status -> to_status）：", text)
        self.assertIn("1. 2024-05-01 14:00｜初始 (初始) -> 已收件 (已收件)｜stage_changed｜已收件", text)
        self.assertIn("2. 2024-05-02 14:00｜已收件 (已收件) -> 司機配送中 (配送中)｜stage_changed｜司機配送中", text)

    def test_tracktw_package_status_preserves_transition_fields(self):
        tracking_data = {
            "tracking_number": "ABC123",
            "package_history": [
                {"time": 1714543200, "status": "門市已收件", "checkpoint_status": "已收件"},
                {"time": 1714629600, "status": "已抵達物流中心", "checkpoint_status": "已到站/集散"},
                {"time": 1714716000, "status": "配送中", "checkpoint_status": "配送中"},
            ],
        }

        report = server_http._build_tracking_report(
            "7-Eleven",
            "abc123",
            {"id": "seven-eleven", "name": "7-Eleven"},
            tracking_data,
        )

        self.assertEqual("配送中", report["current_stage"])
        self.assertEqual("配送中", report["current_status"])
        self.assertEqual("配送中", report["current_checkpoint_status"])
        self.assertEqual("2024-05-03T14:00:00+08:00", report["current_event_time"])
        self.assertEqual(
            {
                "from_status": "已抵達物流中心",
                "from_checkpoint_status": "已到站/集散",
                "to_status": "配送中",
                "to_checkpoint_status": "配送中",
                "current_event_time": "2024-05-03T14:00:00+08:00",
                "stage_changed": True,
            },
            report["latest_transition"],
        )

    def test_tracktw_report_reuses_google_sheet_status_model(self):
        tracking_data = {
            "tracking_number": "ABC123",
            "id": "pkg-1",
            "package_history": [
                {"time": 1714543200, "status": "門市已收件", "checkpoint_status": "已收件"},
                {"time": 1714629600, "status": "已抵達物流中心", "checkpoint_status": "已到站/集散"},
            ],
        }

        report = server_http._build_tracking_report(
            "7-Eleven",
            "abc123",
            {"id": "seven-eleven", "name": "7-Eleven"},
            tracking_data,
        )

        self.assertEqual(
            "Google Sheet: TrackTW / tracktw_active + tracktw_events",
            report["status_model"]["source"],
        )
        self.assertEqual(list(server_http.TRACKTW_ACTIVE_FIELDS), list(report["active_row"].keys()))
        self.assertEqual(list(server_http.TRACKTW_EVENT_FIELDS), list(report["timeline"][0].keys()))
        self.assertEqual("已抵達物流中心", report["active_row"]["current_status"])
        self.assertEqual("已到站/集散", report["active_row"]["current_checkpoint_status"])
        self.assertEqual("2024-05-02T14:00:00+08:00", report["active_row"]["current_event_time"])
        self.assertEqual("門市已收件", report["timeline"][1]["from_status"])
        self.assertEqual("已抵達物流中心", report["timeline"][1]["to_status"])
        self.assertEqual(report["current_event_time"], report["timeline"][1]["current_event_time"])

    def test_tracktw_report_accepts_current_status_without_history(self):
        tracking_data = {
            "tracking_number": "ABC123",
            "current_status": "包裹已送達",
            "current_checkpoint_status": "已送達",
            "current_event_time": "2024-05-03T14:00:00+08:00",
        }

        report = server_http._build_tracking_report(
            "黑貓",
            "abc123",
            {"id": "blackcat", "name": "黑貓宅急便"},
            tracking_data,
        )

        self.assertEqual("已送達", report["current_stage"])
        self.assertEqual("包裹已送達", report["current_status"])
        self.assertEqual("2024-05-03T14:00:00+08:00", report["current_event_time"])
        self.assertEqual("已送達", report["eta"]["eta"])

    def test_tracktw_package_status_exports_xlsx_report(self):
        tracking_data = {
            "tracking_number": "ABC123",
            "package_history": [
                {"time": 1714543200, "status": "已收件", "location": "台北"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(server_http, "_tracktw_find_carrier", return_value={"id": "blackcat", "name": "黑貓宅急便"}), \
                 patch.object(server_http, "_tracktw_import_package", return_value="pkg-1"), \
                 patch.object(server_http, "_tracktw_track_package", return_value=tracking_data):
                response = handle_tracktw_package_status(
                    req_id=1,
                    arguments={
                        "carrier_name": "黑貓",
                        "tracking_number": "abc123",
                        "export_report": True,
                        "report_format": "xlsx",
                        "output_dir": tmpdir,
                    },
                )

            self.assertFalse(tool_is_error(response))
            files = list(Path(tmpdir).glob("*.xlsx"))
            self.assertEqual(1, len(files))
            with zipfile.ZipFile(files[0]) as zf:
                names = set(zf.namelist())
            self.assertIn("xl/worksheets/sheet1.xml", names)
            self.assertIn("xl/worksheets/sheet2.xml", names)


class SafeMcpWriteTests(unittest.TestCase):
    def test_vault_write_reads_back_and_reports_verified_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(server_http, "VAULT_ROOT", Path(tmpdir)):
                response = server_http.handle_vault_write(
                    req_id=1,
                    arguments={"path": "Inbox/test.md", "content": "hello"},
                )

                self.assertFalse(tool_is_error(response))
                self.assertIn("Written and verified: Inbox/test.md", tool_text(response))
                self.assertEqual("hello", Path(tmpdir, "Inbox", "test.md").read_text(encoding="utf-8"))

    def test_vault_append_reads_back_and_reports_verified_append(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            note = Path(tmpdir, "Inbox", "test.md")
            note.parent.mkdir(parents=True)
            note.write_text("before", encoding="utf-8")
            with patch.object(server_http, "VAULT_ROOT", Path(tmpdir)):
                response = server_http.handle_vault_append(
                    req_id=1,
                    arguments={"path": "Inbox/test.md", "content": "after"},
                )

                self.assertFalse(tool_is_error(response))
                self.assertIn("Appended and verified: Inbox/test.md", tool_text(response))
                self.assertEqual("before\nafter", note.read_text(encoding="utf-8"))

    def test_linear_graphql_errors_are_reported_as_blocked_reason(self):
        with patch.object(
            server_http,
            "_linear_graphql",
            side_effect=server_http.LinearMcpError("Invalid API key"),
        ):
            response = server_http.handle_linear_create_issue(
                req_id=1,
                arguments={"title": "Safe MCP test"},
            )

        self.assertTrue(tool_is_error(response))
        text = tool_text(response)
        self.assertIn("[BLOCKED] Linear issue create failed", text)
        self.assertIn("Reason: Invalid API key", text)

    def test_linear_create_issue_verifies_created_issue_by_refetch(self):
        calls = []

        def fake_linear_graphql(query, variables=None):
            calls.append((query, variables))
            if "teams" in query:
                return {"data": {"teams": {"nodes": [{"id": "team-1", "name": "WHO"}]}}}
            if "issueCreate" in query:
                return {
                    "data": {
                        "issueCreate": {
                            "issue": {
                                "identifier": "WHO-123",
                                "title": variables["title"],
                                "url": "https://linear.app/issue/WHO-123",
                            }
                        }
                    }
                }
            return {
                "data": {
                    "issues": {
                        "nodes": [
                            {
                                "id": "issue-uuid",
                                "identifier": "WHO-123",
                                "title": "Safe MCP test",
                                "url": "https://linear.app/issue/WHO-123",
                                "state": {"name": "Todo"},
                                "team": {"states": {"nodes": []}},
                            }
                        ]
                    }
                }
            }

        with patch.object(server_http, "_linear_graphql", side_effect=fake_linear_graphql):
            response = server_http.handle_linear_create_issue(
                req_id=1,
                arguments={"title": "Safe MCP test", "team_name": "WHO"},
            )

        self.assertFalse(tool_is_error(response))
        self.assertIn("Created and verified: [WHO-123] Safe MCP test", tool_text(response))
        self.assertEqual(3, len(calls))

    def test_linear_issue_lookup_uses_team_key_and_number_filter_for_identifier(self):
        captured = {}

        def fake_linear_graphql(query, variables=None):
            captured["query"] = query
            captured["variables"] = variables
            return {
                "data": {
                    "issues": {
                        "nodes": [
                            {
                                "id": "issue-uuid",
                                "identifier": "WHO-123",
                                "title": "Safe MCP test",
                                "url": "https://linear.app/issue/WHO-123",
                                "state": {"name": "Todo"},
                                "team": {"states": {"nodes": []}},
                            }
                        ]
                    }
                }
            }

        with patch.object(server_http, "_linear_graphql", side_effect=fake_linear_graphql):
            issue = server_http._linear_issue_by_identifier("WHO-123")

        self.assertEqual("WHO-123", issue["identifier"])
        self.assertIn("team: { key: { eqIgnoreCase: $teamKey } }", captured["query"])
        self.assertIn("number: { eq: $issueNumber }", captured["query"])
        self.assertEqual({"teamKey": "WHO", "issueNumber": 123}, captured["variables"])

    def test_linear_issue_lookup_uses_uuid_query_for_uuid_input(self):
        captured = {}

        def fake_linear_graphql(query, variables=None):
            captured["query"] = query
            captured["variables"] = variables
            return {
                "data": {
                    "issue": {
                        "id": variables["id"],
                        "identifier": "WHO-123",
                        "title": "Safe MCP test",
                        "url": "https://linear.app/issue/WHO-123",
                        "state": {"name": "Todo"},
                        "team": {"states": {"nodes": []}},
                    }
                }
            }

        with patch.object(server_http, "_linear_graphql", side_effect=fake_linear_graphql):
            issue = server_http._linear_issue_by_identifier("123e4567-e89b-12d3-a456-426614174000")

        self.assertEqual("WHO-123", issue["identifier"])
        self.assertIn("query LinearIssueByUuid", captured["query"])
        self.assertEqual({"id": "123e4567-e89b-12d3-a456-426614174000"}, captured["variables"])


    def test_linear_update_issue_verifies_state_and_comment(self):
        def fake_linear_graphql(query, variables=None):
            if "issueUpdate" in query:
                return {"data": {"issueUpdate": {"issue": {"identifier": "WHO-123", "state": {"name": "Done"}}}}}
            if "commentCreate" in query:
                return {"data": {"commentCreate": {"comment": {"id": "comment-1", "body": variables["body"]}}}}
            if "comments(last: 5)" in query:
                return {
                    "data": {
                        "issues": {
                            "nodes": [
                                {
                                    "id": "issue-uuid",
                                    "identifier": "WHO-123",
                                    "title": "Safe MCP test",
                                    "url": "https://linear.app/issue/WHO-123",
                                    "state": {"name": "Done"},
                                    "team": {"states": {"nodes": [{"id": "done-id", "name": "Done"}]}},
                                    "comments": {"nodes": [{"id": "comment-1", "body": "verified", "createdAt": "now"}]},
                                }
                            ]
                        }
                    }
                }
            return {
                "data": {
                    "issues": {
                        "nodes": [
                            {
                                "id": "issue-uuid",
                                "identifier": "WHO-123",
                                "title": "Safe MCP test",
                                "url": "https://linear.app/issue/WHO-123",
                                "state": {"name": "Todo"},
                                "team": {"states": {"nodes": [{"id": "done-id", "name": "Done"}]}},
                            }
                        ]
                    }
                }
            }

        with patch.object(server_http, "_linear_graphql", side_effect=fake_linear_graphql):
            response = server_http.handle_linear_update_issue(
                req_id=1,
                arguments={"issue_id": "WHO-123", "state": "Done", "comment": "verified"},
            )

        self.assertFalse(tool_is_error(response))
        text = tool_text(response)
        self.assertIn("State updated", text)
        self.assertIn("Comment added", text)
        self.assertIn("Verified state: Done", text)
        self.assertIn("Verified comment: comment-1", text)


class ClaudeCodeAgentSmokeTests(unittest.TestCase):
    def test_claude_code_agent_schema_matches_handler_contract(self):
        response = handle_tools_list(req_id=1, params={})
        listed_tools = response["result"]["tools"]
        listed_claude = next(tool for tool in listed_tools if tool["name"] == "claude_code_agent")
        source_claude = next(tool for tool in TOOLS if tool["name"] == "claude_code_agent")

        self.assertEqual(source_claude, listed_claude)
        self.assertEqual("object", listed_claude["inputSchema"]["type"])
        self.assertEqual(["task"], listed_claude["inputSchema"]["required"])
        self.assertEqual("string", listed_claude["inputSchema"]["properties"]["task"]["type"])
        self.assertEqual("string", listed_claude["inputSchema"]["properties"]["working_dir"]["type"])
        self.assertEqual("boolean", listed_claude["inputSchema"]["properties"]["async"]["type"])

    def test_claude_code_agent_missing_task_returns_tool_error(self):
        response = handle_claude_code_agent(req_id=1, arguments={})

        self.assertTrue(tool_is_error(response))
        self.assertEqual("Error: task is required", tool_text(response))

    def test_claude_code_agent_missing_command_returns_tool_call_error(self):
        original_run_agent_command = server_http.run_agent_command
        try:
            def raise_file_not_found(*args, **kwargs):
                raise FileNotFoundError

            server_http.run_agent_command = raise_file_not_found
            response = handle_tools_call(
                req_id=1,
                params={
                    "name": "claude_code_agent",
                    "arguments": {
                        "task": "say hi",
                        "working_dir": "C:/tmp",
                    },
                },
            )
        finally:
            server_http.run_agent_command = original_run_agent_command

        self.assertTrue(tool_is_error(response))
        self.assertIn("Error: claude command not found", tool_text(response))

    def test_claude_code_agent_normal_tool_call_example(self):
        completed = subprocess.CompletedProcess(
            args=["claude", "-p", "say hi"],
            returncode=0,
            stdout="hello from claude\n",
            stderr="",
        )

        calls = []
        original_run_agent_command = server_http.run_agent_command
        try:
            def fake_run_agent_command(*args, **kwargs):
                calls.append((args, kwargs))
                return completed

            server_http.run_agent_command = fake_run_agent_command
            response = handle_tools_call(
                req_id=1,
                params={
                    "name": "claude_code_agent",
                    "arguments": {
                        "task": "say hi",
                        "working_dir": "C:/tmp",
                    },
                },
            )
        finally:
            server_http.run_agent_command = original_run_agent_command

        self.assertFalse(tool_is_error(response))
        self.assertEqual("hello from claude", tool_text(response))
        self.assertEqual(1, len(calls))
        args, kwargs = calls[0]
        command = args[0]
        self.assertEqual(["cmd.exe", "/c", server_http.CLAUDE_CMD, "-p", "say hi", "--output-format", "text"], command)
        self.assertEqual("C:/tmp", kwargs["cwd"])
        self.assertIsNone(kwargs["env_overrides"]["ANTHROPIC_AUTH_TOKEN"])
        self.assertIsNone(kwargs["env_overrides"]["ANTHROPIC_API_KEY"])


class ExternalApiIntegrationTests(unittest.TestCase):
    def test_warp_cursor_factory_tools_are_registered(self):
        names = {tool["name"] for tool in TOOLS}
        expected = {
            "warp_agent_runs_list",
            "warp_agent_run_status",
            "warp_agent_run_create",
            "cursor_agents_list",
            "cursor_agent_get",
            "cursor_agent_create",
            "cursor_agent_run_status",
            "factory_sessions_list",
            "factory_session_get",
            "factory_computers_list",
            "factory_readiness_reports",
        }
        self.assertTrue(expected.issubset(names))

    def test_warp_agent_runs_list_formats_response(self):
        with patch.object(server_http, "_warp_request", return_value={
            "runs": [
                {"run_id": "run-1", "state": "running", "title": "scan deps"},
            ]
        }):
            response = server_http.handle_warp_agent_runs_list(req_id=1, arguments={"limit": 5})
        self.assertFalse(tool_is_error(response))
        self.assertIn("run-1", tool_text(response))
        self.assertIn("running", tool_text(response))

    def test_warp_missing_api_key_reports_error(self):
        with patch.object(server_http, "WARP_API_KEY", ""):
            response = server_http.handle_warp_agent_run_status(
                req_id=1, arguments={"run_id": "run-1"}
            )
        self.assertTrue(tool_is_error(response))
        self.assertIn("WARP_API_KEY", tool_text(response))

    def test_cursor_agent_create_returns_ids(self):
        with patch.object(server_http, "_cursor_request", return_value={
            "agent": {"id": "bc-abc", "url": "https://cursor.com/agents/bc-abc"},
            "run": {"id": "run-xyz"},
        }):
            response = server_http.handle_cursor_agent_create(
                req_id=1,
                arguments={"prompt": "fix tests", "repo_url": "https://github.com/org/repo"},
            )
        self.assertFalse(tool_is_error(response))
        text = tool_text(response)
        self.assertIn("bc-abc", text)
        self.assertIn("run-xyz", text)

    def test_cursor_agent_create_builds_repo_payload(self):
        captured = {}

        def fake_cursor_request(method, path, payload=None, params=None):
            captured["method"] = method
            captured["path"] = path
            captured["payload"] = payload
            return {"agent": {"id": "bc-1"}, "run": {"id": "run-1"}}

        with patch.object(server_http, "_cursor_request", side_effect=fake_cursor_request):
            server_http.handle_cursor_agent_create(
                req_id=1,
                arguments={
                    "prompt": "review",
                    "repo_url": "https://github.com/org/repo",
                    "branch": "main",
                },
            )
        self.assertEqual("POST", captured["method"])
        self.assertEqual("/v1/agents", captured["path"])
        self.assertEqual("review", captured["payload"]["prompt"]["text"])
        self.assertEqual("main", captured["payload"]["repos"][0]["startingRef"])

    def test_factory_computers_list_formats_response(self):
        with patch.object(server_http, "_factory_request", return_value=[
            {"id": "cmp-1", "name": "dev-box", "status": "active"},
        ]):
            response = server_http.handle_factory_computers_list(req_id=1, arguments={})
        self.assertFalse(tool_is_error(response))
        text = tool_text(response)
        self.assertIn("cmp-1", text)
        self.assertIn("dev-box", text)

    def test_factory_readiness_reports_uses_app_base_url(self):
        with patch.object(server_http, "_factory_request", return_value={
            "reports": [{"reportId": "rpt-1", "repoUrl": "github.com/org/repo"}],
        }) as mock_request:
            response = server_http.handle_factory_readiness_reports(req_id=1, arguments={"limit": 5})
        self.assertFalse(tool_is_error(response))
        self.assertIn("rpt-1", tool_text(response))
        mock_request.assert_called_once()
        self.assertEqual(server_http.FACTORY_APP_BASE_URL, mock_request.call_args.kwargs["base_url"])


if __name__ == "__main__":
    unittest.main()
