# ChatGPT Connector OAuth Incident (2026-07-06)

## 結論先講

這次 `MCP server https://mcp.edgars.tools/mcp does not implement OAuth` 的根因，不是手刻 MCP server 沒做 OAuth，而是 **Cloudflare edge 在 request 到 origin 之前就先回了 403**。

真正卡住 ChatGPT 的點有兩層：

1. **Cloudflare Tunnel route** 上開了 `Enforce Access JWT validation`
2. **WAF / Bot Fight** 對 `/.well-known/*` 與 `/mcp` 還有額外攔截

只要 request 還沒到 `server_http.py`，ChatGPT 就拿不到：

- `/.well-known/oauth-protected-resource`
- `/.well-known/oauth-authorization-server`
- `/.well-known/openid-configuration`
- `/mcp` 回的 `401 + WWW-Authenticate`

它就會直接判定「does not implement OAuth」。

---

## 事故現象

### ChatGPT UI 症狀

- 建立 Connector 時顯示：
  - `MCP server https://mcp.edgars.tools/mcp does not implement OAuth`

### 外部探測症狀

當時從 public 看到：

- `GET https://mcp.edgars.tools/.well-known/oauth-protected-resource` -> `403`
- `GET https://mcp.edgars.tools/.well-known/oauth-protected-resource/mcp` -> `403`
- `GET https://mcp.edgars.tools/.well-known/oauth-authorization-server` -> `403`
- `GET https://mcp.edgars.tools/.well-known/openid-configuration` -> `403`
- `GET/POST https://mcp.edgars.tools/mcp` -> `403`

### 本機 origin 狀態

本機其實是好的：

- `http://127.0.0.1:8765/.well-known/oauth-protected-resource` -> `200`
- `http://127.0.0.1:8765/.well-known/oauth-authorization-server` -> `200`
- `http://127.0.0.1:8765/.well-known/openid-configuration` -> `200`
- `http://127.0.0.1:8765/mcp` 無 token -> `401`

白話：
**OAuth 文件在 origin 有，ChatGPT 只是被 Cloudflare 擋到看不到。**

---

## 真正根因

### 根因 1：Tunnel route 強制 JWT 驗證

在 Cloudflare Tunnel `edgar-local-01-tunnel` 的 `mcp.edgars.tools` route 上，
`Enforce Access JWT validation` 被打開。

這個設定的效果是：

- 任何沒有 `Cf-Access-Jwt-Assertion` 的 request
- 會直接在 tunnel / edge 層被擋掉
- 不會進到 `server_http.py`

這和 Access App 的 `Bypass Everyone` 是不同層的機制。

重點：

- **Access App policy bypass 不會自動關閉 tunnel JWT enforcement**
- 所以就算 Access App 看起來「放行」，request 還是可能被 tunnel 層先 `403`

### 根因 2：WAF / Bot Fight 還在碰 OAuth discovery 路徑

`/.well-known/*` 和 `/mcp` 對 ChatGPT 來說不是一般網頁，而是 OAuth / MCP discovery 契約的一部分。

如果這些 path 還會吃到：

- Bot Fight Mode
- Browser Integrity Check
- Managed rules
- Security level

就可能出現：

- `403 challenge`
- `403 forbidden`
- 某些 client 被擋、某些 client 看起來沒事

---

## 這次有效修法

### Cloudflare side

1. **關閉 tunnel route 的 JWT 強制驗證**
   - `Cloudflare One -> Network -> Tunnels -> edgar-local-01-tunnel -> Published application routes -> mcp.edgars.tools`
   - `Enforce Access JWT validation` -> `Off`

2. **把 `/.well-known/*` 和 `/mcp` 的 skip 規則擴到完整 enough**
   - 至少要讓以下元件不再碰它們：
     - managed rules
     - security level
     - super bot fight
     - browser integrity

3. **關閉 Bot Fight Mode**
   - 否則即使 Access / origin 正常，edge 還是可能先 challenge

### Repo side

1. 修正健康檢查與狀態頁的判準
   - 不再把 `403` 自動當「正常防護」
   - 改成分開看：
     - edge reachable
     - ChatGPT OAuth readiness

2. 補驗：
   - `/.well-known/oauth-protected-resource` 是否真的 `200`
   - `/mcp` 無認證是否回 `401`

---

## 正式驗收標準

若目標是 **ChatGPT Connector OAuth 可安裝**，至少要同時滿足：

1. `GET /.well-known/oauth-protected-resource` -> `200`
2. `GET /.well-known/oauth-protected-resource/mcp` -> `200`
3. `GET /.well-known/oauth-authorization-server` 或 `/.well-known/openid-configuration` -> `200`
4. `GET /mcp` 無認證 -> `401`
5. `POST /mcp` 無認證 -> `401`
6. `WWW-Authenticate` 要帶：
   - `resource_metadata="https://mcp.edgars.tools/.well-known/oauth-protected-resource/mcp"`

如果只有下面這種狀態：

- `/mcp` 回 `403`
- PRM 回 `403`

那不叫安全，也不叫健康。
那叫 **ChatGPT 還沒碰到你的 OAuth**。

---

## 以後再遇到時，先看什麼

照這個順序，不要亂猜：

1. 本機 origin 是否正常
   - `http://127.0.0.1:8765/health`
   - `http://127.0.0.1:8765/.well-known/oauth-protected-resource`

2. public PRM 是否 `200`
   - `https://mcp.edgars.tools/.well-known/oauth-protected-resource`

3. public AS metadata 是否 `200`
   - `https://mcp.edgars.tools/.well-known/oauth-authorization-server`
   - `https://mcp.edgars.tools/.well-known/openid-configuration`

4. public `/mcp` 無認證是否回 `401`
   - `GET /mcp`
   - `POST /mcp`

5. 若 public 還是 `403`
   - 先查 tunnel route 的 JWT enforcement
   - 再查 WAF / Bot Fight / Browser Integrity
   - 最後才查 Python code

---

## 這次的完成證據

修正後已驗證：

- `/.well-known/oauth-protected-resource` -> `200`
- `/.well-known/oauth-protected-resource/mcp` -> `200`
- `/.well-known/oauth-authorization-server` -> `200`
- `/.well-known/openid-configuration` -> `200`
- `GET /mcp` 無認證 -> `401`
- `POST /mcp` 無認證 -> `401`

而且 ChatGPT 端已成功顯示：

- `edgars-mcp 已安裝`

本機 log 也看到：

- `clientInfo.name = "openai-mcp (ChatGPT)"`
- ChatGPT 成功打到 `initialize`

---

## 殘留注意事項

目前 log 還看到 ChatGPT 有打：

- `resources/list`

而目前 server 回：

- `Method not found: resources/list`

這**不影響這次 OAuth 安裝成功**，但如果未來要讓 ChatGPT app 端展示更完整的 resource 能力，可以評估是否補上 `resources/list`。

---

## 一句話版

若下次再看到：

- `does not implement OAuth`

先不要急著重寫 MCP server。
先確認是不是 **Cloudflare edge 根本沒把 OAuth discovery request 送到 origin**。
