#!/usr/bin/env python3
"""Edgar's Knowledge MCP — Streamable HTTP transport for ChatGPT connectors.

Thin adapter over https://knowledge-api.edgars.tools (NOT a new KB).
Reuses tool handlers from server.py (stdio MCP).

Endpoints:
  POST/GET /mcp          Streamable HTTP MCP (auth required)
  GET /health            ok + upstream knowledge-api health
  GET /.well-known/oauth-protected-resource
  GET /.well-known/oauth-protected-resource/mcp
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

# Reuse Knowledge API client + tool handlers from stdio server.
import server as kb

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
AUTH_SERVER = os.environ.get("EDGARS_AUTH_SERVER", "https://auth.edgars.tools").rstrip("/")
MCP_API_TOKEN = os.environ.get("MCP_API_TOKEN", "").strip()
# When MCP_API_TOKEN is unset, any non-empty Bearer is accepted (ChatGPT OAuth
# presence check). Set MCP_TRUST_BEARER=0 to reject all non-canary tokens.
MCP_TRUST_BEARER = os.environ.get("MCP_TRUST_BEARER", "1").strip() not in (
    "0",
    "false",
    "False",
    "no",
)
SERVER_NAME = "edgars-knowledge-http"
SERVER_VERSION = "0.2.0"
PROTOCOL = getattr(kb, "PROTOCOL", "2025-11-25")
MCP_PATH = "/mcp"


def log(msg: str) -> None:
    print(f"[{SERVER_NAME}] {msg}", file=sys.stderr, flush=True)


def public_url(path: str = "") -> str:
    if not path:
        return PUBLIC_BASE_URL
    if not path.startswith("/"):
        path = "/" + path
    return PUBLIC_BASE_URL + path


def resource_metadata_document() -> dict[str, Any]:
    return {
        "resource": PUBLIC_BASE_URL,
        "authorization_servers": [AUTH_SERVER],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["openid", "profile", "email"],
        "resource_documentation": "https://knowledge-api.edgars.tools",
    }


def www_authenticate_value() -> str:
    meta = public_url("/.well-known/oauth-protected-resource/mcp")
    return (
        f'Bearer realm="edgars-knowledge", '
        f'resource_metadata="{meta}", '
        f'scope="openid profile email"'
    )


def extract_bearer(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def is_authorized(auth_header: str | None) -> bool:
    token = extract_bearer(auth_header)
    if not token:
        return False
    if MCP_API_TOKEN and token == MCP_API_TOKEN:
        return True
    if MCP_API_TOKEN and not MCP_TRUST_BEARER:
        return False
    # OAuth / presence-only path for ChatGPT after AS issues a token.
    return MCP_TRUST_BEARER


def structured_tool_result(payload: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": is_error,
    }


def hit_id(hit: dict[str, Any], idx: int) -> str:
    prov = hit.get("provenance") or {}
    raw = (
        prov.get("id")
        or prov.get("pointer")
        or hit.get("source")
        or hit.get("excerpt")
        or str(idx)
    )
    digest = hashlib.sha1(str(raw).encode("utf-8", errors="replace")).hexdigest()[:12]
    backend = hit.get("backend") or "hit"
    return f"{backend}-{digest}"


def tool_search(args: dict[str, Any]) -> dict[str, Any]:
    """ChatGPT company-knowledge alias → knowledge_search shaped as {results:[…]}."""
    query = (args.get("query") or "").strip()
    if not query:
        return structured_tool_result({"results": []})
    status, data = kb.http_json("POST", "/search", {"query": query})
    if status != 200:
        return structured_tool_result(
            {
                "results": [],
                "error": f"search failed HTTP {status}",
                "detail": data,
            },
            is_error=True,
        )
    shaped = kb.normalize_search(query, status, data)
    results = []
    for i, hit in enumerate(shaped.get("hits") or []):
        hid = hit_id(hit, i)
        title = (
            (hit.get("authority_role") or hit.get("backend") or "Knowledge hit")
            + f" [{hid}]"
        )
        url = None
        prov = hit.get("provenance") or {}
        pointer = prov.get("pointer")
        if isinstance(pointer, str) and pointer.startswith("qmd://"):
            url = pointer
        elif isinstance(pointer, str) and pointer.startswith("http"):
            url = pointer
        else:
            url = f"{kb.BASE}/search?q={query}"
        excerpt = (hit.get("excerpt") or "")[:200]
        results.append(
            {
                "id": hid,
                "title": title[:200],
                "url": url,
                "_excerpt": excerpt,
                "_backend": hit.get("backend"),
            }
        )
    # Company-knowledge schema: only id/title/url in structured results.
    clean = [{"id": r["id"], "title": r["title"], "url": r["url"]} for r in results]
    # Stash richer hits under a side channel for fetch via id lookup cache.
    _FETCH_CACHE.store(query, shaped.get("hits") or [], results)
    return structured_tool_result({"results": clean})


def tool_fetch(args: dict[str, Any]) -> dict[str, Any]:
    """ChatGPT company-knowledge alias → knowledge_get shaped as fetch document."""
    doc_id = (args.get("id") or args.get("pointer") or args.get("query") or "").strip()
    if not doc_id:
        return structured_tool_result(
            {"id": "", "title": "", "text": "id is required", "url": "", "metadata": {}},
            is_error=True,
        )
    cached = _FETCH_CACHE.get(doc_id)
    if cached:
        return structured_tool_result(cached)

    # Expand via Knowledge API search (same as knowledge_get).
    status, data = kb.http_json("POST", "/search", {"query": doc_id})
    if status != 200:
        return structured_tool_result(
            {
                "id": doc_id,
                "title": doc_id,
                "text": f"fetch failed HTTP {status}: {json.dumps(data, ensure_ascii=False)}",
                "url": kb.BASE,
                "metadata": {"error": True},
            },
            is_error=True,
        )
    shaped = kb.normalize_search(doc_id, status, data)
    hits = shaped.get("hits") or []
    texts = []
    for h in hits[:8]:
        texts.append(
            f"[{h.get('backend')}] {h.get('authority_role')}\n{(h.get('excerpt') or '')[:2000]}"
        )
    body = "\n\n---\n\n".join(texts) if texts else json.dumps(shaped, ensure_ascii=False, indent=2)
    payload = {
        "id": doc_id,
        "title": f"Edgar's Knowledge: {doc_id[:80]}",
        "text": body[:50000],
        "url": f"{kb.BASE}/search",
        "metadata": {
            "source": "knowledge-api.edgars.tools",
            "mode": "fetch",
            "hit_count": len(hits),
            "note": "Hits are evidence/locators — live-verify Current claims.",
        },
    }
    return structured_tool_result(payload)


class FetchCache:
    """Tiny in-memory map from search result id → fetch document."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict[str, Any]] = {}

    def store(self, query: str, hits: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
        with self._lock:
            for r, h in zip(results, hits):
                self._by_id[r["id"]] = {
                    "id": r["id"],
                    "title": r["title"],
                    "text": (h.get("excerpt") or "")[:50000],
                    "url": r["url"],
                    "metadata": {
                        "backend": h.get("backend"),
                        "authority_role": h.get("authority_role"),
                        "provenance": h.get("provenance"),
                        "query": query,
                        "source": "knowledge-api.edgars.tools",
                    },
                }
            # Cap cache size
            if len(self._by_id) > 500:
                for k in list(self._by_id)[:100]:
                    self._by_id.pop(k, None)

    def get(self, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._by_id.get(doc_id)


_FETCH_CACHE = FetchCache()

# Tool registry: reuse kb.TOOLS handlers + ChatGPT aliases.
HTTP_TOOLS: dict[str, dict[str, Any]] = {
    name: {
        "description": meta["description"],
        "inputSchema": meta["inputSchema"],
        "handler": meta["handler"],
    }
    for name, meta in kb.TOOLS.items()
    if name != "knowledge_intake"  # keep read-focused for ChatGPT connector default
}

# Re-add intake optionally (still available for authenticated callers).
if "knowledge_intake" in kb.TOOLS:
    HTTP_TOOLS["knowledge_intake"] = {
        "description": kb.TOOLS["knowledge_intake"]["description"],
        "inputSchema": kb.TOOLS["knowledge_intake"]["inputSchema"],
        "handler": kb.TOOLS["knowledge_intake"]["handler"],
    }

HTTP_TOOLS["search"] = {
    "description": (
        "Search Edgar's Knowledge (company-knowledge compatible). "
        "Returns result ids/titles/urls; use fetch for full text. "
        "Maps to knowledge-api /search — not a separate KB."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language search query"}
        },
        "required": ["query"],
    },
    "handler": tool_search,
}

HTTP_TOOLS["fetch"] = {
    "description": (
        "Fetch full document content by id from Edgar's Knowledge "
        "(company-knowledge compatible). Use after search."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Document id from search results"}
        },
        "required": ["id"],
    },
    "handler": tool_fetch,
}


def handle_initialize(params: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": (
            "Edgar's Knowledge is the logical shared knowledge layer over "
            "knowledge-api.edgars.tools. Prefer search/fetch (or knowledge_search/"
            "knowledge_get). Hits are evidence/locators — live-verify Current claims."
        ),
    }


def handle_tools_list(_params: dict[str, Any] | None) -> dict[str, Any]:
    tools = [
        {
            "name": name,
            "description": meta["description"],
            "inputSchema": meta["inputSchema"],
        }
        for name, meta in HTTP_TOOLS.items()
    ]
    return {"tools": tools}


def handle_tools_call(params: dict[str, Any] | None) -> dict[str, Any]:
    params = params or {}
    name = params.get("name") or ""
    args = params.get("arguments") or {}
    meta = HTTP_TOOLS.get(name)
    if not meta:
        return kb.error_content(f"Tool not found: {name}")
    try:
        return meta["handler"](args if isinstance(args, dict) else {})
    except Exception as e:  # noqa: BLE001
        log(f"tool error {name}: {e}")
        return kb.error_content(f"{type(e).__name__}: {e}")


def dispatch_rpc(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. Returns response dict, or None for notifications."""
    method = msg.get("method") or ""
    req_id = msg.get("id", None)
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

    # Notifications (no id)
    if "id" not in msg:
        log(f"notification: {method}")
        return None

    if method == "initialize":
        result = handle_initialize(params)
    elif method == "tools/list":
        result = handle_tools_list(params)
    elif method == "tools/call":
        result = handle_tools_call(params)
    elif method == "ping":
        result = {}
    elif method == "notifications/initialized":
        return None
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    return {"jsonrpc": "2.0", "id": req_id, "result": result}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"{SERVER_NAME}/{SERVER_VERSION}"

    def log_message(self, fmt: str, *args: Any) -> None:
        log(f"{self.address_string()} {fmt % args}")

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept, Mcp-Session-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "WWW-Authenticate, Mcp-Session-Id")

    def _send_json(self, code: int, body: Any, extra_headers: dict[str, str] | None = None) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(self, code: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        raw = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _unauthorized(self) -> None:
        self._send_json(
            401,
            {
                "error": "unauthorized",
                "message": "Bearer token required for MCP endpoint",
            },
            extra_headers={"WWW-Authenticate": www_authenticate_value()},
        )

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        # Normalize well-known (keep trailing path semantics)
        raw_path = urlparse(self.path).path

        if raw_path in ("/health", "/health/"):
            h_status, health = kb.http_json("GET", "/health")
            self._send_json(
                200 if h_status == 200 else 503,
                {
                    "ok": h_status == 200,
                    "service": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "public_base_url": PUBLIC_BASE_URL,
                    "upstream": kb.BASE,
                    "upstream_http": h_status,
                    "upstream_health": health,
                },
            )
            return

        if raw_path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/",
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-protected-resource/mcp/",
        ):
            self._send_json(200, resource_metadata_document())
            return

        if raw_path in (MCP_PATH, MCP_PATH + "/"):
            if not is_authorized(self.headers.get("Authorization")):
                self._unauthorized()
                return
            # Streamable HTTP: GET may open SSE; we advertise no standalone stream.
            self.send_response(405)
            self.send_header("Allow", "POST, OPTIONS")
            self.send_header("Content-Type", "application/json")
            self._cors()
            body = b'{"error":"method_not_allowed","message":"Use POST for MCP JSON-RPC"}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if raw_path in ("/", "/index.html"):
            self._send_json(
                200,
                {
                    "service": SERVER_NAME,
                    "mcp": public_url(MCP_PATH),
                    "health": public_url("/health"),
                    "oauth_protected_resource": public_url(
                        "/.well-known/oauth-protected-resource/mcp"
                    ),
                },
            )
            return

        self._send_json(404, {"error": "not_found", "path": raw_path})

    def do_POST(self) -> None:  # noqa: N802
        raw_path = urlparse(self.path).path
        if raw_path not in (MCP_PATH, MCP_PATH + "/"):
            self._send_json(404, {"error": "not_found", "path": raw_path})
            return

        if not is_authorized(self.headers.get("Authorization")):
            self._unauthorized()
            return

        raw = self._read_body()
        try:
            payload = json.loads(raw.decode("utf-8") if raw else "{}")
        except json.JSONDecodeError as e:
            self._send_json(
                400,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}},
            )
            return

        accept = (self.headers.get("Accept") or "").lower()
        prefer_sse = "text/event-stream" in accept and "application/json" not in accept

        def process_one(msg: dict[str, Any]) -> dict[str, Any] | None:
            return dispatch_rpc(msg)

        if isinstance(payload, list):
            responses = [r for r in (process_one(m) for m in payload if isinstance(m, dict)) if r]
            if prefer_sse:
                self._send_sse(responses)
            else:
                # Spec allows batch; ChatGPT typically sends single objects.
                self._send_json(200, responses if responses else [])
            return

        if not isinstance(payload, dict):
            self._send_json(
                400,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                },
            )
            return

        # Notification-only → 202 Accepted
        if "id" not in payload:
            process_one(payload)
            self.send_response(202)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        response = process_one(payload)
        if response is None:
            self.send_response(202)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if prefer_sse:
            self._send_sse([response])
        else:
            self._send_json(200, response)

    def _send_sse(self, messages: list[dict[str, Any]]) -> None:
        parts = []
        for msg in messages:
            parts.append(f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n")
        raw = "".join(parts).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    log(
        f"listening http://{HOST}:{PORT} mcp={public_url(MCP_PATH)} "
        f"upstream={kb.BASE} auth={AUTH_SERVER} "
        f"token_bypass={'set' if MCP_API_TOKEN else 'unset'}"
    )
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("shutting down")
        httpd.shutdown()


if __name__ == "__main__":
    main()
