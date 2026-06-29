# EDGAR-OS v1.0 Cloudflare Feature Sprint 2 Result

Date: 2026-06-29T20:55:00Z

## Scope

- Formalize hooks worker source for GitHub + Linear signature verification.
- Verify live MCP auth posture and recommend client auth strategy.
- Formalize status worker source for live status rendering.

## Output path note

- Requested output path: `V:\00-CLOUDFLARE-FORMALIZATION-RESULT.md`
- Actual output path in this cloud workspace: `/workspace/00-CLOUDFLARE-FORMALIZATION-RESULT.md`
- Blocker: this Linux cloud agent cannot write to the Windows host path `V:\`.

## What was completed

### 1. Formalized Worker source in repo

Added source-of-truth Worker files:

- `cloudflare/workers/edgar-hooks-inbox/index.mjs`
- `cloudflare/workers/edgar-hooks-inbox/wrangler.jsonc`
- `cloudflare/workers/edgars-status/index.mjs`
- `cloudflare/workers/edgars-status/wrangler.jsonc`

#### hooks worker source behavior

- `GET /health` returns:
  - `{ "ok": true, "service": "edgar-hooks-inbox" }`
- `POST /test` returns 200 and stays temporary
- `POST /github`
  - validates `X-Hub-Signature-256`
  - expects `GITHUB_WEBHOOK_SECRET`
  - returns 401 for missing/bad signature
  - returns 200 only when signature is valid
- `POST /linear`
  - validates `Linear-Signature`
  - expects `LINEAR_WEBHOOK_SECRET`
  - returns 401 for missing/bad signature
  - returns 200 only when signature is valid
- `POST /notion`, `POST /cloudflare`
  - remain temporary placeholders

Important correction:

- Current live bundled `edgar-hooks-inbox` code expects `Linear-Signature` to start with `sha256=`.
- Linear docs use a raw hex HMAC in `Linear-Signature`, not `sha256=<hex>`.
- The repo source added here fixes that mismatch.

#### status worker source behavior

- Renders `EDGAR-OS v1.0`
- Shows:
  - `mcp external`
  - `mcp local origin`
  - `hooks health`
  - `hooks github verification`
  - `hooks linear verification`
  - `local host alias`
  - `repo root`
  - `runtime root`
  - `last updated`
- Uses live fetches for:
  - `https://mcp.edgars.tools/mcp`
  - `https://hooks.edgars.tools/health`
- Treats:
  - `401` on MCP as protected/expected
  - `403` + `cf-mitigated: challenge` as protected/challenged edge behavior
- Displays `127.0.0.1:8765` as the origin target, with note that Cloudflare edge cannot directly probe localhost loopback.

### 2. Local source verification completed

Verified locally:

- `node --check cloudflare/workers/edgar-hooks-inbox/index.mjs`
- `node --check cloudflare/workers/edgars-status/index.mjs`

Verified route behavior locally for hooks source:

- `/health` -> 200
- `/test` -> 200
- `/github` without signature -> 401
- `/linear` without signature -> 401

Verified status HTML locally contains:

- `EDGAR-OS v1.0`
- `mcp external`
- `hooks health`
- `V:\projects`
- `G:\AI_WORK_512`
- `EdgarsTool / edgar-local-01`

## Live verification results

### hooks.edgars.tools

Observed from this cloud agent:

- `GET https://hooks.edgars.tools/health` -> `403` with `cf-mitigated: challenge`
- `POST https://hooks.edgars.tools/test` -> `403` with `cf-mitigated: challenge`
- `POST https://hooks.edgars.tools/github` without signature -> `403` challenge at edge
- `POST https://hooks.edgars.tools/linear` without signature -> `403` challenge at edge

Interpretation:

- The edge challenge blocks curl verification before the Worker route behavior can be observed from this agent.
- Therefore the live Worker may still be correct behind the edge, but the required curl-based verification currently fails.

### mcp.edgars.tools/mcp

Observed from this cloud agent:

- `curl -i http://127.0.0.1:8765/mcp -m 15` -> connection failure
  - expected on this Linux cloud agent, because it is not the Windows host running the local MCP origin
- `curl -i https://mcp.edgars.tools/mcp -m 15` -> `403` with `cf-mitigated: challenge`
- `curl -i https://mcp.edgars.tools/.well-known/cloudflare-access-protected-resource/mcp -m 15` -> `404`
- `curl -i https://mcp.edgars.tools/.well-known/oauth-protected-resource -m 15` -> `200`

Interpretation:

- MCP is still protected at the edge.
- From this agent, protection presents as `403 challenge`, not the earlier `401 Unauthorized`.
- The app-level protected resource metadata is still present at `/.well-known/oauth-protected-resource`.
- A Cloudflare Access-specific protected-resource metadata endpoint was not exposed at `/.well-known/cloudflare-access-protected-resource/mcp`.

### status.edgars.tools

Observed from this cloud agent:

- `curl -i https://status.edgars.tools/ -m 15` -> `403` with `cf-mitigated: challenge`

Interpretation:

- The requested live 200 verification could not be completed because the status hostname is also challenged at the edge from this environment.

## MCP client auth recommendation

### Human browser login

- Best for: human-operated browser flows, ChatGPT-style interactive OAuth, portal-style login
- Current state: plausible for humans, but from this cloud agent the edge responds with a managed challenge instead of a plain 401 OAuth negotiation path

### Service token

- Best for: Codex, Claude, Hermes, CI, headless future agents
- Reason:
  - no browser dependency
  - stable for machine-to-machine access
  - easier than relying on interactive challenge completion

### Machine-to-machine client

- Good for: future formal agent infrastructure when you want per-client credentials and revocation
- Better long-term than sharing one service token across many automated clients

### Recommendation by client

- Codex: service token first
- Claude: service token first
- Hermes: service token first
- Future agents: machine-to-machine client if available; otherwise service token
- Human browser use: browser login / Access interactive flow

## Secrets handling

- Only secret names were referenced:
  - `GITHUB_WEBHOOK_SECRET`
  - `LINEAR_WEBHOOK_SECRET`
- No secret values were written into repo, report, or chat

## Blockers

1. **No Cloudflare deployment credentials from this cloud agent**
   - `wrangler whoami` reports unauthenticated
   - `CLOUDFLARE_API_TOKEN`, `CF_API_TOKEN`, account env vars were not present
   - Result: I could not deploy the corrected Worker source to live Cloudflare

2. **Edge challenge blocks required curl verification**
   - `hooks.edgars.tools/*` returned `403 cf-mitigated: challenge`
   - `status.edgars.tools/` returned `403 cf-mitigated: challenge`
   - `mcp.edgars.tools/mcp` returned `403 cf-mitigated: challenge`
   - Result: required live curl expectations (`200` / `401`) cannot be confirmed from this agent

3. **Local origin curl from this cloud agent is not physically reachable**
   - `http://127.0.0.1:8765/mcp` here points to the Linux cloud VM, not your Windows host
   - Result: local-origin verification from this environment is inherently blocked

## Placeholder items still remaining

- `POST /notion` remains temporary
- `POST /cloudflare` remains temporary
- Live deployment of the corrected `hooks` and `status` Worker source is pending credentials/access

## Next step suggestion only

1. Provide this cloud agent with a deploy-capable Cloudflare auth path:
   - `wrangler login`, or
   - a non-chat-exposed deploy mechanism already wired into the environment
2. Review why `hooks.edgars.tools`, `status.edgars.tools`, and `mcp.edgars.tools` are returning managed challenge to curl
3. After deploy access exists:
   - deploy `cloudflare/workers/edgar-hooks-inbox`
   - deploy `cloudflare/workers/edgars-status`
   - rerun the exact curl checks from a non-challenged environment
