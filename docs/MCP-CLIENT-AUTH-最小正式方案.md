# MCP 給 Codex / Claude / Hermes 的最小正式 client auth 方案

這份文件只定義**最小正式方案**，目標是讓人類與機器客戶端各走一條穩定路線，不再混用。

## 一句話版

- **人類互動式 client**：走 **Cloudflare Access Managed OAuth**
- **機器 / agent client**：走 **Cloudflare Access service token**
- **Edgar 自己的本機開發機**：優先走 **localhost + stdio proxy + `MCP_API_TOKEN`**

---

## 建議分流

| 使用情境 | 建議方案 | 原因 |
|---|---|---|
| ChatGPT / 瀏覽器需要人登入 | Managed OAuth | 會自動打開登入流程，符合人類互動習慣 |
| Codex / Claude / Hermes 在 Edgar 自己的 Windows 機器上 | `stdio_proxy.py` → `http://127.0.0.1:8765/mcp` + `MCP_API_TOKEN` | 最簡單、最穩、完全不依賴 public edge |
| Codex / Claude / Hermes 在遠端或雲端 agent | `stdio_proxy.py` → `https://mcp.edgars.tools/mcp` + `CF-Access-Client-Id/Secret` | 不需要人登入，也不用暴露 `MCP_API_TOKEN` |
| CI / cron / fully automated agent | 直接 HTTP + service token，或 stdio proxy + service token | 正式機器身分，方便輪替 |

---

## 最小正式標準

### 1. 本機 Edgar 開發機

適合：

- Claude Desktop
- Hermes
- Codex / Cursor 類需要 stdio server 的客戶端

路徑：

```text
client -> stdio_proxy.py -> http://127.0.0.1:8765/mcp
```

認證：

```text
Authorization: Bearer <MCP_API_TOKEN>
```

優點：

- 不經 public edge
- 不吃 Access / Bot Fight / WAF
- 最適合日常開發與維護

範例：

- [`config/mcp.local.example.json`](../config/mcp.local.example.json)

### 2. 遠端 agent / 雲端 client

適合：

- Codex cloud agent
- Claude Code cloud / remote workflow
- Hermes 若不是跑在 Edgar 本機
- 其他 headless agent

路徑：

```text
client -> stdio_proxy.py -> https://mcp.edgars.tools/mcp
```

認證：

```text
CF-Access-Client-Id: <service-token-client-id>
CF-Access-Client-Secret: <service-token-client-secret>
```

這是 Cloudflare Access 的機器身分，不是人類登入 OAuth。

範例：

- [`config/mcp.remote.stdio.example.json`](../config/mcp.remote.stdio.example.json)

### 3. 人類互動式 public client

適合：

- 會自動打開瀏覽器的 OAuth client
- 需要把請求綁定到真實使用者身份

路徑：

```text
client -> https://mcp.edgars.tools/mcp
```

認證：

- Cloudflare Access Managed OAuth

特性：

- 對人方便
- 對機器不方便
- 不適合無人值守 agent

---

## `stdio_proxy.py` 現在支援的 auth

### Bearer token

可讀環境變數：

- `MCP_API_TOKEN`
- `MCP_AUTH_TOKEN`
- `HERMES_HANDCRAFT_MCP_TOKEN`

### Cloudflare Access service token

可讀環境變數：

- `MCP_CF_ACCESS_CLIENT_ID`
- `MCP_CF_ACCESS_CLIENT_SECRET`

向後相容：

- `CF_ACCESS_CLIENT_ID`
- `CF_ACCESS_CLIENT_SECRET`
- `HERMES_HANDCRAFT_CF_ACCESS_CLIENT_ID`
- `HERMES_HANDCRAFT_CF_ACCESS_CLIENT_SECRET`

當 service token 有設定時，proxy 會自動送：

```text
CF-Access-Client-Id
CF-Access-Client-Secret
```

---

## 對 Codex / Claude / Hermes 的最小正式建議

### Codex

- **Edgar 本機**：local stdio + `MCP_API_TOKEN`
- **遠端 / cloud**：remote stdio + Cloudflare service token

### Claude

- **Edgar 本機**：local stdio + `MCP_API_TOKEN`
- **遠端 / cloud**：remote stdio + Cloudflare service token

### Hermes

- **Edgar 本機**：local stdio + `MCP_API_TOKEN`
- **遠端 / cloud**：remote stdio + Cloudflare service token

---

## 不建議的做法

- 不要讓 Codex / Claude / Hermes 長期依賴人類瀏覽器登入
- 不要把 `MCP_API_TOKEN` 拿去當 public 遠端 client 的正式主方案
- 不要把 service token 寫死在 repo

---

## 最小輪替策略

### `MCP_API_TOKEN`

- 只給 localhost / 本機維運使用

### Cloudflare service token

- 給遠端 agent / headless client
- 之後若要正式化再做：
  - 每個 client 一組
  - 週期輪替
  - 失效時個別撤銷

---

## 最終推薦

如果只選一套最不煩、最穩的方案：

1. **Edgar 本機**：`stdio_proxy.py` + `MCP_API_TOKEN`
2. **所有遠端 agent**：`stdio_proxy.py` + Cloudflare Access service token
3. **只有人類需要互動登入時**：Managed OAuth
