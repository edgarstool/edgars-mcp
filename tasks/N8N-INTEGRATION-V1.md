# EDGARS MCP：n8n Integration v1

本文件是 `tasks/ECS-FOUNDATION-V1.md` 的配套架構契約。

## 定位

`n8n` 納入 EDGARS MCP 框架，但不塞進 `edgars-mcp` Python 程序。

```text
Agent              = 判斷、規劃、選擇工作流程
edgars-mcp         = MCP 政策閘道、參數驗證、允許清單、審計
n8n                = 可重現的自動化執行引擎
Cloudflare         = 公開入口、驗簽、排隊、限流、邊緣儲存
Supabase Postgres  = n8n 工作流程、憑證與執行狀態
1Password          = secret 唯一來源
```

n8n 是後場執行引擎，不是公開產品介面，也不是 Agent 的無限制遙控器。

## 資料庫定案

n8n 不在 ECS 啟動本機 PostgreSQL container。

```text
採用：Supabase managed PostgreSQL
取消：edgars-n8n-postgres container
取消：ECS 本機 PostgreSQL data volume
取消：ECS 本機 PostgreSQL RAM 預算
```

此決定只替換 n8n 的內部狀態資料庫。商家、顧客、用量與產品資料是否使用 Cloudflare D1 或 Supabase，另由產品資料契約決定，不自動混進 n8n schema。

## 產品資料流

```text
LINE / 外部 SaaS
        ↓
Cloudflare Worker
  驗簽、限流、快速回應
        ↓
Cloudflare Queue
  緩衝、重試、削峰
        ↓
ECS dispatcher / edgars-mcp
  商家識別、政策、工作流程選擇、參數驗證
        ↓
n8n internal webhook
  固定流程、多步驟整合、排程、通知
        ↓
LINE / Notion / Google / Email / CRM / D1 / R2
```

n8n 自身狀態：

```text
n8n on ECS
   ↓ TLS PostgreSQL connection
Supabase Postgres
   └── schema: n8n
```

Agent 呼叫路徑：

```text
OpenClaw / Hermes
        ↓ MCP
edgars-mcp workflow tools
        ↓ allowlisted adapter
n8n internal webhook
        ↓
確定性工作流程
```

## 核心原則

1. 客戶不直接登入 n8n。
2. Agent 不取得 n8n 管理權限。
3. n8n 不直接接收 LINE 原始公開 webhook。
4. n8n editor 與 port `5678` 不公開到 Internet。
5. 所有可執行流程必須先登記 stable slug 與 JSON schema。
6. Agent 只能觸發允許清單中的流程。
7. 大型檔案先放 R2，再傳 object key，不穿過 n8n 記憶體長時間搬運。
8. workflow export 可進 Git；credentials、API keys、encryption key 不進 Git。
9. Git 保存歷史，active tree 只保留目前正式設計。
10. 先做單主程序穩定版，需要真實負載證據才升級 queue mode。
11. n8n internal tables 只存在 Supabase 的專用 `n8n` schema。
12. 不使用 Supabase anon key、service-role key 或 Data API 作為 n8n database connection。
13. n8n 使用原生 PostgreSQL connection，並強制 TLS。

## Canonical naming

```text
Compose project:         edgars-automation
n8n service:             edgars-n8n
n8n container:           edgars-n8n
Supabase schema:         n8n
Supabase runtime role:   n8n_runtime
Internal Docker network: edgars-automation
Host bind:               127.0.0.1:5678
Container URL:           http://edgars-n8n:5678
```

正式架構中不存在：

```text
edgars-n8n-postgres service
edgars-n8n-postgres container
local PostgreSQL volume
```

## Supabase connection contract

ECS 上的 n8n 是持續運作的 backend process。

優先順序：

```text
1. ECS 已驗證 IPv6 可直連 Supabase
   → Direct connection :5432

2. ECS 為 IPv4-only 或 direct endpoint 不可達
   → Supavisor session mode :5432
```

禁止使用：

```text
Supavisor transaction mode :6543
```

原因：transaction mode 面向短生命週期、serverless traffic，而且不支援 prepared statements。n8n 是持續運作的 application process，使用 direct connection 或 session mode 比較符合其連線模型。

正式設定：

```text
DB_TYPE=postgresdb
DB_POSTGRESDB_DATABASE=postgres
DB_POSTGRESDB_SCHEMA=n8n
DB_POSTGRESDB_HOST=<from 1Password>
DB_POSTGRESDB_PORT=5432
DB_POSTGRESDB_USER=<dedicated n8n role>
DB_POSTGRESDB_PASSWORD=<from 1Password>
DB_POSTGRESDB_SSL_REJECT_UNAUTHORIZED=true
```

不得使用 Supabase 專案的主要 `postgres` 帳號作為長期 n8n runtime 身份。建立專用 role `n8n_runtime`，權限只涵蓋 n8n 所需的 schema 建立與修改能力。

`n8n` schema 不承載商家正式資料，不暴露為前端 Data API 的產品介面。

## Canonical paths

Repo 內只放部署定義、adapter、workflow exports 與文件：

```text
/home/edgar/workspaces/shared/30-services/edgars-mcp/
├── deploy/n8n/
│   ├── compose.yaml
│   ├── compose.env.example
│   ├── supabase-bootstrap.sql
│   ├── start.sh
│   ├── stop.sh
│   └── check.sh
├── workflows/n8n/
│   ├── README.md
│   ├── registry.yaml
│   └── exports/
└── src/edgars_mcp/
    ├── workflow_registry.py
    └── adapters/n8n.py
```

Config：

```text
/home/edgar/.config/n8n/
├── n8n.op.env
├── supabase-ca.crt
└── policy.yaml
```

Runtime：

```text
/home/edgar/runtime/n8n/
├── data/
├── binary/
├── logs/
└── tmp/
```

不再建立：

```text
/home/edgar/runtime/n8n/postgres
/home/edgar/runtime/n8n/backups/postgres
```

不得把 n8n data、binary、logs、tmp 寫入 repo。

## v1 deployment mode

### 採用

```text
Docker Compose
n8n regular mode
Supabase managed PostgreSQL
1 個 n8n 主程序
Task runners enabled
Pinned stable image version
127.0.0.1 only
```

### 暫不採用

```text
Local PostgreSQL container
Redis
n8n queue mode
額外 worker containers
公開 editor
公開 n8n webhook hostname
n8n beta / latest 浮動 tag
客戶帳號登入
```

Queue mode 只有在以下證據出現後才升級：

- regular mode 已達穩定 concurrency 上限。
- 有持續排隊而不是偶發尖峰。
- 單一 n8n instance 已成為可量測瓶頸。
- Redis 與 worker 的額外 RAM、備份與維運成本有合理回報。

Cloudflare Queue 已負責外部事件緩衝，因此 v1 不重複引入 Redis 排隊層。

## ECS resource guardrails

這些是 EDGARS ECS 的營運上限，不是 n8n 官方最低規格。

```text
n8n memory target:         <= 1536 MiB
Local PostgreSQL target:   0 MiB
Production concurrency:   2
Default workflow timeout: 300 seconds
Maximum workflow timeout: 900 seconds
Execution retention:      168 hours
Execution maximum records: 5000
```

移除本機 PostgreSQL 後，ECS 約釋放原先預留的 768 MiB RAM，以及資料庫 volume、WAL、vacuum、backup 的磁碟與維運負擔。

磁碟控制：

```text
75% used → warning
85% used → 停止接收新的重型工作
15% free → 永久保留區，不納入正常容量預算
```

Supabase 容量控制：

```text
60% of plan database quota → warning
80% of plan database quota → 停止新增非必要 execution payload
90% of plan database quota → 只允許必要流程與清理作業
```

執行資料原則：

- 成功執行只保留必要 metadata，避免完整 payload 長期堆積。
- 錯誤執行保留除錯所需資料，但仍受 retention 限制。
- 不在 execution history 保存 access token、完整顧客附件或敏感輸入。
- 超過 10 MiB 的檔案先進 R2，n8n 只接 object key 與受控下載資訊。
- 批次資料使用分頁或 chunk，禁止一次灌入不受控大陣列。

## edgars-mcp adapter contract

v1 只提供三個 MCP tools：

### `workflow_catalog`

回傳 Agent 當前可使用的工作流程。

### `workflow_run`

要求：

- slug 必須存在 registry。
- input 必須通過 JSON schema。
- version 必須明確，不默認偷偷切最新版。
- 相同 idempotency key 不得重複產生副作用。
- adapter 只呼叫 registry 綁定的 internal webhook。
- 不接受任意 URL、任意 workflow ID 或任意 headers。

### `workflow_status`

依 EDGARS 自己的 execution reference 查詢，回傳受控狀態，不把 n8n 內部完整 execution payload 暴露給 Agent。

## workflow registry

`workflows/n8n/registry.yaml` 是唯一允許清單。

初始 workflows：

```text
line.lead.capture
line.faq.escalate
notion.lead.upsert
merchant.daily.digest
```

初始全部 `enabled: false`。部署完成、secret 可用、逐一驗收後才啟用。

## Secret contract

正式 secret 只由 1Password 提供：

```text
N8N_ENCRYPTION_KEY
N8N_INTERNAL_WEBHOOK_SECRET
N8N_API_KEY
SUPABASE_N8N_DB_HOST
SUPABASE_N8N_DB_PORT
SUPABASE_N8N_DB_DATABASE
SUPABASE_N8N_DB_USER
SUPABASE_N8N_DB_PASSWORD
LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN
NOTION_API_TOKEN
```

Repo 僅可保存 `op://` reference 範例。

規則：

- 不建立 plaintext fallback。
- 不把 API key 傳給 Agent。
- 不把 secret 放進 workflow export。
- 不把 secret 放進 command line、log、GitHub issue、report。
- 不把 Supabase database password 放入 compose file。
- 不把 Supabase service-role key當作 database password。
- 非 Enterprise n8n API key 視為高權限 key，只能由 adapter 使用。
- 工作流程執行優先走受保護 internal webhook，不讓 Agent 直接使用 n8n REST API。

## Public ingress contract

v1：

```text
Cloudflare Worker = 唯一公開 webhook 入口
n8n                = private origin
Supabase Postgres  = managed database endpoint, TLS only
```

LINE 路線：

```text
hooks.edgars.tools/line
→ 驗證 LINE signature
→ 寫入 Cloudflare Queue
→ ECS dispatcher
→ edgars-mcp policy
→ n8n internal webhook
```

目前不得新增：

```text
n8n.edgars.tools
公開 5678
直接將 LINE webhook 指到 ECS
直接將 LINE webhook 指到 n8n
```

## Workflow source control and recovery

正式流程採：

```text
n8n editor
→ review
→ export sanitized JSON
→ workflows/n8n/exports/
→ Git commit
```

回復策略：

```text
Workflow definitions  → Git sanitized exports
Secrets               → 1Password
n8n internal state     → Supabase Postgres
Binary attachments    → R2 references
```

Supabase platform backup 是否可用以及保留時間，必須依實際方案驗證，不在文件中假設。第一位付費客戶上線前，必須完成一次 workflow export + database restore drill。

## License boundary

本架構把 n8n 定位為 Edgar 內部營運引擎：

- 客戶購買的是 LINE 助理、自動化成果、建置與維護服務。
- 客戶不購買 n8n 帳號或 n8n editor access。
- 不 white-label n8n。
- 不以「代管 n8n 帳號」作為產品。
- 共享實例若需要收集每位客戶自己的第三方 SaaS credentials，必須先重新審查 n8n 授權條件。

## Security boundary

Agent 不得：

- 建立或修改 n8n credentials。
- 任意新增 workflow。
- 執行任意 shell command。
- 指定任意 webhook URL。
- 讀取完整 execution payload。
- 操作 editor、users、license、API keys。
- 取得 Supabase database credentials。

n8n workflow 不得預設使用：

- Execute Command。
- 任意 host filesystem read/write。
- 未允許的 community nodes。
- 未驗證來源的 JavaScript Code node。

## Validation gates

部署前：

- `docker compose config` 通過。
- compose 中只有 n8n，沒有 PostgreSQL service。
- image 使用固定 stable tag，不使用 `latest`。
- compose 內無真實 secret。
- port 只綁 `127.0.0.1:5678`。
- Supabase connection 使用 TLS。
- `n8n_runtime` role 只能操作指定 schema。
- runtime/config/repo 邊界通過檢查。

啟動後：

- n8n health check 通過。
- Supabase database migration 通過。
- n8n tables 只出現在 `n8n` schema。
- container restart 後 workflows 與 encryption key 可用。
- concurrency limit 生效。
- execution pruning 設定可見。
- Agent 無法執行 registry 外 workflow。
- 相同 idempotency key 不重複副作用。
- 10 MiB 以上測試檔案走 R2 reference，不進 execution payload。

LINE 商業流程啟用前：

- Cloudflare Worker 驗簽通過。
- Queue retry 與 duplicate event 測試通過。
- n8n 停機時事件不遺失。
- Agent timeout 時能轉真人或回覆受控訊息。
- 每商家用量、錯誤與模型成本可追蹤。
- Supabase database usage 告警可見。
- workflow export + database restore drill 通過。

## Stop conditions

遇到以下情況停止，不自行猜測：

- 需要真實 secret。
- 需要修改 Cloudflare production route。
- 需要公開 n8n editor。
- 需要替客戶建立 n8n 登入帳號。
- 需要收集客戶自有第三方 credentials 且授權邊界未確認。
- 需要導入 Redis / queue mode 但沒有負載證據。
- 無法確認 Supabase 方案的 database quota 或 backup 能力。
- ECS 到 Supabase 的 TLS/session connection 無法穩定建立。

除此之外，以完整、可驗收、可回滾的一個大步完成，不切成無必要的小 phase。
