---
lang: zh-TW
---

# Linear OAuth × Hermes Agent — Windows-native v2

> 最後更新：2026-09-16
> Canonical runtime：`edgars-mcp` 直接讀 Windows Machine/User environment；不需要額外 secret runner。

## 目的

Linear 的 OAuth App `Hermes Agent` 讓 Hermes / edgars-mcp 以 App 身分讀寫 issue、留言並參與 Agent Session。

| 網址 | 用途 |
|---|---|
| `https://mcp.edgars.tools/linear/oauth/authorize` | 開始 Linear 授權 |
| `https://mcp.edgars.tools/linear/oauth/callback` | OAuth callback |
| `https://mcp.edgars.tools/linear/oauth/status` | 檢查設定與 token 狀態 |

Webhook manifest 預設仍為 `enabled: false`；正式事件入口依目前 canonical deployment 走 `hooks.edgars.tools`。

## 1. Linear OAuth App

在 Linear Workspace → Settings → API → OAuth applications 建立或確認 `Hermes Agent`：

- Application name：`Hermes Agent`
- Developer name：`Edgar AI Guild`
- Redirect URI：`https://mcp.edgars.tools/linear/oauth/callback`
- Homepage / Client URI：`https://github.com/Edgars-tool/hermes-agent`

取得 `Client ID` 與 `Client Secret`。Secret 不要寫進 repo、聊天或 log。

## 2. 寫入 Windows runtime environment

需要的名稱：

- `LINEAR_CLIENT_ID`
- `LINEAR_CLIENT_SECRET`
- `LINEAR_WEBHOOK_SECRET`（只有啟用 webhook 簽章驗證時才需要）
- `LINEAR_API_KEY`（既有個人 API 工具使用）

Canonical 儲存位置是 Windows User 或 Machine environment。可由已授權的 Windows agent / PowerShell 設定；不要建立 repo 內 secret 檔。

PowerShell 形式：

```powershell
[Environment]::SetEnvironmentVariable('LINEAR_CLIENT_ID', '<client-id>', 'User')
[Environment]::SetEnvironmentVariable('LINEAR_CLIENT_SECRET', '<client-secret>', 'User')
```

寫入後重啟 edgars-mcp，讓新程序重新載入 environment。

## 3. 重啟與授權

```powershell
Set-Location V:\projects\edgars-mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-mcp.ps1 -Force
```

接著開啟 `https://mcp.edgars.tools/linear/oauth/authorize` 並完成 Linear 授權。

成功後檢查：

- `configured: true`：Client ID / Secret 已被 runtime 讀到
- `token_present: true`：OAuth token 已取得

若 `configured: false`，檢查 Windows environment 名稱與 MCP 是否已重新啟動。

## 4. 常見問題

**App already installed，沒有 Authorize？**

到 Linear Settings → Installed applications → Hermes Agent → Manage，必要時 Revoke access，再重新從 `/linear/oauth/authorize` 開始。

**不想走瀏覽器授權？**

若 Linear OAuth App 已啟用 Client credentials tokens，可使用 `/linear/oauth/bootstrap`，完成後再查 `/linear/oauth/status`。

**callback 說 state 無效？**

授權連結已過期，重新從 `/linear/oauth/authorize` 開始。

**hooks.edgars.tools 跟 mcp.edgars.tools/webhook/linear？**

`hooks.edgars.tools` 是 canonical webhook/event ingress。`mcp.edgars.tools/webhook/linear` 已於 2026-09-16 從 edgars-mcp runtime 移除；8765 上的 legacy webhook paths 必須回 404。

## 相關檔案

- `config/linear-oauth-manifest.json`
- `config/linear-oauth-token.json`（不 commit）
- `V:\projects\cloudflared\HERMES-WEBHOOK.md`
- `docs/Cursor雲端Agent預設-新手版.md`
