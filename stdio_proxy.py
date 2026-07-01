"""
Stdio bridge for the handcraft HTTP MCP endpoint.

This proxy lets any MCP client that launches local servers over stdio (Claude
Desktop / Cursor / Hermes / etc.) talk to handcraft MCP, which is served by
server_http.py over HTTP. It forwards JSON-RPC lines from stdin to the HTTP
endpoint and writes responses back to stdout.
"""

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_MCP_URL = "http://127.0.0.1:8765/mcp"

# Prefer generic env names; keep HERMES_HANDCRAFT_* as backward-compat fallback.
MCP_URL = os.getenv("MCP_URL", os.getenv("HERMES_HANDCRAFT_MCP_URL", DEFAULT_MCP_URL))
REQUEST_TIMEOUT_SECONDS = float(
    os.getenv("MCP_REQUEST_TIMEOUT_SECONDS",
              os.getenv("HERMES_HANDCRAFT_TIMEOUT_SECONDS", "30"))
)
PREFLIGHT_TIMEOUT_SECONDS = float(
    os.getenv("MCP_PREFLIGHT_TIMEOUT_SECONDS",
              os.getenv("HERMES_HANDCRAFT_PREFLIGHT_TIMEOUT_SECONDS", "5"))
)


if sys.platform == "win32":
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    sys.stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", newline="\n", closefd=False)
    sys.stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)


def log(message: str) -> None:
    print(f"[STDIO-PROXY] {message}", file=sys.stderr, flush=True)


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def make_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def load_auth_token() -> str:
    # Prefer generic names; keep HERMES_HANDCRAFT_MCP_TOKEN for backward compat.
    for env_name in ("MCP_API_TOKEN", "MCP_AUTH_TOKEN", "HERMES_HANDCRAFT_MCP_TOKEN"):
        token = os.getenv(env_name, "").strip()
        if token:
            return token
    return ""


def load_cf_access_service_token() -> tuple[str, str]:
    client_id_names = (
        "MCP_CF_ACCESS_CLIENT_ID",
        "CF_ACCESS_CLIENT_ID",
        "HERMES_HANDCRAFT_CF_ACCESS_CLIENT_ID",
    )
    client_secret_names = (
        "MCP_CF_ACCESS_CLIENT_SECRET",
        "CF_ACCESS_CLIENT_SECRET",
        "HERMES_HANDCRAFT_CF_ACCESS_CLIENT_SECRET",
    )
    client_id = next((os.getenv(name, "").strip() for name in client_id_names if os.getenv(name, "").strip()), "")
    client_secret = next((os.getenv(name, "").strip() for name in client_secret_names if os.getenv(name, "").strip()), "")
    return client_id, client_secret


def build_request(payload: dict) -> urllib.request.Request:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    auth_token = load_auth_token()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    client_id, client_secret = load_cf_access_service_token()
    if client_id and client_secret:
        headers["CF-Access-Client-Id"] = client_id
        headers["CF-Access-Client-Secret"] = client_secret
    return urllib.request.Request(MCP_URL, data=body, headers=headers, method="POST")


class PreflightError(RuntimeError):
    pass


# Backward-compat alias for any older code/tests that referenced the old name.
HermesPreflightError = PreflightError


def validate_auth_token() -> str:
    token = load_auth_token()
    client_id, client_secret = load_cf_access_service_token()
    if token:
        return "bearer"
    if client_id and client_secret:
        return "service_token"
    if client_id or client_secret:
        raise PreflightError(
            "Cloudflare Access service token is incomplete. Set both MCP_CF_ACCESS_CLIENT_ID and MCP_CF_ACCESS_CLIENT_SECRET."
        )
    raise PreflightError(
        "No MCP auth is available for handcraft MCP preflight. Set MCP_API_TOKEN for localhost or MCP_CF_ACCESS_CLIENT_ID and MCP_CF_ACCESS_CLIENT_SECRET for Access-protected public MCP."
    )


def describe_preflight_unauthorized_error() -> str:
    has_bearer = bool(load_auth_token())
    client_id, client_secret = load_cf_access_service_token()
    has_service_token = bool(client_id and client_secret)
    if has_bearer and has_service_token:
        return (
            f"handcraft MCP rejected preflight auth at {MCP_URL}. "
            "Check MCP_API_TOKEN, MCP_CF_ACCESS_CLIENT_ID / MCP_CF_ACCESS_CLIENT_SECRET, and Cloudflare Access configuration."
        )
    if has_bearer:
        return f"MCP_API_TOKEN was rejected by handcraft MCP at {MCP_URL}"
    if has_service_token:
        return (
            f"Cloudflare Access service token was rejected by handcraft MCP at {MCP_URL}. "
            "Check MCP_CF_ACCESS_CLIENT_ID / MCP_CF_ACCESS_CLIENT_SECRET and Cloudflare Access configuration."
        )
    return f"handcraft MCP rejected preflight auth at {MCP_URL}"


def run_preflight() -> None:
    validate_auth_token()
    payload = {
        "jsonrpc": "2.0",
        "id": "stdio-preflight",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "stdio-proxy"},
        },
    }

    try:
        response = forward_to_http(payload, timeout=PREFLIGHT_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise PreflightError(describe_preflight_unauthorized_error()) from exc
        raise PreflightError(f"handcraft MCP preflight failed at {MCP_URL}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise PreflightError(f"handcraft MCP is unreachable at {MCP_URL}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise PreflightError(f"handcraft MCP preflight timed out at {MCP_URL}") from exc
    except json.JSONDecodeError as exc:
        raise PreflightError(f"handcraft MCP preflight returned non-JSON from {MCP_URL}") from exc

    if not isinstance(response, dict) or "result" not in response:
        raise PreflightError(f"handcraft MCP preflight returned an invalid initialize response from {MCP_URL}")


def forward_to_http(payload: dict, timeout: float = REQUEST_TIMEOUT_SECONDS) -> dict | None:
    request = build_request(payload)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        if response.status == 202 or not raw:
            return None
        return json.loads(raw.decode("utf-8"))


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
    except PreflightError as exc:
        log(f"Startup aborted: {exc}")
        raise SystemExit(1) from None

    log(f"forwarding stdio JSON-RPC to {MCP_URL}")
    for line in sys.stdin:
        line = line.strip()
        if line:
            handle_line(line)


if __name__ == "__main__":
    main()
