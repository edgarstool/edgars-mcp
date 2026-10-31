# EDG-478 aka1：原生 Auth → 真實 MCP HTTP 撤銷驗證

## Status（結果）

- 日期：2026-11-01；環境：aka1，Linux，Python 3.14.4。
- 工作分支：`test/edg478-native-http-revocation-aka1-20261101`。
- MCP 起點：`f48403e`；PR（變更審查）指定基底：`test/edg478-native-jwt-red-20261028`。
- Auth 唯讀來源：`b8648ee3a83143ac30ec779098fcc33abc1bab43`，沒有修改。
- 完成兩輪 RED → GREEN（先證明錯誤，再修到通過）：撤銷失效、唯讀憑證不得呼叫工具。
- 沒有部署、合併、正式設定修改、DNS 操作、付費資源或帳號操作。沒有變更 issue（任務）狀態。

## 真實邊界與測試替身的區別

`test_edgar_native_http.py` 啟動真正的 `ThreadingHTTPServer` 與
`MCPHTTPHandler`，只綁 `127.0.0.1` 的作業系統隨機埠。
每次驗證都使用真正 TCP 連線送 JSON-RPC `POST /mcp`，不是直接呼叫授權判斷函式。
成功的工具清單與 `echo`（原樣回覆文字）也走真正工具分派。

Auth 使用真實 `create_app(Config(...))`、隔離 SQLite 資料庫及記憶體中產生的 RSA 金鑰。
透過 `TestClient`（程序內 ASGI 請求客戶端）執行 `/authorize`、`/consent`、
PKCE（授權碼兌換防攔截）、`/token`、`/jwks.json`、`/introspect` 與 `/revoke`。
登入 session（登入狀態）由測試直接建立，未測密碼或 MFA（多因素驗證）登入。
AS 端不是 TCP/TLS 服務，不能宣稱跨主機或完整瀏覽器端到端驗證。

正向與撤銷測試沒有替換 JWT 驗證、MCP handler、工具清單或工具分派。
`handle_fs_write` 使用包住原函式的 spy（呼叫監測），同時斷言沒有被呼叫且檔案不存在。
故障注入案例才會替換 introspection（向授權伺服器查驗有效狀態）回應，
用來測試失聯、逾時、錯誤格式及不一致資料時確實拒絕。

## What Changed（修正）

- 保留釘選 JWKS（可信公開金鑰集合）及 RS256 簽章、issuer（簽發者）、
  audience（適用服務）、有效期與 scope（權限範圍）檢查。
- 新增 `HandcraftServerConfig.edgar_native_as_introspect` 可信注入函式。
  未提供函式、函式丟出例外、`active` 不是字面 `True`，一律拒絕。
- 查驗回應必須與已驗章的 `iss/sub/aud/exp/iat/scope/client_id` 一致。
  不接受用戶自報 claims（憑證內容），不依 token 的 `jku` 去下載金鑰。
- 沒有新增網路客戶端、設定網址探索或環境變數開關。測試 adapter（轉接函式）
  以隨機產生的測試機密，驗證身分後呼叫真實 `/introspect`。
- native（原生模式）仍預設關閉。啟用後不回退至 static token（固定憑證）、
  Descope 或 Cloudflare 公開固定憑證替代路徑。
- `tools/call` 額外要求 `mcp:write`，仍須符合設定的基本 scope（預設 `mcp:read`）。
  所有工具呼叫都採此保守限制，包含 `echo`，尚未細分逐工具讀寫權限。
  分派前再次驗章與查驗有效狀態，所以有效工具呼叫會執行兩次查驗，不快取通過結果。

## Verification（驗證紀錄）

| 紀錄 | 實際結果 |
| --- | --- |
| `baseline.txt` | 修改前既有 HTTP 與 JWT 邊界測試：158 passed、1 failed、116 subtests passed |
| `red.txt` | 撤銷後相同未過期憑證仍得到 tools/list 200、tools/call 200，進入寫入函式；預期 401 的斷言失敗 |
| `green-slice.txt` | 中途測試誤以為既有 401 本文是 JSON；實際是純文字 Unauthorized，修正測試解析方式 |
| `green-slice-final.txt` | 最小撤銷修正與既有七項 JWT 測試：8 passed |
| `red-scope.txt` | mcp:read 憑證仍可進入寫入分派，預期 401，實得 200 |
| `green-native.txt` | 新增負向測試及工具權限修正：33 passed |
| `green-final.txt` | 最終 26 項新測試加 7 項既有測試：33 passed |
| `regression.txt` | 七個測試模組：253 passed、4 failed、1 skipped、129 subtests passed |
| `baseline-existing.txt` | 記憶體載入原版 f48403e 的 server_http.py、保留真實 __file__，重跑五個未修改的既有模組：220 passed、相同 4 failed、1 skipped、129 subtests passed |

既有七項 JWT 測試已在最初基準通過，也在最終再次通過。
因此可比較的既有測試為 227 passed、4 failed、1 skipped；新增 26 項全部通過，
沒有增加已知回歸失敗，沒有為了通過而略過或更改既有失敗測試。

四項失敗均在原版重現：

1. `CacheTraceRotationScriptTests::test_cache_trace_rotation_archives_then_reopens_log`：
   Linux 沒有 `powershell`。
2. `WrapDefaultOffTests::test_fleet_route_and_auto_dispatch_use_fixed_arguments_without_leaking_argv`：
   缺 Windows Fleet 指令稿，函式提早回傳，測試預期的 `_run` 呼叫不存在。
3. `WrapLiveSafeTests::test_hermes_and_openclaw_binaries_exist`：缺本機 Hermes 執行檔。
4. `WrapLiveSafeTests::test_qmd_cli_still_resolves`：缺本機 QMD 執行檔。

既有跳過項目：缺 OpenMontage Windows checkout（本機程式副本）。
原版記憶體載入比較額外產生一項 pytest 警告：anyio 已先載入而無法重寫斷言，
不是測試略過或失敗。

### 最終 HTTP 證據

使用**同一枚**真實 Auth 簽發、仍未過期、具 `mcp:read mcp:write` 的憑證：

| 動作 | HTTP |
| --- | --- |
| 撤銷前 POST /mcp tools/list | 200，包含真正 echo 工具 |
| 撤銷前 POST /mcp tools/call echo | 200，實際回覆 before-revocation |
| Auth POST /revoke | 200 |
| Auth POST /introspect | active: false |
| 撤銷後 POST /mcp tools/list | 401 |
| 撤銷後 POST /mcp tools/call fs_write | 401，沒有進入寫入函式、沒有檔案 |

401 本文為 `Unauthorized`，`WWW-Authenticate` 含 `error="invalid_token"`。
完整、不含憑證的 HTTP 摘要在 `green-final.txt` 的 `HTTP_EVIDENCE`。
最初 RED 只使用讀取 scope；最終測試改用讀寫 scope 並先成功呼叫 echo，
避免把撤銷拒絕誤認成缺少寫入權限。

## 重跑方式

在這個 repo 的根目錄，使用隔離 `.venv-edg478`。
Auth 以 `PYTHONPATH` 唯讀載入，未在來源 repo 建立 editable install（可編輯套件安裝）產物。
`python-packages.txt` 記錄實際安裝套件版本，不修改正式 requirements。

```sh
cd /home/edgar/workspaces/edg478-aka1-20261101/edgars-mcp
python3 -m venv .venv-edg478
.venv-edg478/bin/python -m pip install -r docs/receipts/edg478-aka1-20261101/python-packages.txt
env -i PATH="$PATH" HOME="$HOME" PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/home/edgar/workspaces/edg478-aka1-20261101/edgar-auth-server \
  .venv-edg478/bin/python -m pytest -q -s \
  test_edgar_native_http.py test_edgar_issuer_bridge.py \
  --basetemp=.pytest-edg478-rerun
```

回歸測試使用相同隔離環境：

```sh
env -i PATH="$PATH" HOME="$HOME" PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/home/edgar/workspaces/edg478-aka1-20261101/edgar-auth-server \
  .venv-edg478/bin/python -m pytest -q \
  test_server_http.py test_edgar_issuer_bridge.py test_edgar_native_http.py \
  test_mcp_upstreams.py test_context_compaction.py \
  test_hermes_stdio_proxy.py test_stdio_proxy.py \
  --basetemp=.pytest-edg478-rerun-regression --tb=short
```

已提交文字紀錄僅省略冗長的 tools/list 工具目錄 JSON，保留狀態、失敗堆疊與斷言。
完整原始輸出另留在此目錄的 `.raw.log`，由既有 `.gitignore` 排除，不提交。
測試暫存資料與 RED 產生的隔離寫入檔案於收尾清除。

## Known Limits / Risks（未驗證關卡與風險）

- 不提供也不啟用正式 introspection adapter。未來實作必須使用可信通道、
  驗證 AS 身分、設定逾時，而且不得快取有效結果；本次只測到逾時例外的拒絕行為。
- 尚未驗證跨主機 TLS、反向代理、真實瀏覽器授權、登入/MFA、金鑰輪替、
  高併發或逐工具細分權限。AS 全套測試的先前 43 passed 不是本次重跑結果。
- 查驗與工具執行不是資料庫原子交易；不宣稱能取消已開始執行的工具。
  本次保證是撤銷完成後的新 HTTP 請求被拒絕。
- 原生啟用但沒有可信查驗函式會拒絕所有原生憑證，這是刻意的安全行為。
- Linear 連接器讀取 `EDG-478` 回傳 404，因此沒有更新 Linear，也沒有標示產品完成。

## Next（唯一下一步）

審查以指定測試分支為基底的 Draft PR（草稿變更審查），確認可信查驗介面與
保守 tools/call 權限規則後，再另行批准跨主機測試；不要部署本次分支。
