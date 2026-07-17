# Cloudflare Honcho MCP Dashboard Handoff

> Deprecated / 已棄用：不要再要求瀏覽器代理重建 Cloudflare AI Controls 裡的獨立 `honcho` MCP server。

## 現行決策

Honcho 走 `edgars-mcp` 內建工具：

```text
entry.edgars.tools/mcp
→ Cloudflare MCP Portal
→ edgars-mcp
→ honcho__* tools
→ mcp.honcho.dev
```

Cloudflare Portal 裡不需要獨立 `honcho` server。若 Dashboard 裡仍看得到舊的 `honcho` server，應視為 legacy / 舊設定；除非使用者明確要求保留 debug route，否則不要把它加回 `edgars-entry` portal。

## 瀏覽器代理現在要做什麼

若需要操作 Cloudflare Dashboard，只做下列確認：

1. `edgars-entry` portal 包含 `edgars-mcp`。
2. `edgars-mcp` server 狀態是 Ready。
3. 不把獨立 `honcho` server 加入 `edgars-entry`。
4. 若需要看到 Honcho tools，請 sync `edgars-mcp` capabilities，而不是 sync `honcho`。

## 成功判準

```text
edgars-entry portal 可連線
edgars-mcp Ready
tools/list 透過 edgars-mcp 顯示 honcho__* tools
```

## 不要再做

```text
建立 MCP server: honcho
把 https://honcho-mcp.edgars.tools/mcp 加入 Cloudflare Portal
把 HONCHO_FACADE_BEARER_VALUE 填進 Cloudflare AI Controls
要求外部 agent 直接持有 Honcho credential
```

這些是舊方案，已被 `edgars-mcp integrated Honcho tools` 取代。
