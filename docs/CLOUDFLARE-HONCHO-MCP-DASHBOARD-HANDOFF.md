# Cloudflare Honcho MCP Dashboard Handoff

給瀏覽器代理使用。目標是修復 Cloudflare AI Controls 裡 `honcho` MCP server 的 bearer/header credential，讓它在 `edgars-entry` portal 可用。

## 背景

已驗證：

```text
https://honcho-mcp.edgars.tools/mcp
```

使用 `Authorization: Bearer <EDGARS_HONCHO_MCP_FACADE_TOKEN>` 直打 MCP `tools/list` 會回 200，工具數 30，包含 `inspect_workspace`。

Cloudflare API 目前顯示：

```text
Server ID: honcho
Hostname: https://honcho-mcp.edgars.tools/mcp
Auth type: bearer
Status: error
Error: unable to connect to server
```

也已試過 API `PUT /servers/honcho` 覆寫同 URL + `auth_credentials`，Cloudflare 回 success，但 sync 仍失敗且 origin log 沒看到 bearer sync request。判斷剩餘卡點是 Dashboard / 控制面 credential 未正確保存。

## 不可碰

不要修改：

```text
edgars-mcp server
linear server
edgars-entry portal domain
Access application policies
DNS
Tunnel ingress
secrets 本身的值
```

不要顯示或複製 secret 原文到聊天。只可從 Doppler 或密碼管理器取值後填入 Dashboard。

## 要做

1. 打開 Cloudflare Dashboard：

```text
https://dash.cloudflare.com/c2817bff1e0375474720742c17b3dfbb/one/access-controls/ai-controls/mcp-server
```

2. 找到 MCP server：

```text
honcho
```

若既有 `honcho` server 無法正確保存 authentication，刪除並重建它是允許的，因為這是可快速重建的控制面資源。

3. 設定或重建成：

```text
Name: honcho
Server ID: honcho
HTTP URL: https://honcho-mcp.edgars.tools/mcp
Authentication: header-based / bearer
Header name: Authorization
Header value: Bearer <EDGARS_HONCHO_MCP_FACADE_TOKEN>
Require user auth: off / on_behalf=false（若 UI 有此選項）
```

注意：Dashboard 的 `Header value` 不能填 `EDGARS_HONCHO_MCP_FACADE_TOKEN` 這串環境變數名稱，也不能填 `${EDGARS_HONCHO_MCP_FACADE_TOKEN}`。Cloudflare AI Controls 不會讀 Doppler，也不會展開本機 env var。這一格必須貼入 Doppler 取出的實際 token 值，格式如下：

```text
Bearer <Doppler 取出的實際 token>
```

如果 UI 是「Bearer token」單一欄位，而不是「Header name / Header value」兩欄，則只貼實際 token，不要加 `Bearer ` 前綴。

4. 儲存後執行 sync / Sync capabilities。

5. 成功判準：

```text
honcho status = Ready
tools list 包含 inspect_workspace
tools list 包含 list_workspaces
tools list 包含 get_peer_card 或 chat
```

6. 確認 `edgars-entry` portal 包含：

```text
edgars-mcp
honcho
linear
```

目前 API 已確認 portal 內有：

```text
edgars-mcp
linear
```

若 `honcho` 不在 portal，等 `honcho` server Ready 後加入 portal 並 Save。

## 失敗時回報

若失敗，請回報：

```text
Final URL:
Cloudflare UI error text:
honcho server status:
honcho server error:
是否有 Authentication/header-based 欄位:
是否能輸入 Header name = Authorization:
是否能輸入 Header value:
sync 後 origin log 是否有 POST /mcp:
```

## 驗證命令

不要輸出 token。只回報狀態與 tool 名稱。

```powershell
$token = doppler secrets get EDGARS_HONCHO_MCP_FACADE_TOKEN --project handcraft-mcp --config prd --plain
$body = '{ "jsonrpc":"2.0", "id":1, "method":"tools/list", "params":{} }'

Invoke-RestMethod `
  -Uri 'https://honcho-mcp.edgars.tools/mcp' `
  -Method Post `
  -ContentType 'application/json' `
  -Headers @{ Authorization = 'Bearer ' + $token; Accept = 'application/json, text/event-stream' } `
  -Body $body |
  Select-Object -ExpandProperty result |
  Select-Object -ExpandProperty tools |
  Select-Object -First 10 name
```
