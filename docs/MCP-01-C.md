# MCP Server OAuth 相容性問題根因分析與架構決策報告

（手刻 vs FastAPI vs FastMCP；目標：ChatGPT OAuth 全綠）

查閱期間：2026-07-05。MCP 規格為快速演進中的活文件，本報告標示查閱日期與版本風險。凡標「降權」者為社群/第三方來源，信任權重較低；關鍵結論盡量以官方規格 / 官方文件 / 官方 repo 為主。

-----

# 1. Executive Summary（白話結論，10 句內）

1. **現在不該重寫。** 你的手刻 server 主體幾乎可以保留；「does not implement OAuth」這條錯誤在絕大多數情況只是差 1~3 個 metadata / header / path 細節，不是架構錯誤。
1. 最該先做的事：**先修手刻**，把 OAuth「discovery（發現）」這一小塊補齊、補對，就有很高機率從紅變綠。
1. 「does not implement OAuth」白話講就是：**ChatGPT 在你 server 上「找不到」它要的那份 OAuth 說明文件（protected resource metadata / authorization server metadata），或找到的內容不對 / 被 Cloudflare 擋掉 / 被 reverse proxy 改壞了**。
1. 最可能根因排序：**Protected Resource Metadata 路徑不對或 404 ＞ authorization server metadata 取不到 ＞ reverse proxy/Cloudflare 改壞路徑或擋掉 ＞ issuer 不一致 ＞ 401/WWW-Authenticate 行為不符**。
1. **FastAPI 值得納入**，但只當「HTTP/ASGI 外層」用，不是拿來取代你的手刻邏輯——它讓你能穩定掌控路由與 headers，剛好對症。
1. **FastMCP 值得「局部」參考或整合**，因為它把「protected resource metadata + WWW-Authenticate 挑戰」這塊自動化，正是你在踩的坑；但不建議現在整包換成 FastMCP。
1. **官方 Python MCP SDK v2 現在不適合押身家上 production**：截至查閱日仍是 beta（`mcp==2.0.0b1`），穩定版才剛要發布，建議觀望。
1. 拿到全綠最快的路線是：**「純手刻補齊 discovery」→（若一週內補不動）再考慮把 discovery/metadata 這一小層交給 FastMCP 或官方 SDK 產生**。
1. 你重視的「完全掌控 OAuth / discovery / metadata / Cloudflare / proxy / headers / route」——這正是手刻的優勢，也正是問題所在：全綠與否幾乎完全取決於這幾個你已經在掌控的點。
1. 一句話：**先手刻修補，保留主體，FastAPI 當外層，FastMCP 當「metadata 產生器」的候選，官方 SDK v2 觀望，不要現在重寫。**

-----

# 2. Context Restatement（用我的話重述需求）

你有一個**手刻（不靠框架自己寫）的 remote MCP server**，部署在 `mcp.edgars.tools`，路徑 `/mcp`，前面有 **Cloudflare / reverse proxy / tunnel**。在 ChatGPT 的「自訂 MCP 連接 / Connector / Apps」設定中選 OAuth，出現：

> “MCP server <https://mcp.edgars.tools/mcp> does not implement OAuth”

你的目標是把這條線修到「ChatGPT 端判定 OAuth 正確實作（全綠）」。你的偏好與限制：

- **想保留手刻主體**，要對 OAuth / discovery / metadata / Cloudflare / proxy / headers / route 有完整掌控感。
- 不絕對排斥框架，可接受**混合式、漸進式、局部替換**，但不想因為「主流」就整包重寫。
- **非工程背景**，需要術語附白話、技術嚴謹、可交接、可落地。
- 現在要的是**研究與判斷**，不是直接改 code。
- 沒有官方明文的地方，要標示 Fact / Inference / Unknown。

我確認理解無誤：這不是一般框架比較題，而是「一個已存在的手刻 OAuth resource server，卡在 ChatGPT 的 OAuth discovery 判定，要用最小破壞、保留手刻的方式修到全綠，並順帶評估未來演進」。

-----

# 3. Facts（查到的事實，附來源性質）

> 術語小抄：**metadata（中繼資料）**＝一份描述「怎麼跟你做 OAuth」的 JSON 說明文件；**discovery（發現）**＝client 去抓那份說明文件的過程；**issuer（發行者）**＝授權伺服器的身分字串（一個網址）；**PRM**＝Protected Resource Metadata（受保護資源中繼資料）；**AS metadata**＝Authorization Server Metadata（授權伺服器中繼資料）。

**F1（規格 / MCP 官方）** MCP server 作為 OAuth 2.1 resource server，**MUST（必須）實作 RFC 9728 Protected Resource Metadata**；授權伺服器 **MUST 提供 RFC 8414 Authorization Server Metadata 或 OpenID Connect Discovery 至少一種**。來源：modelcontextprotocol.io 授權規格（official spec）。

**F2（規格 / MCP 官方）** MCP server 至少要實作以下之一來告訴 client 去哪拿 metadata：(a) 在 401 回應帶 `WWW-Authenticate` header，內含 `resource_metadata` 指向 PRM；或 (b) 在 well-known URI 提供 metadata。PRM 可放在「路徑感知」位置 `https://host/.well-known/oauth-protected-resource/mcp`，或根位置 `https://host/.well-known/oauth-protected-resource`。來源：MCP 授權規格（official spec）。

**F3（OpenAI 官方）** OpenAI Apps SDK「Authentication」頁明列 ChatGPT 對已驗證 MCP server 的要求：在 MCP server 上 host protected resource metadata；由授權伺服器發布 OAuth metadata（`/.well-known/oauth-authorization-server` 或 `/.well-known/openid-configuration`）；在整個 OAuth 流程 echo（回傳）`resource` 參數；選擇 client 註冊方式（CIMD / DCR / 預定義 client）；用 PKCE（S256）。原文：“ChatGPT queries your MCP server for protected resource metadata.”  來源：developers.openai.com/apps-sdk/build/auth（official docs）。

**F4（OpenAI 官方）** PRM 範例 JSON 必要欄位：`resource`（你的 MCP server 標準 HTTPS 識別碼，ChatGPT 會把這個值原封不動當 OAuth 的 `resource` 參數）、`authorization_servers`（一個或多個 issuer base URL）、`scopes_supported`。來源：developers.openai.com/apps-sdk/build/auth（official docs）。

**F5（OpenAI 官方）** ChatGPT 完成 OAuth 後 redirect 到 `https://chatgpt.com/connector/oauth/{callback_id}`（舊版 published app 仍支援 `https://chatgpt.com/connector_platform_oauth_redirect`）；此 redirect URI 必須加入授權伺服器允許清單。來源：developers.openai.com/apps-sdk/build/auth（official docs）。

**F6（社群實測，關鍵）** 有工程師抓到 ChatGPT 在「新增 MCP server」時的實際 server 端 log（2025-11-06，用戶 jakelin）：ChatGPT 先對 `/mcp` 送未帶 token 的 `POST`（初始化握手），接著**連續 GET 探測約 7 種 well-known 變體**：`/.well-known/openid-configuration`、`/.well-known/oauth-authorization-server`、`/mcp/.well-known/openid-configuration`、`/.well-known/openid-configuration/mcp`、`/.well-known/oauth-authorization-server/mcp`、`/.well-known/oauth-protected-resource`、`/.well-known/oauth-protected-resource/mcp`，最後還 GET `/`。該案例中**這些全部回 404**，連不上。來源：OpenAI 開發者社群（discussion/issue，降權但為第一手實測）。

**F7（社群實測 / OpenAI 員工回覆）** ChatGPT connector 會**直接打 `/.well-known/oauth-authorization-server` 與 `/.well-known/openid-configuration`**（不一定先走 401→WWW-Authenticate 的教科書順序）。OpenAI_Support（2025-12-04）證實：預設 client 初次連線不請求任何 scope，之後已更新為「從 www-authenticate header 自動發現所需 scopes 並在初次握手請求」。 來源：OpenAI 開發者社群（maintainer/官方帳號回覆，降權但具權威）。

**F8（社群實測，關鍵 reverse-proxy 案例）** 一位工程師的 ChatGPT connector 報「Failed to resolve OAuth client」，根因是他的 **NGINX 把 `/.well-known/oauth-authorization-server/mcp` 改寫（rewrite）成 `/mcp/.well-known/oauth-authorization-server`** 後才轉發，導致 ChatGPT 拿到空的 discovery 文件、`oauth_client_params` 變成 null。**把 proxy 改成原樣轉發（不動路徑）後立刻全綠。** 他的結論原文：“ChatGPT is stricter than Claude about the MCP-specific discovery path.”  來源：OpenAI 開發者社群（第一手 resolved 案例）。

**F9（確認錯誤字串）** 「MCP server url does not implement OAuth」為真實存在的錯誤字串（多位用戶 2026-02 回報）。其中一位（AldiPower）明確表示：伺服器已實作 OAuth 2.1、log 顯示 ChatGPT 有成功抓 well-known，但仍報此錯，原文：“Our server has oAuth 2.1 implement and I can see in the server log that chatgpt is sucessfully fetching from the .well-known endpoint!”。  來源：OpenAI 開發者社群（第一手回報，降權）。

**F10（RFC 8414）** 若 issuer 含路徑（如 `https://host/tenant1`），well-known URL 要把 `/.well-known/oauth-authorization-server` **插在 host 與 path 之間**（→ `https://host/.well-known/oauth-authorization-server/tenant1`），不是接在最後。且回傳文件中的 `issuer` **必須與**用來組出 well-known URL 的 issuer identifier **逐字相同**，否則 client 必須拒用。來源：RFC 8414（IETF，spec）。

**F11（規格）** iss / issuer 比較是**嚴格字串比較**：不得做 scheme/host 大小寫折疊、預設 port 省略、**trailing slash（結尾斜線）正規化**、percent-encoding 正規化。換言之 `https://a.com` 與 `https://a.com/` 會被判為不同。來源：MCP 授權規格 / RFC 9207（spec）。

**F12（實務常見坑）** 現實中多數 MCP client（含 VS Code、Claude、依報告推論也含 ChatGPT）在解析 `authorization_servers` 時，**常忽略其中的 path 部分、直接對根網域組 well-known**， 導致 issuer 帶路徑時 discovery 失敗。實務解法是**把 well-known 都攤平到根網域**或用獨立 host。 來源：Microsoft Learn Q&A、多個 GitHub issues（降權，第三方＋廠商）。

**F13（Cloudflare 相關）** Cloudflare 的「Block AI bots / Browser Integrity」與 Access「Managed OAuth」等功能會改變 401 行為或擋流量；已有多起 MCP 連線失敗案例與 Cloudflare 行為有關（如 401 未帶 WWW-Authenticate、或 bot 阻擋）。Cloudflare 官方文件明載：若你自己跑 OAuth server 並依賴自己的 WWW-Authenticate，**不要**開 Managed OAuth，因為它會取代你的 401 行為（原文：“Enabling managed OAuth replaces the 401 response behavior on the protected application.”）。來源：Cloudflare 官方文件 + anthropics/claude-ai-mcp issues（official docs + 第三方）。

**F14（FastMCP 官方 / 維護者）** FastMCP 的 `RemoteAuthProvider` 會**自動建立 RFC 9728 的 PRM endpoint、並回傳正確的 WWW-Authenticate 挑戰**（把你正在踩的坑自動化）。FastMCP 現由 Prefect 團隊維護，**3.0 已於 jlowin.dev「FastMCP 3.0 is GA」發布文正式 GA、PyPI 最新為 3.4.2、並將 repo 從 jlowin/fastmcp 移至 PrefectHQ/fastmcp**。 採用度：2.12 的 OAuth proxy 於 2025-08-31 上線後，**下載量峰值達每日 1.25 million 次**（jlowin.dev 原文：“Downloads exploded from 200,000 to a peak of 1.25 million a day”）；README 逐字宣稱：“the actively maintained standalone project is downloaded a million times a day, and some version of FastMCP powers 70% of MCP servers across all languages”。 第三方調查（bloomberry.com「I analyzed 1400 MCP servers」）亦佐證：“Three SDKs account for 100% of identifiable implementations with FastMCP having the lion’s share”，且同調查指出 “38.7% of MCP servers had no authentication”（ 佐證 OAuth 常被忽略的產業背景）。來源：gofastmcp.com docs、jlowin.dev、github.com/jlowin/fastmcp README（official docs + maintainer statement）；bloomberry.com（第三方，降權）。

**F15（FastMCP 已知坑）** FastMCP 的 `RemoteAuthProvider` 曾有 bug：PRM 的 `resource` 欄位固定回根網址而非實際 `/mcp/` 端點（#1348）；且 `mcp` 依賴 1.17+ 後 PRM endpoint 改為「路徑感知」位置，`/.well-known/oauth-protected-resource` 回 404、只有 `/.well-known/oauth-protected-resource/mcp` 回 200，造成部分 client discovery 失敗（#2077 / #2123）。來源：PrefectHQ/fastmcp GitHub issues（official repo issues）。

**F16（官方 Python SDK v2 狀態）** 官方 modelcontextprotocol/python-sdk **v2 是為 2026-07-28 新版 MCP 規格做的大改版**，把核心從「有狀態、雙向、長連線 session」改成「無狀態 request/response」， 是重寫核心。查閱時 v2 為 beta（具體為 **`mcp==2.0.0b1`**，首個完整支援 2026-07-28 spec 的版本）；穩定線最新為 **v1.28.1（PyPI, 2026-06-26）**；**穩定版 v2 目標約 2026-07-27**（README 原文：“Stable v2 is targeted for 2026-07-27, alongside the spec release”）。官方在 v2.0.0a1 release note 明白警告：**“84% of the 10,000+ PyPI packages that depend on mcp declare no upper bound, and they’ll all resolve to v2 the day the stable release ships. Add `<2` to your existing constraint, for example `mcp>=1.27,<2`”**。 v1.x 仍是穩定線，持續收關鍵修補。 來源：modelcontextprotocol/python-sdk GitHub releases + PyPI（official repo）。

**F17（官方 SDK 也用 FastMCP 血統）** FastMCP 1.0 已於 2024 併入官方 Python MCP SDK； 官方 SDK 內的 `mcp.server.fastmcp.FastMCP` 即源於此。官方 SDK 亦提供 resource server 用的 `TokenVerifier`、`AuthSettings`（RFC 9728 PRM）等原語，並附 simple-auth 範例（AS 與 RS 分離、RFC 8707 strict resource 驗證、legacy AS 相容）。來源：官方 SDK repo + PyPI（official）。

**F18（FastAPI 定位）** FastAPI 是 ASGI Web 框架（建於 Starlette 之上），本身**不是 MCP 框架**，不會幫你產生任何 MCP／OAuth metadata；它的價值在於穩定的 HTTP 路由、middleware、headers 控制。FastMCP／官方 SDK 產生的是 Starlette/ASGI app，可與 FastAPI 互相 mount（`http_app()` / `app.mount()` / `FastMCP.from_fastapi()`），但**必須正確合併 lifespan**，否則會出現「StreamableHTTPSessionManager task group was not initialized」類錯誤。來源：FastMCP docs、官方 SDK issues（official + 第三方）。

**F19（ChatGPT 需要 search/fetch 工具）** 對 ChatGPT deep research / company knowledge 類用途，MCP server 應實作 `search` 與 `fetch` 兩個工具； 缺少會有「search action not found」類錯誤。此與 OAuth 判定是**不同**的檢查。來源：developers.openai.com/api/docs/mcp（official docs）。

**F20（MCP-Protocol-Version header）** 從 MCP 2025-06-18 起，Streamable HTTP 上 `MCP-Protocol-Version` request header 為必要；server 不認得該值時應回 HTTP 400；client 沒帶時 fallback 到 2025-03-26 語意。查閱時最新穩定規格為 2025-11-25，下一版 2026-07-28 將推出。來源：MCP 規格（spec）。

-----

# 4. Unknowns（仍無法確認，及原因）

- **U1（最關鍵 Unknown）** OpenAI **沒有官方明文**說「does not implement OAuth」這句話對應到「哪一個」檢查失敗。整個判定邏輯是從官方 docs + 社群封包實測 + MCP 規格三方交叉「推論」出來的。原因：OpenAI 未公開 connector 的 OAuth 偵測程式碼或明確判定表。
- **U2** 你的 `mcp.edgars.tools/mcp` 目前**實際回什麼**（未帶 token 的 POST 回 200 還是 401？三種 well-known 各回什麼狀態碼與內容？`issuer` 字串為何？有無 trailing slash？）——沒有你的實際封包/log 無法斷定。這是把根因從「推論」變「確定」的關鍵缺口。
- **U3** F9 那批 2026-02 的「well-known 明明抓得到卻仍報錯」案例，究竟是使用者 server 內容不對，還是 **ChatGPT 端當時的 bug/regression**，OpenAI 未公開診斷。原因：官方未回覆根因。（同期 OpenAI 確有其他 connector 端 infra bug，如「unsupported OAuth config type」被官方承認為遷移 bug。）
- **U4** 你目前是否已經在用某個框架片段、你的 auth server 是自建還是外部 IdP（Auth0/Cognito 等）、`/mcp` 是否 stateless——這些會影響最小修補的具體步驟。原因：任務未提供。
- **U5** Cloudflare 前面到底套了哪些設定（Managed OAuth？Block AI bots？WAF？快取？）——會不會是它擋掉或改寫 well-known / 401，需要你的 Cloudflare 設定才能確認。原因：任務未提供。

-----

# 5. Inferences（推論，含依據與信心）

- **I1（信心：高）** 「does not implement OAuth」最可能代表：**ChatGPT 在 discovery 階段拿不到一份有效的 PRM（RFC 9728），且其 fallback（oauth-authorization-server / openid-configuration，根層與 /mcp 路徑層）也都失敗**。依據：F1、F3、F6（全 404 即連不上）、F9、規格 MUST 條款。
- **I2（信心：中高）** 對你這種**手刻 + Cloudflare/reverse proxy/tunnel** 的部署，**最可能的實際兇手是 proxy/Cloudflare 把 well-known 路徑改寫、擋掉，或本機正常但外部行為不同**（F8 的 NGINX 改寫案例、F13 的 Cloudflare 行為就是活生生的例子）。依據：F8、F13、U2/U5 的部署特徵吻合。
- **I3（信心：中高）** 你「手刻主體很可能沒壞，只差 1~3 個 metadata/header/path/issuer 細節」是成立的。依據：F8（只改一條 proxy 規則就全綠）、F9（server 已實作 OAuth 只差判定）、大量社群案例都是小設定。
- **I4（信心：中）** 若 PRM 的 `authorization_servers` 或 `issuer` **帶路徑**，很可能踩到 client「忽略路徑、對根網域組 well-known」的坑（F12），或 issuer 逐字比對因 trailing slash 失敗（F10/F11）。依據：F10、F11、F12。
- **I5（信心：中）** **FastMCP 確實能幫你避開「PRM 產生 + WWW-Authenticate 挑戰 + well-known 路由」這幾個坑**（F14），但它自己也曾在「resource 欄位」「well-known 路徑感知位置」出過同型 bug（F15）——所以它不是魔法，只是把你手刻的那段換成經眾人踩過的實作。依據：F14、F15。
- **I6（信心：高）** **官方 Python SDK v2 現在不宜上 production**：官方自己要你 pin `<2`、穩定版才剛要發布、且是無狀態核心重寫。依據：F16（官方明文）。
- **I7（信心：高）** **FastAPI 無法直接解你的 OAuth 判定問題**（它不產生 metadata），但作為 ASGI 外層能給你穩定、可預測的路由/headers 控制，反而讓你更容易把 well-known 放對位置、避免 proxy 亂改。依據：F18。

-----

# 6. 「does not implement OAuth」最可能的意思（依可能性排序）

> 通用驗證指令（把 `mcp.edgars.tools` 換成你的網域，從**外網**跑，不要只在本機跑）：
> `curl -i https://mcp.edgars.tools/.well-known/oauth-protected-resource`
> `curl -i https://mcp.edgars.tools/.well-known/oauth-protected-resource/mcp`
> `curl -i https://mcp.edgars.tools/.well-known/oauth-authorization-server`
> `curl -i https://mcp.edgars.tools/.well-known/openid-configuration`
> `curl -i -X POST https://mcp.edgars.tools/mcp`（看未帶 token 是回 401 還是 200，有沒有 WWW-Authenticate）

**排序 1（可能性：最高）Protected Resource Metadata 找不到 / 404 / 路徑不對**

- 原因：ChatGPT 探測 PRM 的根層與 `/mcp` 路徑層都失敗（F6 全 404）。
- 症狀：connector 建立時就報 does not implement OAuth，log 可能看到多個 well-known 都是 404。
- 驗證：上面前兩條 curl。**至少一條要回 200 + 合法 JSON（含 resource / authorization_servers）。**

**排序 2（高）Authorization Server Metadata 取不到**

- 原因：PRM 抓到了，但 `authorization_servers` 指向的網址，其 `/.well-known/oauth-authorization-server`（或 openid-configuration）回 404 或無效（GitHub 官方 MCP 就是此類，authorization_servers 指到會 404 的網址）。
- 症狀：更常出現「Error fetching OAuth configuration」，但也會落入「找不到 OAuth」類判定。
- 驗證：第三、四條 curl 要回 200 + 合法 JSON（含 issuer / authorization_endpoint / token_endpoint）。

**排序 3（中高，你的部署特別要看）reverse proxy / Cloudflare / tunnel 導致外部行為與本機不同**

- 原因：proxy 改寫 well-known 路徑（F8）、Cloudflare 擋 bot 或 Managed OAuth 取代了 401（F13）、或快取回舊值。
- 症狀：本機 curl 正常、外網或 ChatGPT 端失敗；或 ChatGPT log 看得到請求卻拿到空/錯內容。
- 驗證：**務必從外網**跑上面 curl，並比對本機結果；檢查 Cloudflare 是否開了 Managed OAuth / Block AI bots / 快取 well-known。

**排序 4（中）issuer 不一致 / trailing slash 不符**

- 原因：PRM/AS metadata 的 `issuer` 與用來組 well-known 的 issuer 逐字不同（含結尾斜線差異）（F10/F11）；或 issuer 帶路徑被 client 忽略路徑（F12）。
- 症狀：discovery 抓得到但被判無效、或 client 對錯網址組 well-known。
- 驗證：確認回傳 JSON 的 `issuer` 與你對外宣告的完全逐字相同（大小寫、斜線、port）。

**排序 5（中低）401 回應行為 / WWW-Authenticate header 不符**

- 原因：未帶 token 的 `/mcp` 回 200（讓 ChatGPT 以為不需 auth），或回 401 但沒帶 `WWW-Authenticate: Bearer resource_metadata="..."`。
- 症狀：ChatGPT 判定為無需驗證（no-auth）或無法起始 OAuth UI。
- 驗證：第五條 curl，未帶 token 應回 **401** 且帶 WWW-Authenticate 指向 PRM。

**排序 6（低，但要排除）protocol/path/discover 流程或工具面先失敗**

- 原因：`MCP-Protocol-Version` header 處理不當（F20）、`/mcp` 初始化握手失敗、或缺 `search`/`fetch` 工具（F19，屬不同檢查但會讓人誤判）。
- 驗證：確認 `/mcp` 的 initialize 握手能過、protocolVersion 一致。

-----

# 7. ChatGPT Connector 很可能在檢查什麼（附必要度）

|檢查項                                                              |必要度                                     |白話說明                |缺少時的現象                             |
|-----------------------------------------------------------------|----------------------------------------|--------------------|-----------------------------------|
|PRM（`/.well-known/oauth-protected-resource[/mcp]`）可取得且格式正確       |**必要**（規格 MUST，F1/F3）                   |那份「怎麼跟我做 OAuth」的說明文件|does not implement OAuth           |
|PRM 含 `resource` 且與 server URL 相符                                |**必要**（F4）                              |說明文件裡要寫清楚「我是誰」      |discovery 被判無效 / token audience 對不上|
|PRM 含 `authorization_servers`（至少一個）                              |**必要**（F1/F4）                           |指出「去哪登入拿 token」     |拿不到授權伺服器 → 找不到 OAuth               |
|AS metadata（oauth-authorization-server 或 openid-configuration）可取得|**必要**（F1/F3）                           |授權伺服器自己的說明文件        |Error fetching OAuth configuration |
|`issuer` 逐字一致（含 trailing slash / 大小寫 / port）                     |**很可能必要**（F10/F11）                      |兩份文件的「身分字串」要完全一樣    |discovery 抓到但被拒用                   |
|well-known 放在根層或正確路徑感知位置                                         |**很可能必要**（F2/F6/F12）                    |文件要放在 client 找得到的位置 |404 → 找不到 OAuth                    |
|未帶 token 時 `/mcp` 回 401                                          |**可能必要**（F3；規格允許直接抓 well-known 作替代）     |沒帶鑰匙就該被擋            |被當 no-auth 或無法起始流程                 |
|401 帶 `WWW-Authenticate` 指向 PRM                                  |**可能必要**（F2/F7；ChatGPT 也會直接探 well-known）|被擋時順便告知去哪拿說明        |較可能仍可靠直接探測補救                       |
|OAuth flow echo `resource` 參數並寫入 token 的 `aud`                   |**必要於「連上之後」**（F4）                       |token 要綁定「只給我用」     |連得上但 tool 呼叫時 401                  |
|支援 authorization code + PKCE(S256)                               |**必要**（F3）                              |標準且防攔截的登入方式         |授權階段失敗                             |
|redirect URI 允許 ChatGPT callback                                 |**必要**（F5）                              |允許 ChatGPT 登入完跳回來   |授權後卡住 / 無法完成                       |
|CIMD 或 DCR 或預定義 client 擇一                                        |**必要**（F3）                              |ChatGPT 怎麼向你「自報身分」  |無法註冊 client                        |
|`MCP-Protocol-Version` 處理正確                                      |可能必要（F20）                               |協議版本協商              |初始化握手異常                            |
|`search` / `fetch` 工具（deep research 類）                           |視用途（F19，非 OAuth 檢查）                     |特定用途要的工具            |search action not found（與 OAuth 無關）|

-----

# 8. Option Comparison Table（五選項比較）

評分為相對比較（依 F/I 推論），非官方數據。

|面向           |①純手刻補齊    |②手刻核心+FastAPI 外層|③手刻核心+FastMCP 局部    |④先手刻修補、之後再遷移|⑤直接重寫成 FastMCP/官方SDK|
|-------------|----------|----------------|--------------------|------------|--------------------|
|現在適合？        |**最適合**   |適合（若已想整外層）      |適合（僅 metadata 這層）   |**最適合（務實）** |不適合（現在）             |
|ChatGPT 全綠成功率|高（若肯逐項驗）  |高               |**很高**（metadata 自動化）|高           |高但過程風險大             |
|風險           |低（改動小）    |低~中             |中（FastMCP 版本坑 F15）  |低           |**高**（整包重寫、退場成本）    |
|開發量          |小         |中               |中小                  |小→（未來中）     |大                   |
|維護量          |中（全自扛）    |中               |中低（metadata 交出去）    |中           |中（但綁框架升級）           |
|可控性（你最在意）    |**最高**    |高               |中高（metadata 讓框架管）   |高           |中（受框架約束）            |
|規格相容性        |靠你自己盯     |靠你自己盯           |**好**（RFC 9728 內建）  |漸進變好        |好                   |
|長期升級成本       |中（規格常變要自追）|中               |低中                  |低中          |中（跟框架大版本，如 v2 重寫）   |
|對非工程使用者友善    |中（全靠你/工程師）|中               |中高（少維護 auth）        |中高          |低（重寫期複雜）            |

**結論：現在選 ①（純手刻補齊）或等價的 ④（先手刻修補、之後再規劃遷移）。③ 作為「若手刻 discovery 一週補不動」的局部備援。⑤ 明確不選（現在）。**

-----

# 9. Recommended Architecture（分階段）

**現在（0~2 週）：純手刻補齊 discovery（選項①/④）**

- 目標：拿到 ChatGPT OAuth 全綠。
- 做什麼：保留手刻主體；只補/修 PRM、AS metadata、issuer 一致性、well-known 路徑、401+WWW-Authenticate、Cloudflare/proxy 原樣轉發。
- 為什麼：F3/F8/I3 顯示這通常只差幾個細節，最小破壞、最快見效。
- 不做什麼：不換框架、不重寫、不動業務邏輯與 tools。

**中期（1~2 個月）：把「HTTP/ASGI 外層」收斂到 FastAPI，並評估把「metadata 產生」局部交給 FastMCP**

- 目標：讓路由/headers/CORS/well-known 更穩定可控，降低未來再踩 proxy/path 坑的機率。
- 做什麼：用 FastAPI/Starlette 當外層，手刻邏輯與 tools 保留為內層 handler；OAuth discovery/PRM 這一小層，評估用 FastMCP 的 `RemoteAuthProvider` 或官方 SDK 原語產生（token 驗證仍可手刻或用其 `TokenVerifier`）。
- 為什麼：F18（FastAPI 定位）＋F14（FastMCP 把 PRM/挑戰自動化）＋I5。
- 不做什麼：不把 tools/business logic 交給框架、不整包遷移、不上官方 SDK v2。

**長期（3 個月以上）：觀望官方 SDK v2 穩定化，再決定要不要更深整合**

- 目標：跟上 2026-07-28 規格與生態，但不當白老鼠。
- 做什麼：待 v2 穩定版（目標約 2026-07-27）釋出且社群驗證後，再評估是否把更多層交給官方 SDK；持續用 MCP Inspector 做回歸測試。
- 為什麼：F16（官方要你 pin `<2`）＋I6。
- 不做什麼：不在 v2 未穩前遷移核心。

-----

# 10. Minimal Fix Path（保留手刻的最小修補，依優先序）

> 前置：先從**外網**跑第 6 節那組 curl，拿到 5 條的實際狀態碼與內容，才知道卡在哪。（這步能把 U2 從 Unknown 變成事實。）

**M1. 確保 PRM 抓得到且正確（最高優先）**

- 目的：讓 ChatGPT 找得到「怎麼跟我做 OAuth」。
- 技術點：在 `/.well-known/oauth-protected-resource` **與** `/.well-known/oauth-protected-resource/mcp` **都**提供 200 + JSON，含 `resource`（= `https://mcp.edgars.tools/mcp` 或你的標準識別碼）、`authorization_servers`、`scopes_supported`。兩個位置都放可同時滿足根層與路徑感知的 client（規避 F6/F12/F15 同型坑）。
- 驗證：curl 兩條都回 200 + 合法 JSON。
- 風險：低。
- 修好後：does not implement OAuth 很可能消失或改變成下一個更具體的錯誤。

**M2. 確保 AS metadata 抓得到**

- 目的：讓 ChatGPT 找到「去哪登入拿 token」。
- 技術點：`authorization_servers` 指向的 base，其 `/.well-known/oauth-authorization-server`（自建 auth 時）或 `/.well-known/openid-configuration`（用外部 IdP 時）回 200 + 合法 JSON（含 `issuer`、`authorization_endpoint`、`token_endpoint`、`code_challenge_methods_supported: ["S256"]`，DCR 時含 `registration_endpoint`）。若用外部 IdP，讓 PRM 直接指向 IdP 的 issuer，別自己代管。
- 驗證：curl 對應 well-known 回 200。
- 風險：低~中（自建 auth 較複雜）。
- 修好後：進入實際 authorize/token 流程。

**M3. issuer 逐字一致 + 去除 trailing slash 陷阱**

- 目的：避免 discovery 抓到卻被判無效。
- 技術點：確認回傳 JSON 的 `issuer` 與「用來組 well-known 的 issuer identifier」完全逐字相同（大小寫/斜線/port）；盡量讓 issuer **不帶路徑**（用根網域或獨立 host），規避 F12。
- 驗證：肉眼比對 + 依 RFC 8414 規則核對。
- 風險：低。

**M4. Cloudflare / reverse proxy 原樣轉發（你的部署高風險項）**

- 目的：讓外部行為＝本機行為。
- 技術點：proxy 對 `/.well-known/...` **不要改寫路徑**（F8 的教訓）；關掉會擋 ChatGPT 的 Block AI bots / Browser Integrity；若你自管 OAuth，**不要**開 Cloudflare Access「Managed OAuth」（它會取代你的 401，F13）；well-known 加 `Cache-Control: no-store` 或短 TTL 避免快取舊值。
- 驗證：外網 curl ＝ 本機 curl；ChatGPT log 看到的內容正確。
- 風險：中（動到基礎設施，需小心）。
- 修好後：本機正常卻連不上的鬼打牆會消失。

**M5. 401 + WWW-Authenticate 行為**

- 目的：符合被擋時的標準行為、順便給 scope。
- 技術點：未帶 token 的 `/mcp` 回 **401**，帶 `WWW-Authenticate: Bearer resource_metadata="https://mcp.edgars.tools/.well-known/oauth-protected-resource", scope="..."`。
- 驗證：curl -X POST 無 token 看 header。
- 風險：低。

**M6. OAuth flow：echo `resource` + redirect URI + PKCE**

- 目的：讓「連上之後」不會 token 被拒。
- 技術點：authorize/token 全程保留並驗證 `resource` 參數、寫入 token `aud`；授權伺服器允許 `https://chatgpt.com/connector/oauth/{callback_id}`（與舊 `connector_platform_oauth_redirect`）；支援 S256 PKCE。
- 驗證：完成一次真實連線；tool 呼叫不再 401。
- 風險：中。

-----

# 11. Hybrid Architecture Proposal（具體混合方案）

**分層建議（白話：把系統切成幾層，各層決定手刻或交給誰）：**

- **最外層 HTTP / ASGI / 路由 / headers / CORS → 可交給 FastAPI（建議中期做）**
  - 好處：路由與 headers 可預測、well-known 好放對位置、middleware 統一、與 Cloudflare 搭配更穩。
  - 代價：多一層依賴；需正確合併 lifespan（FastMCP/SDK mount 進 FastAPI 有 lifespan 注意事項，見 F18）。
- **OAuth discovery / PRM / WWW-Authenticate 挑戰 → 可局部交給 FastMCP 的 `RemoteAuthProvider` 或官方 SDK 原語（建議評估）**
  - 好處：RFC 9728 PRM 與挑戰自動產生（F14），正中你在踩的坑。
  - 代價：要盯 FastMCP 已知的 resource 欄位 / 路徑感知 well-known bug（F15），並鎖版本。
- **token 驗證（verify JWT / introspection）→ 保留手刻，或用其 `TokenVerifier`（兩者皆可）**
  - 好處：你維持對 issuer/aud/scope 驗證的完全掌控。
  - 代價：手刻要自己維護 JWKS 快取與輪替。
- **tools / business logic → 一律保留手刻（現在不建議替換）**
  - 好處：這是你的核心價值與掌控感所在，且與 OAuth 判定無關。
  - 代價：無。
- **Authorization Server（發 token 的 IdP）→ 若目前自建且維護吃力，長期可考慮外部 IdP（Auth0/Cognito/WorkOS 等）；若你享受掌控，維持自建亦可**
  - 好處：外部 IdP 省掉 DCR/PKCE/JWK 輪替等重擔（多方一致建議；產業背景參考 F14 的 bloomberry 調查：“38.7% of MCP servers had no authentication”，顯示自建 auth 門檻高、常被略過）。
  - 代價：少一點掌控感；多一個外部依賴。

**一句話混合原則：外層 HTTP 交 FastAPI、metadata/discovery 這一小層交 FastMCP（或官方 SDK）產生、token 驗證與 tools 保留手刻。** 這樣既修好全綠、又不毀掉你的手刻主體與掌控感。

-----

# 12. Migration Path（漸進遷移，禁止一上來整包重寫）

**Phase 1（0~2 週）：手刻原地修補（不遷移）**

- 目標：ChatGPT OAuth 全綠。
- 變更範圍：只動 well-known/PRM/AS metadata/issuer/proxy/401，見第 10 節。
- 成功條件：ChatGPT 建立 connector 不再報 does not implement OAuth，且能完成一次 OAuth 連線 + tool 呼叫。
- 回退條件：任何改動造成現有功能壞掉 → git 還原該項。
- 風險：低。

**Phase 2（1~2 個月）：導入 FastAPI 外層 + 局部 metadata 交給框架**

- 目標：降低未來再踩路由/proxy 坑的機率、減輕 auth 維護。
- 變更範圍：以 FastAPI/Starlette 當外層 mount 手刻內層；PRM/discovery 改用 FastMCP `RemoteAuthProvider` 或官方 SDK 原語產生；tools/business logic 不動。
- 成功條件：功能等價 + 全綠維持 + 通過 MCP Inspector 測試。
- 回退條件：框架整合造成 discovery 或 tool 退化 → 退回 Phase 1 的純手刻版本（保留該分支）。
- 風險：中。

**Phase 3（3 個月以上）：視官方 SDK v2 穩定度決定是否更深整合**

- 目標：跟上 2026-07-28 規格與生態。
- 變更範圍：待 v2 穩定（目標約 2026-07-27）+ 社群驗證後，評估把更多層交給官方 SDK；否則維持 Phase 2 架構。
- 成功條件：v2 穩定版 + 你的關鍵路徑在 staging 通過回歸。
- 回退條件：v2 有重大 breaking / 生態未跟上 → 續留 Phase 2。
- 風險：中（靠延後決策把風險壓低）。

-----

# 13. Decision（明確回答，不模糊）

1. **現在是否應該重寫？→ 不。** 理由：問題是 discovery 的幾個細節（F8/F9/I3），不是架構；重寫成本高、退場風險大（⑤ 最高風險），且官方 SDK v2 未穩（F16/I6）。「不是現在」的關鍵在於：重寫解決的不是你現在卡住的東西。
1. **現在是否應該先修手刻？→ 是，這是第一優先。** 依第 10 節最小修補路線。
1. **是否建議納入 FastAPI？→ 是，但當「HTTP/ASGI 外層」用，中期導入，不取代手刻邏輯。**（F18/I7）
1. **是否建議納入 FastMCP？→ 局部建議：只把 PRM/discovery/WWW-Authenticate 這一層交給它（`RemoteAuthProvider`），並鎖版本、盯已知 bug。不建議現在整包改用 FastMCP。**（F14/F15/I5）
1. **最適合先拿到 ChatGPT OAuth 全綠的路線？→ 選項①「純手刻補齊 discovery」（＝④的第一步）。** 先跑外網 curl 定位，再依 M1→M6 修補。若一週內 discovery 補不動，才把 metadata 這一小層局部換成 FastMCP/官方 SDK 產生。

**排序（先做→後做）：** 純手刻補齊 discovery（①/④-Phase1） ＞ FastAPI 外層 + FastMCP 局部 metadata（②③/Phase2） ＞ 觀望官方 SDK v2（Phase3） ＞＞ 整包重寫（⑤，不選）。

-----

# 14. Sources（來源清單）

1. Model Context Protocol — Authorization（授權規格，含 RFC 9728/8414 MUST、well-known、issuer 比較）。modelcontextprotocol.io/specification/…/basic/authorization。查閱 2026-07-05。性質：official spec。
1. Model Context Protocol — Authorization Server Discovery（well-known 探測順序、issuer 驗證）。modelcontextprotocol.io/specification/draft/basic/authorization/authorization-server-discovery。查閱 2026-07-05。性質：official spec。
1. OpenAI Apps SDK — Authentication（ChatGPT 對 MCP OAuth 的要求、PRM 欄位、redirect URI、securitySchemes、CIMD/DCR/PKCE）。developers.openai.com/apps-sdk/build/auth。查閱 2026-07-05。性質：official docs。
1. OpenAI — Building MCP servers for ChatGPT（search/fetch 工具需求、FastMCP 範例）。developers.openai.com/api/docs/mcp。查閱 2026-07-05。性質：official docs。
1. OpenAI 開發者社群 — 「New MCP Connector does not follow MCP Authorization Spec」（ChatGPT 直打 oauth-authorization-server/openid-configuration；OpenAI_Support 回覆 scope 發現更新）。community.openai.com/t/…/1358992。查閱 2026-07-05。性質：discussion + maintainer statement（降權）。
1. OpenAI 開發者社群 — 「[Resolved] Trouble with ChatGPT Connector OAuth (Detailed)」（NGINX 改寫 well-known 路徑導致失敗、原樣轉發後全綠；ChatGPT 比 Claude 嚴格）。community.openai.com/t/…/1359112。查閱 2026-07-05。性質：first-hand resolved case（降權）。
1. OpenAI 開發者社群 — 「Not able to add ChatGPT App/MCP Server to ChatGPT」（含確切錯誤字串「does not implement OAuth」與 2025-11-06 well-known 全 404 的請求 log）。community.openai.com/t/…/1365324。查閱 2026-07-05。性質：first-hand report（降權）。
1. RFC 8414 — OAuth 2.0 Authorization Server Metadata（issuer 帶路徑時 well-known 插入規則、issuer 逐字比對）。datatracker.ietf.org/doc/html/rfc8414。查閱 2026-07-05。性質：spec。
1. Microsoft Learn Q&A — MCP client 忽略 authorization_servers 路徑、對根網域組 well-known（實務坑與解法）。learn.microsoft.com/…/5904511。查閱 2026-07-05。性質：vendor Q&A（降權）。
1. Cloudflare One Docs — Managed OAuth（會取代 401 行為；自管 OAuth 勿開）與 MCP portals。developers.cloudflare.com/cloudflare-one/…。查閱 2026-07-05。性質：official docs。
1. anthropics/claude-ai-mcp GitHub issues（#49、#393、#410、#506：Cloudflare tunnel/Block AI bots、401 缺 WWW-Authenticate、token 後靜默等 proxy 相關症狀）。github.com/anthropics/claude-ai-mcp。查閱 2026-07-05。性質：third-party issues（降權，僅作旁證）。
1. FastMCP 官方文件 — Authentication / RemoteAuthProvider / TokenVerifier / ASGI 整合。gofastmcp.com。查閱 2026-07-05。性質：official docs。
1. jlowin.dev — FastMCP 2.12/2.13/3.0 發布文（OAuth proxy、production readiness、由 Prefect 維護、下載量峰值 1.25M/日、市佔宣稱 70%）。jlowin.dev/blog。查閱 2026-07-05。性質：maintainer statement。
1. PrefectHQ/fastmcp GitHub issues #1348 / #2077 / #2123（RemoteAuthProvider resource 欄位 bug、well-known 路徑感知位置導致 404）。github.com/PrefectHQ/fastmcp。查閱 2026-07-05。性質：official repo issues。
1. modelcontextprotocol/python-sdk GitHub releases（v2 為 2026-07-28 規格重寫、`2.0.0b1` beta、穩定版目標 2026-07-27、v1.28.1 為穩定線、建議 pin `<2`、“84% of the 10,000+ PyPI packages… declare no upper bound”）。github.com/modelcontextprotocol/python-sdk/releases。查閱 2026-07-05。性質：official repo。
1. modelcontextprotocol/python-sdk — simple-auth 範例與 oauth_server.py（resource server、TokenVerifier、AuthSettings、legacy AS 相容）。github.com/modelcontextprotocol/python-sdk/tree/main/examples。查閱 2026-07-05。性質：official repo。
1. FastMCP — ASGI/Starlette 與 FastAPI 整合文件（http_app、mount、lifespan、from_fastapi）。fastmcp.wiki / gofastmcp.com。查閱 2026-07-05。性質：official docs + 第三方教學。
1. MCP 規格版本演進（2025-03-26 / 2025-06-18 / 2025-11-25；MCP-Protocol-Version header 必要、400 行為）。modelcontextprotocol.io/specification/versioning 等。查閱 2026-07-05。性質：spec。
1. github/github-mcp-server issues #1081 / #921（ChatGPT「Error fetching OAuth configuration」；authorization_servers 指向 404 的 AS metadata）。github.com/github/github-mcp-server。查閱 2026-07-05。性質：official repo issues（旁證）。
1. RFC 9728 — OAuth 2.0 Protected Resource Metadata（PRM 文件結構與 well-known 位置）。datatracker.ietf.org/doc/html/rfc9728。查閱 2026-07-05。性質：spec。
1. bloomberry.com — 「I analyzed 1400 MCP servers」（三大 SDK 佔 100%、FastMCP 佔最大宗；38.7% MCP server 無驗證）。查閱 2026-07-05。性質：third-party 調查（降權，僅作產業背景旁證）。

（註：凡標「降權」者為社群/第三方來源，信任權重較低，已在對應 Fact/Inference 標明；關鍵結論盡量以 official spec / official docs / official repo 為主。最關鍵的 Unknown 是：OpenAI 未公開「does not implement OAuth」對應到哪一個檢查失敗，本報告的根因排序為交叉推論，需以你 server 的實際外網封包驗證才能從推論變確定。）