# EDGARS MCP：ECS Foundation v1

## 核心原則

這不是「把舊架構包起來繼續背」。

這次採用 clean-slate convergence：

```text
Git history = 唯一歷史保存層
active tree = 只保留現在最好的正式結構
```

預設規則：

1. 有更好的正式方案，就取代舊方案。
2. 舊名稱、舊入口、舊 wrapper、舊 runtime 路徑不因懷舊而保留。
3. 只有能指出「目前仍有真實使用者或外部系統依賴」時，才允許暫時相容。
4. 暫時相容必須有移除日期、owner、驗收條件，不能無限期存在。
5. 不建立 `legacy/` 雜物間來延續混亂。
6. 需要追溯時用 Git commit、tag、branch，不把歷史垃圾留在主目錄。

## 工作邊界

- 工作分支：`refactor/ecs-foundation-v1`
- 基底分支：`master`
- 不直接修改 `master`
- 不碰真實 secret
- 不修改 Cloudflare production
- 不自行合併
- 可以刪除已被正式新入口取代的檔案
- 可以改檔名、模組名、服務名、Docker 名、runtime 名、文件名
- 可以重構 imports、tests、entry points
- 不得刪除 MCP tool 功能或改變外部 tool schema，除非測試證明原功能本身已無效且 compare report 明確記錄

## 唯一正式名稱

```text
Project slug:        edgars-mcp
Python package:      edgars_mcp
GitHub repo:         edgarstool/edgars-mcp
systemd service:     edgars-mcp.service
Docker project:      edgars-mcp
Docker service:      edgars-mcp
Docker container:    edgars-mcp
Default host:        127.0.0.1
Default port:        8765
Health endpoint:     /health
MCP endpoint:        /mcp
```

主架構禁止再使用：

```text
mcp-handcraft
handcraft-mcp
handcraft-http
Handcraft-McpCommon
Start-HandcraftStack
G:\AI_WORK_512
V:\projects
Doppler 作為 ECS 必要依賴
```

歷史文字只存在 Git history。Active tree 內除 migration report 的 before/after 表格外，不保留上述舊名。

## ECS canonical paths

```text
Source:   /home/edgar/workspaces/shared/30-services/edgars-mcp
Config:   /home/edgar/.config/edgars-mcp
Runtime:  /home/edgar/runtime/edgars-mcp
Run:      /home/edgar/runtime/edgars-mcp/run
State:    /home/edgar/runtime/edgars-mcp/state
Logs:     /home/edgar/runtime/edgars-mcp/logs
Cache:    /home/edgar/runtime/edgars-mcp/cache
Tmp:      /home/edgar/runtime/edgars-mcp/tmp
```

Canonical filenames：

```text
edgars-mcp.pid
edgars-mcp.out.log
edgars-mcp.err.log
edgars-mcp.env.example
edgars-mcp.op.env.example
```

## 理想 repository layout

```text
edgars-mcp/
├── README.md
├── pyproject.toml
├── src/
│   └── edgars_mcp/
│       ├── __init__.py
│       ├── config.py
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
│   ├── windows/
│   │   ├── install.ps1
│   │   ├── start.ps1
│   │   ├── check.ps1
│   │   └── stop.ps1
│   └── docker/
│       ├── Dockerfile
│       └── compose.yaml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ECS-FOUNDATION.md
│   └── WINDOWS.md
└── reports/
    └── ECS-FOUNDATION-COMPARE.md
```

Windows 若仍為正式支援平台，應直接重構成 `deploy/windows/` 的一等公民，不叫 legacy，不保留舊 Handcraft 命名，不依賴散落 root `.cmd`。

## 實作要求

### 1. 命名徹底收斂

全文搜尋：

```text
mcp-handcraft
handcraft-mcp
handcraft-http
Handcraft
G:\AI_WORK_512
V:\projects
```

Active code、script、config、README、docs、tests、service、Docker 全部改成新名稱與新路徑。

允許在 `reports/ECS-FOUNDATION-COMPARE.md` 的 before/after 表格引用舊名，除此之外 active tree 不殘留舊名。

### 2. Python package 正規化

- 建立 `src/edgars_mcp/`。
- 使用 `git mv` 搬移主要 Python 邏輯。
- root 舊入口檔若已被正式 package entry point 取代，直接刪除。
- 修正 imports、tests、CLI entry points。
- `python -m edgars_mcp.http_server` 可啟動。
- `python -m edgars_mcp.stdio_server` 可啟動。
- 建立清楚的 `pyproject.toml`。
- 依賴必須可重現，但不要無目的追最新版。

### 3. 跨平台能力邊界

現有工具含 Windows / desktop integration。Linux 上：

- 不得在 import 階段因缺少 Windows dependency 崩潰。
- 可用工具正常註冊。
- 不可用工具回傳結構化 `unavailable` 與缺少依賴原因。
- 不假裝 Windows-only tool 在 ECS 可用。
- 產出 capability inventory：Linux-ready、Windows-ready、optional dependency、unsupported。

### 4. Runtime 與 source 完全分離

可變資料不得寫回 repo：

- PID → `$EDGARS_MCP_RUN_DIR`
- state / SQLite → `$EDGARS_MCP_STATE_DIR`
- logs → `$EDGARS_MCP_LOG_DIR`
- cache → `$EDGARS_MCP_CACHE_DIR`
- tmp → `$EDGARS_MCP_TMP_DIR`

核心程式使用 `$HOME` / `Path.home()` 建立預設路徑，不硬編碼 `/home/edgar`。

### 5. 1Password-first

ECS 正式 secrets 流程：

```text
1Password CLI + op:// references
```

建立：

```text
config/edgars-mcp.op.env.example
```

只放 reference 範例，不放真值：

```text
MCP_API_TOKEN=op://Edgar ECS Agents/edgars-mcp/MCP_API_TOKEN
```

Linux start：

```bash
op run --env-file "$HOME/.config/edgars-mcp/edgars-mcp.op.env" -- python -m edgars_mcp.http_server
```

要求：

- 缺 `MCP_API_TOKEN` 時 fail-fast。
- 缺 1Password authentication 時清楚失敗。
- 不建立 plaintext fallback。
- 不把 secret 寫進 command line、log、repo。
- Doppler 不作 ECS 依賴。
- 若 Windows 仍需要 secret manager，也應優先統一到 1Password；沒有真實阻礙就移除 Doppler 專用啟動流程與文件。

### 6. systemd user service

建立 `deploy/linux/edgars-mcp.service`，安裝至：

```text
~/.config/systemd/user/edgars-mcp.service
```

要求：

- 不設定 `User=`。
- `WorkingDirectory` 指向 canonical source。
- `ExecStart` 呼叫 `deploy/linux/start.sh`。
- `Restart=on-failure`。
- 僅監聽 `127.0.0.1:8765`。
- 不建立 public ingress。
- install script 建立 runtime/config 目錄與正確權限。

### 7. Docker foundation

- project、service、container 都叫 `edgars-mcp`。
- bind `127.0.0.1:8765:8765`。
- state/logs/cache/tmp 使用 host bind mount。
- source code 不作可變 volume。
- healthcheck 使用 `/health`。
- `restart: unless-stopped`。
- image / compose 不含 secrets。
- 文件示範 `op run -- docker compose ...`。
- systemd native 與 Docker 是二選一部署模式，不同時搶 port。

### 8. Windows 地基一起整理

現在能改就一起改：

- 移除 root `run.cmd`、`run_http.cmd`、`run_stdio.cmd` 等舊入口。
- 將正式 Windows 操作收斂到 `deploy/windows/*.ps1`。
- PowerShell module、function、PID、log、task 名稱統一 `EdgarsMcp` / `edgars-mcp`。
- 移除 `Handcraft-*` 命名。
- Windows runtime 預設可由環境變數決定，不再硬編碼 G/V 槽。
- 舊 scheduled task 或外部啟動器若仍依賴舊檔名，compare report 列出一次性 migration 指令，不保留永久 wrapper。

### 9. 文件只描述現在

README 只描述新正式架構：

1. What it is
2. Canonical naming
3. Linux native
4. Windows native
5. Docker
6. Runtime/config/secrets boundaries
7. Validation
8. Platform capability matrix

不要在 README 留大量舊架構考古。遷移差異集中在 compare report，完成合併後可另行 archive 或刪除 report。

## 驗收

至少執行：

```text
python -m compileall src
python -m pytest
python -m edgars_mcp.http_server smoke test
HTTP GET /health = 200
MCP initialize handshake 成功
缺 MCP_API_TOKEN 時 fail-fast
Linux 缺 Windows dependency 時 server 仍能啟動
Docker image build 成功
Docker healthcheck 成功
Docker Compose config 成功
PowerShell syntax / PSScriptAnalyzer（可用時）
shellcheck deploy/linux/*.sh（可用時）
```

最後全文掃描，除 compare report 的 before/after 區段外，active tree 不得命中：

```text
mcp-handcraft
handcraft-mcp
handcraft-http
Handcraft-McpCommon
Start-HandcraftStack
G:\AI_WORK_512
V:\projects
```

## Compare report

建立：

```text
reports/ECS-FOUNDATION-COMPARE.md
```

必須包含：

- base commit / final commit
- 新增、搬移、刪除、修改檔案
- 所有舊入口的替代入口
- 一次性 migration 指令
- Python entry points
- Linux service
- Windows scripts
- Docker mode
- runtime/config/secret boundary
- capability inventory
- 完整驗證結果
- 未完成項目
- 已知風險
- merge checklist
- rollback 指令

## 停止條件

只有以下情況停下：

- 需要真實 token、password、private key。
- 需要修改 Cloudflare production。
- 需要改 GitHub repo 名稱或 public URL。
- 必須改外部 MCP tool schema。
- 發現仍有真實外部系統依賴舊入口，且無法用一次性 migration 解決。

除此之外，直接完成整包重構，不切成 proposal 小碎片，不因舊檔存在就保留舊檔。
