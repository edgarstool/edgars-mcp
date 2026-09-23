# edgars-mcp v2.0.0 — 使用指南

## 日常使用

正常情況不需要手動啟動。Windows 排程 `edgars-mcp-http` 會呼叫 `Start_Handcraft_MCP_HTTP.vbs`，再進入 canonical Windows-native starter。

手動重啟：

```powershell
Set-Location V:\projects\edgars-mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-mcp.ps1 -Force
```

健康檢查：

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing
mcporter list
```

預期：health 200，`edgars-mcp` 為 253 tools。

## Secret / API key

Server 與 stdio proxy 直接讀 Windows Machine/User environment。舊的 secret-runner 與 container bootstrap 已退役，不應復原。

## Wrapper profile

Canonical profile 啟用：Playwright、Windows-MCP、Desktop Commander、OpenMontage、Hermes、OpenClaw。

明確不併入 edgars-mcp：Descope、cloudflared、1Password Connect wrapper，以及 self-hosted Honcho 的 REST/identity-gate plane。它們是獨立服務/工具，不是 253-tool generic MCP profile 的一部分。

## Cursor

使用 `config/mcp.local.example.json` 的 direct-Python 形式，不要在 MCP command 外面再包 secret runner。

## 故障判斷

1. `/health` 不通：執行 `start-mcp.ps1 -Force`。
2. health 正常但 tools 數不對：確認 starter 是 repo 目前版本，並檢查是否有舊 process。
3. 個別 provider tool 缺 key：補 Windows environment variable 後重啟 HTTP server。
4. 不要為了修 key 問題重新引入已退役的 bootstrap 路徑。
