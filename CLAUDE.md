# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案性質
手刻 MCP Server（Model Context Protocol），不依賴官方 SDK，只用 Python 標準庫實作協議。

## 入口分開使用

| 檔案 | 傳輸方式 | 用途 |
|------|----------|------|
| `server.py` + `run.cmd` | stdio | 本地 client（Ollama、龍蝦） |
| `server_http.py` + `run_http.cmd` | HTTP POST | 瀏覽器、MCP Inspector、Cloudflare Tunnel |

## 架構

```
client input (JSON-RPC)
    ↓
dispatch(msg) → REQUEST_HANDLERS lookup
    ↓
handle_*(req_id, params) → 回傳 dict
    ↓
send_response / _send_json
```

- `server_http.py` 有完整工具清單：`echo`、`codex_agent`、`claude_code_agent`
- `server.py` 只有 `echo`（stdio 測試版）

## 重要實作細節

- **Windows stdin/stdout**：第 6-11 行有 `msvcrt.setmode` 處理二進位模式，防止 `\n` 被轉成 `\r\n` 或插入 BOM
- **CORS 白名單**：`ALLOWED_HOSTNAMES` 在第 102 行，部署 Tunnel 前需加入允許的 origin
- **Agent timeout**：`AGENT_TIMEOUT_SECONDS` 環境變數，預設 90 秒（第 20 行）

## 常用指令

```cmd
run.cmd           :: 啟動 stdio 版
run_http.cmd     :: 啟動 HTTP 版（port 8765）
```

## 部署注意

HTTP 版部署在 `https://mcp.whoasked.vip/mcp`，用 Cloudflare Tunnel 對外暴露。修改允許的 origin 需改 `server_http.py:102` 的 `ALLOWED_HOSTNAMES`。
