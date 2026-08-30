# 給執行代理的佈署指令（Deployment Instructions）— MCP v2 Phase 2

這份文件是**純操作指令**，給實際動手的執行代理（Codex / Claude Code，以下統稱「你」）看的，不是策略文件。策略、架構原則、地雷清單、驗收/回退條件都在同目錄的
`MCP-02-PHASE2-FASTAPI-FASTMCP-EXECUTION-BRIEF.md`（以下稱「主任務書」）——**開工前必須先讀完主任務書全文，這份文件只講「怎麼把主任務書的內容，用工具實際跑起來」。**

Linear 看板結構已經建好：

- 主票：**EDG-372**（`edgars-mcp Phase 2：FastAPI 外層 + FastMCP 局部 Metadata`）
- 子票（對應主任務書第 5 節的四個 Phase）：
  - **EDG-373** = Phase 2.0（準備）
  - **EDG-374** = Phase 2.1（FastAPI 外層 mount + 移除 Cloudflare Access 分支）
  - **EDG-375** = Phase 2.2（FastMCP 局部接手 PRM/discovery）
  - **EDG-376** = Phase 2.3（收尾清理）

---

## 1. Git 工作流規則

1. **絕對不要直接改 master。** 保護點是 branch `checkpoint/pre-phase2-fastapi-fastmcp` @ commit `9b0915fa`（已推上 `origin`）。從這裡切出工作分支：

   ```
   git checkout checkpoint/pre-phase2-fastapi-fastmcp
   git checkout -b feat/mcp-v2-fastapi-fastmcp-phase2
   ```

2. **一個 Phase 一個（或多個）commit，但不要跨 Phase 混在一個 commit 裡。** 每個 commit message 要標明對應哪張 Linear 票（例如 `feat(mcp): FastAPI outer layer mount [EDG-374]`），方便之後回溯。
3. **每個 Phase 結束、驗收通過後，才 push 該階段的 commit 到 `origin/feat/mcp-v2-fastapi-fastmcp-phase2`。** 不要等到全部 4 個 Phase 做完才一次 push——中途機器出事，至少不會整批遺失。
4. **任何一個 Phase 的回退條件被觸發（見主任務書第 7 節），立刻 `git checkout checkpoint/pre-phase2-fastapi-fastmcp`，不要試圖在壞掉的分支上硬修。** 壞掉的分支保留著（不要刪），另外開一個新分支繼續，方便之後回頭診斷哪裡壞的。
5. 全部 4 個 Phase 都驗收通過、且王世鈞確認後，才能考慮 merge 回 `master`——**這是需要王世鈞明確同意的動作，你自己不要 merge。**

---

## 2. Linear 看板規則（工作追蹤，不是選配）

1. **開始一個 Phase 前**：把對應子票（EDG-373~376）的狀態從 `Backlog` 改成 `In Progress`（或看板上等義的「進行中」）。
2. **過程中**：每完成主任務書該 Phase 條列的一個小步驟，就在該子票下留一則 comment，簡短寫「做了什麼、對照主任務書哪一條」。**不要憋到最後才一次寫一大段**——中途出事，王世鈞才看得出卡在哪一步。
3. **遇到主任務書第 8 節列的 Unknown、或任何你判斷不了、需要王世鈞決策的事情**：**直接在該子票留言問，不要自己猜、不要停在原地空等。** 先去做這個 Phase 裡不受此問題影響的其他部分，回頭再處理被卡住的那塊。（例如 Phase 2.1 的 chatgpt-honcho 認證方式，見主任務書「決策更新」第 1 點，尚未定案前先跳過那一步，做完其他步驟。）
4. **Phase 驗收通過後**：
   - 附上驗收證據（curl 輸出、MCP Inspector 截圖或 log、測試結果）**直接貼在子票的 comment 裡**，不要只說「測過了，沒問題」。
   - 把子票狀態改成 `Done`（或看板等義的「完成」）。
   - 回到主票 EDG-372，留一則簡短總結 comment，說明這個 Phase 完成、下一個 Phase 是什麼。
5. **任一 Phase 觸發回退條件（主任務書第 7 節）**：子票狀態改成一個能反映「卡住/回退」的狀態（例如 `Blocked` 或加註），**在子票和主票都留言說明**：卡在哪、為什麼判斷要回退、需要王世鈞決定什麼。**不要自己決定要不要繼續，這是紅線。**

---

## 3. 子代理使用規範（如果你有能力產生子代理／並行 agent）

如果你（Codex 或 Claude Code）具備產生子代理（sub-agent）或並行 agent 執行的能力，**強烈建議在以下情況使用，而不是同一個 agent 球員兼裁判**：

### 3.1 「寫」跟「查」分開

每個 Phase 驗收前，**用一個獨立的、沒看過你怎麼寫程式碼過程的子代理，重新對照主任務書第 4 節「已知地雷」表跟該 Phase 的驗收條件，逐條驗證**，而不是自己寫完自己勾自己過。理由很直接：寫程式碼的那個 agent 對自己的假設有盲點，容易「我覺得應該沒問題」就跳過驗證；一個沒有寫程式包袱的子代理重新核對，比較可能抓到真的漏掉的地方。

具體做法（以主任務書第 4 節地雷表為例）：
- 產生一個子代理，任務是「針對 PRM `resource` 欄位是否等於實際端點 URL，逐一 curl 4 個 well-known 變體並回報結果」——只做這一件事，回報 raw 輸出，不要它順便幫你判斷「應該過了」。
- 另一個子代理專門測「Cloudflare Access 分支移除後，原本依賴它的端點是否意外變公開」——同樣只做驗證、回報事實，不要它自己下結論說沒事。
- 主 agent 拿到這些獨立回報後，自己判斷是否真的符合驗收條件，再去 Linear 留言、改狀態。

### 3.2 平行處理彼此不依賴的驗證項

Phase 2.1 跟 Phase 2.2 驗收時要測的東西彼此獨立（例如「84 個工具抽測」跟「webhook 功能等價」互不相關），如果你能平行跑多個子代理，把這些獨立驗證項分給不同子代理同時做，比一個一個循序測快，也降低「測到一半漏看前面結果」的風險。**但寫程式碼本體（Phase 2.1 的路由搬遷）不要拆給多個子代理同時改，同一段程式碼多方同時改會互相踩線——寫的部分維持單一 agent 或單一分支序列執行，只有「驗證」跟「檢查」的部分適合平行。**

---

## 4. 多代理協調規範（A2A，Agent-to-Agent）

如果王世鈞這次是同時派了不只一個代理在處理這件事（例如 Codex 跟 Claude Code 都有可能被叫去做，或是你自己內部又開了子代理），**協調的單一真相來源（single source of truth）是 Linear 子票的 comment thread，不是口頭默契、不是各自腦內狀態。**

具體規則：

1. **開始動工前，先看該子票（EDG-373~376）目前的 comment，確認有沒有別的代理已經在做、或已經卡在某個決策點。** 如果已經有人在動，不要重複做或互相覆蓋；如果卡在某個 Unknown 等王世鈞回覆，你也一樣等，不要自己猜著先動。
2. **你做的每一步都要留痕跡在 Linear comment 裡（見第 2 節），這本身就是 A2A 的交接機制**——下一個接手的代理（不管是你自己下一輪、還是另一個代理）看 comment 就知道現在進度到哪、卡在哪、已經驗證過什麼，不用重新問王世鈞一次。
3. **絕對不要兩個代理同時在同一個 git 分支上互相覆蓋 commit。** 如果偵測到 `feat/mcp-v2-fastapi-fastmcp-phase2` 已經有別人推上去的新 commit、而你本地不知道這些改動，**先 `git pull` 看清楚改了什麼，在 Linear 子票留言確認你的理解，再繼續**，不要用 `git push --force` 蓋過去。
4. **如果你判斷需要另一個代理類型接手（例如你是 Codex，判斷這一步需要瀏覽器操作去測 ChatGPT 連接器 OAuth 全流程，那部分不是你能力範圍）**，在 Linear 子票明確寫「這部分需要有瀏覽器操作能力的代理接手，已完成的部分是 X，交接狀態是 Y」，而不是自己假裝測過了。

---

## 5. 每個 Phase 的具體啟動指令

### EDG-373 / Phase 2.0
```
把 EDG-373 狀態改成 In Progress。
從 checkpoint/pre-phase2-fastapi-fastmcp 切出 feat/mcp-v2-fastapi-fastmcp-phase2。
pip install fastapi uvicorn，鎖版本進 requirements.txt。
跑一個最小 FastAPI + uvicorn hello-world，確認 port 不衝突。
驗收通過後，在 EDG-373 留言附上啟動 log，狀態改 Done。
```

### EDG-374 / Phase 2.1
```
把 EDG-374 狀態改成 In Progress。
讀主任務書第 5 節 Phase 2.1 的完整步驟（含 chatgpt-honcho 認證方式待王世鈞決策、暫時跳過那一步）。
每完成一個子步驟就在 EDG-374 留言。
用獨立子代理驗證第 4 節地雷表最後一列（Cloudflare Access 分支移除後的存取控制）。
MCP Inspector 全流程測試 + 兩種授權模式 401/200 測試，證據貼在 EDG-374。
驗收通過後狀態改 Done，回 EDG-372 留摘要，開始 EDG-375。
```

### EDG-375 / Phase 2.2
```
把 EDG-375 狀態改成 In Progress。
讀主任務書第 5 節 Phase 2.2，逐一處理第 4 節列的 FastMCP 已知 bug（#1348, #2077, #2123）。
用獨立子代理分別驗證第 4 節每一條地雷，回報 raw 證據。
完整走一次 ChatGPT 和 Claude 連接器的真實新增流程，全綠才算過。
證據（curl 輸出、連接器截圖）貼在 EDG-375，狀態改 Done。
```

### EDG-376 / Phase 2.3
```
確認 EDG-374、EDG-375 都已經穩定運行至少一週（不是驗收當下通過就算，要有時間觀察）。
把 EDG-376 狀態改成 In Progress。
移除舊 handler code、更新 run_http.cmd、更新主任務書與 V2-手刻升級清單.md。
Cloudflare 後台 Access Application/Policy 的處置，只記錄待辦、不要自己動手——這需要王世鈞另外明確指示。
全部完成後，在 EDG-372 主票留言總結整個 Phase 2 的結果，等王世鈞確認是否 merge 回 master。
```

---

## 6. 最後提醒

- 這整份文件跟主任務書都是**指引**，不是免責條款。任何一步你自己覺得「怪怪的、跟預期不一樣」，即使沒有明確寫在回退條件裡，也要停下來在 Linear 留言，不要憑感覺硬推過去。
- 王世鈞沒有技術背景，**不要在 Linear comment 裡只寫技術術語就結束**，簡短講一句白話「這代表什麼、有沒有風險」，讓他不用回頭問你就看得懂現況。
