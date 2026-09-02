---
lang: zh-TW
---

# Linear 委派給 Agent — EDGAR-OS Current

> 更新：2026-09-02

## 一句話

Linear 的 Agent 委派需要四件事都成立：**OAuth App、Agent Session Events、Webhook 收件、Activity 回寫**。

EDGAR-OS 唯一 canonical public event ingress：

`https://hooks.edgars.tools/webhooks/linear`

不要建立第二套公開 webhook hostname，也不要把主機上的 Hermes / OpenClaw / linear-orchestrator port 當公共入口。

## 正確流程

```text
Linear AgentSessionEvent
        ↓
hooks.edgars.tools
        ↓
驗簽 / normalize / dedupe
        ↓
durable event receipt
        ↓
async fan-out
        ↓
Hermes / OpenClaw / orchestrator 等 bounded executor
        ↓
Linear agentActivityCreate: thought / response / error
```

### Event Portal 的硬規則

- 沒有 durable receipt 就不得成功 ACK。
- 重送同一事件必須可 dedupe / idempotent。
- Event Portal 負責事件進站與可靠保存；Agent runtime 負責後續工作。
- Source config、舊文件或歷史成功紀錄都不等於目前 production route 已通，需 live verify。

## OAuth 與 Webhook 分工

| 功能 | Canonical |
|---|---|
| MCP / Linear OAuth | `https://mcp.edgars.tools` |
| Linear OAuth callback | `https://mcp.edgars.tools/linear/oauth/callback` |
| Linear Agent webhook | `https://hooks.edgars.tools/webhooks/linear` |

OAuth 成功只代表 App 有權限；委派成功仍需要 webhook 被接收、快速送出 `thought`，最後再回 `response` / `error`。

## Linear App 必要設定

- Redirect URI：`https://mcp.edgars.tools/linear/oauth/callback`
- Webhook URL：`https://hooks.edgars.tools/webhooks/linear`
- Webhook enabled：ON
- Agent session events：ON
- OAuth scopes 至少包含目前 Agent integration 所需的 `read`、`write`、`app:assignable`、`app:mentionable`

Signing secret、client secret、token 不寫進文件、Git、Linear comment 或聊天；使用既有 secret execution lane。

## 驗收

真正 PASS 至少要有：

1. `hooks.edgars.tools` live reachability。
2. Linear signature 驗證 PASS。
3. Event Portal 寫入 durable receipt 並能 read-back。
4. 同一 event 重送不產生第二份邏輯事件。
5. durable storage 故障時不得回成功 ACK。
6. Agent Session created 後能在 Linear 要求時間內送出 `thought`。
7. Executor 完成後能送 `response` 或精確 `error`。

目前 source / staging contract 已證明 durable-receipt-before-ack 行為；public Cloudflare route 必須另外 live verify，不能由這份文件假設成功。

## 禁止復活的舊模式

- 不保留 retired product-domain alias。
- 不保留第二套 `webhooks.*` public authority 當 fallback。
- 不把 `mcp.edgars.tools/webhook/linear` 當 Agent webhook authority。
- 不把 Windows / VPS localhost port 直接公開成 canonical webhook endpoint。
- 不因舊 README、Git history、Agent memory 自動恢復 deprecated hostname。

## 官方 Linear 參考

- Agent: https://linear.app/developers/agents
- Agent interaction: https://linear.app/developers/agent-interaction
- Agent best practices: https://linear.app/developers/agent-best-practices
- OAuth: https://linear.app/developers/oauth-actor-authorization
- Webhooks: https://linear.app/developers/webhooks
