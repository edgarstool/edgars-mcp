# Phase 2 FastAPI 殼 — 收工包（2026-09-05）

這次專案的交接，不是取代 `server_http.py`。

## 一句話

手刻 tools 留下。FastAPI 只當 HTTP 外殼。FastMCP 只幫忙產 PRM。外網 OAuth 全綠卡在 **Cloudflare edge**，不是 origin。

## Git

- 分支：`feat/phase2-fastapi-shell-20260905`
- 起點：`checkpoint/pre-phase2-fastapi-fastmcp` @ `9b0915fa`
- 不要合進 `master`，除非德德點頭

## 本機已驗（port 18780，origin 8765 沒動）

- `GET /health` → 200
- `GET /.well-known/oauth-protected-resource` → 200，`resource` = `https://mcp.edgars.tools/mcp`
- `GET /.well-known/oauth-protected-resource/mcp` → 200 JSON（不是 HTML）
- `POST /mcp` 無 token → 401 + `WWW-Authenticate` 帶 `resource_metadata`

## 外網還沒過（要改 Cloudflare，未動 production）

- 根 PRM 的 `resource` 缺 `/mcp`
- path-aware PRM → 302 到 `auth.edgars.tools` HTML
- 無 token `POST /mcp` → 307 → `/callback` 迴圈

## 檔案對照（repo 根才是執行檔）

| 根目錄 | 用途 |
|---|---|
| `server_fastapi.py` | FastAPI 外殼，dispatch 回 `server_http.py` |
| `fastapi_adapters.py` | Request 轉換 |
| `fastmcp_auth.py` | FastMCP RemoteAuthProvider；import 失敗就退回手刻 PRM |
| `run_fastapi.cmd` | 啟動 |
| `requirements.txt` | `fastapi==0.141.1` `uvicorn==0.49.0` `fastmcp==3.4.2` `mcp>=1.24,<2` |
| `docs/MCP-PHASE2-AUTH-RESEARCH.md` | 授權研究 |
| `docs/MCP-INTEGRATION-RESEARCH.md` | 整合研究 |

本資料夾是副本／交接，改程式請改 repo 根。

## 未做（決策）

- 未改 Cloudflare Access / tunnel / Managed OAuth
- 未猜 chatgpt-honcho 認證方式
- 未開 PR 合 master
- 未派多代理隊友（這輪是單人收工）

## Linear

- EDG-373 / EDG-374 已留言外網 vs origin 證據
