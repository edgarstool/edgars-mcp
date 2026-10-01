#!/usr/bin/env python3
"""Edgar's Knowledge MCP — Round 2 adapter over knowledge-api.edgars.tools.

Not a KB. Not a RAG stack. Wraps the existing Knowledge API runtime only.
Transport: MCP JSON-RPC over stdio (Grok AddMcpServer command mode).

Round 2 relevance/honesty retained.
Gov-write: intake create with before/after read-back receipt;
knowledge_update = true-update or structured UNSUPPORTED (no silent second object).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

# Windows: keep stdin/stdout as binary-backed UTF-8 text streams.
# Without this, Windows may translate \n→\r\n or insert BOM and break JSON-RPC framing.
if sys.platform == "win32":
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    sys.stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", newline="\n", closefd=False)
    sys.stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)

BASE = os.environ.get("EDGARS_KNOWLEDGE_API", "https://knowledge-api.edgars.tools").rstrip("/")


def _timeout_seconds(default: float = 30.0) -> float:
    raw = os.environ.get("EDGARS_KNOWLEDGE_TIMEOUT", str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


TIMEOUT = _timeout_seconds()
SERVER_NAME = "edgars-knowledge"
SERVER_VERSION = "0.2.2-gov-write"
PROTOCOL = "2025-11-25"

AGENT_KB_GITHUB = "https://github.com/edgarstool/Agent-KB"
AGENT_KB_POINTER_NOTE = (
    "Agent-KB file bodies are not served by knowledge-api /search as full documents. "
    f"Use GitHub: {AGENT_KB_GITHUB} (or follow QMD locators to source)."
)

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

# Noise / canary patterns (adapter-side ranking)
_RE_MODIFY_INTENT = re.compile(
    r"\bMODIFY(?:IED)?\b|\bREWRITE\b|\bPATCH\s+EXISTING\b|\bUPDATE\s+IN\s*PLACE\b",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had",
        "her", "was", "one", "our", "out", "has", "his", "how", "its", "may", "new",
        "now", "old", "see", "way", "who", "did", "get", "let", "put", "say", "she",
        "too", "use", "dad", "mom", "from", "with", "this", "that", "what", "when",
        "where", "which", "while", "about", "into", "over", "after", "before",
        "stuff", "things", "thing", "misc", "data", "info", "hello", "test", "tests",
        "please", "just", "some", "more", "than", "then", "them", "they", "have",
        "been", "were", "will", "your", "does", "doing",
    }
)
_WEAK_RELEVANCE_TOKENS = frozenset(
    {
        "round1", "round2", "canary", "event", "events", "knowledge", "edgar",
        "edgars", "receipt", "probe", "status", "memory", "honcho", "qmd",
        "pointer", "source", "query", "content", "summary", "note", "notes",
    }
)
_VAGUE_SINGLE = frozenset(
    {"stuff", "things", "thing", "misc", "data", "info", "hello", "test", "asdf", "foo", "bar", "baz"}
)

_RE_ACK_ONLY = re.compile(r"^(ACK|NO_REPLY)\s*$", re.IGNORECASE | re.MULTILINE)
_RE_ID_CHECK = re.compile(r"id-check-", re.IGNORECASE)
_RE_DURABILITY = re.compile(
    r"(durability[\s_-]?canary|e2e[\s_-]?canary|canary[\s_-]?ack|honcho[\s_-]?canary)",
    re.IGNORECASE,
)
_RE_QMD_EMPTY = re.compile(r"^\s*No results found\.?\s*$", re.IGNORECASE | re.MULTILINE)
_RE_EVENT_ID = re.compile(r"\b([A-Z][A-Z0-9]+(?:-[A-Z0-9]+){2,})\b")
_RE_AGENT_KB_CLAIM = re.compile(
    r"(agent[\s_-]?kb|/master\b|CORE/|PLAYBOOKS/|ADAPTERS/|"
    r"edgarstool/Agent-KB|qmd://agent-kb)",
    re.IGNORECASE,
)
_RE_CONTABO = re.compile(r"contabo", re.IGNORECASE)
_MIN_SUBSTANTIVE_LEN = 40


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


# ---------------------------------------------------------------------------
# Structured MCP tool results
# ---------------------------------------------------------------------------


def text_content(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": False}
    if isinstance(payload, dict):
        out["structuredContent"] = payload
    return out


def error_content(msg: str) -> dict[str, Any]:
    """Legacy plain-text error (prefer structured_error)."""
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def structured_error(
    code: str,
    message: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Common failure shape: ok=false + error.code + isError=true."""
    payload: dict[str, Any] = {
        "ok": False,
        "error": {"code": code, "message": message},
    }
    if extra:
        payload.update(extra)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": True,
    }


def structured_ok(payload: dict[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    body.setdefault("ok", True)
    text = json.dumps(body, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": body,
        "isError": False,
    }


# ---------------------------------------------------------------------------
# Ranking / noise helpers (adapter-side; no new KB)
# ---------------------------------------------------------------------------


def _excerpt_of(hit: dict[str, Any]) -> str:
    return str(hit.get("excerpt") or hit.get("content") or "")


def is_qmd_empty_locator(excerpt: str) -> bool:
    s = (excerpt or "").strip()
    if not s:
        return True
    if _RE_QMD_EMPTY.search(s) and "qmd://" not in s.lower():
        return True
    # Whole blob is only "No results found."
    if _RE_QMD_EMPTY.fullmatch(s):
        return True
    return False


def is_noise_excerpt(excerpt: str) -> bool:
    s = (excerpt or "").strip()
    if not s:
        return True
    if _RE_ACK_ONLY.fullmatch(s) or _RE_ACK_ONLY.search(s) and len(s) < 24:
        # Pure ACK / NO_REPLY lines
        if s.upper() in ("ACK", "NO_REPLY") or _RE_ACK_ONLY.fullmatch(s):
            return True
    if s.upper() in ("ACK", "NO_REPLY"):
        return True
    if _RE_ID_CHECK.search(s):
        return True
    if _RE_DURABILITY.search(s):
        return True
    if is_qmd_empty_locator(s):
        return True
    return False


def is_substantive_hit(hit: dict[str, Any]) -> bool:
    excerpt = _excerpt_of(hit).strip()
    if is_noise_excerpt(excerpt):
        return False
    if is_qmd_empty_locator(excerpt):
        return False
    # Locator with a real qmd:// pointer counts even if short
    prov = hit.get("provenance") or {}
    pointer = prov.get("pointer") if isinstance(prov, dict) else None
    if isinstance(pointer, str) and pointer.startswith("qmd://") and "No results found" not in excerpt:
        return True
    return len(excerpt) >= _MIN_SUBSTANTIVE_LEN


def looks_like_agent_kb_pointer(pointer: str) -> bool:
    p = (pointer or "").strip().lower()
    if not p:
        return False
    if p.startswith("qmd://agent-kb"):
        return True
    if "agent-kb" in p or "agent_kb" in p:
        return True
    if "/core/" in p or p.endswith(".md") and ("edgars-knowledge" in p or "promptos" in p):
        # path-like Agent-KB docs
        if "core/" in p or "playbooks/" in p or "adapters/" in p:
            return True
    return bool(_RE_AGENT_KB_CLAIM.search(pointer or ""))



def query_tokens(query: str) -> list[str]:
    tokens = [t for t in re.split(r"[\s/:_\-.]+", (query or "").lower()) if len(t) >= 3]
    return [t for t in tokens if t not in _STOPWORDS]


def is_vague_or_no_signal_query(query: str) -> bool:
    """Vague / stopword-only / single generic token → honest empty search."""
    q = (query or "").strip()
    if not q:
        return True
    tokens = query_tokens(q)
    if not tokens:
        return True
    if len(tokens) == 1 and tokens[0] in _VAGUE_SINGLE:
        return True
    # Very short non-distinctive
    if len(tokens) == 1 and len(tokens[0]) <= 4:
        return True
    return False


def looks_like_qmd_pointer(pointer: str) -> bool:
    return (pointer or "").strip().lower().startswith("qmd://")


def _hit_text_blob(hit: dict[str, Any]) -> str:
    parts = [_excerpt_of(hit)]
    prov = hit.get("provenance") or {}
    if isinstance(prov, dict):
        for k in ("pointer", "id", "path", "uri"):
            v = prov.get(k)
            if v:
                parts.append(str(v))
        meta = prov.get("metadata") or {}
        if isinstance(meta, dict):
            for k in ("event_id", "kc_event_id", "pointer"):
                if meta.get(k):
                    parts.append(str(meta[k]))
    if hit.get("backend"):
        parts.append(str(hit.get("backend")))
    return " ".join(parts).lower()


def relevance_token_hits(hit: dict[str, Any], query: str) -> tuple[int, int, list[str]]:
    """Return (strong_hits, strong_total, strong_tokens)."""
    blob = _hit_text_blob(hit)
    tokens = query_tokens(query)
    strong = [t for t in tokens if t not in _WEAK_RELEVANCE_TOKENS]
    if not strong:
        strong = list(tokens)
    n = sum(1 for t in strong if t in blob)
    return n, len(strong), strong


def is_relevant_hit(hit: dict[str, Any], query: str, *, mode: str = "search") -> bool:
    """Require real query/pointer overlap — length-only Honcho soft-match is not enough."""
    q = (query or "").strip()
    if not q:
        return False
    blob = _hit_text_blob(hit)
    q_lower = q.lower()
    if q_lower in blob:
        return True
    # Exact event_id style
    if len(q) >= 8 and q_lower.replace("-", "") in blob.replace("-", ""):
        # still require at least one strong token if many hyphens
        pass
    n, total, strong = relevance_token_hits(hit, q)
    if total == 0:
        return False
    if mode == "get" or looks_like_qmd_pointer(q) or ("-" in q and total >= 3):
        # Pointer-like: majority of strong tokens (min 2 when available)
        need = 1 if total == 1 else max(2, (total + 1) // 2)
        return n >= need
    # Search: at least one strong token; for longer queries prefer 2+
    if total >= 4:
        return n >= 2
    return n >= 1


def hit_matches_qmd_pointer(hit: dict[str, Any], pointer: str) -> bool:
    p = (pointer or "").strip().lower()
    if not p.startswith("qmd://"):
        return False
    blob = _hit_text_blob(hit)
    if p in blob:
        return True
    # path fragment without scheme
    frag = p[len("qmd://") :]
    if frag and frag in blob:
        return True
    # basename-ish
    base = frag.split("/")[-1].split(":")[0]
    if base and len(base) >= 6 and base.lower() in blob:
        # still require backend qmd when only basename matches
        return (hit.get("backend") or "").lower() == "qmd"
    return False


def score_hit(hit: dict[str, Any], query: str) -> float:
    """Higher = better. Noise gets large negative score."""
    excerpt = _excerpt_of(hit)
    q = (query or "").strip()
    q_lower = q.lower()
    score = 0.0

    if is_noise_excerpt(excerpt):
        score -= 1000.0
        return score

    if is_qmd_empty_locator(excerpt):
        score -= 900.0
        return score

    excerpt_lower = excerpt.lower()
    prov = hit.get("provenance") or {}
    event_id = None
    if isinstance(prov, dict):
        meta = prov.get("metadata") or {}
        if isinstance(meta, dict):
            event_id = meta.get("event_id") or meta.get("kc_event_id")
        event_id = event_id or prov.get("id")
        pointer = prov.get("pointer")
    else:
        pointer = None

    # Exact event_id / query substring
    if q and q in excerpt:
        score += 80.0
    if q_lower and q_lower in excerpt_lower:
        score += 40.0
    if event_id and q and str(event_id) == q:
        score += 120.0
    elif event_id and q and str(event_id).lower() in q_lower:
        score += 60.0

    # Prefer query tokens present
    tokens = [t for t in re.split(r"[\s/:_]+", q_lower) if len(t) >= 3]
    if tokens:
        hits_tok = sum(1 for t in tokens if t in excerpt_lower)
        score += 8.0 * hits_tok

    # Longer substantive content
    score += min(len(excerpt), 2000) / 100.0

    # Prefer QMD locators with real pointers over empty
    if hit.get("backend") == "qmd":
        if isinstance(pointer, str) and pointer.startswith("qmd://"):
            score += 25.0
        else:
            score -= 5.0

    # Exact-looking IDs in query matching excerpt
    for m in _RE_EVENT_ID.finditer(q):
        eid = m.group(1)
        if eid in excerpt:
            score += 50.0

    return score


def rank_and_filter_hits(
    hits: list[dict[str, Any]],
    query: str,
    *,
    drop_noise: bool = True,
    keep_top_noise_if_empty: bool = False,
    require_relevance: bool = True,
) -> list[dict[str, Any]]:
    if require_relevance and is_vague_or_no_signal_query(query):
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for h in hits:
        s = score_hit(h, query)
        hh = dict(h)
        hh["_score"] = round(s, 3)
        hh["_noise"] = is_noise_excerpt(_excerpt_of(h)) or is_qmd_empty_locator(_excerpt_of(h))
        hh["_relevant"] = is_relevant_hit(hh, query, mode="search")
        scored.append((s, hh))
    scored.sort(key=lambda x: x[0], reverse=True)

    if drop_noise:
        kept = [
            h
            for s, h in scored
            if s > -500 and not h.get("_noise") and (not require_relevance or h.get("_relevant"))
        ]
        if kept:
            return kept
        if keep_top_noise_if_empty:
            return [h for _, h in scored[:3]]
        return []
    return [h for _, h in scored]


def apply_current_vs_historical(hit: dict[str, Any], query: str) -> dict[str, Any]:
    """Shape Contabo / Current claims so memory is never presented as live health."""
    out = dict(hit)
    excerpt = _excerpt_of(hit)
    q = query or ""
    if _RE_CONTABO.search(q) or _RE_CONTABO.search(excerpt):
        backend = (hit.get("backend") or "").lower()
        if backend == "honcho":
            out["current_vs_historical"] = (
                "historical/memory evidence about Contabo — NOT live health. "
                "Current Contabo health requires live verify (provider/status), "
                "not Knowledge memory hits."
            )
            out["live_verify_required"] = True
        elif backend == "qmd":
            out["current_vs_historical"] = (
                "architecture/historical locator (Contabo) — follow source; "
                "Current health requires live verify — Knowledge is locator only."
            )
            out["live_verify_required"] = True
        else:
            out["current_vs_historical"] = (
                "Contabo-related evidence — live-verify before treating as Current health."
            )
            out["live_verify_required"] = True
    return out


def contabo_banner(query: str) -> dict[str, Any] | None:
    if not _RE_CONTABO.search(query or ""):
        return None
    return {
        "banner": "LIVE_VERIFY",
        "message": (
            "Contabo Current health is NOT answered by Knowledge memory/locators alone. "
            "Treat hits as historical/architecture evidence; live-verify provider/status "
            "for Current claims. Never present ACK/memory as health."
        ),
    }


# ---------------------------------------------------------------------------
# Normalize search (+ ranking)
# ---------------------------------------------------------------------------


def normalize_search(
    query: str,
    status: int,
    data: Any,
    *,
    apply_ranking: bool = True,
) -> dict[str, Any]:
    """Shape API search into MCP-friendly hits with provenance + ranking."""
    out: dict[str, Any] = {
        "query": query,
        "api": BASE,
        "http_status": status,
        "ok": True,
        "semantics": (
            "Edgar's Knowledge is the logical shared knowledge layer. "
            "Hits are evidence/locators, not automatically Current truth. "
            "Live-verify mutable Current claims."
        ),
        "hits": [],
        "backends": {},
        "ranking": {"applied": apply_ranking, "noise_filtered": False},
    }
    banner = contabo_banner(query)
    if banner:
        out["live_verify"] = banner

    if not isinstance(data, dict):
        out["raw"] = data
        return out

    honcho = data.get("honcho") or {}
    qmd = data.get("qmd") or {}
    raw_hits: list[dict[str, Any]] = []

    honcho_hits = honcho.get("hits") or []
    qmd_hits = qmd.get("hits") or []

    out["backends"]["honcho"] = {
        "status": honcho.get("status"),
        "hit_count_raw": len(honcho_hits),
    }
    out["backends"]["qmd"] = {
        "source": qmd.get("source"),
        "hit_count_raw": len(qmd_hits),
    }

    for h in honcho_hits:
        content = h.get("content") or ""
        raw_hits.append(
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

    for h in qmd_hits:
        raw = h.get("raw") if isinstance(h, dict) else str(h)
        raw_s = str(raw or "")
        pointer = None
        for line in raw_s.splitlines():
            if line.startswith("qmd://"):
                pointer = line.split()[0]
                break
        # Do not count empty QMD "No results found." as a successful locator
        empty = is_qmd_empty_locator(raw_s)
        hit = {
            "backend": "qmd",
            "authority_role": "QMD (retrieval / locator)",
            "excerpt": raw_s[:1200],
            "source": qmd.get("source") or "qmd",
            "provenance": {"pointer": pointer, "raw_head": raw_s[:200]},
            "freshness": None,
            "current_vs_historical": "locator — follow source and live-verify if Current",
            "_qmd_empty": empty,
        }
        raw_hits.append(hit)

    out["backends"]["honcho"]["hit_count"] = len(honcho_hits)
    # Count only non-empty QMD locators as successful locator hits
    qmd_real = [h for h in raw_hits if h.get("backend") == "qmd" and not h.get("_qmd_empty")]
    out["backends"]["qmd"]["hit_count"] = len(qmd_real)
    out["backends"]["qmd"]["empty_locator_count"] = sum(
        1 for h in raw_hits if h.get("backend") == "qmd" and h.get("_qmd_empty")
    )

    if apply_ranking:
        ranked = rank_and_filter_hits(raw_hits, query, drop_noise=True)
        out["ranking"]["noise_filtered"] = True
        out["ranking"]["raw_hit_count"] = len(raw_hits)
        out["ranking"]["kept_hit_count"] = len(ranked)
        shaped = [apply_current_vs_historical(h, query) for h in ranked]
        # Strip internal flags
        for h in shaped:
            h.pop("_qmd_empty", None)
            h.pop("_noise", None)
        out["hits"] = shaped
    else:
        for h in raw_hits:
            h.pop("_qmd_empty", None)
        out["hits"] = [apply_current_vs_historical(h, query) for h in raw_hits]

    return out


def best_substantive_body(
    hits: list[dict[str, Any]],
    query: str | None = None,
    *,
    mode: str = "get",
) -> dict[str, Any] | None:
    for h in hits:
        if not is_substantive_hit(h):
            continue
        if query is not None and not is_relevant_hit(h, query, mode=mode):
            continue
        return h
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def tool_knowledge_search(args: dict[str, Any]) -> dict[str, Any]:
    query = (args.get("query") or "").strip()
    if not query:
        return structured_error("INVALID_ARGS", "query is required")
    status, data = http_json("POST", "/search", {"query": query})
    if status == 0:
        return structured_error(
            "UPSTREAM_HTTP",
            f"upstream unreachable: {json.dumps(data, ensure_ascii=False)}",
            extra={"http_status": status, "detail": data},
        )
    if status != 200:
        return structured_error(
            "UPSTREAM_HTTP",
            f"search failed HTTP {status}",
            extra={"http_status": status, "detail": data},
        )
    shaped = normalize_search(query, status, data, apply_ranking=True)
    if not shaped.get("hits"):
        # Honest empty after noise filter — not fake success with canaries
        shaped["ok"] = True
        shaped["empty_after_ranking"] = True
        shaped["note"] = (
            "No substantive ranked hits after filtering ACK/id-check/durability/"
            "QMD-empty noise. This is not authoritative evidence."
        )
    return structured_ok(shaped)


def tool_knowledge_get(args: dict[str, Any]) -> dict[str, Any]:
    """Return body/evidence for a pointer or structured NOT_FOUND / NOT_SUPPORTED."""
    pointer = (args.get("pointer") or args.get("source") or args.get("query") or "").strip()
    if not pointer:
        return structured_error(
            "INVALID_ARGS",
            "pointer, source, or query is required",
        )

    agent_kb = looks_like_agent_kb_pointer(pointer)

    status, data = http_json("POST", "/search", {"query": pointer})
    if status == 0:
        return structured_error(
            "UPSTREAM_HTTP",
            f"upstream unreachable: {json.dumps(data, ensure_ascii=False)}",
            extra={"http_status": status, "pointer": pointer, "detail": data},
        )
    if status != 200:
        return structured_error(
            "UPSTREAM_HTTP",
            f"get/search failed HTTP {status}",
            extra={"http_status": status, "pointer": pointer, "detail": data},
        )

    shaped = normalize_search(pointer, status, data, apply_ranking=True)
    hits = shaped.get("hits") or []
    qmd_ptr = looks_like_qmd_pointer(pointer)

    if qmd_ptr:
        # Honest QMD miss: never soft-match unrelated Honcho as found:true
        qmd_candidates = [
            h
            for h in hits
            if (h.get("backend") or "").lower() == "qmd"
            and not is_qmd_empty_locator(_excerpt_of(h))
            and hit_matches_qmd_pointer(h, pointer)
        ]
        best = best_substantive_body(qmd_candidates, pointer, mode="get")
        if best is None:
            return structured_error(
                "NOT_SUPPORTED",
                (
                    f"QMD pointer {pointer!r} could not be hydrated via knowledge-api. "
                    "Empty/unrelated locators and Honcho soft-matches are not a successful get. "
                    "Follow the qmd:// URI at its source (or GitHub for Agent-KB)."
                ),
                extra={
                    "pointer": pointer,
                    "mode": "knowledge_get",
                    "found": False,
                    "backends": shaped.get("backends"),
                    "ranking": shaped.get("ranking"),
                    "github": AGENT_KB_GITHUB if agent_kb else None,
                    "note": "QMD is locator-only here; unhydratable URI → NOT_SUPPORTED, not soft success.",
                },
            )
    else:
        best = best_substantive_body(hits, pointer, mode="get")

    if best is None:
        if agent_kb:
            return structured_error(
                "NOT_SUPPORTED",
                (
                    "No substantive Agent-KB body hydrated via knowledge-api search. "
                    + AGENT_KB_POINTER_NOTE
                ),
                extra={
                    "pointer": pointer,
                    "github": AGENT_KB_GITHUB,
                    "mode": "knowledge_get",
                    "found": False,
                    "backends": shaped.get("backends"),
                    "ranking": shaped.get("ranking"),
                },
            )
        return structured_error(
            "NOT_FOUND",
            (
                f"No substantive body/locator for pointer={pointer!r}. "
                "Search returned only noise, empty QMD, or unrelated soft-matches."
            ),
            extra={
                "pointer": pointer,
                "mode": "knowledge_get",
                "found": False,
                "backends": shaped.get("backends"),
                "ranking": shaped.get("ranking"),
                "note": (
                    "No dedicated /get on Knowledge API; get expands via /search "
                    "then ranks/filters with relevance. Noise/soft-match-only is NOT_FOUND."
                ),
            },
        )

    body_excerpt = _excerpt_of(best)
    payload: dict[str, Any] = {
        "ok": True,
        "mode": "knowledge_get",
        "pointer": pointer,
        "found": True,
        "body": body_excerpt,
        "best_hit": {k: v for k, v in best.items() if not str(k).startswith("_")},
        "hits": hits[:5],
        "api": BASE,
        "http_status": status,
        "backends": shaped.get("backends"),
        "ranking": shaped.get("ranking"),
        "semantics": shaped.get("semantics"),
        "note": (
            "No dedicated /get on Knowledge API; expanded via ranked /search. "
            "Hits are evidence/locators — live-verify Current claims."
        ),
    }
    if shaped.get("live_verify"):
        payload["live_verify"] = shaped["live_verify"]
    if agent_kb:
        payload["agent_kb"] = {
            "hydrated_via_search": True,
            "github_fallback": AGENT_KB_GITHUB,
            "note": "Substantial excerpt found via search; for full file prefer GitHub.",
        }
    return structured_ok(payload)


def tool_knowledge_context_pack(args: dict[str, Any]) -> dict[str, Any]:
    """Minimal Context Pack for Prompt Forge / generic query (CORE §5-ish)."""
    query = (args.get("query") or "").strip()
    if not query:
        return structured_error("INVALID_ARGS", "query is required")

    status, data = http_json("POST", "/search", {"query": query})
    if status == 0:
        return structured_error(
            "UPSTREAM_HTTP",
            f"upstream unreachable: {json.dumps(data, ensure_ascii=False)}",
            extra={"http_status": status, "detail": data},
        )
    if status != 200:
        return structured_error(
            "UPSTREAM_HTTP",
            f"search failed HTTP {status}",
            extra={"http_status": status, "detail": data},
        )

    shaped = normalize_search(query, status, data, apply_ranking=True)
    evidence = (shaped.get("hits") or [])[:5]
    pointers: list[str] = []
    for h in evidence:
        prov = h.get("provenance") or {}
        if isinstance(prov, dict):
            p = prov.get("pointer")
            if isinstance(p, str) and p.startswith("qmd://"):
                pointers.append(p)
            eid = None
            meta = prov.get("metadata") or {}
            if isinstance(meta, dict):
                eid = meta.get("event_id")
            if eid:
                pointers.append(str(eid))
            elif prov.get("id"):
                pointers.append(str(prov["id"]))

    # Authority: prefer Agent-KB / QMD locators over Honcho memory when present
    authority = "Edgar's Knowledge (logical layer) — evidence/locators, not auto-Current"
    for h in evidence:
        role = h.get("authority_role") or ""
        if "QMD" in role or (h.get("backend") == "qmd"):
            authority = (
                "QMD locators + semantic roles (Agent-KB/CORE when pointed). "
                "Honcho memory is evidence only — live-verify Current."
            )
            break

    unknown: list[str] = []
    if not evidence:
        unknown.append("No substantive ranked evidence for this query")
    unknown.append("Full document bodies may require GitHub (Agent-KB) or live systems")

    conflicts: list[Any] = []  # optional; deferred full fixtures

    pack: dict[str, Any] = {
        "ok": True,
        "goal": f"Assemble minimal context pack for: {query}",
        "authority": authority,
        "evidence": evidence,
        "constraints": [
            "Hits are evidence/locators, not automatically Current truth",
            "Live-verify mutable Current claims",
            "Do not treat ACK/id-check/durability canaries as topical evidence",
        ],
        "unknown": unknown,
        "conflicts": conflicts,
        "pointers": list(dict.fromkeys(pointers))[:12],
        "freshness": {
            "source": "live knowledge-api /search at call time",
            "api": BASE,
            "http_status": status,
        },
        "semantics": shaped.get("semantics"),
        "backends": shaped.get("backends"),
        "ranking": shaped.get("ranking"),
        "query": query,
    }
    if shaped.get("live_verify"):
        pack["live_verify"] = shaped["live_verify"]
        pack["constraints"].append(shaped["live_verify"]["message"])

    return structured_ok(pack)


def _backend_health_qmd(qmd: Any, s_status: int) -> dict[str, Any]:
    """Gateway answers HTTP 200 even when QMD is down: inspect qmd.error and per-bucket error.

    2026-09-26..10-02 outage: a bucket like {"error": "...Connection refused"} was counted as a hit.
    """
    if not isinstance(qmd, dict):
        return {"reachable": False, "search_http": s_status, "error": "gateway response had no qmd section"}
    buckets = qmd.get("hits") or []
    bucket_errors = [str(b.get("error")) for b in buckets if isinstance(b, dict) and b.get("error")]
    error = qmd.get("error") or (bucket_errors[0] if bucket_errors else None)
    real = [b for b in buckets if not (isinstance(b, dict) and b.get("error"))]
    return {
        "reachable": s_status == 200 and error is None and qmd.get("hits") is not None,
        "search_http": s_status,
        "hit_count": len(real),
        "error_bucket_count": len(bucket_errors),
        "error": str(error) if error else None,
        "source": qmd.get("source"),
        "backend": qmd.get("backend"),
    }


def _backend_health_honcho(honcho: Any, s_status: int) -> dict[str, Any]:
    if not isinstance(honcho, dict):
        return {"reachable": False, "search_http": s_status, "error": "gateway response had no honcho section"}
    status = honcho.get("status")
    error = honcho.get("error")
    if error is None and isinstance(status, int) and status != 200:
        error = f"honcho HTTP {status}"
    return {
        "reachable": s_status == 200 and error is None,
        "search_http": s_status,
        "hit_count": len(honcho.get("hits") or []),
        "status": status,
        "error": str(error) if error else None,
    }


def tool_knowledge_status(_args: dict[str, Any]) -> dict[str, Any]:
    h_status, health = http_json("GET", "/health")
    s_status, sdata = http_json("POST", "/search", {"query": "Edgar's Knowledge status probe"})
    backends: dict[str, Any] = {"knowledge_api": {"http_status": h_status, "body": health}}
    if isinstance(sdata, dict):
        honcho = sdata.get("honcho")
        qmd = sdata.get("qmd")
        backends["honcho"] = _backend_health_honcho(honcho, s_status)
        backends["qmd"] = _backend_health_qmd(qmd, s_status)
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

    payload: dict[str, Any] = {
        "ok": h_status == 200 and not degraded,
        "knowledge_api": BASE,
        "live_check": True,
        "health_http": h_status,
        "health": health,
        "backends": backends,
        "degraded": degraded,
        "freshness": "live probe at call time",
        "historical_note": (
            "Do not answer status solely from the 2026-09-04 canonicalization receipt; "
            "this tool always hits live /health + /search. "
            "Memory hits are not health."
        ),
    }
    if degraded:
        return structured_error(
            "DEGRADED",
            f"One or more backends degraded: {', '.join(degraded)}",
            extra=payload,
        )
    return structured_ok(payload)


def tool_knowledge_sources(_args: dict[str, Any]) -> dict[str, Any]:
    h_status, health = http_json("GET", "/health")
    return structured_ok(
        {
            "entry": "Edgar's Knowledge (logical shared layer — not a database)",
            "runtime": BASE,
            "runtime_health_http": h_status,
            "runtime_service": (health or {}).get("service") if isinstance(health, dict) else None,
            "reachable_backends_via_search": ["honcho", "qmd"],
            "internal_roles": CANONICAL_ROLES,
            "agent_kb_pointer": AGENT_KB_GITHUB,
            "note": (
                "Roles are semantic contracts from Agent-KB CORE/EDGARS-KNOWLEDGE.md. "
                "Retrieval mechanisms (BM25/vector/QMD) are not separate truth stores."
            ),
        }
    )


def _intake_claims_agent_kb(args: dict[str, Any], body: dict[str, Any]) -> bool:
    """Refuse spoofed Agent-KB / master / CORE path writes."""
    blobs = [
        str(args.get("source") or ""),
        str(args.get("kind") or ""),
        str(body.get("source") or ""),
        str(body.get("kind") or ""),
        str(args.get("summary") or ""),
        " ".join(str(p) for p in (args.get("paths") or [])),
    ]
    joined = " ".join(blobs)
    if _RE_AGENT_KB_CLAIM.search(joined):
        # Allow honest receipts that merely *mention* Agent-KB in content? 
        # Spec: if source/kind claims agent-kb as writable → refuse.
        src = str(args.get("source") or body.get("source") or "").lower()
        kind = str(args.get("kind") or body.get("kind") or "").lower()
        paths = " ".join(str(p) for p in (args.get("paths") or [])).lower()
        if re.search(r"agent[\s_-]?kb", src) or "agent-kb" in src:
            return True
        if "master" in src and ("agent" in src or "kb" in src):
            return True
        if re.search(r"agent[\s_-]?kb", kind):
            return True
        if "qmd://agent-kb" in paths or "/core/" in paths or "agent-kb" in paths:
            return True
        if "edgarstool/agent-kb" in joined.lower():
            return True
    return False


def _intake_is_modify_intent(args: dict[str, Any], body: dict[str, Any]) -> bool:
    """Detect modify/rewrite attempts that must not silently dedupe-as-success."""
    if args.get("modify") is True or args.get("update") is True or args.get("rewrite") is True:
        return True
    kind = str(args.get("kind") or body.get("kind") or "").lower().strip()
    if kind in ("modify", "update", "patch", "rewrite", "mutate", "upsert"):
        return True
    blob = " ".join(
        [
            str(args.get("content") or ""),
            str(args.get("summary") or ""),
            str(body.get("summary") or ""),
            str(body.get("content") or ""),
        ]
    )
    if _RE_MODIFY_INTENT.search(blob):
        return True
    return False


def tool_knowledge_intake(args: dict[str, Any]) -> dict[str, Any]:
    """Optional bounded write through existing /intake. Requires content field."""
    content = args.get("content")
    if not content:
        return structured_error(
            "INVALID_ARGS",
            "intake requires content. Optional: event_id, summary, kind, source, paths. "
            "Do not use for secrets. Agent-KB/master path claims are refused. "
            "Modify/same-event_id rewrite is refused (use knowledge_update → UNSUPPORTED).",
        )

    kind = args.get("kind") or "receipt"
    source = args.get("source") or "grok-forge-mcp"
    body = {
        "content": content,
        "event_id": args.get("event_id") or "GROK-FORGE-KNOWLEDGE-INTAKE",
        "summary": args.get("summary") or "Grok Forge bounded knowledge intake",
        "kind": kind,
        "source": source,
    }
    if args.get("paths"):
        body["paths"] = args["paths"]

    if _intake_is_modify_intent(args, body):
        return structured_error(
            "UNSUPPORTED",
            (
                "Refusing intake modify/rewrite. Same event_id may dedupe without updating "
                "(silent non-update). knowledge_update is also unsupported in this adapter. "
                "Use a new event_id for a new bounded receipt, or edit the authority home directly."
            ),
            extra={
                "refused": True,
                "called_intake": False,
                "reason": "modify_intent",
                "event_id": body.get("event_id"),
                "kind": kind,
            },
        )

    if _intake_claims_agent_kb(args, body):
        return structured_error(
            "AMBIGUOUS_AUTHORITY",
            (
                "Refusing intake that claims Agent-KB / master / CORE path as writable. "
                "Agent-KB is stable authority via GitHub, not /intake. "
                "Use kind=receipt with an honest non-Agent-KB source for bounded receipts."
            ),
            extra={
                "refused": True,
                "sent_preview": {k: v for k, v in body.items() if k != "content"},
                "github": AGENT_KB_GITHUB,
            },
        )

    # Non-receipt kinds that look like authority writes without clear target
    kind_l = str(kind).lower()
    if kind_l not in ("receipt", "lesson", "note", "event", "memory", "probe"):
        # still allow through to API for known kinds; ambiguous authority kinds refused
        if kind_l in ("knowledge", "agent-kb", "ssot", "update", "rule", "core"):
            return structured_error(
                "AMBIGUOUS_AUTHORITY",
                (
                    f"kind={kind!r} looks like an authority/KB write. "
                    "MCP intake only supports bounded receipts (kind=receipt) with honest source. "
                    "Updates/rules require clear target+provenance (see knowledge_update)."
                ),
                extra={"refused": True, "kind": kind},
            )

    event_id = str(body.get("event_id") or "")
    marker = str(content)[:120]
    before: dict[str, Any] = {"queried": False, "found": False}
    if event_id:
        b_status, b_data = http_json("POST", "/search", {"query": event_id})
        if b_status == 200:
            b_shaped = normalize_search(event_id, b_status, b_data, apply_ranking=True)
            b_hits = b_shaped.get("hits") or []
            preexisting = [
                h
                for h in b_hits
                if event_id.lower() in _hit_text_blob(h)
            ]
            before = {
                "queried": True,
                "found": bool(preexisting),
                "hit_count": len(preexisting),
                "excerpt_head": (_excerpt_of(preexisting[0])[:240] if preexisting else None),
                "note": "Pre-create search by event_id",
            }

    status, data = http_json("POST", "/intake", body)
    ok = status in (200, 201) and (not isinstance(data, dict) or data.get("ok") is not False)
    payload = {
        "http_status": status,
        "response": data,
        "sent": {k: v for k, v in body.items() if k != "content"},
        "content_len": len(str(content)),
        "before": before,
    }
    if not ok:
        return structured_error(
            "UPSTREAM_HTTP",
            f"intake failed HTTP {status}",
            extra=payload,
        )
    # Honest no-op: upstream dedupe must not look like a successful modify/write
    if isinstance(data, dict) and data.get("deduped") is True:
        return structured_error(
            "UNSUPPORTED",
            (
                "Intake returned deduped=true (no new body written). "
                "Treating silent same-event_id no-op as failure, not success. "
                "This is not an update — original body retained."
            ),
            extra={
                **payload,
                "refused": True,
                "called_intake": True,
                "reason": "deduped_noop",
                "write": {
                    "semantic_type": "receipt_create_attempt",
                    "canonical_destination": "honcho_via_intake",
                    "writable": False,
                    "reason": "event_id_already_exists_deduped",
                },
            },
        )

    # After read-back (before already captured pre-intake)
    after: dict[str, Any] = {"queried": False, "found": False, "pointer": None}
    read_back_verified = False
    if event_id:
        a_status, a_data = http_json("POST", "/search", {"query": event_id})
        if a_status == 200:
            a_shaped = normalize_search(event_id, a_status, a_data, apply_ranking=True)
            a_hits = a_shaped.get("hits") or []
            matched = [
                h
                for h in a_hits
                if event_id.lower() in _hit_text_blob(h)
                or (marker[:48].lower() in _hit_text_blob(h) if len(marker) >= 16 else False)
            ]
            pointer = None
            if matched:
                prov = matched[0].get("provenance") or {}
                if isinstance(prov, dict):
                    pointer = prov.get("pointer") or prov.get("id")
                    meta = prov.get("metadata") or {}
                    if isinstance(meta, dict) and meta.get("event_id"):
                        pointer = pointer or meta.get("event_id")
                pointer = pointer or event_id
            read_back_verified = bool(matched)
            after = {
                "queried": True,
                "found": bool(matched),
                "hit_count": len(matched),
                "pointer": pointer,
                "excerpt_head": (_excerpt_of(matched[0])[:240] if matched else None),
            }

    write_receipt = {
        "semantic_type": str(kind),
        "canonical_destination": "honcho_via_knowledge_api_/intake",
        "writable": True,
        "operation": "create",
        "event_id": event_id,
        "before": before,
        "after": after,
        "pointer": after.get("pointer") or event_id,
        "read_back_verified": read_back_verified,
        "note": (
            "Create only. In-place update is not supported by knowledge-api "
            "(paths: /health,/intake,/search). Use knowledge_update for modify attempts."
        ),
    }
    payload["write"] = write_receipt
    payload["ok"] = True
    if not read_back_verified:
        # Create claimed ok but read-back miss — still surface honesty
        return structured_error(
            "VERIFY_FAILED",
            (
                "Intake returned ok but read-back did not find the new event/marker yet. "
                "Not claiming durable create success."
            ),
            extra=payload,
        )
    return structured_ok(payload)


def tool_knowledge_update(args: dict[str, Any]) -> dict[str, Any]:
    """True in-place update with before/after read-back, or structured UNSUPPORTED.

    knowledge-api exposes only /health,/intake,/search — no /update. Same event_id
    intake dedupes and retains the ORIGINAL body. Creating a *new* event_id would be a
    silent second object and is refused on this tool.
    """
    target = (
        args.get("target")
        or args.get("pointer")
        or args.get("event_id")
        or args.get("id")
        or ""
    )
    target_s = str(target).strip()
    content = args.get("content")
    content_s = str(content).strip() if content is not None else ""

    if not target_s:
        return structured_error(
            "AMBIGUOUS_AUTHORITY",
            (
                "knowledge_update requires a clear target (event_id/pointer) + content. "
                "No update was performed."
            ),
            extra={
                "supported": False,
                "called_intake": False,
                "called_update": False,
                "write": {
                    "semantic_type": "update",
                    "canonical_destination": "unknown",
                    "writable": False,
                    "reason": "missing_target",
                },
                "hint": "Use knowledge_intake for *new* bounded receipts with a fresh event_id.",
            },
        )

    if looks_like_agent_kb_pointer(target_s) or _RE_AGENT_KB_CLAIM.search(target_s):
        return structured_error(
            "AMBIGUOUS_AUTHORITY",
            (
                "Refusing update aimed at Agent-KB / stable authority path. "
                f"Edit via GitHub ({AGENT_KB_GITHUB}), not Knowledge MCP /intake."
            ),
            extra={
                "supported": False,
                "called_intake": False,
                "called_update": False,
                "target": target_s,
                "github": AGENT_KB_GITHUB,
                "write": {
                    "semantic_type": "stable_rule_update",
                    "canonical_destination": "Agent-KB/GitHub",
                    "writable": False,
                    "reason": "wrong_authority_home",
                },
            },
        )

    # Refuse "update by creating a second object" (new event_id alongside old target)
    new_eid = str(args.get("new_event_id") or args.get("as_new_event_id") or "").strip()
    if new_eid and new_eid != target_s:
        return structured_error(
            "UNSUPPORTED",
            (
                "Refusing update-via-second-object. A new event_id would create a parallel "
                "receipt without modifying the target. No write was performed."
            ),
            extra={
                "supported": False,
                "called_intake": False,
                "called_update": False,
                "target": target_s,
                "refused_new_event_id": new_eid,
                "reason": "no_silent_second_object",
                "write": {
                    "semantic_type": "update",
                    "canonical_destination": "honcho",
                    "writable": False,
                    "reason": "second_object_forbidden",
                },
            },
        )

    # Before snapshot via ranked search
    before: dict[str, Any] = {"queried": False, "found": False}
    status, data = http_json("POST", "/search", {"query": target_s})
    if status == 200:
        shaped = normalize_search(target_s, status, data, apply_ranking=True)
        hits = shaped.get("hits") or []
        relevant = [h for h in hits if is_relevant_hit(h, target_s, mode="get")] or [
            h for h in hits if target_s.lower() in _hit_text_blob(h)
        ]
        best = relevant[0] if relevant else None
        before = {
            "queried": True,
            "found": best is not None,
            "hit_count": len(relevant),
            "excerpt_head": (_excerpt_of(best)[:240] if best else None),
            "pointer": target_s,
            "backends": shaped.get("backends"),
        }
    elif status == 0:
        return structured_error(
            "UPSTREAM_HTTP",
            f"upstream unreachable during update before-read: {json.dumps(data, ensure_ascii=False)}",
            extra={"target": target_s, "called_intake": False, "called_update": False},
        )

    # Live API has no modify path (verified: POST /update → 404; paths=/health,/intake,/search).
    # Same-event_id /intake → deduped=true retaining ORIGINAL. Do not call /intake here.
    return structured_error(
        "UNSUPPORTED",
        (
            "True in-place update is not available: knowledge-api has no /update, and "
            "same event_id /intake dedupes without changing the body. "
            "No write was performed (no second object created)."
        ),
        extra={
            "supported": False,
            "called_intake": False,
            "called_update": False,
            "target": target_s,
            "content_provided": bool(content_s),
            "content_len": len(content_s),
            "before": before,
            "after": None,
            "read_back_verified": False,
            "api_paths": ["/health", "/intake", "/search"],
            "write": {
                "semantic_type": "update",
                "canonical_destination": "honcho",
                "writable": False,
                "reason": "honcho_intake_dedupe_only_no_modify_api",
                "before": before,
                "after": None,
                "pointer": target_s,
                "read_back_verified": False,
            },
            "hint": (
                "For a *new* bounded receipt use knowledge_intake with a fresh event_id. "
                "For Agent-KB rules use GitHub. Do not fake update by minting a second object."
            ),
        },
    )


TOOLS = {
    "knowledge_search": {
        "description": (
            "Query Edgar's Knowledge (logical shared layer via knowledge-api). "
            "Returns ranked excerpts with source, authority role, provenance. "
            "ACK/id-check/durability noise is filtered. "
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
            "Retrieve substantive body/evidence for a pointer, qmd:// URI, event id, or path "
            "via ranked Knowledge API search. Returns structured NOT_FOUND when only noise/"
            "empty locators match; Agent-KB may return NOT_SUPPORTED + GitHub pointer if "
            "body cannot be hydrated."
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
    "knowledge_context_pack": {
        "description": (
            "Build a minimal Context Pack (goal, authority, evidence≤5, unknown, "
            "conflicts, pointers, freshness, semantics) for Prompt Forge or a generic query. "
            "Uses ranked search; filters canary noise."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Pack topic / query"},
            },
            "required": ["query"],
        },
        "handler": tool_knowledge_context_pack,
    },
    "knowledge_status": {
        "description": (
            "Live status of knowledge-api.edgars.tools and reachable backends (Honcho, QMD). "
            "Always probes live; do not substitute historical receipts. "
            "Returns DEGRADED structured error when backends are down."
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
            "Requires content. Refuses Agent-KB/master spoof and modify/rewrite intents. "
            "Not for secrets. Prefer retrieval tools first."
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
    "knowledge_update": {
        "description": (
            "Stub: updates are unsupported without clear target/provenance. "
            "Attempts true update with before read-back; returns UNSUPPORTED when "
            "knowledge-api cannot modify in place. Never creates a second object; "
            "never calls /intake for modify."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "pointer": {"type": "string"},
                "event_id": {"type": "string"},
                "content": {"type": "string"},
                "id": {"type": "string"},
            },
        },
        "handler": tool_knowledge_update,
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
        send_result(
            msg["id"],
            structured_error("UPSTREAM_HTTP", f"{type(e).__name__}: {e}"),
        )


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
    log(f"started base={BASE} version={SERVER_VERSION}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            log(f"parse error: {e}")
            send_error(None, -32700, "Parse error")
            continue
        if "id" in msg:
            handle_request(msg)
        else:
            log(f"notification: {msg.get('method')}")


if __name__ == "__main__":
    main()
