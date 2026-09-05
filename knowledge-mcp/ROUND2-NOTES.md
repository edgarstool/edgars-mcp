# Round2 P0 — Knowledge MCP (4 FAIL targets)

Branch: `smith/knowledge-mcp-round2-p0` → base `forge/edgars-knowledge-mcp`

## Version
- stdio `server.py`: `0.2.1-round2`
- HTTP `http_server.py`: `0.3.0-round2` (loads `server.py.round2` if present, else `server.py`)

## SCOPE (Forge-locked)
1. **NOT_FOUND on get-miss** — relevance-gated `knowledge_get`; soft Honcho match ≠ found
2. **Vague/gibberish empty** — vague/no-signal + no token overlap → empty hits (`empty_after_ranking`)
3. **Intake modify refuse** — MODIFY/rewrite intent → `UNSUPPORTED` before `/intake`; `deduped=true` → not success
4. **QMD get honest miss** — unhydratable `qmd://` → `NOT_SUPPORTED` (no Honcho soft success)

## Ship form
Tip `server.py`/`http_server.py` are thin loaders over `_round2_*.z64.p*` (no `@file://`). Expand for review: join parts → b64decode → zlib. Round1 `_round1_*.z64` archive may remain.

## Live
**Live Grok plugin stays Round1** until Forge integrates this PR.
