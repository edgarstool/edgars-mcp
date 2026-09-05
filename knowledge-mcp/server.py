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

# PART1_END - will continue in next push if needed
