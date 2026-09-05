# Edgar's Knowledge MCP

Thin MCP adapter over the existing Knowledge API runtime:

`https://knowledge-api.edgars.tools`

Not a KB. Not a RAG stack. Not a replacement for Honcho/QMD.

## Tools

| Tool | Maps to |
|---|---|
| `knowledge_search` | `POST /search` |
| `knowledge_get` | `POST /search` (expand pointer/query) |
| `knowledge_status` | live `GET /health` + bounded search |
| `knowledge_sources` | semantic roles + runtime health |
| `knowledge_intake` | optional `POST /intake` (requires `content`) |

## Run (stdio)

```bash
python3 server.py
```

Optional env:

- `EDGARS_KNOWLEDGE_API` (default `https://knowledge-api.edgars.tools`)
- `EDGARS_KNOWLEDGE_TIMEOUT` (default `30`)

## Grok install

Add MCP server (command mode):

- name: `edgars-knowledge`
- command: `python3`
- args: path to this `server.py` on the Grok computer

Prefer this over inventing a second knowledge store.

## Semantics

Preserve `CORE/EDGARS-KNOWLEDGE.md`:

- Edgar's Knowledge = logical shared layer (not a database)
- Agent-KB / Obsidian / Honcho / QMD / Hermes-Wiki / Current world / historical Cloud KB keep their roles
- Retrieval hit ≠ Current truth; live-verify mutable Current claims
