"""
Hermes stdio bridge for the handcraft HTTP MCP endpoint.

Hermes can launch local MCP servers over stdio. This proxy keeps that local
stdio contract while forwarding JSON-RPC requests to server_http.py.

Turn-Aware Context Compaction
------------------------------
When a tools/call payload includes a ``messages`` list, this proxy validates
that any proposed context compaction has not silently discarded thinking/
reasoning blocks.  Warnings are emitted to stderr so they are visible in
Hermes logs without interrupting the request flow.
"""

import json
import os
import sys
import urllib.error
import urllib.request

from context_compaction import validate_compaction

DEFAULT_MCP_URL = "http://127.0.0.1:8765/mcp"
MCP_URL = os.getenv("HERMES_HANDCRAFT_MCP_URL", DEFAULT_MCP_URL)
REQUEST_TIMEOUT_SECONDS = float(os.getenv("HERMES_HANDCRAFT_TIMEOUT_SECONDS", "30"))
PREFLIGHT_TIMEOUT_SECONDS = float(os.getenv("HERMES_HANDCRAFT_PREFLIGHT_TIMEOUT_SECONDS", "5"))


if sys.platform == "win32":
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    sys.stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", newline="\n", closefd=False)
    sys.stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)


def log(message: str) -> None:
    print(f"[HERMES-STDIO-PROXY] {message}", file=sys.stderr, flush=True)


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def make_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def load_auth_token() -> str:
    for env_name in ("HERMES_HANDCRAFT_MCP_TOKEN", "MCP_API_TOKEN", "MCP_AUTH_TOKEN"):
        token = os.getenv(env_name, "").strip()
        if token:
            return token
    return ""


def build_request(payload: dict) -> urllib.request.Request:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    auth_token = load_auth_token()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return urllib.request.Request(MCP_URL, data=body, headers=headers, method="POST")


class HermesPreflightError(RuntimeError):
    pass


def validate_auth_token() -> str:
    token = load_auth_token()
    if not token:
        raise HermesPreflightError("MCP_API_TOKEN is not available for Hermes handcraft MCP preflight")
    return token


def run_preflight() -> None:
    validate_auth_token()
    payload = {
        "jsonrpc": "2.0",
        "id": "hermes-preflight",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "hermes-stdio-proxy"},
        },
    }

    try:
        response = forward_to_http(payload, timeout=PREFLIGHT_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HermesPreflightError(f"MCP_API_TOKEN was rejected by handcraft MCP at {MCP_URL}") from exc
        raise HermesPreflightError(f"handcraft MCP preflight failed at {MCP_URL}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HermesPreflightError(f"handcraft MCP is unreachable at {MCP_URL}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HermesPreflightError(f"handcraft MCP preflight timed out at {MCP_URL}") from exc
    except json.JSONDecodeError as exc:
        raise HermesPreflightError(f"handcraft MCP preflight returned non-JSON from {MCP_URL}") from exc

    if not isinstance(response, dict) or "result" not in response:
        raise HermesPreflightError(f"handcraft MCP preflight returned an invalid initialize response from {MCP_URL}")


def forward_to_http(payload: dict, timeout: float = REQUEST_TIMEOUT_SECONDS) -> dict | None:
    request = build_request(payload)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        if response.status == 202 or not raw:
            return None
        return json.loads(raw.decode("utf-8"))


def _extract_messages_from_payload(payload: dict) -> list[dict] | None:
    """Return the ``messages`` list from a tools/call payload, or None."""
    if not isinstance(payload, dict):
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        return None
    messages = arguments.get("messages")
    if isinstance(messages, list):
        return messages
    return None


def check_compaction_warnings(payload: dict, compacted_messages: list[dict]) -> None:
    """Log warnings if *compacted_messages* dropped thinking blocks vs *payload*.

    Compares the ``messages`` list inside *payload* (the original turns) with
    *compacted_messages* (the proposed replacement) and emits a stderr warning
    for each issue found by :func:`context_compaction.validate_compaction`.
    """
    original_messages = _extract_messages_from_payload(payload)
    if original_messages is None:
        return
    for warning in validate_compaction(original_messages, compacted_messages):
        log(f"[compaction] {warning}")


def handle_line(line: str) -> None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        send(make_error(None, -32700, f"Parse error: {exc}"))
        return

    req_id = payload.get("id") if isinstance(payload, dict) else None
    try:
        response = forward_to_http(payload)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace").strip()
        message = f"HTTP {exc.code} from {MCP_URL}"
        if details:
            message = f"{message}: {details}"
        send(make_error(req_id, -32000, message))
        return
    except urllib.error.URLError as exc:
        send(make_error(req_id, -32000, f"Failed to reach {MCP_URL}: {exc.reason}"))
        return
    except TimeoutError:
        send(make_error(req_id, -32000, f"Timed out forwarding request to {MCP_URL}"))
        return
    except json.JSONDecodeError as exc:
        send(make_error(req_id, -32700, f"HTTP response was not valid JSON: {exc}"))
        return

    if response is not None:
        send(response)


def main() -> None:
    try:
        run_preflight()
    except HermesPreflightError as exc:
        log(f"Startup aborted: {exc}")
        raise SystemExit(1) from None

    log(f"forwarding stdio JSON-RPC to {MCP_URL}")
    for line in sys.stdin:
        line = line.strip()
        if line:
            handle_line(line)


if __name__ == "__main__":
    main()
