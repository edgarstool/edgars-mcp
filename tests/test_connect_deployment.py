"""Behavioral contracts for the self-hosted 1Password Connect deployment."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deploy" / "docker" / "compose.yaml"
CONTAINER_START = ROOT / "deploy" / "docker" / "start.sh"
LINUX_START = ROOT / "deploy" / "linux" / "start.sh"
INSTALL_CONNECT = ROOT / "deploy" / "linux" / "install-connect.sh"
INSTALL_STACK = ROOT / "deploy" / "docker" / "install.sh"
CHECK_CONTAINER = ROOT / "deploy" / "docker" / "check.sh"


class _ConnectHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"name":"1Password Connect API","version":"test"}')
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class _McpCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/mcp" or self.headers.get("Authorization") != "Bearer test-mcp-token":
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        names = [f"tool_{number}" for number in range(75)] + [
            "warp_agent_runs_list",
            "warp_agent_run_status",
            "warp_agent_run_create",
        ]
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": name} for name in names]}}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class ConnectComposeContractTests(unittest.TestCase):
    def test_stack_installer_prepares_connect_and_starts_the_private_compose_stack(self) -> None:
        """The supported install path must converge files and launch all services in one command."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            credentials_source = temporary / "downloaded-credentials.json"
            credentials_source.write_text('{"verifier":"test"}\n', encoding="utf-8")
            token_source = temporary / "downloaded-token"
            token_source.write_text("connect-token\n", encoding="utf-8")
            home = temporary / "home"
            home.mkdir()
            result_file = temporary / "docker-argv.json"
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['FAKE_DOCKER_RESULT']).write_text(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "FAKE_DOCKER_RESULT": str(result_file),
                }
            )

            completed = subprocess.run(
                ["bash", str(INSTALL_STACK), str(credentials_source), str(token_source)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((home / ".config" / "1password-connect" / "1password-credentials.json").is_file())
            self.assertTrue((home / ".config" / "1password-connect" / "edgars-mcp.token").is_file())
            self.assertEqual(
                (ROOT / "config" / "edgars-mcp.op.env.example").read_text(encoding="utf-8"),
                (home / ".config" / "edgars-mcp" / "edgars-mcp.op.env").read_text(encoding="utf-8"),
            )
            for directory in ("run", "state", "logs", "cache", "tmp"):
                self.assertTrue((home / "runtime" / "edgars-mcp" / directory).is_dir())
            self.assertEqual(
                ["compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build"],
                json.loads(result_file.read_text(encoding="utf-8")),
            )

    def test_compose_runs_connect_api_sync_and_mcp_with_connect_on_loopback_only(self) -> None:
        """Connect must support native fallback without becoming publicly reachable."""
        compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
        services = compose["services"]

        self.assertEqual("1password/connect-api:1.8", services["op-connect-api"]["image"])
        self.assertEqual("1password/connect-sync:1.8", services["op-connect-sync"]["image"])
        self.assertEqual(["127.0.0.1:8080:8080"], services["op-connect-api"]["ports"])
        self.assertEqual(
            "http://op-connect-api:8080",
            services["edgars-mcp"]["environment"]["OP_CONNECT_HOST"],
        )
        self.assertIn("op_connect_credentials", services["op-connect-api"]["secrets"])
        self.assertIn("op_connect_credentials", services["op-connect-sync"]["secrets"])
        self.assertIn("op_connect_token", services["edgars-mcp"]["secrets"])

    def test_compose_bootstrap_secrets_come_from_operator_owned_files(self) -> None:
        """Connect credentials and tokens must never be embedded in Git or image metadata."""
        compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))

        self.assertEqual(
            "${HOME}/.config/1password-connect/1password-credentials.json",
            compose["secrets"]["op_connect_credentials"]["file"],
        )
        self.assertEqual(
            "${HOME}/.config/1password-connect/edgars-mcp.token",
            compose["secrets"]["op_connect_token"]["file"],
        )


class ContainerStartContractTests(unittest.TestCase):
    def test_container_check_resolves_token_through_connect_and_verifies_tools(self) -> None:
        """The live check must prove health, the 78-tool contract, and Warp through Connect."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            token_file = temporary / "connect-token"
            token_file.write_text("test-connect-token\n", encoding="utf-8")
            env_file = temporary / "edgars-mcp.op.env"
            env_file.write_text("MCP_API_TOKEN=op://vault/item/token\n", encoding="utf-8")
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_op = fake_bin / "op"
            fake_op.write_text(
                "#!/usr/bin/env python3\n"
                "import os, subprocess, sys\n"
                "separator = sys.argv.index('--')\n"
                "environment = os.environ.copy()\n"
                "environment['MCP_API_TOKEN'] = 'test-mcp-token'\n"
                "raise SystemExit(subprocess.call(sys.argv[separator + 1:], env=environment))\n",
                encoding="utf-8",
            )
            fake_op.chmod(0o755)

            server = ThreadingHTTPServer(("127.0.0.1", 0), _McpCheckHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                env = os.environ.copy()
                env.update(
                    {
                        "PATH": f"{fake_bin}:{env['PATH']}",
                        "OP_CONNECT_HOST": "http://op-connect-api:8080",
                        "OP_CONNECT_TOKEN_FILE": str(token_file),
                        "EDGARS_MCP_OP_ENV_FILE": str(env_file),
                        "EDGARS_MCP_CHECK_URL": f"http://127.0.0.1:{server.server_port}",
                    }
                )
                completed = subprocess.run(
                    ["bash", str(CHECK_CONTAINER)],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("PASS: health, 78 tools, Warp Oz tools", completed.stdout.strip())

    def test_start_reads_connect_token_file_and_runs_mcp_through_op(self) -> None:
        """The MCP process must resolve op:// references through the private Connect API."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            token_file = temporary / "connect-token"
            token_file.write_text("test-connect-token\n", encoding="utf-8")
            env_file = temporary / "edgars-mcp.op.env"
            env_file.write_text("MCP_API_TOKEN=op://vault/item/token\n", encoding="utf-8")
            result_file = temporary / "op-result.json"
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_op = fake_bin / "op"
            fake_op.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['FAKE_OP_RESULT']).write_text(json.dumps({\n"
                "  'host': os.environ.get('OP_CONNECT_HOST'),\n"
                "  'token': os.environ.get('OP_CONNECT_TOKEN'),\n"
                "  'service_account': os.environ.get('OP_SERVICE_ACCOUNT_TOKEN'),\n"
                "  'argv': sys.argv[1:],\n"
                "}))\n",
                encoding="utf-8",
            )
            fake_op.chmod(0o755)

            server = ThreadingHTTPServer(("127.0.0.1", 0), _ConnectHealthHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                env = os.environ.copy()
                env.update(
                    {
                        "PATH": f"{fake_bin}:{env['PATH']}",
                        "FAKE_OP_RESULT": str(result_file),
                        "OP_CONNECT_HOST": f"http://127.0.0.1:{server.server_port}",
                        "OP_CONNECT_TOKEN_FILE": str(token_file),
                        "EDGARS_MCP_OP_ENV_FILE": str(env_file),
                    }
                )
                completed = subprocess.run(
                    ["bash", str(CONTAINER_START)],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(0, completed.returncode, completed.stderr)
            invocation = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertEqual(env["OP_CONNECT_HOST"], invocation["host"])
            self.assertEqual("test-connect-token", invocation["token"])
            self.assertIsNone(invocation["service_account"])
            self.assertEqual(
                [
                    "run",
                    "--env-file",
                    str(env_file),
                    "--",
                    "python",
                    "-m",
                    "edgars_mcp.http_server",
                ],
                invocation["argv"],
            )

    def test_start_fails_before_op_when_connect_token_is_missing(self) -> None:
        """An empty bootstrap token must stop startup instead of launching an unauthenticated MCP."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            env_file = temporary / "edgars-mcp.op.env"
            env_file.write_text("MCP_API_TOKEN=op://vault/item/token\n", encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "OP_CONNECT_HOST": "http://127.0.0.1:9",
                    "OP_CONNECT_TOKEN_FILE": str(temporary / "missing-token"),
                    "EDGARS_MCP_OP_ENV_FILE": str(env_file),
                }
            )

            completed = subprocess.run(
                ["bash", str(CONTAINER_START)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("Connect token", completed.stderr)


class LinuxStartContractTests(unittest.TestCase):
    def test_native_start_uses_default_connect_token_file_outside_systemd(self) -> None:
        """Manual native starts must use the installed Connect token without a systemd context."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            source = temporary / "source"
            python_bin = source / ".venv" / "bin" / "python"
            python_bin.parent.mkdir(parents=True)
            python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python_bin.chmod(0o755)
            config = home / ".config" / "edgars-mcp"
            config.mkdir(parents=True)
            (config / "edgars-mcp.op.env").write_text(
                "MCP_API_TOKEN=op://vault/item/token\n", encoding="utf-8"
            )
            connect_config = home / ".config" / "1password-connect"
            connect_config.mkdir(parents=True)
            (connect_config / "edgars-mcp.token").write_text(
                "manual-connect-token\n", encoding="utf-8"
            )
            result_file = temporary / "token-result"
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_op = fake_bin / "op"
            fake_op.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"whoami\" ]]; then exit 0; fi\n"
                "printf '%s' \"$OP_CONNECT_TOKEN\" > \"$FAKE_OP_RESULT\"\n",
                encoding="utf-8",
            )
            fake_op.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "FAKE_OP_RESULT": str(result_file),
                    "EDGARS_MCP_SOURCE_DIR": str(source),
                    "EDGARS_MCP_CONFIG_DIR": str(config),
                }
            )
            env.pop("CREDENTIALS_DIRECTORY", None)
            env.pop("OP_CONNECT_TOKEN", None)
            env.pop("OP_CONNECT_TOKEN_FILE", None)

            completed = subprocess.run(
                ["bash", str(LINUX_START)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("manual-connect-token", result_file.read_text(encoding="utf-8"))

    def test_connect_installer_places_bootstrap_files_outside_checkout(self) -> None:
        """Provisioning must copy operator-supplied Connect files with private permissions."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            credentials_source = temporary / "downloaded-credentials.json"
            credentials_source.write_text('{"verifier":"test"}\n', encoding="utf-8")
            token_source = temporary / "downloaded-token"
            token_source.write_text("connect-token\n", encoding="utf-8")
            home = temporary / "home"
            home.mkdir()
            env = os.environ.copy()
            env["HOME"] = str(home)

            completed = subprocess.run(
                ["bash", str(INSTALL_CONNECT), str(credentials_source), str(token_source)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            target = home / ".config" / "1password-connect"
            credentials_target = target / "1password-credentials.json"
            token_target = target / "edgars-mcp.token"
            self.assertEqual(credentials_source.read_bytes(), credentials_target.read_bytes())
            self.assertEqual(token_source.read_bytes(), token_target.read_bytes())
            self.assertEqual(0o700, target.stat().st_mode & 0o777)
            self.assertEqual(0o600, credentials_target.stat().st_mode & 0o777)
            self.assertEqual(0o600, token_target.stat().st_mode & 0o777)

    def test_systemd_start_reads_connect_credential_instead_of_service_account(self) -> None:
        """Native restarts must authenticate op through Connect, not a cloud service account."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            python_bin = source / ".venv" / "bin" / "python"
            python_bin.parent.mkdir(parents=True)
            python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python_bin.chmod(0o755)

            config = temporary / "config"
            config.mkdir()
            env_file = config / "edgars-mcp.op.env"
            env_file.write_text("MCP_API_TOKEN=op://vault/item/token\n", encoding="utf-8")

            credentials = temporary / "credentials"
            credentials.mkdir()
            (credentials / "op-connect-token").write_text(
                "native-connect-token\n", encoding="utf-8"
            )

            result_file = temporary / "op-result.json"
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_op = fake_bin / "op"
            fake_op.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "if sys.argv[1:] == ['whoami']:\n"
                "    raise SystemExit(0)\n"
                "Path(os.environ['FAKE_OP_RESULT']).write_text(json.dumps({\n"
                "  'host': os.environ.get('OP_CONNECT_HOST'),\n"
                "  'token': os.environ.get('OP_CONNECT_TOKEN'),\n"
                "  'service_account': os.environ.get('OP_SERVICE_ACCOUNT_TOKEN'),\n"
                "  'argv': sys.argv[1:],\n"
                "}))\n",
                encoding="utf-8",
            )
            fake_op.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "FAKE_OP_RESULT": str(result_file),
                    "CREDENTIALS_DIRECTORY": str(credentials),
                    "EDGARS_MCP_SOURCE_DIR": str(source),
                    "EDGARS_MCP_CONFIG_DIR": str(config),
                    "EDGARS_MCP_OP_ENV_FILE": str(env_file),
                    "OP_CONNECT_HOST": "http://127.0.0.1:8080",
                }
            )
            completed = subprocess.run(
                ["bash", str(LINUX_START)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            invocation = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertEqual("http://127.0.0.1:8080", invocation["host"])
            self.assertEqual("native-connect-token", invocation["token"])
            self.assertIsNone(invocation["service_account"])
            self.assertEqual(
                ["run", "--env-file", str(env_file), "--", str(python_bin), "-m", "edgars_mcp.http_server"],
                invocation["argv"],
            )


if __name__ == "__main__":
    unittest.main()
