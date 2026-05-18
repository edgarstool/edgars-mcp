"""
手刻 MCP Server - Streamable HTTP 版本
協議版本: 2025-11-25
依賴: 僅 Python 標準庫 (http.server, json, urllib.parse)

端點:
- POST /mcp
- POST /webhook/package
回應模式: 單次 JSON（不開 SSE stream，Phase 2 基礎版）
"""

import sys
import json
import os
import subprocess
import tempfile
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

CODEX_CMD = r"C:\Users\Windows10-JS\AppData\Roaming\npm\codex.cmd"
CODEX_DEFAULT_WORKDIR = r"C:\Users\Windows10-JS"
AGENT_TIMEOUT_SECONDS = int(os.getenv("MCP_AGENT_TIMEOUT_SECONDS", "90"))

PORT = 8765
PROTOCOL_VERSION = "2025-11-25"
MCP_PATH = "/mcp"
PACKAGE_WEBHOOK_PATH = "/webhook/package"

SERVER_INFO = {
    "name": "handcraft-mcp",
    "version": "0.1.0",
}

TOOLS = [
    {
        "name": "echo",
        "description": "Echoes back the input message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to echo back",
                }
            },
            "required": ["message"],
        },
    },
    {
        "name": "codex_agent",
        "description": (
            "Delegates a task to the Codex AI coding agent running on the local machine. "
            "Codex will autonomously plan, write code, run shell commands, and edit files "
            "to complete the task. Use this when you want another AI agent to handle "
            "implementation work independently. Returns Codex's final response."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task or instruction for Codex to execute autonomously",
                },
                "working_dir": {
                    "type": "string",
                    "description": (
                        f"Working directory for Codex to operate in "
                        f"(default: {CODEX_DEFAULT_WORKDIR})"
                    ),
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "claude_code_agent",
        "description": (
            "Delegates a task to the Claude Code AI coding agent running on the local machine. "
            "Claude Code will autonomously plan, write code, run shell commands, and edit files "
            "to complete the task. Best for complex coding, refactoring, multi-file operations, "
            "and tasks requiring deep codebase understanding. Returns Claude Code's final response."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The coding task or question to send to Claude Code.",
                },
                "working_dir": {
                    "type": "string",
                    "description": (
                        f"Working directory for Claude Code to operate in "
                        f"(default: {CODEX_DEFAULT_WORKDIR})"
                    ),
                },
            },
            "required": ["task"],
        },
    },
]

# ── Origin 白名單（防 DNS rebinding，spec 強制要求）────────────────────────────
# 允許 localhost / 127.0.0.1 任意 port，供本地開發 + MCP Inspector 使用。
# Cloudflare Tunnel 接入後，瀏覽器 origin 會是 tunnel domain，需另行加入。
ALLOWED_HOSTNAMES = {"localhost", "127.0.0.1", "mcp.whoasked.vip"}


# ─── 共用工具 ─────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[MCP-HTTP] {msg}", file=sys.stderr, flush=True)


def make_response(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def make_webhook_response(event_type: str, accepted: bool = True) -> dict:
    return {
        "ok": accepted,
        "type": event_type,
        "service": "handcraft-package-webhook",
    }


def run_agent_command(command: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=AGENT_TIMEOUT_SECONDS,
        cwd=cwd,
        shell=False,
    )


def finalize_agent_output(
    result: subprocess.CompletedProcess,
    *,
    stdout_text: str = "",
    fallback_label: str,
) -> tuple[str, bool]:
    stdout_text = stdout_text.strip() if stdout_text else ""
    stderr_text = (result.stderr or "").strip()

    output = stdout_text or (result.stdout or "").strip()

    if result.returncode != 0:
        sections = []
        if stderr_text:
            sections.append(f"[stderr]\n{stderr_text}")
        if output:
            sections.append(f"[stdout]\n{output}")
        output = "\n".join(sections).strip()

    if not output:
        output = f"{fallback_label} exited with code {result.returncode} (no output)"

    return output, result.returncode != 0


# ─── Request Handlers（與 stdio 版邏輯相同，改為 return 而非 send）────────────

def handle_initialize(req_id, params: dict) -> dict:
    log(f"initialize: client protocolVersion={params.get('protocolVersion')}")
    return make_response(req_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": SERVER_INFO,
    })


def handle_ping(req_id, params: dict) -> dict:
    log("ping")
    return make_response(req_id, {})


def handle_tools_list(req_id, params: dict) -> dict:
    log(f"tools/list: returning {len(TOOLS)} tool(s)")
    return make_response(req_id, {"tools": TOOLS})


def handle_tools_call(req_id, params: dict) -> dict:
    name = params.get("name")
    arguments = params.get("arguments", {})
    log(f"tools/call: name={name} arguments={arguments}")

    if name == "echo":
        message = arguments.get("message", "")
        return make_response(req_id, {
            "content": [{"type": "text", "text": f"echo: {message}"}],
            "isError": False,
        })

    if name == "codex_agent":
        return handle_codex_agent(req_id, arguments)

    if name == "claude_code_agent":
        return handle_claude_code_agent(req_id, arguments)

    return make_response(req_id, {
        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        "isError": True,
    })


def handle_codex_agent(req_id, arguments: dict) -> dict:
    task = arguments.get("task", "").strip()
    working_dir = arguments.get("working_dir", CODEX_DEFAULT_WORKDIR)

    if not task:
        return make_response(req_id, {
            "content": [{"type": "text", "text": "Error: task is required"}],
            "isError": True,
        })

    log(f"codex_agent: task={task!r} workdir={working_dir!r}")

    # -o <file> で最終メッセージをファイルに書き出す
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="codex_out_")
    os.close(tmp_fd)

    try:
        result = run_agent_command(
            [
                "cmd.exe",
                "/c",
                CODEX_CMD,
                "exec",
                "--full-auto",       # 自動承認、sandbox=workspace-write
                "--ephemeral",       # セッションファイルを残さない
                "--skip-git-repo-check",
                "-C", working_dir,
                "-o", tmp_path,      # 最終メッセージをファイルへ
                task,
            ],
            cwd=working_dir,
        )
        log(f"codex_agent: exit_code={result.returncode}")

        # -o に書かれた最終メッセージを優先、なければ stdout を使う
        output = ""
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                output = f.read().strip()
        except Exception:
            pass

        output, is_error = finalize_agent_output(
            result,
            stdout_text=output,
            fallback_label="Codex",
        )

    except subprocess.TimeoutExpired:
        output = f"codex_agent timed out after {AGENT_TIMEOUT_SECONDS} seconds"
        is_error = True
    except Exception as exc:
        output = f"Failed to run Codex: {exc}"
        is_error = True
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return make_response(req_id, {
        "content": [{"type": "text", "text": output}],
        "isError": is_error,
    })


def handle_claude_code_agent(req_id, arguments: dict) -> dict:
    task = arguments.get("task", "").strip()
    working_dir = arguments.get("working_dir", CODEX_DEFAULT_WORKDIR)

    if not task:
        return make_response(req_id, {
            "content": [{"type": "text", "text": "Error: task is required"}],
            "isError": True,
        })

    log(f"claude_code_agent: task={task!r} workdir={working_dir!r}")

    try:
        result = run_agent_command(
            ["claude", "-p", task, "--output-format", "text"],
            cwd=working_dir,
        )
        log(f"claude_code_agent: exit_code={result.returncode}")

        output, is_error = finalize_agent_output(
            result,
            fallback_label="Claude Code",
        )

    except subprocess.TimeoutExpired:
        output = f"claude_code_agent timed out after {AGENT_TIMEOUT_SECONDS} seconds"
        is_error = True
    except FileNotFoundError:
        output = "Error: claude command not found. Run: winget install Anthropic.ClaudeCode"
        is_error = True
    except Exception as exc:
        output = f"Failed to run Claude Code: {exc}"
        is_error = True
    return make_response(req_id, {
        "content": [{"type": "text", "text": output}],
        "isError": is_error,
    })


REQUEST_HANDLERS = {
    "initialize":  handle_initialize,
    "ping":        handle_ping,
    "tools/list":  handle_tools_list,
    "tools/call":  handle_tools_call,
}


def dispatch(msg: dict):
    """處理單一 JSON-RPC 訊息。Notification 回傳 None；Request 回傳 response dict。"""
    method = msg.get("method", "")
    req_id = msg.get("id")          # Notification 沒有 id
    params = msg.get("params") or {}

    if req_id is None:
        log(f"NOTIFICATION {method} (no response)")
        return None

    handler = REQUEST_HANDLERS.get(method)
    if handler is None:
        log(f"METHOD NOT FOUND: {method}")
        return make_error(req_id, -32601, f"Method not found: {method}")

    try:
        return handler(req_id, params)
    except Exception as exc:
        log(f"HANDLER ERROR [{method}]: {exc}")
        return make_error(req_id, -32603, f"Internal error: {exc}")


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class MCPHTTPHandler(BaseHTTPRequestHandler):

    # ── CORS preflight ────────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self._add_cors_headers()
        self.end_headers()

    # ── 主要端點 ──────────────────────────────────────────────────────────────
    def do_POST(self):
        if self.path == PACKAGE_WEBHOOK_PATH:
            self._handle_package_webhook()
            return

        if self.path != MCP_PATH:
            self.send_response(404)
            self.end_headers()
            return

        # ── Origin 驗證（spec 強制，防 DNS rebinding）─────────────────────────
        origin = self.headers.get("Origin", "")
        if origin and not self._is_allowed_origin(origin):
            log(f"403 Forbidden: Origin={origin!r}")
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Forbidden: Origin not allowed")
            return

        # ── 讀取 body ─────────────────────────────────────────────────────────
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        log(f"RECV ← {raw.decode('utf-8', errors='replace')}")

        # ── JSON parse ────────────────────────────────────────────────────────
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._send_json(make_error(None, -32700, f"Parse error: {exc}"), status=400)
            return

        if not isinstance(msg, dict):
            self._send_json(make_error(None, -32600, "Invalid Request: expected JSON object"), status=400)
            return

        # ── Dispatch ──────────────────────────────────────────────────────────
        response = dispatch(msg)

        if response is None:
            # Notification → 202 Accepted, 不回 body
            self.send_response(202)
            self._add_cors_headers()
            self.end_headers()
            return

        self._send_json(response)

    def _handle_package_webhook(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        raw_text = raw.decode("utf-8", errors="replace")
        log(f"PACKAGE WEBHOOK RECV ← {raw_text}")

        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._send_json(
                    {
                        **make_webhook_response("package", accepted=False),
                        "error": f"Invalid JSON: {exc}",
                    },
                    status=400,
                )
                return
        else:
            payload = {}

        if not isinstance(payload, dict):
            self._send_json(
                {
                    **make_webhook_response("package", accepted=False),
                    "error": "Invalid payload: expected JSON object",
                },
                status=400,
            )
            return

        self._send_json({
            **make_webhook_response("package"),
            "received": True,
        })

    # ── 回應輔助 ──────────────────────────────────────────────────────────────
    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        log(f"SEND → {body.decode('utf-8')}")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _add_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization, Accept, Mcp-Session-Id")

    def _is_allowed_origin(self, origin: str) -> bool:
        try:
            hostname = urllib.parse.urlparse(origin).hostname or ""
            return hostname in ALLOWED_HOSTNAMES
        except Exception:
            return False

    # ── 把 http.server 的 access log 導到 stderr ──────────────────────────────
    def log_message(self, fmt, *args):
        log(f"{self.address_string()} - {fmt % args}")


# ─── 主程式 ───────────────────────────────────────────────────────────────────

def main() -> None:
    server = HTTPServer(("0.0.0.0", PORT), MCPHTTPHandler)
    log(f"handcraft-mcp HTTP server starting")
    log(f"Protocol : {PROTOCOL_VERSION}")
    log(f"Endpoint : POST http://localhost:{PORT}{MCP_PATH}")
    log(f"Webhook : POST http://localhost:{PORT}{PACKAGE_WEBHOOK_PATH}")
    log(f"Allowed origins: {ALLOWED_HOSTNAMES}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Server stopped (KeyboardInterrupt)")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
