<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# 搜尋2025年最新資料，主題：手刻MCP server（不使用FastMCP或官方SDK，直接實作JSON-RPC 2.0 + SSE的MCP協議）

需要找：

1. 個人開發者的實作經驗文章、GitHub討論、Reddit/HN討論
2. 有沒有人記錄手刻過程中遇到的具體困難（協議細節、debug難點）
3. AI輔助（Claude/Cursor/Copilot）手刻MCP時的成功或失敗案例
4. 跟FastMCP比較後選擇手刻的理由是什麼

來源優先：GitHub issues/discussions、dev.to、個人技術部落格、Reddit r/ClaudeAI r/mcp
排除：官方文件、廠商行銷文章

以下是 2025 年手刻 MCP server（不用 FastMCP / 官方 SDK）的實際社群資料彙整。

***

## 手刻 MCP 的現狀

手刻 MCP server 的討論相對分散，因為大多數教學都直奔 SDK/FastMCP，但仍有一批開發者選擇直接實作協議層。以下按你的四個問題分類整理。

***

## 1. 個人開發者實作案例

- **JVM Weekly（2026-02）**：這篇是目前品質最高的「裸協議實作」文章 ，完整記錄用純 Java/JVM 實作 stdio 版 MCP，不依賴任何 SDK，直接操作 stdin/stdout 跑 JSON-RPC 2.0，文章標題是 [Understanding MCP Through Raw STDIO Communication](https://www.jvm-weekly.com/p/understanding-mcp-through-raw-stdio)。[^1_1]
- **Go 語言手刻（prasanthmj.github.io）**：2025 年初的文章 ，[MCP server in Go](https://prasanthmj.github.io/ai/mcp-go/) 從零用 Go 實作，手動建 decoder/encoder 操作 stdin/stdout JSON-RPC，沒有依賴官方 Go SDK（當時根本不存在）。[^1_2]
- **Scala 3 手刻（windymelt/mcp-scala）**：用 Scala 3 + Scala.js 直接實作 JSON-RPC 2.0，沒有走官方 SDK，編譯成 Node.js 執行 。[^1_3]
- **Stack Overflow 問題（2025-04）**：有開發者試圖手刻 PHP + Python 版 SSE MCP，明確記錄了「tools/resources 完全沒傳到 Inspector 或 CursorAI」的問題，三次嘗試全部 timeout 。[^1_4]

***

## 2. 手刻過程的具體困難

這是最有價值的部分。已記錄的痛點：

**stdout 污染問題（最高頻踩坑）**

- stdio 傳輸模式下，stdout 就是協議通道，任何 `console.log` / `print` 都會直接破壞 JSON-RPC 訊息流 。開發者形容這是「最常見的單一錯誤」。FastMCP 之所以建議 logging 導向 stderr，根本原因就是這個。[^1_5]

**SSE 雙通道架構邏輯複雜**

- SSE 模式需要同時維護：GET `/sse`（長連接推送）+ POST `/messages`（請求端點），兩條通道必須用 `sessionId` 配對 。手刻時自己處理 session 狀態管理不易。[^1_6]

**Handshake 初始化訊息時序**

- 手刻者回報 initialize → capabilities 交換的訊息時序出錯時，client 完全沉默，沒有任何明顯錯誤訊息，很難 debug 。[^1_7][^1_4]

**Scale 路由地獄（SSE 特有）**

- GitHub Discussion \#102 中有平台開發者記錄：SSE 因為 HTTP 無狀態，POST 請求和 SSE 連接會到不同 replica，手刻路由邏輯時幾乎無解 。FastMCP 後來加了 streamable HTTP 的 workaround，但手刻者得自己解決。[^1_8]

**Serverless 冷啟動 + Logging 衝突**

- 手刻者在 AWS Lambda 環境碰到 FastAPI/FastMCP logging 互衝問題，Powertools decorators 全部失效 。這個問題在純手刻時更嚴重，因為沒有 middleware 可以接。[^1_9]

***

## 3. AI 輔助手刻 MCP 的案例

**成功案例**

- LinkedIn 上有記錄用 Claude Code 在 3 小時內建出完整 MCP server（含 SSE 通道），Claude Code 正確處理了 SSE session 管理邏輯 。[^1_10]
- Termdock 的教學顯示 Claude Code 能正確生成 stdio MCP，包括自動將 log 導向 stderr 而非 stdout 。[^1_5]

**失敗 / 限制案例**

- HN 討論（2025-06）中有人總結：AI 輔助生成的 MCP server 常見問題是「initialize handshake 格式正確但 capabilities negotiation 細節錯誤」，client 不報錯只是靜默失敗 。[^1_11]
- Stack Overflow 的 PHP 手刻案例中，使用 AI 生成的初版 code 全部都在 tools/resources 傳遞環節卡死 ，顯示 AI 對 SSE + JSON-RPC 2.0 協議細節的掌握度有限。[^1_4]

***

## 4. 手刻 vs FastMCP 的選擇理由

整理社群中手刻者的實際理由：


| 選擇手刻的理由 | 代表來源 |
| :-- | :-- |
| 語言不支援 SDK（Go/Rust 早期、PHP、Scala） | [^1_2][^1_3] |
| 需要完全控制協議細節（自訂 transport） | [^1_1] |
| FastMCP 預設無 auth，安全顧慮 | [^1_12] |
| 學習目的，理解底層再用框架 | [^1_1][^1_2] |
| 避免 FastMCP 的 serverless 不相容問題 | [^1_13][^1_9] |

**FastMCP 預設不安全**這條很值得注意：有安全研究指出，FastMCP 預設 `transport="http"` + `host="0.0.0.0"` 是完全無 auth、無加密的，任何知道 IP:port 的人都能連入 。這讓部分安全意識強的開發者選擇手刻以完全掌控 auth 流程。[^1_12]

***

## 手刻的最小協議流程（參考）

根據 JVM Weekly 和 Go 實作文章整理的裸協議最小實作路徑 ：[^1_14][^1_1][^1_2]

```
1. 建立 stdin 讀取迴圈，每行一個 JSON-RPC 訊息
2. 處理 initialize 請求 → 回覆 serverInfo + capabilities
3. 實作 tools/list handler → 回傳 tools 陣列
4. 實作 tools/call handler → 執行邏輯 → 回傳 content
5. 所有 log 強制走 stderr，stdout 只有 JSON-RPC
6. notifications 不帶 id，responses 帶相同 id
```

SSE 版額外需要：

- GET `/sse` 保持長連接，推送 `data:` 格式事件
- POST `/messages` 接收請求，透過 sessionId 映射回對應 SSE 連接
- 初始 SSE 事件必須包含 `sessionId` 供 client 後續使用[^1_6]

***

**缺資料補充**：目前 Reddit r/mcp、r/ClaudeAI 上的手刻討論量很少，大多數貼文都推薦直接用 SDK。手刻的一手經驗文章以個人技術部落格和 GitHub Discussions 為主，2025 上半年的案例最多（SDK 生態還不完整的時期）。
<span style="display:none">[^1_15][^1_16][^1_17][^1_18][^1_19][^1_20][^1_21][^1_22][^1_23][^1_24][^1_25][^1_26][^1_27][^1_28][^1_29][^1_30][^1_31][^1_32][^1_33][^1_34][^1_35][^1_36][^1_37][^1_38][^1_39][^1_40][^1_41][^1_42][^1_43]</span>

<div align="center">⁂</div>

[^1_1]: https://www.jvm-weekly.com/p/understanding-mcp-through-raw-stdio

[^1_2]: https://prasanthmj.github.io/ai/mcp-go/

[^1_3]: https://skywork.ai/skypage/en/windymelt-json-rpc-mcp-server-ai/1981582239283081216

[^1_4]: https://stackoverflow.com/questions/79505420/how-to-implement-a-model-context-protocol-mcp-server-with-sse

[^1_5]: https://www.termdock.com/en/blog/build-first-mcp-server-claude-code

[^1_6]: https://cirra.ai/articles/salesforce-mcp-servers-technical-guide

[^1_7]: https://skywork.ai/skypage/en/MCP-SSE-Server-Sample-A-Deep-Dive-for-AI-Engineers/1972560383681687552

[^1_8]: https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/102

[^1_9]: https://ranthebuilder.cloud/blog/mcp-server-on-aws-lambda/

[^1_10]: https://www.linkedin.com/posts/nielsberglund_building-an-event-management-system-with-activity-7418618818656260096-FKiT

[^1_11]: https://news.ycombinator.com/item?id=44314289

[^1_12]: https://cardinalops.com/blog/mcp-defaults-hidden-dangers-of-remote-deployment/

[^1_13]: https://www.reddit.com/r/mcp/comments/1m4o8wu/mcp_is_overengineered_and_breaks_serverless/

[^1_14]: https://www.gravitee.io/blog/mcp-api-gateway-explained-protocols-caching-and-remote-server-integration

[^1_15]: https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1391

[^1_16]: https://modelcontextprotocol.io/seps/1686-tasks

[^1_17]: https://clickhouse.com/blog/how-to-build-ai-agents-mcp-12-frameworks

[^1_18]: https://towardsdatascience.com/creating-and-deploying-an-mcp-server-from-scratch/

[^1_19]: https://www.speakeasy.com/mcp/deploying-mcp-servers

[^1_20]: https://composio.dev/content/mcp-server-step-by-step-guide-to-building-from-scrtch

[^1_21]: https://sidbharath.com/blog/the-ultimate-guide-to-model-context-protocol-part-4-build-your-own-mcp-server/

[^1_22]: https://www.reddit.com/r/programming/comments/1n17vn1/mcp_servers_cant_be_the_future_can_they/

[^1_23]: https://www.kdnuggets.com/fastmcp-the-pythonic-way-to-build-mcp-servers-and-clients

[^1_24]: https://www.freecodecamp.org/news/how-to-build-a-custom-mcp-server-with-typescript-a-handbook-for-developers/

[^1_25]: https://blog.sentry.io/introducing-mcp-server-monitoring/

[^1_26]: https://machinelearningmastery.com/building-a-simple-mcp-server-in-python/

[^1_27]: https://github.com/modelcontextprotocol/servers

[^1_28]: https://techcommunity.microsoft.com/blog/azurearchitectureblog/decision-matrix-api-vs-mcp-tools-—-the-great-integration-showdown-🥊/4499385

[^1_29]: https://xenoss.io/blog/mcp-model-context-protocol-enterprise-use-cases-implementation-challenges

[^1_30]: https://securityboulevard.com/2025/06/what-are-the-best-practices-for-mcp-security/

[^1_31]: https://news.ycombinator.com/item?id=44846871

[^1_32]: https://hackmd.io/@ll-24-25/S1Ob3ylleg

[^1_33]: https://github.com/wkusnierczyk/raku-mcp-sdk

[^1_34]: https://github.com/modelcontextprotocol/typescript-sdk/issues/509

[^1_35]: https://www.reddit.com/r/rust/comments/1lepymv/announcing_mcpprotocolsdk_a_new_rust_sdk_for_ai/

[^1_36]: https://datasciencedojo.com/blog/guide-to-model-context-protocol/

[^1_37]: https://www.getzep.com/ai-agents/developer-guide-to-mcp/

[^1_38]: https://www.abstractalgorithms.dev/headless-agents-deploying-skills-as-mcp-server

[^1_39]: https://github.com/modelcontextprotocol/rust-sdk

[^1_40]: https://github.com/pieces-app/pro_tips/blob/main/guides/MCP/Bridging%20Local%20MCP%20Clients%20to%20Remote%20Servers%20with%20mcp-remote.md

[^1_41]: https://agnt.one/blog/the-model-context-protocol-for-ai-agents

[^1_42]: https://kyrylai.com/2025/02/14/mcp-llm-integration/

[^1_43]: https://modelcontextprotocol.io/llms-full.txt


---

# 2026有新增值得注意的內容嗎

2026 有幾個值得注意的重大變化，直接影響手刻邏輯。

***

## SSE 已正式被棄用

**Streamable HTTP** 在 2025-03-26 spec 版本正式取代 HTTP+SSE，成為遠端傳輸的新標準 。這對手刻者的意義：[^2_1][^2_2]

- 舊的雙端點架構（GET `/sse` + POST `/messages`）已過時，新架構合併成**單一 POST endpoint**
- Server 可以選擇「單次 JSON 回應」或「開啟 SSE stream 推送多訊息」，但都走同一個 endpoint
- 解決了之前 SSE 的最大手刻痛點：**不再需要手動管理 sessionId 配對**[^2_3]

***

## JSON-RPC Batching 被加入又被移除

這是 2025 年協議最混亂的一段 ：[^2_4]

- **2025-03-26**：加入 JSON-RPC batching（client 可以一次送多個 tool call）
- **2025-06-18**：因為「沒有值得的使用案例」被直接移除
- 如果你在 2025 上半年手刻並實作了 batch 處理，那段邏輯現在是死碼

手刻時要確認 spec 版本，避免按已棄用的行為實作。

***

## 協議版本 2025-11-25 的細節修正

對手刻者直接有用的兩個 minor change ：[^2_5]

- **stdio logging 正式明文規定**：server 可以用 `stderr` 記錄「所有 log 類型」，不只是 error，這解決了之前 spec 措辭模糊的問題
- **Streamable HTTP 新增 403 規定**：收到無效 Origin header 時必須回 HTTP 403，手刻 HTTP transport 時要加這個 guard

***

## OAuth 要求升級

2025-06-18 spec 開始將 MCP server 定義為 **OAuth Resource Server** ，不再是可選項：[^2_4]

- 手刻遠端 server 若要符合新規範，需要完整實作 OAuth 2.0 resource server 角色
- FastMCP 等框架尚未完整支援，手刻者反而更容易自己控制（這成了一個新的手刻理由）

***

## 2026 新增的手刻參考資源

- **JVM Weekly 2026-02 文章**（[Understanding MCP Through Raw STDIO](https://www.jvm-weekly.com/p/understanding-mcp-through-raw-stdio)）：目前最完整的裸協議實作教學，用 Java 示範，完全無框架依賴[^2_6]
- **SEP-1686 Tasks（2026-03）**：長時間執行任務的新草案 ，目前還是 proposal 階段，不建議手刻時投入這部分，但要知道它存在[^2_7]

***

**核心結論**：如果現在開始手刻，transport 直接選 **Streamable HTTP**（不要再做 SSE 雙端點）；spec 版本鎖定 `2025-11-25`；OAuth 部分如果是內部工具可先跳過，公開服務就要認真處理。
<span style="display:none">[^2_10][^2_11][^2_12][^2_13][^2_14][^2_15][^2_16][^2_8][^2_9]</span>

<div align="center">⁂</div>

[^2_1]: https://fast.io/resources/mcp-streamable-http-transport/

[^2_2]: https://docs.spring.io/spring-ai/reference/api/mcp/mcp-streamable-http-server-boot-starter-docs.html

[^2_3]: https://brightdata.com/blog/ai/sse-vs-streamable-http

[^2_4]: https://www.speakeasy.com/mcp/release-notes

[^2_5]: https://modelcontextprotocol.io/specification/2025-11-25/changelog

[^2_6]: https://www.linkedin.com/pulse/understanding-mcp-through-raw-stdio-communication-david-skowroński-igjzf

[^2_7]: https://modelcontextprotocol.io/seps/1686-tasks

[^2_8]: https://blog.qualys.com/product-tech/2026/03/19/mcp-servers-shadow-it-ai-qualys-totalai-2026

[^2_9]: https://fenxi.fr/en/blog/mcp-model-context-protocol-connecting-ai-business-tools-2026/

[^2_10]: https://sainam.tech/blog/mcp-complete-guide-2026/

[^2_11]: https://equixly.com/blog/2026/02/12/how-mcp-servers-challenge-traditional-api-security-models/

[^2_12]: https://codilime.com/blog/model-context-protocol-explained/

[^2_13]: https://www.arcade.dev/blog/announcing-native-support-for-mcp-servers/

[^2_14]: https://indigo.ai/en/blog/context-engineering/

[^2_15]: https://modelcontextprotocol.info/blog/first-mcp-anniversary/

[^2_16]: https://blog.ray-realms.com/da-zao-ni-de-di-yi-ge-mcp-server-cong-gai-nian-dao-shi-zuo/


---

# Streamable HTTP transport如何實作細節

可以，2026 的重點已經不是「怎麼做 SSE」，而是「怎麼正確做 Streamable HTTP」。現在多數新文章都把它當預設傳輸，並且明確示範用 `POST /mcp` 取代舊的雙端點 SSE 架構 。[^3_1][^3_2]

## 2026 的實作重點

- **單一入口**：通常是 `POST /mcp`，用 JSON-RPC 2.0 包住 MCP 請求與回應 。[^3_3][^3_1]
- **可串流也可非串流**：同一個 endpoint 可以回一次 JSON，也可以保持連線持續推送事件 。[^3_4][^3_1]
- **session 管理簡化**：相較舊 SSE，需要自己對齊 `GET /sse` + `POST /messages`，Streamable HTTP 省掉很多配對邏輯 。[^3_2][^3_5]
- **仍然要嚴格區分 stdout/stderr**：stdio 類型的舊坑在 HTTP 下少很多，但如果你同時支援 stdio，log 亂寫到 stdout 依然會炸 。[^3_6][^3_7]


## 典型請求流程

一個常見的 Streamable HTTP 流程是這樣：

1. Client 對 `POST /mcp` 送 `initialize`。
2. Server 回 `serverInfo`、`capabilities`，必要時建立 session。
3. Client 再送 `tools/list`、`resources/list`、`prompts/list` 之類的 JSON-RPC 方法。
4. 真正的 `tools/call` 可以用單次 JSON 回覆，也可以用串流回覆較長結果 。[^3_8][^3_1][^3_2]

## 手刻時要注意的細節

- **Content-Type**：通常要接受並回 JSON，實作上要能辨識 JSON-RPC body 。[^3_1]
- **sessionId**：有些實作會自己生成 session，讓後續請求能對應同一條會話 。[^3_2][^3_1]
- **連線關閉清理**：`res.on('close')` 之類的資源釋放很重要，不然長連線會漏 。[^3_1]
- **錯誤回應格式**：要回符合 JSON-RPC 的錯誤，不是一般 REST error 。[^3_1]
- **Origin / 安全性**：2025-11 版之後，無效 Origin 需要回 403，公開服務不能偷懶 。[^3_7]


## 你會遇到的常見坑

- 把它當成一般 REST API 寫，結果 client 端只看到連線成功、沒有 protocol 回應 。[^3_9][^3_1]
- 以為一定要 SSE 才能串流，實際上新規格已經把 Streamable HTTP 當主要方向 。[^3_5][^3_4]
- 初始化順序錯掉，client 會很安靜地失敗，不一定丟出好懂的錯誤 。[^3_10][^3_6]


## 目前最實用的手刻策略

如果你要自己實作，現在比較穩的路線是：

- 先做 **`POST /mcp` 單入口**
- 先支援 **非串流 JSON 回覆**
- 再加 **串流回覆**
- 最後才補 **session、auth、Origin 檢查**[^3_4][^3_7][^3_1]

這樣比直接重做舊 SSE 雙端點更符合 2026 的主流做法 。[^3_11][^3_5]

你要的話，我下一則可以直接給你一份 **「Node.js / Express 手刻 Streamable HTTP MCP server 的最小可運行範本」**，用繁中註解、直接可貼進專案。
<span style="display:none">[^3_12][^3_13][^3_14]</span>

<div align="center">⁂</div>

[^3_1]: https://ithelp.ithome.com.tw/articles/10353095

[^3_2]: https://maple.link/2025/05/22/MCP-streamable-http-协议通信过程/

[^3_3]: https://blog.ray-realms.com/da-zao-ni-de-di-yi-ge-mcp-server-cong-gai-nian-dao-shi-zuo/

[^3_4]: https://fast.io/resources/mcp-streamable-http-transport/

[^3_5]: https://brightdata.com/blog/ai/sse-vs-streamable-http

[^3_6]: https://www.linkedin.com/pulse/understanding-mcp-through-raw-stdio-communication-david-skowroński-igjzf

[^3_7]: https://modelcontextprotocol.io/specification/2025-11-25/changelog

[^3_8]: https://lijianfei.com/post/streamable-httpmcp-xie-yi-de-jin-hua-yu-shi-xian/

[^3_9]: https://ithelp.ithome.com.tw/articles/10388172

[^3_10]: https://stackoverflow.com/questions/79505420/how-to-implement-a-model-context-protocol-mcp-server-with-sse

[^3_11]: https://github.com/microsoft/mcp-for-beginners/blob/main/translations/zh-TW/03-GettingStarted/06-http-streaming/README.md

[^3_12]: https://www.facebook.com/groups/aixedu/posts/踩了一整天的坑openai-的-responses-api-若以-streamable-http-方式呼叫-mcp-server-保證呼叫了但不使用必須以-ss/698672096461847/

[^3_13]: https://blog.csdn.net/m0_37242314/article/details/149335566

[^3_14]: https://www.wsisp.com/helps/39173.html

