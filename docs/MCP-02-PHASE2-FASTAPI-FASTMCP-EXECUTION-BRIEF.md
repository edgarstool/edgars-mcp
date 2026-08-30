# MCP v2 Phase 2 施工任務書：FastAPI 外層 + FastMCP 局部 Metadata

狀態：草案，等王世鈞（Edgar）確認後才可開工
撰寫日期：2026-08-30
承接文件：`docs/MCP-01-C.md`（架構決策報告）、`docs/V2-手刻升級清單.md`（手刻升級原則）
保護點（rollback 用）：`checkpoint/pre-phase2-fastapi-fastmcp`（commit `9b0915fa`，已推上 `origin`）

---

## 0. 給執行代理（Codex / Claude Code）的一句話原則

> **外層 HTTP/ASGI/路由/headers/CORS 交給 FastAPI；OAuth discovery（`/.well-known/*`、PRM、WWW-Authenticate 挑戰）這一小層局部交給 FastMCP 的 `RemoteAuthProvider`；token 驗證、84 個工具的業務邏輯、webhook、Linear OAuth、Honcho proxy 全部保留手刻，原封不動搬過去掛成路由。**

不是重寫，是「換外殼、留內臟」。任何一步如果變成「順手把 XX 也改用官方 SDK / FastMCP 寫」，就是範圍蔓延（scope creep），要停下來回報，不要自己延伸。

---

## 1. 為什麼做這件事（Why）

現有 `server_http.py`（8887 行）是純 Python 標準庫手刻的 `BaseHTTPRequestHandler`，用一堆 `if path == ...` 手動比對路由。這在早期（協議不穩、要完全掌控 discovery 細節時）是對的選擇，`docs/MCP-01-P.md` 整理的社群經驗也支持「手刻換取完全控制」這個理由。

但現在的問題是：

1. **路由層太脆弱**：任何一個 `/.well-known/*` 路徑錯字、漏加一個 elif分支，就會讓 ChatGPT 或 Claude 的 OAuth discovery 整個失敗（這次已經修過一輪：RFC 9728 Protected Resource Metadata 缺失、issuer 不一致）。這類問題會持續發生，因為手刻路由沒有框架幫你檢查一致性。
2. **CORS / headers 邏輯散落各處**：`_add_cors_headers()`、`_validate_streamable_http_content_headers()` 這些要在每個 handler 手動呼叫，容易漏。
3. **discovery/metadata 產生完全靠手刻字串組 JSON**：容易出現這次遇到的「issuer 對不上」「resource 欄位打錯」這類低階錯誤，而這正是 FastMCP 的 `RemoteAuthProvider` 已經自動化、且被業界大量驗證過的部分（`docs/MCP-01-C.md` F14：FastMCP 目前市佔最大宗）。

**Phase 2 不是為了趕流行，是為了把「最容易手滑出錯、而且已經出錯過」的那一層，換成有社群大量驗證過的實作，同時保留你最在意的：token 驗證邏輯、業務邏輯、對 Cloudflare/proxy 行為的完全掌控。**

---

## 2. 現況基線（Baseline，2026-08-30 量測）

| 項目 | 數值 |
|---|---|
| `server_http.py` 行數 | 8887 行 |
| HTTP server 實作 | `ThreadingHTTPServer(ThreadingMixIn, HTTPServer)`，單一 `MCPHTTPHandler(BaseHTTPRequestHandler)` |
| 啟動方式 | `run_http.cmd` → `op.exe run --env-file .env.op -- python server_http.py`，`server.serve_forever()`，單一 port（常數 `PORT`） |
| MCP 工具數量 | 84 個（`TOOLS = [...]` 靜態清單 + `mmx_handlers.DISPATCH` 額外掛載） |
| 已安裝但未使用的套件 | `fastmcp==3.2.0`（環境裡已經有，但 code 完全沒 import） |
| 尚未安裝 | `fastapi`（import 直接失敗） |
| Git 保護點 | branch `checkpoint/pre-phase2-fastapi-fastmcp` @ `9b0915fa`，已推到 `origin` |

### 2.1 現有路由清單（do_GET / do_POST / do_DELETE 逐條列出，Phase 2 必須全部等價保留）

**GET**
- `/.well-known/oauth-authorization-server`（RFC 8414）
- `/.well-known/oauth-protected-resource`（RFC 9728，全域）
- `/.well-known/oauth-protected-resource/mcp`（RFC 9728，`/mcp` 專用）
- `/.well-known/oauth-protected-resource/chatgpt-honcho`（ChatGPT-Honcho gateway 專用，authorization_server 指向 Cloudflare Access team domain，跟其他兩個不一樣，**這是最容易漏掉的分支**）
- `/.well-known/openid-configuration`
- `/authorize`（內建 OAuth authorize 端點）
- `/health`（`HEALTH_PATH`，部分情境需要 Cloudflare Access 驗證才能存取）
- `/linear/oauth/authorize`、`/linear/oauth/callback`、`/linear/oauth/status`、`/linear/oauth/bootstrap`
- `/mcp`、`/chatgpt-honcho`（Streamable HTTP 規範明定：無 server-initiated SSE 時，已驗證的 GET 要回 405 + `Allow: POST, OPTIONS`，不是 404）

**POST**
- `/token`（內建 OAuth token 端點）
- `/register`（RFC 7591 動態客戶端註冊 DCR）
- `/webhook/discord`
- `/webhook/package`（`PACKAGE_WEBHOOK_PATH`）
- `/webhook/linear`、`/webhooks/linear`（兩個路徑都要接受，Linear 官方用複數形）
- `/honcho-mcp`（`HONCHO_MCP_PATH`）
- `/mcp`（當 request hostname 等於 `honcho_mcp_hostname` 時，走 Honcho proxy 分支，**不是走一般 MCP 邏輯**——這是一個依賴 Host header 判斷行為的隱藏分支，遷移時最容易漏）
- `/chatgpt-honcho`
- `/mcp`（一般情況）：先驗證授權 → 驗證 Streamable HTTP content headers → 驗證 Origin（防 DNS rebinding）→ 讀 body → 進 JSON-RPC dispatch

**DELETE**
- 至少對 `/chatgpt-honcho`、`/mcp` 有專屬處理（session 終止語意，Streamable HTTP 規範的一部分）

**OPTIONS**
- 全域 CORS preflight，回 200 + CORS headers

### 2.2 授權模式（三選一，運行時動態判斷，Phase 2 絕對不能改變判斷邏輯本身）

`main()` 啟動時 log 出三種模式：
1. Cloudflare Access managed public endpoint（`config.cloudflare_access_enabled`）
2. Descope JWT validation（`config.descope_enabled`，這次剛加的）
3. Built-in bearer/OAuth（預設）

三者互斥判斷寫在 `_ensure_mcp_request_authorized()` 與 `_requires_cloudflare_access_for_request()`。**這段是全案風險最高的部分，Phase 2 絕對不能重寫這段邏輯，只能原封不動搬過去當一個 dependency / middleware 呼叫。**

---

## 3. 目標架構（Target Architecture）

```
┌─────────────────────────────────────────────────────┐
│  FastAPI app（ASGI 外層，新加）                        │
│  - 路由註冊、CORS middleware、headers 統一管理           │
│  - mount 手刻邏輯（下面兩塊）                            │
├─────────────────────────────────────────────────────┤
│  A. FastMCP RemoteAuthProvider（局部，只管 metadata）    │
│     - /.well-known/oauth-authorization-server         │
│     - /.well-known/oauth-protected-resource(+variants)│
│     - WWW-Authenticate 401 挑戰產生                     │
│     ⚠️ 需要客製化 resource 欄位（F15 已知 bug：預設回根網址）│
│     ⚠️ 需要客製化 path-aware well-known（F15 已知 404 坑）│
├─────────────────────────────────────────────────────┤
│  B. 手刻邏輯層（原封不動搬移，只改「怎麼被呼叫」不改「內容」）│
│     - _ensure_mcp_request_authorized（三模式授權判斷）    │
│     - 84 個工具 + mmx_handlers.DISPATCH                │
│     - Linear OAuth 全流程                              │
│     - Honcho proxy、ChatGPT-Honcho gateway             │
│     - 所有 webhook（Discord/Package/Linear）            │
│     - /token、/register（DCR）——是否交給 FastMCP 待評估   │
└─────────────────────────────────────────────────────┘
```

**明確不動的東西**：
- `HandcraftServerConfig` dataclass 與其三種授權模式判斷邏輯
- `TOOLS` 清單與所有 `handle_*` 工具函式本體
- `mmx_handlers.DISPATCH`
- Descope/Cloudflare Access 的 JWT 驗證細節
- Linear OAuth 全流程（authorize/callback/status/bootstrap + token 儲存）
- 所有 webhook handler 的簽章驗證邏輯

---

## 4. 已知地雷與強制驗證動作（引用 `docs/MCP-01-C.md` F14/F15/F18，不可省略任何一項）

| 地雷 | 來源 | 強制驗證動作 |
|---|---|---|
| FastMCP `RemoteAuthProvider` 的 PRM `resource` 欄位預設固定回根網址，不是實際 `/mcp` 端點 | PrefectHQ/fastmcp #1348 | Phase 2 完成後，逐一 curl 每個 `/.well-known/oauth-protected-resource*` 變體，人工比對 `resource` 欄位是否等於「該端點自己的完整 URL」，不能全部回根網址 |
| `mcp` 依賴 1.17+ 後，well-known endpoint 改成「路徑感知」位置；`/.well-known/oauth-protected-resource` 可能回 404，只有帶路徑後綴的版本回 200 | PrefectHQ/fastmcp #2077 / #2123 | 對照本文件 2.1 節列出的**全部 4 個 well-known 變體**逐一測試，尤其是 `chatgpt-honcho` 那個要指向 Cloudflare Access issuer 而非內建 AS 的分支 |
| FastAPI/FastMCP 掛進彼此若 lifespan 沒合併好，會炸 `StreamableHTTPSessionManager task group was not initialized` | `docs/MCP-01-C.md` F18 | 啟動後第一件事：對 `/mcp` 打一個完整的 `initialize` → `tools/list` → 呼叫一個工具的完整流程，跑通才算過，不能只看 server 有沒有噴 exception 就當作成功 |
| FastMCP 預設 `transport="http"` + `host="0.0.0.0"` 完全無 auth | `docs/MCP-01-P.md` | FastMCP 只拿來產生 metadata，本身不能直接對外聽 port；必須確認最終 bind 的是 FastAPI/Uvicorn，FastMCP 只是被 mount 進去的 sub-app，沒有自己開獨立端口 |
| `Host` header 判斷分支（`/mcp` + hostname == honcho_mcp_hostname → 走 Honcho proxy）容易在框架化路由時被忽略 | 本次盤點（2.1 節） | 這個分支要明確寫成一個 FastAPI dependency 或 middleware，不能只用 path 比對，要連 `Host` header 一起測 |

---

## 5. 分階段執行步驟（每階段都要能獨立驗收、獨立回退）

### Phase 2.0：準備（風險：低）
1. 從 `checkpoint/pre-phase2-fastapi-fastmcp` 切新分支 `feat/mcp-v2-fastapi-fastmcp-phase2`
2. `pip install fastapi uvicorn`，把版本鎖進 `requirements.txt`（`fastmcp` 已經在環境裡但沒鎖版本，順便鎖 `fastmcp==3.2.0` 或評估是否要對齊到報告提到的更新版）
3. 不改任何現有邏輯，先確認 `fastapi` + 已安裝的 `fastmcp` 能一起 import、跑一個最小 hello-world ASGI app 起得來

**驗收**：`uvicorn` 能把一個空的 FastAPI app 跑起來，port 不衝突。
**回退**：刪分支即可，master 完全不受影響。

### Phase 2.1：FastAPI 外層 mount 手刻邏輯（風險：中，這是最大一塊工）
1. 建立 FastAPI app，把 `ThreadingHTTPServer` + `MCPHTTPHandler` 的每一條路由（2.1 節清單）逐一轉成 FastAPI route，**函式內容直接呼叫原本 `MCPHTTPHandler` 裡對應的 `_handle_*` 方法邏輯**（可以先用 adapter 包一層，讓手刻函式簽章不用大改）
2. 把 CORS 從手動 `_add_cors_headers()` 換成 FastAPI 的 `CORSMiddleware`，但要對照現有允許清單（`ALLOWED_HOSTNAMES`）逐一比對，不能改寬也不能改窄
3. `Host` header 分支（Honcho proxy）用 FastAPI 的 dependency 或自訂 middleware 顯式處理
4. **這階段先不碰 FastMCP**，`.well-known/*` 還是先用原本手刻的 JSON 產生邏輯，只是換個方式掛路由——**目的是先驗證「换外殼」這件事本身沒把原本的行為改壞**

**驗收**：MCP Inspector（官方測試工具）跑過 `initialize` → `tools/list` → 抽測 5 個代表性工具（含至少一個會呼叫外部 API 的、一個 mmx_handlers 的）→ 全部等價於 Phase 2 之前。三種授權模式（Cloudflare Access / Descope / built-in bearer）都要各測一次 401/200 行為。
**回退**：整個 Phase 2.1 若卡住，退回 `checkpoint/pre-phase2-fastapi-fastmcp`，`server_http.py` 完全不變。

### Phase 2.2：FastMCP 局部接手 PRM/discovery（風險：中高，地雷最多的一塊）
1. 只把 4 個 well-known 端點（2.1 節列的 4 個變體）換成 FastMCP `RemoteAuthProvider` 產生
2. 針對第 4 節列的兩個已知 bug（resource 欄位、路徑感知 404）逐一寫客製化 override 或 monkey-patch，不能假設裝上就會對
3. `/authorize`、`/token`、`/register`（DCR）**先不動**，維持手刻——這幾個牽涉到實際簽發 token，出錯代價比 metadata 更高，等 2.2 穩定後再評估是否要交出去

**驗收**：完整跑一次「ChatGPT 新增連接器」與「Claude 新增連接器」的完整 OAuth 流程（不是只測 API 回應，是真的走一次使用者會走的路），兩邊都要全綠。第 4 節的每一條驗證動作都要跑過留紀錄。
**回退**：只退 Phase 2.2，Phase 2.1 的 FastAPI 外層保留，well-known 端點退回手刻版本。

### Phase 2.3：收尾與清理（風險：低）
1. 移除舊的 `BaseHTTPRequestHandler`/`ThreadingHTTPServer` 相關 code（確認 Phase 2.1/2.2 都穩定運行至少一週後再刪，不要一次做完馬上刪）
2. 更新 `run_http.cmd`（可能要換成 `uvicorn` 啟動指令而非直接 `python server_http.py`）
3. 更新本文件與 `docs/V2-手刻升級清單.md`，記錄最終落地版本

---

## 6. 整體驗收標準（Definition of Done）

- [ ] MCP Inspector 完整測試通過（`initialize`、`tools/list`、抽測工具呼叫）
- [ ] ChatGPT 連接器：新增 → OAuth 全綠 → 至少成功呼叫一個工具
- [ ] Claude 連接器：新增 → OAuth 全綠 → 至少成功呼叫一個工具
- [ ] 三種授權模式（Cloudflare Access / Descope / built-in bearer）各自的 401/200 行為與 Phase 2 之前逐條比對一致
- [ ] 所有 webhook（Discord / Package / Linear 兩種路徑）功能等價
- [ ] Linear OAuth 全流程（authorize/callback/status/bootstrap）功能等價
- [ ] Honcho proxy（含 Host header 判斷分支）功能等價
- [ ] 84 個工具全部可呼叫，抽測至少 10 個（含最常用與最少用各半）
- [ ] 全程未修改 token 驗證邏輯本體、未把工具業務邏輯交給框架

## 7. 整體回退條件

任一 Phase 出現以下情況，立即停止並回報，不要「先繼續做完再說」：
- ChatGPT 或 Claude 的 OAuth 從綠變紅，且 30 分鐘內無法定位原因
- 任何工具呼叫的回應內容跟 Phase 2 之前不一致（不只是格式，是內容/行為）
- 授權判斷邏輯出現「應該擋卻放行」的情況（安全性問題，優先權最高，立即回退整個 Phase）

回退動作：`git checkout checkpoint/pre-phase2-fastapi-fastmcp`，或視當時進度回退到對應的 Phase 邊界 commit。

---

## 8. Unknown / 待確認事項（不要自己猜，卡住就回報）

1. `fastmcp==3.2.0` 是誰、何時、為何裝進這台機器的環境？跟這次 Phase 2 規劃無關的既有殘留，還是有人已經開始試驗？——**開工前建議先確認，避免踩到別人未完成的實驗**。
2. `/token`、`/register`（DCR）是否要在 Phase 2.2 一併交給 FastMCP，還是永久保留手刻？本文件目前建議「先不動」，但這是可以在 Phase 2.2 驗收後重新評估的開放問題。
3. 目前 production 是跑在哪個 port、單一 process 是否有多 worker 的計畫？`docs/V2-手刻升級清單.md` 提過「多 worker 無狀態確認」，Phase 2 換到 uvicorn 之後，如果之後要開多 worker，要重新確認手刻邏輯裡有沒有偷偷用了 in-memory 全域狀態（例如 `LINEAR_OAUTH_PENDING_STATES` 這種 module-level dict，多 worker 下會失效）。這個目前記錄在案，Phase 2 範圍內不處理，但要寫進已知限制。

---

## 9. 給執行代理的啟動 prompt（可直接複製貼給 Codex / Claude Code）

> 請閱讀 `docs/MCP-02-PHASE2-FASTAPI-FASTMCP-EXECUTION-BRIEF.md` 全文，這是 Phase 2 的完整施工任務書。從 `checkpoint/pre-phase2-fastapi-fastmcp` 切出 `feat/mcp-v2-fastapi-fastmcp-phase2` 分支開始，嚴格按照第 5 節的 Phase 2.0 → 2.1 → 2.2 → 2.3 順序執行，每個 Phase 結束都要跑完該 Phase 的「驗收」項目才能進下一個 Phase。第 6 節的整體驗收標準是最終目標，第 7 節的回退條件是紅線，觸發就停下來回報，不要自己決定要不要繼續。第 4 節列的地雷是已知會出事的地方，每一項都要有對應的驗證證據（curl 輸出、測試截圖或 log），不能只憑「應該沒問題」就跳過。第 8 節的 Unknown 事項，卡住了就回報，不要自己猜測填空。
