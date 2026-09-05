# SMITH ROUND1 IMPL NOTES

| Field | Value |
|---|---|
| When (Asia/Taipei) | 2026-09-06 ~00:20 |
| Worker | Smith implementation worker |
| Live freeze | `server.py` == `server.py.exact` untouched |
| Stdio | `knowledge-mcp/server.py.round1` |
| HTTP | `knowledge-mcp/http_server.py.round1` (importlib → `server.py.round1` if present) |

## MUST → changes

| MUST | What changed |
|---|---|
| **1. knowledge_get fidelity** | `tool_knowledge_get` ranks/filters `/search` hits; returns `body` + `best_hit` on substantive match; else structured `NOT_FOUND` (`isError: true`). No longer returns search-noise as success. |
| **2. Exact-ID / topical ranking** | Adapter helpers `is_noise_excerpt`, `score_hit`, `rank_and_filter_hits`: demote/filter `ACK`/`NO_REPLY`, `id-check-*`, durability canaries; QMD `"No results found."` not counted as locator success; prefer exact event_id / query substring / longer content. Applied in `normalize_search(..., apply_ranking=True)` used by search/get/pack. |
| **3. Structured errors** | `structured_error(code, message, extra=)` → `{ok:false, error:{code,message}, ...}` + MCP `isError:true`. Codes: `NOT_FOUND`, `DEGRADED`, `AMBIGUOUS_AUTHORITY`, `INVALID_ARGS`, `UPSTREAM_HTTP`, plus `NOT_SUPPORTED` / `UNSUPPORTED`. Stdio parse failures emit JSON-RPC `-32700`. |
| **4. Current vs historical Contabo** | `contabo_banner` + `apply_current_vs_historical`: Contabo queries get `live_verify` banner; Honcho/QMD hits labeled historical/locator — never presented as live health. |
| **5. knowledge_context_pack** | New tool: args `{query}` required. Returns goal, authority, evidence (≤5 ranked non-noise), constraints, unknown, conflicts (empty optional), pointers, freshness, semantics. |
| **6. knowledge_update stub + intake harden** | `knowledge_update` always `AMBIGUOUS_AUTHORITY` or `UNSUPPORTED`; **never** calls `/intake`. `knowledge_intake` refuses Agent-KB/master/CORE path spoof and authority-like kinds with `AMBIGUOUS_AUTHORITY`; bounded `kind=receipt` with honest source still allowed. |
| **7. Agent-KB hydrate** | If pointer looks like Agent-KB and search yields substantive body → return hydrated excerpt + github fallback note; else `NOT_SUPPORTED` + `https://github.com/edgarstool/Agent-KB`. |

## Copilot P0s included

- win32 stdio binary/UTF-8 wrap
- safe `TIMEOUT` via `_timeout_seconds()` (invalid/≤0 → 30)
- stdio `-32700` on JSON parse error

## HTTP import strategy

`http_server.py.round1` uses `importlib.machinery.SourceFileLoader` to load sibling `server.py.round1` when that file exists; otherwise `server.py` (needed because `spec_from_file_location` has no loader for `*.round1`). Local Round1 HTTP testing does not overwrite live `server.py`. Deploy may still copy/rename `server.py.round1` → `server.py`.

## Deferred (explicit)

filters/limit/mode UI, QMD multi-split polish, full intake routing, conflict fixtures beyond empty `conflicts[]`, ChatGPT provenance restore, full update+readback.

## Limitations vs upstream API

- No dedicated `/get` — get/pack still fan out to `/search` then shape.
- Agent-KB full file bodies are not guaranteed via search; hydrate is best-effort excerpt.
- `/intake` dedupe may not update same `event_id` (hence update stub refuses fake success).
- Ranking is adapter heuristic only; upstream Honcho soft-match noise still exists raw — filtered before Agent sees success payloads.
