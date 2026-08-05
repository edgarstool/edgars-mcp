---
name: linear-agent-session
description: Handle Linear Agent Session delegation workflows (AgentSessionEvent webhooks, thought/response activities). Use when a user delegates an issue to Hermes Agent in Linear, when debugging "Did not respond", or when implementing agentActivityCreate writeback.
version: 1.0.0
metadata:
  hermes:
    tags: [linear, agent-session, delegation, webhook, agentActivityCreate]
    related_skills: [linear, linear-webhook-bridge]
---

# Linear Agent Session

## When to Use

Use when:

- A Linear issue is **delegated** to Hermes Agent (not merely assigned to a human).
- Linear shows **Did not respond** on an agent session.
- You receive or implement `AgentSessionEvent` webhooks.
- You must call `agentActivityCreate` back to Linear.

Do **not** use for:

- Normal issue triage with personal API key only (use `linear` skill).
- OAuth setup alone (use the current Linear application manifest in `config/`).

## Official Protocol (summary)

Linear docs: https://linear.app/developers/agent-interaction

1. User delegates issue → Linear creates **Agent Session**.
2. Linear POSTs `AgentSessionEvent` (`action: created`) to your webhook URL.
3. Your backend must:
   - HTTP ack within **5 seconds** (202 + background work is OK).
   - `agentActivityCreate` with type **`thought`** within **10 seconds**.
   - Run agent work (Hermes).
   - `agentActivityCreate` with type **`response`** when done.

`agentActivityCreate` requires **OAuth app token** (`client_credentials`), not `lin_api_*`.

## Our Stack

```
Linear → webhooks.edgars.tools/webhooks/linear
      → linear-orchestrator (:8645)
      → hermes -z --cli --continue <session> --skills linear
      → agentActivityCreate (thought + response)
```

**edgars-mcp** `/webhook/linear` only logs — it does **not** complete agent sessions.

Infrastructure repo: `linear-orchestrator` (Edgar-s-Tool/linear-orchestrator).

## Hermes Prompt Rules (when invoked by orchestrator)

When processing an `AgentSessionEvent`:

1. Read issue context via linear tools if needed.
2. Produce a single plain-text reply (≤500 chars, 繁體中文) for Linear writeback.
3. Return `__SKIP__` if no user-visible reply is needed.
4. Do **not** assume webhook handling — orchestrator owns thought/response timing.

## Debugging Checklist

1. Webhook URL live? (`webhooks.edgars.tools/webhooks/linear`, not `mcp.edgars.tools/webhook/linear`)
2. `linear-orchestrator` running? (`systemctl status`, `:8645/healthz`)
3. `LINEAR_OAUTH_CLIENT_ID/SECRET` set for writeback?
4. `LINEAR_WEBHOOK_SECRET` matches Linear app signing secret?
5. Thought sent within 10s? (check orchestrator deliveries dashboard)
6. Hermes CLI reachable? (`HERMES_PATH`)

## References

- `config/linear-oauth-manifest.json` — current application contract
- `docs/ARCHITECTURE.md` — edgars-mcp runtime boundary
- The external `linear-orchestrator` repository — agent-session implementation
