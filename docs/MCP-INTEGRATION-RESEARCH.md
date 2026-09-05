# MCP 整合研究報告 - FastAPI + FastMCP + Handcraft

## 研究背景

根據「V2-手刻升級清單.md」的 Phase 2.0 目標：
- **目標**：外層 HTTP/ASGI/路由/headers/CORS 交給 FastAPI
- **目標**：OAuth discovery 局部交給 FastMCP
- **保留**：token 驗證、業務邏輯、webhook 等全部保留手刻

## 問題分析

### 1. FastMCP 3.4.2 的設計限制

根據 MCP-01-P.md 中的分析：
- **Streamable HTTP 2026-07-28**：單一 POST endpoint，支援單次 JSON 回應或 SSE stream
- **28 條路由**：文檔中提到，但未具體列出
- **工具發現**：FastMCP 可從任何 Python 函式自動生成 MCP tool schema

### 2. 原有 handcraft MCP 架構

從 server_http.py 可見：
- 78+ 個工具實作在 `TOOLS` 列表中
- 每個 tool 有 `name`、`description`、`inputSchema`
- `DISPATCH` 物件處理工具呼叫
- 保留原有的 OAuth、Webhook、系統工具等

### 3. 整合挑戰

**A. 工具遷移問題**
- FastMCP 使用 `@mcp.tool()` 裝飾器登錄工具
- handcraft 工具是同步的字典格式
- 需要保留工具的行為和參數驗證

**B. 授權模式問題**
- handcraft 支援 Descope JWT + Bearer Token 兩種
- FastMCP 內建的 AuthProvider 與現有 OAuth 流程衝突
- 需要在 FastAPI 層處理授權，再轉給 FastMCP

**C. WebSocket/SSE 問題**
- FastMCP 的 streamable-http 支援 SSE
- handcraft 使用 HTTP POST + JSON
- 需要決定走哪條傳輸路徑

## 研究結論

### 整合方案：分層架構

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI 層 (Phase 2.0)           │
│  - HTTP/ASGI/路由/CORS (由此控制)                   │
│  - OAuth 2.0 Resource Server 端點                   │
│  - 授權中介層 (保留 handcraft 的 Descope JWT)     │
│  - Well-known endpoints (.well-known/*)            │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                   MCP Dispatch 層 (Phase 2.0)       │
│  - 從 server_http.py 中的 DISPATCH 物件取得工具   │
│  - 手動註冊工具到 FastMCP 實例                     │
│  - 處理 JSON-RPC 2.0 協議                           │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                   工具執行層 (保留)                │
│  - server_http.py 中的所有工具實作 (78+ 個)        │
│  - 無需修改現有的工具行為                           │
│  - 保留對外依賴 (Linear、Notion、Observidian 等)  │
└─────────────────────────────────────────────────────┘
```

### 實作步驟

1. **建立 FastMCP 主實例** - 用於工具註冊與 discovery
2. **工具遷移腳本** - 從 TOOLS 列表自動生成 @mcp.tool() 裝飾器
3. **授權橋接** - FastAPI 中處理 OAuth，FastMCP 使用 open app
4. **路由映射** - 28 條路由的具體實作:
   - `/` - OAuth 授權跳轉
   - `/token` - Token 發放
   - `/.well-known/oauth-authorization-server` - OAuth metadata
   - `/.well-known/oauth-protected-resource` - Resource metadata
   - `/mcp` - MCP 入口 (JSON-RPC)
   - `/webhook/package` - Package webhook
   - `/webhook/linear` - Linear webhook
   - `/health` - 健康檢查
   - 以及其他工具相關的路由...

5. **Phase 2.1 前置** - 準備移除 Cloudflare Access 授權

## 後續行動

因為 28 條路由的具體內容未從文件中完整提取，建議：
1. 先完成 Phase 2.0 的基本架構
2. 在 Phase 2.1 移除 Cloudflare Access 前，由您確認現有的路由配置
3. 工具遷移採取漸進式方式：保留原有 server_http.py，FastMCP 只在必要時註冊少數工具