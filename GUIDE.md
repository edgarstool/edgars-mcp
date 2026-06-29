# handcraft-mcp 使用指南

連接你的 AI 工具到這台 MCP Server，即可使用 Codex、Claude Code 代理功能。

---

## 快速連接

### MCP Server 資訊

| 項目 | 內容 |
|------|------|
| 端點 | `https://mcp.edgars.tools/mcp` |
| 協議版本 | 2025-11-25 |
| 傳輸方式 | Streamable HTTP (POST) |

---

## 各客戶端設定方式

### Claude Code

在 `~/.claude.json` 的 `mcpServers` 加入：

```json
{
  "mcpServers": {
    "handcraft-mcp": {
      "type": "http",
      "url": "https://mcp.edgars.tools/mcp"
    }
  }
}
```

或直接執行：

```bash
npx mcp-add \
  --name handcraft-mcp \
  --type http \
  --url "https://mcp.edgars.tools/mcp" \
  --clients "claude code"
```

---

### Claude Desktop

在 `claude_desktop_config.json` 加入：

```json
{
  "mcpServers": {
    "handcraft-mcp": {
      "type": "http",
      "url": "https://mcp.edgars.tools/mcp"
    }
  }
}
```

**設定檔位置：**
- Windows：`%APPDATA%\Claude\claude_desktop_config.json`
- macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`

---

### Cursor

#### 本機（推薦：stdio proxy → 本機 HTTP）

1. 先啟動 HTTP server：`.\run_http.cmd` 或 `.\scripts\Start-HandcraftStack.ps1 -SkipPublic`
2. 在 Cursor `Settings > MCP` 加入（也可用 repo 內 `config\mcp.local.example.json`）：

```json
{
  "mcpServers": {
    "handcraft-mcp": {
      "command": "doppler",
      "args": [
        "run",
        "--project", "handcraft-mcp",
        "--config", "prd",
        "--",
        "py", "-3", "V:\\projects\\mcp-handcraft\\stdio_proxy.py"
      ]
    }
  }
}
```

等價啟動命令：`V:\projects\mcp-handcraft\run_stdio.cmd`

`stdio_proxy.py` 會從 Doppler/env 讀 `MCP_API_TOKEN`，轉送到 `http://127.0.0.1:8765/mcp`。

#### 外網（OAuth HTTP）

進入 `Settings > MCP`，新增：

```json
{
  "handcraft-mcp": {
    "type": "http",
    "url": "https://mcp.edgars.tools/mcp"
  }
}
```

外網連線走 MCP 內建 OAuth（見 README 的 ChatGPT 連接器設定）。若 Cloudflare 回 `DNS points to prohibited IP`，需先修正 `mcp.edgars.tools` 的 tunnel DNS（見 OPS.md）。

---

### Windsurf

在 `~/.codeium/windsurf/mcp_config.json` 加入：

```json
{
  "mcpServers": {
    "handcraft-mcp": {
      "type": "http",
      "url": "https://mcp.edgars.tools/mcp"
    }
  }
}
```

---

### VS Code (Copilot)

在 `.vscode/mcp.json` 加入：

```json
{
  "servers": {
    "handcraft-mcp": {
      "type": "http",
      "url": "https://mcp.edgars.tools/mcp"
    }
  }
}
```

---

## 可用工具

### `echo`
測試連線是否正常，回傳你傳入的訊息。

```
輸入：message (string)
輸出：echo: <你的訊息>
```

**範例：**
> 請用 echo 工具傳送 "hello"

---

### `codex_agent`
把任務委派給本機的 Codex AI 代理自動執行。

```
輸入：
  task        (string, 必填) — 要執行的任務描述
  working_dir (string, 選填) — 工作目錄，預設 C:\Users\Windows10-JS
輸出：Codex 執行完成後的最終回覆
```

**範例：**
> 請用 codex_agent 在桌面建立一個 hello.py 並執行它

---

### `claude_code_agent`
把任務委派給本機的 Claude Code 代理自動執行，適合複雜程式碼任務。

```
輸入：
  task        (string, 必填) — 要執行的程式任務
  working_dir (string, 選填) — 工作目錄，預設 C:\Users\Windows10-JS
輸出：Claude Code 執行完成後的最終回覆
```

**範例：**
> 請用 claude_code_agent 幫我分析 C:\Users\Windows10-JS\mcp-handcraft\server_http.py 的結構

---

## 驗證連線

用 curl 測試：

```bash
curl -X POST https://mcp.edgars.tools/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","clientInfo":{"name":"test","version":"1.0"},"capabilities":{}}}'
```

正常回應：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-11-25",
    "serverInfo": { "name": "handcraft-mcp", "version": "0.1.0" },
    "capabilities": { "tools": {} }
  }
}
```

---

## 常見問題

**Q: 連不上怎麼辦？**
先用 curl 測試端點，確認 server 正在運行。

**Q: 工具沒出現？**
重啟客戶端（Claude Code / Cursor），讓它重新讀取 MCP 設定。

**Q: 執行任務太慢？**
`codex_agent` 和 `claude_code_agent` timeout 設為 5 分鐘，複雜任務請耐心等待。
