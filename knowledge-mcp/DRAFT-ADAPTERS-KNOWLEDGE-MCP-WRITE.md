# DRAFT → Agent-KB `ADAPTERS/KNOWLEDGE-MCP-WRITE.md`

> Thin governance for Knowledge MCP create/update. Not a new KB.
> Status: DRAFT for Forge/Agent-KB review (Smith gov-write, 2026-09-06).

## Scope

Applies to Grok/ChatGPT Knowledge MCP adapters over `knowledge-api.edgars.tools`.

## Create (`knowledge_intake`)

- Allowed: bounded **new** receipts (`kind=receipt` / lesson / note / …) with honest `source`.
- Required write receipt fields: `semantic_type`, `canonical_destination`, `writable`, `before`, `after`, `pointer`, `read_back_verified`.
- Flow: search **before** → `/intake` → search **after** → only claim success if read-back finds the new `event_id`/marker.
- Refuse: Agent-KB/master/CORE spoof → `AMBIGUOUS_AUTHORITY`.
- Refuse: modify/rewrite intent on intake → `UNSUPPORTED` (do not use intake as update).
- Same `event_id` with `deduped=true` → `UNSUPPORTED` (original retained; not an update).

## Update (`knowledge_update`)

- Require clear `target` (`event_id` / pointer) + intended `content`.
- Capture **before** via ranked search.
- **Do not** call `/intake` for updates.
- Live API paths today: `/health`, `/intake`, `/search` only — **no `/update`**. Same-event_id intake dedupes without changing the body.
- Therefore return structured `UNSUPPORTED` with `before`, `after=null`, `called_intake=false`, `writable=false`, unless a verified modify API appears later.
- **No silent second object:** refuse minting a new `event_id` to “simulate” update (`reason=no_silent_second_object`).
- Agent-KB / stable rules → GitHub (`edgarstool/Agent-KB`), not MCP intake.

## Authority homes (write-back)

| Result | Home |
|---|---|
| Bounded receipt / canary | Honcho via `/intake` (create only) |
| Stable cross-agent rule | Agent-KB (GitHub) |
| Human long-form | Obsidian |
| Current project state | project SSoT / Linear / repo / live |
| Secret | secret manager only |

## Agent rule

Retrieval hit ≠ Current. Memory ≠ Current. If destination unclear → `AMBIGUOUS_AUTHORITY`. Prefer create+read-back over fake modify.
