---
lang: zh-TW
---

# Linear 委派給 Hermes Agent — 新手版（給德德）

> 最後更新：2026-06-30  
> 問題現象：在 Linear 把 issue **委派（Delegate）** 給「Hermes Agent」後，畫面顯示 **Did not respond**（沒有回應）。
>
> **硬護欄：這份文件的正式 webhook 入口是 `webhooks.edgars.tools`（gateway ingress），不是 `hooks.edgars.tools`（Cloudflare Worker inbox）。**

---

## 這是什麼？（白話）

Linear 的「Agent」不是普通機器人帳號。你把 issue 委派給 Hermes 時，Linear 會：

1. 開一個 **Agent Session**（代理工作階段）
2. 用 **Webhook** 通知你的後端：「有人委派給你了」
3. 等你的後端在 **10 秒內** 先回一句「我收到了」（官方叫 `thought` activity）
4. 等 Hermes 真正做完後，再回 **正式結果**（`response` activity）

**OAuth 登入成功**（例如 EDG-285 smoke test）只代表 Hermes **有權限** 讀寫 Linear。  
**人類委派流程** 還需要：**Webhook 有收到 + 10 秒內回 thought + 做完回 response**。  
缺任何一環，Linear 就會顯示 **Did not respond**。

---

## 官方文件（必讀連結）

| 主題 | 連結 |
|------|------|
| Agent 入門 | https://linear.app/developers/agents |
| Agent Session / Webhook / Activity API | https://linear.app/developers/agent-interaction |
| 最佳實踐（10 秒 thought 規則） | https://linear.app/developers/agent-best-practices |
| OAuth `actor=app` + scopes | https://linear.app/developers/oauth-actor-authorization |
| Webhook 簽章驗證 | https://linear.app/developers/webhooks |
| 使用者文件（怎麼委派） | https://linear.app/docs/agents-in-linear |

### 官方要求摘要

| 項目 | 要求 |
|------|------|
| OAuth scopes | `read`, `write`, `app:assignable`, `app:mentionable` |
| 安裝方式 | OAuth URL 加 `actor=app`（以 App 身分，不是個人） |
| Webhook 類別 | 必須勾選 **Agent session events** |
| 收到 `created` 事件後 | **10 秒內** 送 `agentActivityCreate`，type=`thought` |
| Webhook 回應 | **5 秒內** HTTP 200/202（可先 ack，背景再跑 Hermes） |
| 做完工作後 | 送 type=`response`（或 `error` / `elicitation`） |
| 回寫 API | `agentActivityCreate` **只能用 OAuth App token**，個人 API Key 會被拒 |

---

## 我們的架構（誰負責什麼）

```
你在 Linear 委派 issue 給 Hermes Agent
        │
        ▼
Linear 送 AgentSessionEvent webhook
        │
        ▼
https://webhooks.edgars.tools/webhooks/linear   ← 公開入口（Cloudflare Tunnel）
        │
        ▼
linear-orchestrator（Windows，port 8645）            ← 中介層（必須在跑）
   1. 驗簽章
   2. 10 秒內回 thought（「收到委派…」）
   3. 叫 Hermes CLI 做事
   4. 用 OAuth token 回 response 到 Linear
        │
        ▼
Linear 顯示 Hermes 有回應（不再是 Did not respond）
```

### 各元件現況

| 元件 | 位置 | 現況 | 能不能完成委派流程 |
|------|------|------|-------------------|
| **OAuth** | `mcp.edgars.tools/linear/oauth/*` | ✅ 已通（EDG-285） | 只解決「有權限」，不解決 webhook |
| **mcp-handcraft webhook** | `mcp.edgars.tools/webhook/linear` | ⚠️ 只收 log，**不會回 Linear** | ❌ |
| **edgars-hooks Worker** | `hooks.whoasked.vip` | ⚠️ 骨架，只存 R2/D1 | ❌ |
| **webhooks.edgars.tools** | tunnel → `:8645` | ✅ 正式 Hermes webhook 入口 | ✅（若 tunnel + service 正常） |
| **linear-orchestrator** | Windows `:8645` + tunnel | ✅ 正確實作（需確認有在跑） | ✅（若 tunnel + service 正常） |

> **結論**：OAuth 成功 ≠ 委派成功。必須走 **linear-orchestrator** 這條路。

---

## 為什麼會「Did not respond」？（根因）

通常是下面 **一個或多個** 同時成立：

### 1. Webhook 沒送到能處理的地方

- Linear App 設定的 Webhook URL 指到 **沒在跑的網址**（例如舊的 `webhook.whoasked.vip`）
- 或指到 **mcp-handcraft**（只 ack、不寫回 Linear）
- 或 **cloudflared tunnel 沒跑 / 指錯 port** → 502/530

### 2. 10 秒內沒送 `thought`

Linear 官方規定：收到 `AgentSessionEvent` 的 `created` 後，**10 秒內** 必須有 agent activity。  
若 Hermes 跑很久才第一次回 Linear，UI 會先顯示 **Did not respond**。

> 2026-06-30 已在 `linear-orchestrator` 加上：收到委派後 **立刻** 送 `thought`「收到委派，Hermes 開始處理…」。

### 3. 回寫用了錯的 token

`agentActivityCreate` 只能用 **OAuth App token**（client_credentials），不能用個人 `lin_api_...` Key。

需要在 **`%USERPROFILE%\.hermes\.env`**（或 Doppler `handcraft-mcp/prd`）有：

- `LINEAR_OAUTH_CLIENT_ID`
- `LINEAR_OAUTH_CLIENT_SECRET`

（跟 Doppler `handcraft-mcp/prd` 裡 Hermes Agent 那組一樣）

### 4. linear-orchestrator 沒在跑

即使 tunnel 正常，Windows 上 orchestrator 停了就沒人接 webhook。

---

### 4. WSL 搶 localhost:8645（2026-06-30 實際根因）

`healthz` 200 **不代表** 委派 webhook 有到 Windows orchestrator。

若 WSL 裡還跑舊版 `linear-orchestrator`：

- `wslrelay` 佔 `127.0.0.1:8645`
- tunnel → `localhost:8645` → **WSL 舊版**（可能缺 OAuth webhook secret / 沒 thought ack）
- Windows 版 log **完全沒有** `AgentSessionEvent` → Linear 顯示 **Did not respond**

修復：停 WSL 舊版、重啟 Windows 版（啟動腳本已自動處理）。

---

## 你要做的檢查清單（照順序）

### 步驟 0：Hermes Agent App ≠ Workspace Webhook（必讀）

Linear 有 **兩套** webhook，容易搞混：

| 設定位置 | 用途 | 委派給 Hermes 需要嗎？ |
|----------|------|------------------------|
| **Settings → API → Hermes Agent**（OAuth 應用程式） | Agent Session、OAuth App 事件 | ✅ **必須** |
| **Settings → Webhooks → linear-orchestrator**（工作區 webhook） | Issue / Comment 一般事件 | ❌ 不能取代上面 |

**委派（Delegate）只會觸發 OAuth App 的 `AgentSessionEvent`**，不會走 workspace webhook。

### 步驟 1：確認 Hermes Agent OAuth App 設定

打開 [linear.app/settings/api](https://linear.app/settings/api) → 點 **Hermes Agent**（OAuth 應用程式那一列，不是下方 Webhooks 區）：

| 欄位 | 應該是 |
|------|--------|
| Redirect URI | `https://mcp.edgars.tools/linear/oauth/callback` |
| **Webhook URL** | `https://webhooks.edgars.tools/webhooks/linear` |
| **Webhook 已啟用** | ✅ 打開 |
| **Agent session events** | ✅ **必須勾選**（沒勾 = 委派永遠 Did not respond） |
| Scopes | 含 `app:assignable`, `app:mentionable` |

**Signing secret（重要）：**

1. 在同一頁複製 Hermes Agent 的 **Signing secret**
2. 貼到 `%USERPROFILE%\.hermes\.env` 的 `LINEAR_OAUTH_WEBHOOK_SECRET=...`
3. Workspace webhook 的 secret 放 `LINEAR_WEBHOOK_SECRET=...`（兩個可能不同，orchestrator 會都試）

> ❌ 不要只改 **Settings → Webhooks → linear-orchestrator** 就以為委派會通。

### 步驟 2：確認 tunnel + orchestrator 活著

在 **Windows PowerShell**：

```powershell
cd G:\AI_WORK_512\repos\linear-orchestrator
powershell -ExecutionPolicy Bypass -File .\scripts\Check-LinearOrchestrator.ps1 -Public
```

本機：

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8645/healthz" -UseBasicParsing
```

公網（tunnel 修好後）：

```powershell
Invoke-WebRequest -Uri "https://webhooks.edgars.tools/healthz" -UseBasicParsing
```

若公網 530/502：到 Cloudflare Dashboard 把 **webhooks.edgars.tools** 指到 **`http://localhost:8645`**（見下方 tunnel 設定）。

若本機 FAIL：先啟動 orchestrator：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Start-LinearOrchestrator.ps1 -Wait
```

### 步驟 3：確認 OAuth 密碼在 orchestrator 端

Windows `%USERPROFILE%\.hermes\.env` 需有（名稱一字不差）：

```
LINEAR_OAUTH_CLIENT_ID=...
LINEAR_OAUTH_CLIENT_SECRET=...
LINEAR_WEBHOOK_SECRET=...              # workspace webhook signing secret
LINEAR_OAUTH_WEBHOOK_SECRET=...        # Hermes Agent App 頁的 signing secret（委派必備）
LINEAR_API_KEY=lin_api_...             # 一般 comment 用（非 agent session 時）
HERMES_PATH=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\hermes.exe
```

（路徑可省略，啟動腳本會自動找 Hermes 桌面版。）

Doppler 專案 `handcraft-mcp` / config `prd` 可複製；**不要貼在聊天**。

### 步驟 4：再試一次委派

1. 開一個測試 issue（或 EDG-285）
2. 按 **Delegate** → 選 **Hermes Agent**
3. 應在 **幾秒內** 看到「收到委派，Hermes 開始處理…」
4. Hermes 跑完後看到正式回覆

### 步驟 5：還是失敗？看 log

| 看哪 | 指令 |
|------|------|
| orchestrator | `Get-Content G:\AI_WORK_512\run\linear-orchestrator\orchestrator.err.log -Tail 30` |
| 最近 webhook | 瀏覽器開 `http://127.0.0.1:8645/`（dashboard） |
| Hermes | Hermes 桌面版 APP 的 log / 設定 |

---

## Hermes 需要「技能」嗎？

**要，但分兩層：**

### 層 1：基礎設施（linear-orchestrator）

這不是 Hermes skill，是 **獨立 Python 服務**：

- Repo：https://github.com/Edgar-s-Tool/linear-orchestrator
- 負責 webhook → thought → 叫 Hermes → response
- 文件：`G:\AI_WORK_512\repos\linear-orchestrator\docs\WINDOWS-SETUP.zh-TW.md`

### 層 2：Hermes 執行時 skill

orchestrator 叫 Hermes 時會加 `--skills linear`，載入 Linear 相關 skill 讓 agent 知道怎麼讀 issue、留言。

相關 skill 參考：

- `V:\projects\linear-webhook-bridge\SKILL.md` — 四層 bridge 設計
- `./plugins/linear/skills/linear-agent-session/SKILL.md` — Agent Session 協定

**Hermes 本身不會自動知道 Agent Session 協定**；必須靠 orchestrator 處理 webhook + API 回寫。

---

## 常見 Q&A

**Q：OAuth status 顯示 OK，為什麼委派還是 Did not respond？**  
→ OAuth 只驗「App 已安裝」。委派還需要 webhook 送達 + 10 秒 thought + response。

**Q：webhooks.edgars.tools 跟 mcp.edgars.tools/webhook/linear 差在哪？**  
→ **webhooks.edgars.tools** 走 tunnel → linear-orchestrator，會在 10 秒內回 thought。**mcp.edgars.tools/webhook/linear** 只記 log，不能當 Agent webhook。

**Q：hooks.whoasked.vip 可以嗎？**  
→ 那是 `edgars-hooks` Worker 骨架，**只存事件、不會叫 Hermes**。不能當 Agent webhook 終點。

**Q：我可以只用 mcp.edgars.tools 嗎？**  
→ `/webhook/linear` 目前只記 log，**不會** `agentActivityCreate`。不行。

**Q：誰來改 production？**  
→ 改 Linear App webhook URL、tunnel、Windows orchestrator 都要你確認後再做。AI 可以準備步驟，不會偷偷 deploy。

---

## 給 AI 的修復優先順序

1. Linear App webhook → `https://webhooks.edgars.tools/webhooks/linear` + 啟用 Agent session events  
2. Windows `linear-orchestrator` running + OAuth env 齊  
3. cloudflared tunnel 指到 **Windows `http://localhost:8645`**  
4. 確認 thought ack（10 秒規則）  
5. Hermes 桌面版 CLI + `linear` skill 可跑  
6. 舊 `webhook.whoasked.vip` tunnel 路由可刪除（已遷移）

---

## Cloudflare Tunnel 設定（webhooks.edgars.tools）

Dashboard → **edgar-local-01-tunnel** → **Add a public hostname**（或編輯既有）：

| 欄位 | 值 |
|------|-----|
| **Subdomain** | `webhooks` |
| **Domain** | `edgars.tools` |
| **Service type** | HTTP |
| **URL** | `http://localhost:8645` |

DNS 會自動建立 CNAME（同 **mcp.edgars.tools** 模式，指向 `*.cfargotunnel.com`）。勿手動 A 到 `127.0.0.1`。

驗證：`https://webhooks.edgars.tools/healthz` 應回 200。

---

## 開機自動啟動（Windows）

```cmd
G:\AI_WORK_512\repos\linear-orchestrator\scripts\install-windows-scheduled-task.cmd
```

---

## 相關檔案

| 檔案 | 用途 |
|------|------|
| `config/linear-oauth-manifest.json` | OAuth App 設定草稿 |
| `docs/Linear-OAuth設定-新手版.md` | OAuth 授權步驟 |
| `G:\AI_WORK_512\repos\linear-orchestrator\` | Webhook 中介實作 + Windows 啟動腳本 |
| `G:\AI_WORK_512\repos\cloudflared\HERMES-WEBHOOK.md` | Tunnel + 架構運維 |
