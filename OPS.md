# handcraft-mcp 操作手冊

> 適用版本：0.1.0｜最後更新：2026-04-14

---

## 1. 架構一覽

```
本機
├── server.py          ← stdio 模式（Claude Desktop / OpenClaw 本機呼叫）
├── server_http.py     ← HTTP 模式（遠端 / mcp.edgars.tools）
├── run.cmd            ← 啟動 stdio server（透過 Doppler 注入 key）
└── run_http.cmd       ← 啟動 HTTP server（透過 Doppler 注入 key）

Doppler（雲端）
└── project: handcraft-mcp / config: prd
    └── 存放所有 API key，啟動時注入，不落地

Cloudflare Tunnel
└── mcp.edgars.tools → 本機 :8765/mcp

Cloudflare Access（建議 public 模式）
└── Managed OAuth / Access policies 保護外網 `mcp.edgars.tools`
```

### 兩個 server 的差異

| | server.py (stdio) | server_http.py (HTTP) |
|---|---|---|
| 用途 | 本機 agent 直連 | 外網 / 遠端呼叫 |
| 啟動方式 | `run.cmd` | `run_http.cmd` |
| Port | 無（stdin/stdout） | 8765 |
| 工具數 | echo | 主力完整工具集 |
| Auth | 無需 | localhost 可用 bearer；外網建議 Cloudflare Access Managed OAuth |

---

## 2. 啟動 / 停止

> **⚠️ 啟動前必填:`MCP_API_TOKEN`**
>
> `run_http.cmd` / `server_http.py` 啟動時會讀 `MCP_API_TOKEN`,**沒設會 fail-fast**,不再使用 repo 內明文 fallback。
> Token 走 Doppler stdin 或 Web UI 設定,不要寫進命令列或 shell history。
>
> 最小啟動範例:
>
> ```cmd
> :: 先確認 Doppler 已設好(handcraft-mcp / prd)
> doppler secrets get MCP_API_TOKEN --plain
> :: 啟動(會用 doppler run 自動注入)
> run_http.cmd
> ```
>
> 缺 token 時 server 印 `MCP_API_TOKEN is required` 後 exit。詳見下方第 4 節「Secrets / Doppler 管理」。


### 啟動 HTTP server（常用）
```cmd
cd V:\projects\edgars-mcp
run_http.cmd
```

### 恢復完整 public MCP path（:8765 + cloudflared + /mcp）
```powershell
cd V:\projects\edgars-mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-HandcraftStack.ps1
```

這個腳本會：
- 確認 `http://127.0.0.1:8765/health`
- 若本機 HTTP server 沒活著，用 Doppler 啟動 `server_http.py`
- 確認或啟動 `cloudflared`
- 檢查 `https://mcp.edgars.tools/mcp` 是否 reachable

> 若 public hostname 已套 Cloudflare Access，外網檢查可能看到 `401`、`302` 或 Cloudflare Access login page；這算是「可連到而且已受保護」，不等於故障。

### 只做健康檢查
```powershell
cd V:\projects\edgars-mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-HandcraftHealth.ps1
```

### 啟動 stdio server（本機 MCP client 用）
```cmd
run.cmd
```

### 停止
在執行中的視窗按 `Ctrl+C`。

### 確認是否在跑
```bash
# 確認 port 8765 是否被監聽
netstat -ano | findstr :8765
# 確認服務健康
curl.exe http://127.0.0.1:8765/health
```

---

## 3. Secret 管理（Doppler）

### 新增 key
```powershell
doppler secrets set MY_API_KEY --project handcraft-mcp --config prd
# 在互動式 stdin 貼上值；不要把值放在命令列
```

### 更新 key
```powershell
doppler secrets set MY_API_KEY --project handcraft-mcp --config prd
# 在互動式 stdin 貼上新值；不要使用 MY_API_KEY=真值
```

### 刪除 key
```bash
doppler secrets delete MY_API_KEY
```

### 查看目前所有 key（值會遮蔽）
```bash
doppler secrets
```

### 查看特定 key
避免在一般 shell 直接印出 secret 值。需要確認是否存在時，用 `doppler secrets` 看遮蔽後清單；真的要看值，請走 Doppler Web UI 或受控的 secrets 區，不要把輸出複製進 repo、log 或對話。

### Web UI
https://dashboard.doppler.com → 選 `handcraft-mcp` → `prd`

### 改完 key 要重啟 server
Doppler 在啟動時注入，改完 key 要停掉 server 重跑 `run_http.cmd`。

---

## 4. 在 server_http.py 讀取 key

server 啟動後環境變數已注入，直接讀 `os.getenv()`：

```python
import os
MY_KEY = os.getenv("MY_API_KEY", "")  # 第二個參數是預設值
```

建議在 server 最上層（import 區之後）集中宣告：

```python
# ── Secrets（由 Doppler 注入）─────────────────────────
MY_API_KEY = os.getenv("MY_API_KEY", "")
OTHER_KEY  = os.getenv("OTHER_KEY", "")
```

---

## 5. 新增 tool 流程

所有工具在 `server_http.py` 修改。兩個地方要動：

### 步驟 1：在 TOOLS 清單加定義（約第 45 行）

```python
{
    "name": "my_tool",
    "description": "說明這個工具做什麼",
    "inputSchema": {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "輸入說明"},
        },
        "required": ["input"],
    },
},
```

### 步驟 2：在 handle_tools_call 加分支（約第 569 行）

```python
if name == "my_tool":
    return handle_my_tool(req_id, arguments)
```

### 步驟 3：實作 handler function

```python
def handle_my_tool(req_id, arguments: dict) -> dict:
    val = arguments.get("input", "")
    # 你的邏輯，例如呼叫外部 API
    result = call_some_api(val)
    return make_response(req_id, make_tool_text_response(result))
```

---

## 6. 環境變數（可在 Doppler 設定）

| 變數名稱 | 預設值 | 說明 |
|---|---|---|
| `MCP_AGENT_TIMEOUT_SECONDS` | `300` | agent 指令最長執行秒數 |
| `MCP_JOB_RETENTION_SECONDS` | `3600` | 背景 job 結果保留時間（秒） |

修改方式：
非敏感設定可直接寫值；secret / token 不要這樣放進命令列。

```bash
doppler secrets set MCP_AGENT_TIMEOUT_SECONDS=600
```

---

## 7. 安全設定

### Bearer Token（HTTP server / localhost）

HTTP server 啟動時會讀 `MCP_API_TOKEN`，沒有設定會直接中止，不再使用 repo 內明文 fallback。  
這個 token 主要留給：

- localhost `POST /mcp`
- `stdio_proxy.py`
- 維運腳本與 smoke test

public hostname 不建議再把它當外網主認證。

設定 token 時走 Doppler stdin / Web UI，不要把 token 寫進命令列或 shell history：

```powershell
doppler secrets set MCP_API_TOKEN --project handcraft-mcp --config prd
# 在互動式 stdin 貼上 token
```

本機手動驗證 `/mcp` 時使用 wrapper。它只從環境變數讀 token，不接受 token 參數：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-HandcraftMcp.ps1
```

### Cloudflare Access（public `/mcp` 建議做法）

當外網 `mcp.edgars.tools` 要像正式 SaaS 一樣走登入 / redirect / OAuth，建議：

1. 在 Cloudflare Zero Trust 建 **Self-hosted Access application**
2. 開 **Managed OAuth**
3. 記下 Access application 的 `AUD`
4. 在 `server_http.py` 對 `Cf-Access-Jwt-Assertion` 做 origin 端驗證

必要環境變數：

```text
MCP_CLOUDFLARE_ACCESS_ENABLED=true
MCP_CLOUDFLARE_ACCESS_TEAM_DOMAIN=<team>.cloudflareaccess.com
MCP_CLOUDFLARE_ACCESS_AUD=<access-app-aud>
```

可選：

```text
MCP_CLOUDFLARE_ACCESS_JWKS_URL=https://<team>.cloudflareaccess.com/cdn-cgi/access/certs
MCP_CLOUDFLARE_ACCESS_DISABLE_BUILTIN_OAUTH=true
MCP_CLOUDFLARE_ACCESS_ALLOW_PUBLIC_TOKEN_FALLBACK=false
```

當 `MCP_CLOUDFLARE_ACCESS_ENABLED=true` 且請求 hostname 是 public base URL 時，repo 內建：

- `/.well-known/oauth-authorization-server`
- `/.well-known/oauth-protected-resource`
- `/authorize`
- `/token`
- `/register`

不再作為外網主流程。

### Codex / Claude / Hermes 最小正式 auth

建議固定分工：

1. **Edgar 本機**
   - `stdio_proxy.py` 轉送到 `http://127.0.0.1:8765/mcp`
   - 用 `MCP_API_TOKEN`

2. **遠端 / 雲端 agent**
   - `stdio_proxy.py` 轉送到 `https://mcp.edgars.tools/mcp`
   - 用 Cloudflare Access service token
   - 透過這兩個 header 進入 Access：
     - `CF-Access-Client-Id`
     - `CF-Access-Client-Secret`

proxy 支援的環境變數：

```text
MCP_CF_ACCESS_CLIENT_ID
MCP_CF_ACCESS_CLIENT_SECRET
```

向後相容也接受：

```text
CF_ACCESS_CLIENT_ID
CF_ACCESS_CLIENT_SECRET
HERMES_HANDCRAFT_CF_ACCESS_CLIENT_ID
HERMES_HANDCRAFT_CF_ACCESS_CLIENT_SECRET
```

3. **人類互動式 client**
   - 走 Cloudflare Access Managed OAuth

參考：

- `config/mcp.local.example.json`
- `config/mcp.remote.stdio.example.json`
- `docs/MCP-CLIENT-AUTH-最小正式方案.md`

### Origin 白名單（DNS rebinding 防護）

在 `server_http.py` 的 `ALLOWED_HOSTNAMES`：
```python
ALLOWED_HOSTNAMES = {"localhost", "127.0.0.1", "mcp.edgars.tools"}
```

新增允許的 origin：
```python
ALLOWED_HOSTNAMES = {"localhost", "127.0.0.1", "mcp.edgars.tools", "new.domain.com"}
```

---

## 8. Cloudflare Tunnel

| 設定項目 | 值 |
|---|---|
| Tunnel 名稱（現役） | `edgar-local-01-tunnel` |
| Tunnel ID | `5361a5cd-20f7-4639-95f1-92c1b28d31e1` |
| 對外網址 | `https://mcp.edgars.tools` |
| 本機目標 | `http://localhost:8765` |

> **Deprecated**：`~/.cloudflared/config.yml` 內的 `home-tunnel`（`0e0a1b13-...`）已停用。`Start-HandcraftStack.ps1` 不再用該 yaml；若 Windows 服務 `Cloudflared` 已在跑，腳本不會重複啟動 tunnel。

Tunnel 由 `cloudflared` 常駐管理（建議用 Windows 服務或 `cloudflared tunnel run edgar-local-01-tunnel`）。確認狀態：

```powershell
cloudflared tunnel info 5361a5cd-20f7-4639-95f1-92c1b28d31e1
Get-Service Cloudflared
```

### 外網 403：`DNS points to prohibited IP`（Cloudflare error 1000）

代表 `mcp.edgars.tools` 的 DNS 記錄未正確指向 tunnel（例如仍指向 localhost / 禁止 IP）。在 Cloudflare Dashboard → Zero Trust → Networks → Tunnels → `edgar-local-01-tunnel` 確認 Public Hostname `mcp.edgars.tools` 存在，並讓 DNS 走 tunnel CNAME（`5361a5cd-20f7-4639-95f1-92c1b28d31e1.cfargotunnel.com`），不要手動 A 到 `127.0.0.1`。

修正 DNS 屬於 production 變更，動手前請先確認。

---

## 9. Log 查看

HTTP server 的 log 輸出到 stderr（執行中的視窗）：
```
[MCP-HTTP] handcraft-mcp HTTP server starting
[MCP-HTTP] tools/call: name=codex_agent ...
[MCP-HTTP] codex_agent: exit_code=0
```

若要存到檔案：
```cmd
run_http.cmd 2> V:\projects\edgars-mcp\mcp.log
```

---

## 10. 連線測試

```bash
# 確認 server 正常回應
curl -X POST http://localhost:8765/mcp \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"clientInfo\":{\"name\":\"test\",\"version\":\"1.0\"},\"capabilities\":{}}}"

# 確認外網（public hostname 套 Access 後，未授權時可能回 401/302 或 Access login）
curl -X POST https://mcp.edgars.tools/mcp \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}"

# 確認 ChatGPT OAuth discovery
curl https://mcp.edgars.tools/.well-known/oauth-protected-resource
```

正常回應包含 `"serverInfo": { "name": "edgars mcp" }`。  
若未登入 Access，出現 Access login / 401 代表 edge 在工作。
但若要讓 ChatGPT Connector 判定 OAuth 已實作，還必須讓 `/.well-known/oauth-protected-resource` 回 `200`；若這條是 `403`，代表 discovery 仍被 edge 擋住。

### Hermes stdio proxy

Use `stdio_proxy.py` when Hermes needs a stdio MCP command but the handcraft MCP service is running through `server_http.py`.

```powershell
python .\stdio_proxy.py
```

The proxy defaults to `http://127.0.0.1:8765/mcp`; override with `MCP_URL` only when needed.

### Webhook URL quick reference

Do not collapse these into one URL during review:

- MCP endpoint: `https://mcp.edgars.tools/mcp`
- Discord webhook: `https://mcp.edgars.tools/webhook/discord`
- Package / TrackTW webhook: `https://mcp.edgars.tools/webhook/package`
- Linear webhook: `https://mcp.edgars.tools/webhook/linear`

如果要讓 webhook 不跟 `/mcp` 共用 Access policy，建議把對外 webhook URL 分到另一個 base URL，並在環境變數設定：

```text
MCP_WEBHOOK_BASE_URL=https://hooks.mcp.edgars.tools
```

若 webhook 仍保留公開直打，至少設定：

```text
MCP_PACKAGE_WEBHOOK_TOKEN=<secret>
MCP_LINEAR_WEBHOOK_TOKEN=<secret>
MCP_DISCORD_WEBHOOK_TOKEN=<secret>
```

呼叫方可用 `Authorization: Bearer <secret>` 或 `X-Handcraft-Webhook-Token`。

Local package webhook test:

```powershell
curl.exe -X POST http://127.0.0.1:8765/webhook/package -H "Content-Type: application/json" -d "{\"tracking_number\":\"TEST123\"}"
```

Local Linear webhook test:

```powershell
curl.exe -X POST http://127.0.0.1:8765/webhook/linear -H "Content-Type: application/json" -d "{\"type\":\"Issue\",\"action\":\"create\"}"
```

### cache-trace rotation / archive

`logs\cache-trace.jsonl` is treated as gateway/runtime trace output. The current `mcp-handcraft` Python server does not write `cache-trace.jsonl` directly; if the file exists, it is expected to come from the surrounding gateway/runtime wrapper or deployment path. Do not mix this lane with gateway secret repair.

Rotation policy:

- Rotate when the file is at least `128MB`, or older than `1` day.
- Archive to `logs\archive\cache-trace\`.
- Keep the newest `14` archives in the primary archive folder; older archives are moved to `retired\` instead of being deleted.
- Create a `.checkpoint.json` before moving the active log.
- Never archive to Desktop, secrets folders, `.openclaw\workspace`, or AI cache paths.
- Do not delete the active log; the script moves it to archive and creates a new empty `cache-trace.jsonl`.

Run from the repo root:

```powershell
.\scripts\Rotate-CacheTrace.ps1
```

For scheduled runs, use the wrapper. It writes the latest run result to `logs\cache-trace-rotation-status.json`:

```powershell
.\scripts\Run-CacheTraceRotation.ps1
```

Windows Scheduled Task:

- Task name: `McpHandcraftCacheTraceRotation`
- Cadence: hourly
- Action: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "V:\projects\edgars-mcp\scripts\Run-CacheTraceRotation.ps1"`

Use `-WhatIf` to preview:

```powershell
.\scripts\Rotate-CacheTrace.ps1 -WhatIf
```

After rotation, verify the gateway can still append to the new log:

```powershell
Add-Content -LiteralPath .\logs\cache-trace.jsonl -Value '{"check":"write-after-rotation"}'
Get-Item .\logs\cache-trace.jsonl | Select-Object FullName,Length,LastWriteTime
```

---

## 11. 常見問題

**Q：改完 Doppler key，server 沒有讀到新值**
→ 停掉 server，重跑 `run_http.cmd`。Doppler 只在啟動時注入。

**Q：curl 回 403 Forbidden: Origin not allowed**
→ 把你的 origin 加進 `ALLOWED_HOSTNAMES`。

**Q：public `/mcp` 回 401 / 302 / Cloudflare Access login**
→ 若你已啟用 Cloudflare Access，這通常代表 edge 正常在保護入口。先確認 client 是否已完成 Managed OAuth。

**Q：localhost `/mcp` 回 401 Unauthorized**
→ 不要把 bearer token 寫在 `curl -H` 命令列。確認 `MCP_API_TOKEN` 已由 Doppler/env 提供，然後跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-HandcraftMcp.ps1
```

**Q：agent 工具回 timeout**
→ 試試加 `"async": true` 改成背景執行，再用 `agent_job_status` 查結果。

**Q：Doppler 登入過期**
```bash
doppler login
```

**Q：確認 Doppler 綁定正確**
```bash
cd V:\projects\edgars-mcp
doppler configure
```
應顯示 `project=handcraft-mcp config=prd`。

---

## 12. 檔案結構快查

```
mcp-handcraft/
├── server.py          stdio MCP server（skeleton）
├── server_http.py     HTTP MCP server（主力）
├── run.cmd            啟動 stdio（doppler run --）
├── run_http.cmd       啟動 HTTP（doppler run --）
├── GUIDE.md           客戶端連線設定指南
├── DOPPLER.md         Doppler 架構說明
├── OPS.md             本文件（操作手冊）
└── README.md          專案說明
```

---

## 13. 相關連結

| 資源 | 網址 |
|---|---|
| 外網端點 | https://mcp.edgars.tools/mcp |
| Doppler Web UI | https://dashboard.doppler.com |
| Doppler 官方 fork | https://github.com/Edgars-tool/python-doppler-env |
| Cloudflare DNS | https://dash.cloudflare.com |
