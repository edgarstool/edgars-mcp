# Cloudflare Formalization Sprint 2 - 2026-06-29

## 摘要

- `mcp.edgars.tools/mcp` 現在已經由 Cloudflare Access 接手 public 保護
- `hooks.edgars.tools` 與 `status.edgars.tools` 已解除 Bot Fight 誤攔
- `hooks` / `status` 的 Worker source-of-truth 已補進 `mcp-handcraft` repo
- MCP 給 Codex / Claude / Hermes 的最小正式 auth 方案已定稿

## 目前狀態

### MCP

- Public URL: `https://mcp.edgars.tools/mcp`
- Tunnel route: `mcp.edgars.tools -> http://127.0.0.1:8765`
- Access App: `edgar-mcp-local`
- Managed OAuth: enabled
- Allow email: `edgar@edgarbeyourself.com`

### Hooks

- `https://hooks.edgars.tools/health` -> 200
- `https://hooks.edgars.tools/test` -> 200
- GitHub / Linear 驗簽版 source 已補進 repo
- `POST /notion`、`POST /cloudflare` 仍是 temporary placeholder

### Status

- `https://status.edgars.tools/` -> 200
- status page 目前會顯示：
  - EDGAR-OS v1.0
  - mcp external
  - mcp local origin
  - hooks health
  - github / linear verification state
  - host alias
  - repo root
  - runtime root
  - last updated

## MCP client auth 最小正式方案

### 1. 人類互動式

- 走 Cloudflare Access Managed OAuth

### 2. Edgar 本機上的 Codex / Claude / Hermes

- `stdio_proxy.py` -> `http://127.0.0.1:8765/mcp`
- 用 `MCP_API_TOKEN`

### 3. 遠端 / 雲端 agent

- `stdio_proxy.py` -> `https://mcp.edgars.tools/mcp`
- 用 Cloudflare Access service token
- 需要：
  - `MCP_CF_ACCESS_CLIENT_ID`
  - `MCP_CF_ACCESS_CLIENT_SECRET`

## Repo 內已補的檔案

- `cloudflare/workers/edgar-hooks-inbox/index.mjs`
- `cloudflare/workers/edgar-hooks-inbox/wrangler.jsonc`
- `cloudflare/workers/edgars-status/index.mjs`
- `cloudflare/workers/edgars-status/wrangler.jsonc`
- `docs/MCP-CLIENT-AUTH-最小正式方案.md`
- `00-CLOUDFLARE-FORMALIZATION-RESULT.md`

## 仍待完成

- 確認 live `hooks` Worker 是否已部署到修正後的 Linear 驗簽版本
- 建一組正式的 Cloudflare Access service token 給遠端 agent
- 視需要把 `POST /notion`、`POST /cloudflare` 從 placeholder 升級

## 下一步建議

1. 建立遠端 agent 用的 Cloudflare Access service token
2. 產出 Codex / Claude / Hermes 的實際 client config
3. 視需要驗一次 live `POST /github` / `POST /linear` 無簽章應回 401
