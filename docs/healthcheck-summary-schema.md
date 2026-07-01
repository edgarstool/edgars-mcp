# healthcheck-summary.json — JSON Schema 與血統圖

本文件定義 `check-mcp-health.ps1` 產生的 `healthcheck-summary.json` 結構，並說明欄位血統（lineage）。

---

## 檔案位置

| 環境 | 路徑 |
|------|------|
| Runtime（主要） | `G:\AI_WORK_512\run\mcp-handcraft\healthcheck-summary.json` |
| 狀態追蹤（連續失敗） | `G:\AI_WORK_512\run\mcp-handcraft\healthcheck-state.json` |
| 日誌 | `V:\projects\mcp-handcraft\logs\healthcheck.log` |

每次執行 `check-mcp-health.ps1` 都會**覆蓋**同一檔案（非 append）；如需歷史記錄請讀 log。

---

## JSON Schema（Draft-07 相容）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "healthcheck-summary",
  "title": "MCP Healthcheck Summary",
  "description": "check-mcp-health.ps1 每次執行的輸出快照",
  "type": "object",
  "required": [
    "ok", "alert", "consecutive_failures", "alert_threshold",
    "pass", "fail", "skip",
    "local_base_url", "checked_at", "layers"
  ],
  "properties": {
    "ok": {
      "type": "boolean",
      "description": "true = 全部 layer 通過（fail=0）；false = 至少一個 layer 失敗"
    },
    "alert": {
      "type": "boolean",
      "description": "true = consecutive_failures ≥ alert_threshold，需人工介入"
    },
    "consecutive_failures": {
      "type": "integer",
      "minimum": 0,
      "description": "連續失敗次數；成功後歸零"
    },
    "alert_threshold": {
      "type": "integer",
      "minimum": 1,
      "default": 3,
      "description": "觸發 alert 所需的連續失敗次數（預設 3）"
    },
    "pass": {
      "type": "integer",
      "minimum": 0,
      "description": "本次通過的 layer 數"
    },
    "fail": {
      "type": "integer",
      "minimum": 0,
      "description": "本次失敗的 layer 數"
    },
    "skip": {
      "type": "integer",
      "minimum": 0,
      "description": "因前層失敗而跳過的 layer 數"
    },
    "local_base_url": {
      "type": "string",
      "format": "uri",
      "description": "本機 MCP server base URL（預設 http://127.0.0.1:8765）"
    },
    "public_mcp_url": {
      "type": ["string", "null"],
      "format": "uri",
      "description": "public MCP endpoint；-SkipPublic 時為 null"
    },
    "checked_at": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 時間戳記（PowerShell .ToString('o')）"
    },
    "layers": {
      "type": "object",
      "description": "5 層 cascade 各層結果",
      "required": ["process", "port", "tcp", "http", "tunnel"],
      "properties": {
        "process": { "$ref": "#/definitions/LayerProcess" },
        "port":    { "$ref": "#/definitions/LayerPort" },
        "tcp":     { "$ref": "#/definitions/LayerTcp" },
        "http":    { "$ref": "#/definitions/LayerHttp" },
        "tunnel":  { "$ref": "#/definitions/LayerTunnel" }
      }
    }
  },
  "definitions": {
    "LayerBase": {
      "type": "object",
      "required": ["name", "status"],
      "properties": {
        "name":   { "type": "string" },
        "ok":     { "type": ["boolean", "null"], "description": "null = skipped" },
        "status": { "type": "string", "enum": ["pass", "fail", "skip"] },
        "skip_reason": {
          "type": ["string", "null"],
          "description": "前層失敗原因代碼，status=skip 時才出現"
        }
      }
    },
    "LayerProcess": {
      "allOf": [{ "$ref": "#/definitions/LayerBase" }],
      "description": "Layer 1：handcraft-http python 行程存活",
      "properties": {
        "pid":          { "type": ["integer", "null"], "description": "存活行程 PID；找不到時 null" },
        "pid_from_file":{ "type": ["integer", "null"], "description": "從 PID file 讀取的 PID" },
        "port_owner":   { "type": ["integer", "null"], "description": "netstat 找到的 port owner PID" }
      }
    },
    "LayerPort": {
      "allOf": [{ "$ref": "#/definitions/LayerBase" }],
      "description": "Layer 2：netstat 確認 :Port LISTENING",
      "properties": {
        "port":      { "type": "integer" },
        "owner_pid": { "type": ["integer", "null"] }
      }
    },
    "LayerTcp": {
      "allOf": [{ "$ref": "#/definitions/LayerBase" }],
      "description": "Layer 3：TCP 實際連線 127.0.0.1:Port",
      "properties": {
        "host":       { "type": "string" },
        "port":       { "type": "integer" },
        "latency_ms": { "type": ["integer", "null"], "description": "連線延遲毫秒；失敗或 skip 時 null" },
        "error":      { "type": ["string", "null"] }
      }
    },
    "LayerHttp": {
      "allOf": [{ "$ref": "#/definitions/LayerBase" }],
      "description": "Layer 4：HTTP GET /health → 200",
      "properties": {
        "url":    { "type": "string", "format": "uri" },
        "status": { "type": ["integer", "null"], "description": "HTTP 狀態碼；連線失敗時 null" },
        "error":  { "type": ["string", "null"] }
      }
    },
    "LayerTunnel": {
      "allOf": [{ "$ref": "#/definitions/LayerBase" }],
      "description": "Layer 5：cloudflared 行程 + public MCP 端點可達",
      "properties": {
        "cloudflared_process": {
          "type": "boolean",
          "description": "cloudflared 行程是否存活"
        },
        "public_url":    { "type": ["string", "null"], "format": "uri" },
        "public_status": { "type": ["integer", "null"], "description": "public endpoint HTTP 狀態碼；401/403/405 視為可達" },
        "public_error":  { "type": ["string", "null"] },
        "skip_public":   { "type": "boolean", "description": "-SkipPublic switch 是否啟用" }
      }
    }
  }
}
```

---

## 欄位血統圖（Lineage Diagram）

```
check-mcp-health.ps1
│
├─ params ──────────────────────────────────────────────────────────────────┐
│   -LocalBaseUrl  →  local_base_url, layers.*.url                          │
│   -PublicMcpUrl  →  public_mcp_url, layers.tunnel.public_url              │
│   -Port          →  layers.port.port, layers.tcp.port                     │
│   -AlertThreshold → alert_threshold, alert (判斷條件)                      │
│   -SkipPublic    →  layers.tunnel.skip_public                             │
└───────────────────────────────────────────────────────────────────────────┘
│
├─ Handcraft-McpCommon.psm1
│   ├─ Get-HandcraftConfig()       → config (RepoRoot, LocalHealthUrl, ...)
│   ├─ Read-HandcraftPidFile()     → layers.process.pid_from_file
│   ├─ Get-PortOwnerPid()          → layers.process.port_owner
│                                    layers.port.owner_pid
│   ├─ Test-ProcessAlive()         → layers.process.ok
│   ├─ Test-PortListening()        → layers.port.ok
│   ├─ Invoke-HandcraftHttpProbe() → layers.http.{ok, status, error}
│                                    layers.tunnel.{public_status, public_error}
│   └─ (TcpClient inline)         → layers.tcp.{ok, latency_ms, error}
│
├─ healthcheck-state.json (R/W)
│   ├─ 讀取 consecutive_failures  → consecutive_failures (加 1 或歸零)
│   └─ 寫回 consecutive_failures  → healthcheck-state.json.consecutive_failures
│
├─ 計算欄位
│   ├─ pass / fail / skip         ← 各 layer.status 計數
│   ├─ ok                         ← fail == 0
│   ├─ alert                      ← consecutive_failures >= alert_threshold
│   └─ checked_at                 ← (Get-Date).ToString("o")
│
└─ 輸出
    ├─ healthcheck-summary.json   ← 本文件所描述的完整結構（覆蓋）
    └─ logs/healthcheck.log       ← 單行 append（供 DailyReport 使用）
```

---

## 範例輸出（全部通過）

```json
{
  "ok": true,
  "alert": false,
  "consecutive_failures": 0,
  "alert_threshold": 3,
  "pass": 5,
  "fail": 0,
  "skip": 0,
  "local_base_url": "http://127.0.0.1:8765",
  "public_mcp_url": "https://mcp.edgars.tools/mcp",
  "checked_at": "2025-07-01T09:00:00.0000000+08:00",
  "layers": {
    "process": { "name": "process", "ok": true, "status": "pass", "pid": 12345, "pid_from_file": 12345, "port_owner": 12345 },
    "port":    { "name": "port",    "ok": true, "status": "pass", "port": 8765, "owner_pid": 12345 },
    "tcp":     { "name": "tcp",     "ok": true, "status": "pass", "host": "127.0.0.1", "port": 8765, "latency_ms": 2, "error": null },
    "http":    { "name": "http",    "ok": true, "status": "pass", "url": "http://127.0.0.1:8765/health", "status": 200, "error": null },
    "tunnel":  { "name": "tunnel",  "ok": true, "status": "pass", "cloudflared_process": true, "public_url": "https://mcp.edgars.tools/mcp", "public_status": 401, "public_error": null, "skip_public": false }
  }
}
```

---

## 範例輸出（HTTP 失敗，後層 skip）

```json
{
  "ok": false,
  "alert": false,
  "consecutive_failures": 1,
  "alert_threshold": 3,
  "pass": 3,
  "fail": 1,
  "skip": 1,
  "checked_at": "2025-07-01T09:05:00.0000000+08:00",
  "layers": {
    "process": { "name": "process", "ok": true,  "status": "pass", "pid": 12345 },
    "port":    { "name": "port",    "ok": true,  "status": "pass", "port": 8765 },
    "tcp":     { "name": "tcp",     "ok": true,  "status": "pass", "latency_ms": 3 },
    "http":    { "name": "http",    "ok": false, "status": "fail", "url": "http://127.0.0.1:8765/health", "status": null, "error": "Unable to connect" },
    "tunnel":  { "name": "tunnel",  "ok": null,  "status": "skip", "skip_reason": "http_failed_or_skipped" }
  }
}
```

---

## healthcheck-state.json 結構

```json
{
  "consecutive_failures": 2,
  "updated_at": "2025-07-01T09:10:00.0000000+08:00"
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `consecutive_failures` | integer | 連續失敗次數；check 成功後歸零 |
| `updated_at` | string (ISO 8601) | 最後更新時間 |

> **重置方式**：刪除或清空 `healthcheck-state.json`，下次檢查將從 0 計數。
