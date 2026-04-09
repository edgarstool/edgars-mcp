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

## 現況提醒

- `server.py` 是本地 `stdio` 入口
- `server_http.py` 是 HTTP 入口
- `server_http.py` 目前已接上 `codex_agent`
- `server_http.py` 目前也已接上 `claude_code_agent` 與 `gemini_agent`

## Claude Code 前提

如果要用 `claude_code_agent`，本機需要先完成：

```powershell
winget install Anthropic.ClaudeCode
claude auth login
```

如果 `claude` 指令不在 PATH，HTTP tool call 會失敗。

## HTTP 版注意事項

- `server_http.py` 目前預設會在 `300` 秒內等 agent 回覆。
- 這是降低長任務在外層被過早 timeout 的機率。
- 若要改長一點，可設定環境變數 `MCP_AGENT_TIMEOUT_SECONDS`。
