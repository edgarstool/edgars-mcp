# EDG-478：跨程序 AS HTTP（本機授權服務）驗證

## Status（結果）

2026-11-01，aka1 Linux；程式與驗收測試完成，未提交、推送或開草稿審查。
分支：`test/edg478-cross-process-tcp-aka1-20261101`，起點／目前 HEAD：
`b18663e3fc73d476e1db767151661772e7c1014d`。
AS（授權服務）唯讀來源：`b8648ee3a83143ac30ec779098fcc33abc1bab43`。

Git 未設定作者身分，`git var GIT_AUTHOR_IDENT` 回傳 128；
執行環境規則禁止以 `git -c user.*` 或其他方式覆寫身分，因此沒有製造提交。
尚無新 commit（提交）或 PR（變更審查）連結。未來指定的草稿基底是
`test/edg478-native-http-revocation-aka1-20261101`，不是主幹。
Linear（任務系統）讀取 `EDG-478` 回傳 404，沒有更動遠端任務。

## Files Changed（新增檔案）

- `native_introspection.py`：標準函式庫實作的可信 HTTP 狀態查詢轉接器。
- `test_edgar_native_tcp.py`：30 項新增測試，重用既有真實 MCP TCP 輔助函式。
- 本文件：可重現命令、測試摘要與限制。

既有 `server_http.py`、AS 來源、依賴清單與正式設定均未修改。

## What Changed（實際邊界）

```text
pytest 父程序
  ├─ 真實 HTTPX → 127.0.0.1:隨機埠 → 獨立 spawn 子程序
  │                                  uvicorn + 原生 FastAPI AS
  │                                  暫存 SQLite、隨機 RSA、測試用戶端
  └─ 真實 TCP POST /mcp → 同程序的 MCPHTTPHandler 伺服器執行緒
                           └─ HTTPIntrospectionClient
                                → 真實 TCP POST /introspect → 上述 AS 子程序
```

先綁定 `127.0.0.1:0`，將同一個監聽 socket（網路插座）交給子程序，
不先釋放再搶埠。以實際 `/healthz` 探測啟動；
結束時 terminate/join，必要時 kill/join，確認程序停止並刪除暫存資料庫。

`/authorize`、`GET/POST /consent`、`/token`、`/jwks.json`、
`/introspect`、`/revoke` 全部經真實 TCP。PKCE（授權碼防攔截）真的兌換，
同意表單的 CSRF（防偽欄位）由 HTTP 頁面解析，不直接讀資料庫取代流程。
只有登入狀態與用戶端註冊由隔離測試預建。

權杖宣稱的 issuer（簽發者）固定為 `https://issuer.edg478.test`；
實際傳輸是 **`http://127.0.0.1:<port>`，沒有 TLS（加密傳輸）**。
沒有向該測試網域送請求，也沒有宣稱正式路由或公開 HTTPS 已通過。

轉接器只使用操作者提供的固定端點、client ID（用戶端代號）及隨機測試機密，
透過 `client_secret_post` 認證。每次都真正查詢，不快取有效結果。
不接受權杖指定的 URL、不追蹤重新導向、不讀代理環境變數、不重試，
不把來訪的 Bearer（持有人）認證標頭轉送。權杖僅放在標準查詢表單。
輸入表單上限 8192 bytes，回應上限 65536 bytes，逾時須有限且不超過 30 秒。
預設要求 HTTPS 並使用 Python 預設憑證檢查；
測試明確開啟 `allow_loopback_http=True`，僅容許數字型本機位址。
native（原生模式）仍預設關閉；建立或注入轉接器不會自動啟用。

## Verification（實測與紀錄摘要）

| 階段 | 結果 |
| --- | --- |
| 初始 RED（先失敗） | 1 failed，真實 AS TCP 簽發及查詢已成功，但轉接器模組尚不存在 |
| 行為 RED（認證缺漏） | 1 failed，轉接器未送 client_secret，AS 拒絕，MCP 得到 401 而非預期 200 |
| GREEN（補上機密認證） | 新增 30 項 + 既有原生 33 項，63 passed，38.42 秒 |
| 完整相關回歸 | 283 passed、4 failed、1 skipped、129 subtests passed，66.93 秒 |
| 最終暫存清理修正後重跑 | 30 項新增測試全部通過，18.89 秒 |

與基底已提交的 `docs/receipts/edg478-aka1-20261101/README.md` 比較，
通過數從 253 增為 283，四項失敗與一項略過相同。沒有修改或跳過失敗測試；
本次沒有另外重新執行舊版原始碼基準。

既有四項失敗：

1. `CacheTraceRotationScriptTests::test_cache_trace_rotation_archives_then_reopens_log`：缺 `powershell`。
2. `WrapDefaultOffTests::test_fleet_route_and_auto_dispatch_use_fixed_arguments_without_leaking_argv`：缺 Windows Fleet 指令稿。
3. `WrapLiveSafeTests::test_hermes_and_openclaw_binaries_exist`：缺本機 Hermes 執行檔。
4. `WrapLiveSafeTests::test_qmd_cli_still_resolves`：缺本機 QMD 執行檔。

### HTTP 狀態證據

| 動作／對照 | HTTP／結果 |
| --- | --- |
| 機密用戶端正確認證查詢狀態 | 200、active: true |
| 撤銷前 tools/list、tools/call echo | 200、200，真正回覆 `echo: cross-process` |
| 同一枚未過期 JWT（簽章權杖）POST /revoke | 200；再查詢 active: false；離線驗章仍通過 |
| 撤銷後 tools/list、tools/call fs_write | 401、401；目標檔案不存在 |
| 錯誤機密／公開用戶端／僅 Bearer 呼叫 AS 查詢 | 401／401／401 |
| MCP 使用錯誤機密查詢 AS | 401 |
| AS 子程序真的停止後，tools/list、fs_write | 401、401，兩次合計小於 4 秒，沒有寫檔 |
| 錯誤 issuer／audience（適用服務）／scope（權限） | 全部 401 |
| 真實 mcp:read 權杖列清單／呼叫 echo 或 fs_write | 200／401／401，沒有寫檔 |

另以明確標示的真實 TCP 故障伺服器測重新導向、實際逾時、錯誤 JSON、
非物件、非布林 active 及過大回應，全部拒絕；它不是原生 AS 成功證據。
沒有用假狀態查詢函式冒充原生網路驗證。
測試輸出的 `TCP_EVIDENCE`、`CREDENTIAL_EVIDENCE`、`OUTAGE_EVIDENCE`
僅包含狀態摘要，不輸出權杖、機密、登入 cookie 或私鑰。

## 重跑方式

使用既有隔離直譯器，不安裝套件、不讀正式環境：

```sh
cd /home/edgar/workspaces/edg478-aka1-20261101/edgars-mcp-as-tcp
env -i PATH="$PATH" HOME="$HOME" PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/home/edgar/workspaces/edg478-aka1-20261101/edgar-auth-server \
  /home/edgar/workspaces/edg478-aka1-20261101/edgars-mcp/.venv-edg478/bin/python \
  -m pytest -q test_edgar_native_tcp.py test_edgar_native_http.py \
  test_edgar_issuer_bridge.py --tb=short
```

完整相關回歸在同一命令加入 `test_server_http.py test_mcp_upstreams.py
test_context_compaction.py test_hermes_stdio_proxy.py test_stdio_proxy.py`。
需顯示無機密的狀態證據時加 `-s`；既有 MCP 日誌會額外印出冗長工具目錄。
初始 RED 只描述已觀察到的舊狀態，不會在最後版本上再次失敗。

## Known Limits / Risks（限制與風險）

- 沒有公開 HTTPS、跨主機、瀏覽器端到端、密碼登入、多因素驗證或正式路由驗證。
  測試明確手送合成 session cookie（登入狀態），不宣稱瀏覽器 Secure-cookie 行為通過。
- 有限逾時是 socket I/O（網路讀寫）逾時，不是含 DNS 或持續零星送資料的整體硬截止時間。
- 未測金鑰輪替、並行負載或逐工具細分權限。沿用既有規則，所有 tools/call 都要求 mcp:write。
- 查驗與工具執行不是原子交易；不保證撤銷能中止已開始的呼叫。
- 沒有更動 `.hermes`、1Password、正式服務、DNS、雲端設定或供應商憑證。
- 沒有執行 AS 全套測試；本次是兩端整合與既有 MCP 相關回歸驗證。

## Next（唯一下一步）

由已設定合法 Git 身分的環境提交這三個檔案、推送現有分支，並以上述指定基底
開 Draft stacked PR（疊在前一分支上的草稿審查），不要合併或部署。
