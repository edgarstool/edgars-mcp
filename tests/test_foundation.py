"""Behavioral contracts for the Linux/Contabo foundation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

EXPECTED_TOOL_NAMES = [
    "echo",
    "codex_agent",
    "gemini_agent",
    "claude_code_agent",
    "copilot_agent",
    "droid_agent",
    "agent_job_status",
    "agent_job_list",
    "agent_job_cleanup",
    "smart_agent",
    "notion_search",
    "notion_get_page",
    "mmx_image_generate",
    "mmx_video_generate",
    "mmx_speech_synthesize",
    "mmx_music_generate",
    "mmx_vision_describe",
    "mmx_search_query",
    "mmx_text_chat",
    "mmx_quota_show",
    "ollama_agent",
    "ollama_list_models",
    "ollama_generate",
    "ollama_chat",
    "fs_list",
    "fs_read",
    "fs_write",
    "fs_move",
    "fs_delete",
    "fs_search",
    "fs_disk_info",
    "sys_run",
    "sys_info",
    "sys_processes",
    "git_status",
    "git_log",
    "git_diff",
    "git_commit",
    "browser_screenshot",
    "browser_get_text",
    "browser_run_script",
    "browser_visible_open",
    "browser_visible_navigate",
    "browser_visible_click",
    "browser_visible_type",
    "browser_visible_screenshot",
    "browser_visible_close",
    "vault_read",
    "vault_write",
    "vault_append",
    "vault_list",
    "vault_search",
    "vault_delete",
    "vault_move",
    "vault_daily_note",
    "vault_recent",
    "vault_tasks",
    "vault_tags",
    "vault_create_from_template",
    "vault_sort_inbox",
    "tracktw_carriers",
    "tracktw_package_status",
    "image_generate_free",
    "web_search",
    "linear_issues",
    "linear_create_issue",
    "linear_update_issue",
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
]


def run_package_script(source: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env["PYTHONPATH"] = str(SRC)
    if env:
        process_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


class PackageContractTests(unittest.TestCase):
    def test_package_import_preserves_all_mcp_tool_names(self) -> None:
        """Moving the server into a package must not drop or rename an MCP tool."""
        completed = run_package_script(
            "import json; from edgars_mcp.http_server import TOOLS; "
            "print(json.dumps([tool['name'] for tool in TOOLS]))",
            env={"MCP_API_TOKEN": "test-token"},
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(EXPECTED_TOOL_NAMES, json.loads(completed.stdout))

    def test_runtime_paths_default_below_home_and_never_inside_source(self) -> None:
        """A cloud deployment must keep mutable state outside the Git checkout."""
        with tempfile.TemporaryDirectory() as home:
            completed = run_package_script(
                "import json; from edgars_mcp.config import RuntimePaths; "
                "print(json.dumps(RuntimePaths.from_env().as_dict(), sort_keys=True))",
                env={"HOME": home},
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            runtime = Path(home) / "runtime" / "edgars-mcp"
            self.assertEqual(
                {
                    "cache": str(runtime / "cache"),
                    "logs": str(runtime / "logs"),
                    "root": str(runtime),
                    "run": str(runtime / "run"),
                    "state": str(runtime / "state"),
                    "tmp": str(runtime / "tmp"),
                },
                json.loads(completed.stdout),
            )

    def test_runtime_path_environment_overrides_are_honored(self) -> None:
        """Operators must be able to relocate each mutable data class independently."""
        completed = run_package_script(
            "import json; from edgars_mcp.config import RuntimePaths; "
            "print(json.dumps(RuntimePaths.from_env().as_dict(), sort_keys=True))",
            env={
                "EDGARS_MCP_RUNTIME_DIR": "/srv/runtime",
                "EDGARS_MCP_LOG_DIR": "/srv/logs",
                "EDGARS_MCP_TMP_DIR": "/srv/tmp",
            },
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("/srv/runtime", json.loads(completed.stdout)["root"])
        self.assertEqual("/srv/logs", json.loads(completed.stdout)["logs"])
        self.assertEqual("/srv/tmp", json.loads(completed.stdout)["tmp"])

    def test_server_defaults_to_loopback(self) -> None:
        """The origin must not become publicly reachable without an explicit gateway."""
        with tempfile.TemporaryDirectory() as runtime:
            completed = run_package_script(
                "from edgars_mcp.http_server import build_server; "
                "server = build_server(port=0); "
                "print(server.server_address[0]); server.server_close()",
                env={
                    "MCP_API_TOKEN": "test-token",
                    "EDGARS_MCP_RUNTIME_DIR": runtime,
                },
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("127.0.0.1", completed.stdout.strip())

    def test_headless_linux_marks_visible_browser_tools_unavailable(self) -> None:
        """A Contabo server must report a clear capability boundary instead of crashing."""
        completed = run_package_script(
            "import json; from edgars_mcp.config import tool_capability; "
            "print(json.dumps(tool_capability('browser_visible_open', platform_name='Linux', env={})))"
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            {
                "available": False,
                "reason": "visible browser requires a desktop display",
                "status": "unavailable",
            },
            json.loads(completed.stdout),
        )


if __name__ == "__main__":
    unittest.main()
