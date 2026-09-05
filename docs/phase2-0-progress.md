# Phase 2.0 進度（2026-09-05）

分支：`feat/phase2-fastapi-shell-20260905`（從 `checkpoint/pre-phase2-fastapi-fastmcp` 切出）
Linear：EDG-373 已 Done；本輪補外網證據留言。

## 外網 vs origin

本機 origin `127.0.0.1:8765` 正確（401 + PRM）。
外網 Cloudflare 錯誤（302 HTML / 307 callback loop）。未改 production。

## 本機殼

從既有 `feat/mcp-v2-fastapi-fastmcp-phase2` 取出 FastAPI 外殼（tools 仍 dispatch 到手刻）：
- `server_fastapi.py`
- `fastapi_adapters.py`
- `fastmcp_auth.py`
- `run_fastapi.cmd`
- `requirements.txt`（鎖 fastapi 0.141.1 / uvicorn 0.49.0 / fastmcp 3.4.2，並 pin `mcp>=1.24,<2`）

FastMCP import 失敗時 PRM 退回手刻 JSON（`resource` 仍是 `/mcp`）。
401 改帶完整 `WWW-Authenticate` resource_metadata。
