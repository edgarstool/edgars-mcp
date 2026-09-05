#!/usr/bin/env python3
"""Edgar's Knowledge MCP — thin adapter over knowledge-api.edgars.tools.

Not a KB. Not a RAG stack. Wraps the existing Knowledge API runtime only.
Transport: MCP JSON-RPC over stdio (Grok AddMcpServer command mode).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get("EDGARS_KNOWLEDGE_API", "https://knowledge-api.edgars.tools").rstrip("/")
TIMEOUT = float(os.environ.get("EDGARS_KNOWLEDGE_TIMEOUT", "30"))
SERVER_NAME = "edgars-knowledge"
SERVER_VERSION = "0.1.0"
PROTOCOL = "2025-11-25"

# Canonical internal roles (from CORE/EDGARS-KNOWLEDGE.md) — not live discovery.
CANONICAL_ROLES = [
    {
        "role": "Agent-KB",
        "authority": "stable cross-agent rules / contracts",
        "mutable_current": False,
        "note": "Stable authority/source. Not a chat transcript.",
    },
    {
        "role": "Obsidian",
        "authority": "human long-form knowledge",
        "mutable_current": False,
        "note": "Human vault; not agent SSoT.",
    },
    {
        "role": "Honcho",
        "authority": "cognitive / cross-session memory",
        "mutable_current": True,
        "note": "Memory hit ≠ Current truth; verify when execution-relevant.",
    },
    {
        "role": "QMD",
        "authority": "retrieval / locator",
        "mutable_current": False,
        "note": "Locator only. Follow provenance to source.",
    },
    {
        "role": "Hermes-Wiki",
        "authority": "derived map",
        "mutable_current": False,
        "note": "Derived projection; revalidate runtime facts.",
    },
    {
        "role": "project SSoT / Worklog / Linear / repo / provider / live",
        "authority": "Current world",
        "mutable_current": True,
        "note": "Live verify required for Current claims.",
    },
    {
        "role": "old Cloud KB / START HERE",
        "authority": "historical provenance / pointers",
        "mutable_current": False,
        "note": "Historical only; not Current SSoT.",
    },
]


def log(msg: str) -> None:
    print(f"[edgars-knowledge] {msg}", file=sys.stderr, flush=True)


def send(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def send_result(req_id: Any, result: Any) -> None:
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


def send_error(req_id: Any, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def http_json(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    url = f"{BASE}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"{SERVER_NAME}/{SERVER_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return resp.status, {"raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw) if raw else {"error": str(e)}
        except json.JSONDecodeError:
            return e.code, {"error": str(e), "raw": raw}
    except Exception as e:  # noqa: BLE001 — surface to MCP caller
        return 0, {"error": type(e).__name__, "message": str(e)}


def text_content(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def error_content(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def normalize_search(query: str, status: int, data: Any) -> dict[str, Any]:
    """Shape API search into MCP-friendly hits with provenance."""
    out: dict[str, Any] = {
        "query": query,
        "api": BASE,
        "http_status": status,
        "semantics": (
            "Edgar's Knowledge is the logical shared knowledge layer. "
            "Hits are evidence/locators, not automatically Current truth. "
            "Live-verify mutable Current claims."
        ),
        "hits": [],
        "backends": {},
    }
    if not isinstance(data, dict):
        out["raw"] = data
        return out

    honcho = data.get("honcho") or {}
    qmd = data.get("qmd") or {}
    out["backends"]["honcho"] = {
        "status": honcho.get("status"),
        "hit_count": len(honcho.get("hits") or []),
    }
    out["backends"]["qmd"] = {
        "source": qmd.get("source"),
        "hit_count": len(qmd.get("hits") or []),
    }

    for h in honcho.get("hits") or []:
        content = h.get("content") or ""
        out["hits"].append(
            {
                "backend": "honcho",
                "authority_role": "Honcho (cognitive / cross-session memory)",
                "excerpt": content[:1200],
                "source": "honcho",
                "provenance": {
                    "id": h.get("id"),
                    "peer_id": h.get("peer_id"),
                    "session_id": h.get("session_id"),
                    "workspace_id": h.get("workspace_id"),
                    "created_at": h.get("created_at"),
                    "metadata": h.get("metadata"),
                },
                "freshness": h.get("created_at"),
                "current_vs_historical": "memory — verify before treating as Current",
            }
        )

    for h in qmd.get("hits") or []:
        raw = h.get("raw") if isinstance(h, dict) else str(h)
        raw_s = str(raw or "")
        pointer = None
        for line in raw_s.splitlines():
            if line.startswith("qmd://"):
                pointer = line.split()[0]
                break
        out["hits"].append(
            {
                "backend": "qmd",
                "authority_role": "QMD (retrieval / locator)",
                "excerpt": raw_s[:1200],
                "source": qmd.get("source") or "qmd",
                "provenance": {"pointer": pointer, "raw_head": raw_s[:200]},
                "freshness": None,
                "current_vs_historical": "locator — follow source and live-verify if Current",
            }
        )
    return out


def tool_knowledge_search(args: dict[str, Any]) -> dict[str, Any]:
    query = (args.get("query") or "").strip()
    if not query:
        return error_content("query is required")
    status, data = http_json("POST", "/search", {"query": query})
    if status != 200:
        return error_content(f"search failed HTTP {status}: {json.dumps(data, ensure_ascii=False)}")
    return text_content(normalize_search(query, status, data))


def tool_knowledge_get(args: dict[str, Any]) -> dict[str, Any]:
    """Larger context for a known pointer/query via search + optional focus."""
    pointer = (args.get("pointer") or args.get("source") or args.get("query") or "").strip()
    if not pointer:
        return error_content("pointer, source, or query is required")
    # Prefer searching the pointer/path so QMD/Honcho can expand context.
    status, data = http_json("POST", "/search", {"query": pointer})
    if status != 200:
        return error_content(f"get/search failed HTTP {status}: {json.dumps(data, ensure_ascii=False)}")
    shaped = normalize_search(pointer, status, data)
    shaped["mode"] = "knowledge_get"
    shaped["note"] = (
        "No dedicated /get on Knowledge API; this expands via /search. "
        "For Agent-KB file bodies use GitHub; for live Current use the live system."
    )
    return text_content(shaped)


def tool_knowledge_status(_args: dict[str, Any]) -> dict[str, Any]:
    h_status, health = http_json("GET", "/health")
    # Live probe backends lightly via a bounded search
    s_status, sdata = http_json("POST", "/search", {"query": "Edgar's Knowledge status probe"})
    backends: dict[str, Any] = {"knowledge_api": {"http_status": h_status, "body": health}}
    if isinstance(sdata, dict):
        backends["honcho"] = {
            "reachable": s_status == 200,
            "search_http": s_status,
            "hit_count": len((sdata.get("honcho") or {}).get("hits") or []),
            "status": (sdata.get("honcho") or {}).get("status"),
        }
        backends["qmd"] = {
            "reachable": s_status == 200 and bool((sdata.get("qmd") or {}).get("hits") is not None),
            "search_http": s_status,
            "hit_count": len((sdata.get("qmd") or {}).get("hits") or []),
            "source": (sdata.get("qmd") or {}).get("source"),
        }
    else:
        backends["honcho"] = {"reachable": False, "error": sdata}
        backends["qmd"] = {"reachable": False, "error": sdata}

    degraded = []
    if h_status != 200:
        degraded.append("knowledge_api")
    if not backends.get("honcho", {}).get("reachable"):
        degraded.append("honcho")
    if not backends.get("qmd", {}).get("reachable"):
        degraded.append("qmd")

    return text_content(
        {
            "knowledge_api": BASE,
            "live_check": True,
            "ok": h_status == 200 and not degraded,
            "health_http": h_status,
            "health": health,
            "backends": backends,
            "degraded": degraded,
            "freshness": "live probe at call time",
            "historical_note": (
                "Do not answer status solely from the 2026-09-04 canonicalization receipt; "
                "this tool always hits live /health + /search."
            ),
        }
    )


def tool_knowledge_sources(_args: dict[str, Any]) -> dict[str, Any]:
    h_status, health = http_json("GET", "/health")
    return text_content(
        {
            "entry": "Edgar's Knowledge (logical shared layer — not a database)",
            "runtime": BASE,
            "runtime_health_http": h_status,
            "runtime_service": (health or {}).get("service") if isinstance(health, dict) else None,
            "reachable_backends_via_search": ["honcho", "qmd"],
            "internal_roles": CANONICAL_ROLES,
            "note": (
                "Roles are semantic contracts from Agent-KB CORE/EDGARS-KNOWLEDGE.md. "
                "Retrieval mechanisms (BM25/vector/QMD) are not separate truth stores."
            ),
        }
    )


def tool_knowledge_intake(args: dict[str, Any]) -> dict[str, Any]:
    """Optional bounded write through existing /intake. Requires content field."""
    content = args.get("content")
    if not content:
        return error_content(
            "intake requires content. Optional: event_id, summary, kind, source, paths. "
            "Do not use for secrets."
        )
    body = {
        "content": content,
        "event_id": args.get("event_id") or "GROK-FORGE-KNOWLEDGE-INTAKE",
        "summary": args.get("summary") or "Grok Forge bounded knowledge intake",
        "kind": args.get("kind") or "receipt",
        "source": args.get("source") or "grok-forge-mcp",
    }
    if args.get("paths"):
        body["paths"] = args["paths"]
    status, data = http_json("POST", "/intake", body)
    ok = status in (200, 201) and (not isinstance(data, dict) or data.get("ok") is not False)
    payload = {"http_status": status, "response": data, "sent": {k: v for k, v in body.items() if k != "content"}, "content_len": len(str(content))}
    if not ok:
        return error_content(json.dumps(payload, ensure_ascii=False))
    return text_content(payload)


TOOLS = {
    "knowledge_search": {
        "description": (
            "Query Edgar's Knowledge (logical shared layer via knowledge-api). "
            "Returns excerpts with source, authority role, provenance. "
            "Hits are evidence/locators — live-verify Current claims."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
        "handler": tool_knowledge_search,
    },
    "knowledge_get": {
        "description": (
            "Retrieve larger relevant context for a known pointer, qmd:// URI, path, or query "
            "by expanding through the Knowledge API search fan-out."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pointer": {"type": "string"},
                "source": {"type": "string"},
                "query": {"type": "string"},
            },
        },
        "handler": tool_knowledge_get,
    },
    "knowledge_status": {
        "description": (
            "Live status of knowledge-api.edgars.tools and reachable backends (Honcho, QMD). "
            "Always probes live; do not substitute historical receipts."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_knowledge_status,
    },
    "knowledge_sources": {
        "description": (
            "Show Edgar's Knowledge entry semantics and internal roles "
            "(Agent-KB, Obsidian, Honcho, QMD, Hermes-Wiki, Current world, historical Cloud KB)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_knowledge_sources,
    },
    "knowledge_intake": {
        "description": (
            "Optional: write a bounded knowledge event/receipt through existing /intake. "
            "Requires content. Not for secrets. Prefer retrieval tools first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "event_id": {"type": "string"},
                "summary": {"type": "string"},
                "kind": {"type": "string"},
                "source": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["content"],
        },
        "handler": tool_knowledge_intake,
    },
}


def handle_initialize(msg: dict[str, Any]) -> None:
    send_result(
        msg["id"],
        {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    )


def handle_tools_list(msg: dict[str, Any]) -> None:
    tools = [
        {
            "name": name,
            "description": meta["description"],
            "inputSchema": meta["inputSchema"],
        }
        for name, meta in TOOLS.items()
    ]
    send_result(msg["id"], {"tools": tools})


def handle_tools_call(msg: dict[str, Any]) -> None:
    params = msg.get("params") or {}
    name = params.get("name") or ""
    args = params.get("arguments") or {}
    meta = TOOLS.get(name)
    if not meta:
        send_error(msg["id"], -32601, f"Tool not found: {name}")
        return
    try:
        result = meta["handler"](args if isinstance(args, dict) else {})
        send_result(msg["id"], result)
    except Exception as e:  # noqa: BLE001
        log(f"tool error {name}: {e}")
        send_result(msg["id"], error_content(f"{type(e).__name__}: {e}"))


def handle_request(msg: dict[str, Any]) -> None:
    method = msg.get("method") or ""
    if method == "initialize":
        handle_initialize(msg)
    elif method == "tools/list":
        handle_tools_list(msg)
    elif method == "tools/call":
        handle_tools_call(msg)
    elif method == "ping":
        send_result(msg["id"], {})
    else:
        send_error(msg.get("id"), -32601, f"Method not found: {method}")


def main() -> None:
    log(f"started base={BASE}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            log(f"parse error: {e}")
            continue
        if "id" in msg:
            handle_request(msg)
        else:
            log(f"notification: {msg.get('method')}")


if __name__ == "__main__":
    main()
