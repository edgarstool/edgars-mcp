# mcp-handcraft

這個資料夾有兩條不同的 MCP server 入口，請分開使用，不要混用。

## 入口分工

- `run.cmd`
  啟動 `server.py`
  給本地 `stdio` 方式的 MCP client 使用。
  適合 Ollama、龍蝦這類直接用標準輸入輸出溝通的本地流程。

- `run_http.cmd`
  啟動 `server_http.py`
  給 HTTP 方式的 MCP client 使用。
  適合 MCP Inspector、瀏覽器測試、或其他會用 `POST /mcp` 連進來的 client。

- `hermes_stdio_proxy.py`
  給 Hermes 這類只會啟動 stdio MCP server 的 client 使用。
  它不另外實作 tool，只把 stdio JSON-RPC 轉送到 `server_http.py` 的 `POST /mcp`。
  因為它綁定的是本 repo 的 handcraft HTTP MCP endpoint，所以放在 `mcp-handcraft`。

## 現況提醒

- `server.py` 是本地 `stdio` 入口
- `server_http.py` 是 HTTP 入口
- `server_http.py` 目前已接上 `codex_agent`
- `server_http.py` 目前也已接上 `claude_code_agent`

## Claude Code 前提

如果要用 `claude_code_agent`，本機需要先完成：

```powershell
winget install Anthropic.ClaudeCode
claude auth login
```

如果 `claude` 指令不在 PATH，HTTP tool call 會失敗。

## HTTP 版注意事項

- `server_http.py` 目前預設會在 `90` 秒內等 agent 回覆。
- 這是為了避免 Cloudflare Tunnel 一類的 HTTP 代理先超時，外面只看到空白或中斷。
- 若要改長一點，可設定環境變數 `MCP_AGENT_TIMEOUT_SECONDS`。

## Hermes stdio proxy

先啟動 HTTP 版：

```powershell
.\run_http.cmd
```

Hermes 端可改成啟動：

```powershell
python .\hermes_stdio_proxy.py
```

預設會轉送到 `http://127.0.0.1:8765/mcp`。如果 HTTP endpoint 不在本機預設位置，可設定：

```powershell
$env:HERMES_HANDCRAFT_MCP_URL = "https://mcp.whoasked.vip/mcp"
```

若 endpoint 需要 bearer token，設定 `HERMES_HANDCRAFT_MCP_TOKEN`；本檔不保存 token，也不要把 runtime log、`.screenshots/`、`__pycache__/` 或圖片檔 commit 進 repo。

## Package webhook

給 TrackTW / 包裹通知使用的 webhook URL：

```text
https://mcp.whoasked.vip/webhook/package
```

本機對應 endpoint 是：

```text
http://127.0.0.1:8765/webhook/package
```

這條不是 MCP endpoint。對方要「接 MCP」時給 `/mcp`；對方要「包裹 webhook」時給 `/webhook/package`。
