# Gov-write (create + true update / UNSUPPORTED)

Branch: `smith/knowledge-mcp-gov-write` → `forge/edgars-knowledge-mcp`

## Versions
- stdio `0.2.2-gov-write`
- HTTP `0.3.1-gov-write`

## Behavior
1. **Create canary** (`knowledge_intake`): before search → intake → after read-back; write receipt with semantic_type/destination/writable/before/after/pointer/read_back_verified.
2. **Update** (`knowledge_update`): before read-back; API has no /update; same-event_id intake only dedupes → structured UNSUPPORTED; **no silent second object**.
3. Draft Agent-KB note: `DRAFT-ADAPTERS-KNOWLEDGE-MCP-WRITE.md`

## Evidence
Live probe 2026-09-06: POST /update → 404 paths=/health,/intake,/search; same event_id intake → deduped=true retaining ORIGINAL.
