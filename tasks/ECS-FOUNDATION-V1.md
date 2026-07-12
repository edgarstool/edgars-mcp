# EDGARS MCP：ECS Foundation v1

## 任務性質

這是一個可回復、可比較、可驗收的完整重構任務。

- 工作分支：`refactor/ecs-foundation-v1`
- 基底分支：`master`
- 不直接修改 `master`
- 不碰任何真實 secret
- 不部署 Cloudflare ingress
- 不刪除現有功能
- 使用 `git mv` 保留歷史
- 完成後提交 compare report，不自行合併

## 目標

把目前混用的 `mcp-handcraft`、`handcraft-mcp`、`handcraft-http`、Windows 專用 runtime 路徑，收斂成唯一正式名稱：

```text
edgars-mcp
```

ECS / Linux 主架構不得再依賴：

```text
G:\AI_WORK_512
V:\projects
Doppler
Windows PowerShell
.cmd
硬編碼的 Windows user profile
```

舊 Windows 流程可以保留於 `legacy/windows/` 或 compatibility wrapper，但不得再主導 README、Linux service、Docker、runtime、logs、PID、config 的命名。

## Canonical naming contract

```text
Project slug:        edgars-mcp
Python package:      edgars_mcp
GitHub repo:         edgarstool/edgars-mcp
Service:             edgars-mcp.service
Docker project:      edgars-mcp
Docker container:    edgars-mcp
Default host:        127.0.0.1
Default port:        8765
Health endpoint:     /health
MCP endpoint:        /mcp
```

ECS canonical paths：

```text
Source:   /home/edgar/workspaces/shared/30-services/edgars-mcp
Runtime:  /home/edgar/runtime/edgars-mcp
Config:   /home/edgar/.config/edgars-mcp
Run:      /home/edgar/runtime/edgars-mcp/run
State:    /home/edgar/runtime/edgars-mcp/state
Logs:     /home/edgar/runtime/edgars-mcp/logs
Cache:    /home/edgar/runtime/edgars-mcp/cache
Tmp:      /home/edgar/runtime/edgars-mcp/tmp
```

Canonical runtime filenames：

```text
edgars-mcp.pid
edgars-mcp.out.log
edgars-mcp.err.log
edgars-mcp.env.example
edgars-mcp.op.env.example
```

## Desired repository layout

在不犧牲既有功能的前提下，盡量收斂至：

```text
edgars-mcp/
├── README.md
├── pyproject.toml
├── src/
│   └── edgars_mcp/
│       ├── __init__.py
│       ├── http_server.py
│       ├── stdio_server.py
│       ├── stdio_proxy.py
│       └── mmx_handlers.py
├── tests/
│   └── test_http_server.py
├── config/
│   ├── edgars-mcp.env.example
│   └── edgars-mcp.op.env.example
├── deploy/
│   ├── linux/
│   │   ├── edgars-mcp.service
│   │   ├── install.sh
│   │   ├── start.sh
│   │   ├── check.sh
│   │   └── uninstall.sh
│   └── docker/
│       ├── Dockerfile
│       └── compose.yaml
├── legacy/
│   └── windows/
├── docs/
│   ├── ECS-FOUNDATION.md
│   └── WINDOWS-MIGRATION.md
└── reports/
    └── ECS-FOUNDATION-COMPARE.md
```

如果現況耦合太深，允許保留薄 compatibility wrappers，但必須：

1. 明確標為 deprecated。
2. 只做轉呼叫，不再承載主要邏輯。
3. 主程式邏輯移入 `src/edgars_mcp/`。
4. 不在主架構重新引入 `handcraft-*` 命名。

## Required implementation

### 1. Naming convergence

全 repo 搜尋並分類：

```text
mcp-handcraft
handcraft-mcp
handcraft-http
Handcraft
G:\AI_WORK_512
V:\projects
```

處理規則：

- active source、Linux、Docker、README 主流程：改成 `edgars-mcp`。
- 歷史紀錄、incident report、migration note：可保留原字串，但必須標示 historical / legacy。
- Windows 相容層：移到 `legacy/windows/`，名稱可以保留以維持相容，但不得成為預設入口。
- 不修改 URL `https://mcp.edgars.tools/mcp`。

### 2. Python package cleanup

- 建立正式 Python package `edgars_mcp`。
- 將主要 Python 邏輯以 `git mv` 搬入 package。
- 修正 imports、tests、entry points。
- `python -m edgars_mcp.http_server` 必須可啟動。
- `python -m edgars_mcp.stdio_server` 必須可啟動。
- 建立或整理 `pyproject.toml`，明確定義 Python 版本與依賴。
- 不要盲目升級所有 dependency，只做可重現安裝所需的收斂。

### 3. Linux capability boundary

目前工具包含大量 Windows / local-desktop integration。ECS 上缺少這些外部程式時：

- server 不得在 import 階段崩潰。
- 可用工具正常註冊。
- 不可用工具應回傳結構化 `unavailable` / dependency missing 訊息。
- 不要假裝 Windows-only tool 在 Linux 可用。
- 產出 capability inventory，列出：Linux-ready、需要額外安裝、Windows-only、未知。

### 4. Runtime separation

所有可變資料不得寫回 repo：

- PID → `$EDGARS_MCP_RUN_DIR`
- state / SQLite → `$EDGARS_MCP_STATE_DIR`
- logs → `$EDGARS_MCP_LOG_DIR`
- cache → `$EDGARS_MCP_CACHE_DIR`
- tmp → `$EDGARS_MCP_TMP_DIR`

提供集中設定模組，環境變數優先，並使用上述 ECS canonical paths 作為 `edgar` 使用者的預設值。

不得硬編碼 `/home/edgar` 到 Python 核心邏輯，應以 `$HOME` / `Path.home()` 組合。部署文件才可顯示完整 canonical path。

### 5. 1Password-first secret design

ECS 正式模式使用 1Password，不以 Doppler 作必要依賴。

建立：

```text
config/edgars-mcp.op.env.example
```

內容只放 `op://...` reference 範例，不放真實 secret，例如：

```text
MCP_API_TOKEN=op://Edgar ECS Agents/edgars-mcp/MCP_API_TOKEN
```

Linux `start.sh` 應支援：

```bash
op run --env-file "$HOME/.config/edgars-mcp/edgars-mcp.op.env" -- python -m edgars_mcp.http_server
```

要求：

- 沒有 `MCP_API_TOKEN` 時 fail-fast。
- 沒有 1Password authentication 時清楚失敗。
- 不產生 plaintext fallback。
- 不把 token 放進 command line、log、repo。
- Doppler 文件移入 Windows legacy / migration context，不作 ECS 主流程。

### 6. systemd user service

建立 `deploy/linux/edgars-mcp.service`，目標安裝位置：

```text
~/.config/systemd/user/edgars-mcp.service
```

要求：

- `User=` 不要寫在 user service。
- `WorkingDirectory` 指向 canonical source。
- `ExecStart` 呼叫 `deploy/linux/start.sh`。
- `Restart=on-failure`。
- 合理的 restart delay。
- 僅監聽 `127.0.0.1:8765`。
- service 不直接暴露 public interface。
- logs 優先進 journald，同時允許 application log 寫到 runtime logs。
- install script 必須建立 runtime/config 目錄與權限。
- install 不得自動啟用 Cloudflare hostname。

### 7. Docker foundation

建立 production-oriented Dockerfile 與 Compose：

- project / service / container 名稱統一 `edgars-mcp`。
- bind `127.0.0.1:8765:8765`。
- runtime 的 state/logs/cache/tmp 透過 host bind mount。
- source code 不作可變資料 volume。
- healthcheck 使用 `/health`。
- `restart: unless-stopped`。
- 不在 image 或 compose 寫入 secrets。
- 文件使用 `op run -- docker compose ...` 示範 secret injection。
- Compose 與 systemd 是兩種部署選項，不可同時搶 port。

### 8. Documentation cleanup

README 第一行與主要說明必須稱為 `edgars-mcp`。

README 必須清楚分成：

1. What it is
2. Canonical naming
3. Local Windows legacy mode
4. ECS Linux native mode
5. Docker mode
6. Runtime/config/secrets boundaries
7. Health validation
8. Known platform limitations

建立 `docs/ECS-FOUNDATION.md`，記錄 canonical paths、service、Docker、1Password、驗收與 rollback。

建立 `docs/WINDOWS-MIGRATION.md`，說明舊名稱與舊路徑如何被相容或移入 legacy。

## Validation gates

至少執行並記錄：

```text
python -m compileall src
python -m pytest
python -m edgars_mcp.http_server 相關 smoke test
HTTP GET /health = 200
MCP initialize handshake 成功
缺少 MCP_API_TOKEN 時 fail-fast
Linux 缺少 Windows dependency 時 server 仍能啟動
Docker image build 成功
Docker healthcheck 成功
Compose config 驗證成功
shellcheck deploy/linux/*.sh（若 shellcheck 可用）
```

另執行全文掃描，active Linux / Docker / README 主流程不得殘留：

```text
mcp-handcraft
handcraft-mcp
handcraft-http
G:\AI_WORK_512
V:\projects
```

歷史與 migration 文件命中可接受，但 compare report 必須逐項解釋。

## Compare report

完成後建立：

```text
reports/ECS-FOUNDATION-COMPARE.md
```

必須包含：

- 原始 branch / commit
- 完成 branch / commit
- 新增、搬移、刪除、修改檔案清單
- 舊名命中清單與保留理由
- Python package 入口
- Linux service 安裝路徑
- Docker 執行方式
- runtime/config/secret 邊界
- capability inventory
- 所有驗證結果
- 未完成項目
- 已知風險
- merge 前檢查清單
- rollback 指令

## Stop conditions

遇到以下情況停止，不要自行猜：

- 需要真實 token / password / private key。
- 需要修改 Cloudflare production 設定。
- 需要刪除工具或改變外部 MCP tool schema。
- 測試顯示目前 Windows production 會無法相容，且沒有薄 wrapper 可解。
- 需要改 GitHub repo 名稱或 public URL。

除此之外，直接完成整包任務，不要拆成多輪 proposal。
