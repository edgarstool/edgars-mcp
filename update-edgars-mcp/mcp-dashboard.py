# -*- coding: utf-8 -*-
"""
edgars mcp 即時控制台
本機小伺服器：只綁 127.0.0.1:8788，不對外開放、不需要登入。
即時數據來源：
  - http://127.0.0.1:8765/health   （MCP 本機健康資訊）
  - https://mcp.edgars.tools/mcp   （外網 MCP 探測）
  - https://mcp.edgars.tools/.well-known/oauth-protected-resource （ChatGPT OAuth discovery 探測）
  - Windows 服務 / process 狀態
  - V:\\projects\\edgars-mcp\\logs\\ 的 log 檔即時 tail
啟動：雙擊「MCP-即時控制台.cmd」，或 py -3 MCP-即時控制台.py
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BIND_HOST = "127.0.0.1"
BIND_PORT = 8788
MCP_HEALTH_URL = "http://127.0.0.1:8765/health"
MCP_EXTERNAL_URL = "https://mcp.edgars.tools/mcp"
MCP_PRM_URL = "https://mcp.edgars.tools/.well-known/oauth-protected-resource"
LOGS_DIR = r"V:\projects\edgars-mcp\logs"
STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", r"C:\Users\EdgarsTool\AppData\Roaming"),
    r"Microsoft\Windows\Start Menu\Programs\Startup",
)
STARTUP_SCRIPTS = ["edgars-handcraft-mcp.cmd", "edgars-cloudflared-tunnel.cmd"]
CREATE_NO_WINDOW = 0x08000000


def _http_get(url: str, timeout: float = 6.0):
    """回傳 (status_code, body_text 或 None, error 或 None)"""
    req = urllib.request.Request(url, headers={"User-Agent": "mcp-dashboard/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(20000).decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return e.code, None, None
    except Exception as e:
        return None, None, str(e)


def _port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        return (out.stdout or "") + (out.stderr or "")
    except Exception as e:
        return f"ERR:{e}"


def collect_status() -> dict:
    result: dict = {"time": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 1. MCP 本機 /health
    code, body, err = _http_get(MCP_HEALTH_URL, 5)
    health = None
    if code == 200 and body:
        try:
            health = json.loads(body)
        except Exception:
            pass
    result["local"] = {"http": code, "error": err, "health": health,
                       "ok": bool(health and health.get("ok"))}

    # 2. 外網探測
    code2, _, err2 = _http_get(MCP_EXTERNAL_URL, 8)
    code3, _, err3 = _http_get(MCP_PRM_URL, 8)
    result["external"] = {
        "mcp_http": code2,
        "mcp_error": err2,
        "prm_http": code3,
        "prm_error": err3,
        "reachable": code2 in (200, 401, 405, 406),
        "oauth_ready": code3 == 200 and code2 in (200, 401, 405, 406),
    }

    # 3. port 8765
    result["port_8765"] = _port_listening(8765)

    # 4. Cloudflared 服務
    sc_out = _run(["sc", "query", "Cloudflared"])
    result["cloudflared"] = "RUNNING" in sc_out

    # 5. Claude Desktop process 數
    tl = _run(["tasklist", "/FI", "IMAGENAME eq claude.exe", "/FO", "CSV", "/NH"])
    result["claude_procs"] = tl.count("claude.exe")

    # 6. 啟動腳本存在性
    result["startup_scripts"] = {
        name: os.path.isfile(os.path.join(STARTUP_DIR, name))
        for name in STARTUP_SCRIPTS
    }
    return result


def list_logs() -> list[dict]:
    items = []
    if os.path.isdir(LOGS_DIR):
        for name in sorted(os.listdir(LOGS_DIR)):
            p = os.path.join(LOGS_DIR, name)
            if os.path.isfile(p):
                st = os.stat(p)
                items.append({
                    "name": name, "size": st.st_size,
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(st.st_mtime)),
                })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def tail_log(name: str, lines: int = 200) -> dict:
    # 防止路徑跳脫：只允許 logs 目錄裡的檔名
    safe = os.path.basename(name)
    p = os.path.join(LOGS_DIR, safe)
    if not os.path.isfile(p) or os.path.dirname(os.path.abspath(p)) != os.path.abspath(LOGS_DIR):
        return {"error": "檔案不存在", "name": safe}
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 512 * 1024))  # 最多讀最後 512KB
            data = f.read().decode("utf-8", "replace")
        text_lines = data.splitlines()[-lines:]
        return {"name": safe, "size": size, "lines": text_lines}
    except Exception as e:
        return {"error": str(e), "name": safe}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 安靜模式
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/api/status":
                self._json(collect_status())
            elif u.path == "/api/logs":
                self._json({"files": list_logs()})
            elif u.path == "/api/log":
                name = (q.get("file") or [""])[0]
                lines = int((q.get("lines") or ["200"])[0])
                self._json(tail_log(name, min(max(lines, 10), 1000)))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)


PAGE = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>edgars mcp 即時控制台</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--bd:#2b3240;--tx:#e6edf3;--mut:#9aa7b4;--grn:#2ea043;--red:#f85149;--amb:#d29922;--blu:#388bfd}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font-family:"Segoe UI",system-ui,"Microsoft JhengHei",sans-serif;line-height:1.55}
.wrap{max-width:1100px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:22px;margin:0 0 2px}.sub{color:var(--mut);margin:0 0 18px;font-size:13px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(215px,1fr))}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px 16px}
.card h3{margin:0 0 6px;font-size:12px;color:var(--mut);font-weight:600;letter-spacing:.04em}
.big{font-size:17px;font-weight:600}.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;word-break:break-all}
.ok{color:#4ac26b}.bad{color:var(--red)}.warn{color:var(--amb)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:7px;vertical-align:middle}
.dot.g{background:var(--grn)}.dot.r{background:var(--red)}.dot.a{background:var(--amb)}
.sec{margin:22px 0 8px;font-size:14px;font-weight:600}
select,button{background:#21262d;border:1px solid var(--bd);color:var(--tx);border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer}
button:hover,select:hover{border-color:var(--blu)}
#logbox{background:#0a0d12;border:1px solid var(--bd);border-radius:10px;padding:12px;height:380px;overflow:auto;font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:pre-wrap;word-break:break-all;color:#c9d4df}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:6px 0 10px}
.kv{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--bd);font-size:13px}
.kv:last-child{border:0}.kv span:first-child{color:var(--mut)}
.foot{color:var(--mut);font-size:12px;margin-top:26px;text-align:center}
label{font-size:12.5px;color:var(--mut)}
</style></head><body><div class="wrap">
<h1>🛠️ edgars mcp 即時控制台</h1>
<p class="sub">每 10 秒自動更新 · <span id="upd">載入中…</span></p>

<div class="grid" id="cards"></div>

<div class="sec">🔎 /health 詳細資訊</div>
<div class="card" id="healthDetail">載入中…</div>

<div class="sec">📜 即時 Log</div>
<div class="bar">
  <select id="logSel"></select>
  <label><input type="checkbox" id="autoLog" checked> 每 5 秒自動更新</label>
  <button onclick="loadLog()">重新整理</button>
  <span id="logInfo" style="color:var(--mut);font-size:12px"></span>
</div>
<div id="logbox">選擇上方 log 檔…</div>

<p class="foot">只綁 127.0.0.1:8788，僅本機可看。資料來源：/health、外網探測、Windows 服務、logs 目錄。</p>
</div>
<script>
function chip(ok,txtOk,txtBad,warn){
  const cls = ok ? 'g' : (warn ? 'a' : 'r');
  const t = ok ? txtOk : txtBad;
  return '<span class="dot '+cls+'"></span><span class="big '+(ok?'ok':(warn?'warn':'bad'))+'">'+t+'</span>';
}
async function refresh(){
  try{
    const r = await fetch('/api/status'); const s = await r.json();
    document.getElementById('upd').textContent = '最後更新 ' + s.time;
    const h = s.local.health || {};
    const auth = h.auth || {};
    const cards = [
      ['MCP 伺服器', chip(s.local.ok, '運作中', s.port_8765 ? 'health 異常' : '停止')],
      ['ChatGPT OAuth readiness', chip(s.external.oauth_ready, 'PRM '+s.external.prm_http+' / MCP '+s.external.mcp_http, (s.external.prm_error || s.external.mcp_error || ('PRM '+s.external.prm_http+' / MCP '+s.external.mcp_http)))],
      ['外網 mcp.edgars.tools', chip(s.external.reachable, 'MCP HTTP '+s.external.mcp_http, s.external.mcp_error || ('HTTP '+s.external.mcp_http), !s.external.oauth_ready && s.external.reachable)],
      ['Cloudflared 隧道', chip(s.cloudflared, '服務 Running', '服務未執行')],
      ['Claude Desktop', chip(s.claude_procs>0, s.claude_procs+' 個 process', '未執行')],
      ['協定版本', '<div class="big">'+(h.protocolVersion||'—')+'</div>'],
      ['OAuth 有效 token', '<div class="big">'+(auth.oauth_active_tokens!==undefined?auth.oauth_active_tokens:'—')+'</div>'],
      ['API token 設定', chip(!!auth.mcp_api_token_configured, '已設定', '未設定', true)],
      ['啟動腳本', chip(Object.values(s.startup_scripts).every(Boolean), '兩支都在', '有缺！')]
    ];
    document.getElementById('cards').innerHTML =
      cards.map(c=>'<div class="card"><h3>'+c[0]+'</h3>'+c[1]+'</div>').join('');
    const rows = [];
    if(h.server) rows.push(['名稱 / 版本', h.server.name+' v'+h.server.version]);
    if(h.public) rows.push(['對外 MCP URL', h.public.mcp_url]);
    if(h.local) rows.push(['本機監聽', h.local.host+':'+h.local.port+h.local.mcp_path]);
    rows.push(['OAuth 模式', auth.oauth_mode||'—']);
    rows.push(['Cloudflare Access', auth.cloudflare_access_enabled?'啟用':'停用（用其他授權法）']);
    if(h.webhooks) rows.push(['Webhooks', h.webhooks.join('、')]);
    document.getElementById('healthDetail').innerHTML =
      rows.map(r=>'<div class="kv"><span>'+r[0]+'</span><span class="mono">'+r[1]+'</span></div>').join('');
  }catch(e){
    document.getElementById('upd').textContent = '更新失敗：'+e;
  }
}
async function loadLogList(){
  const r = await fetch('/api/logs'); const d = await r.json();
  const sel = document.getElementById('logSel');
  const cur = sel.value;
  sel.innerHTML = d.files.map(f=>'<option value="'+f.name+'">'+f.name+'（'+(f.size/1024).toFixed(1)+' KB · '+f.mtime+'）</option>').join('');
  if(cur) sel.value = cur;
}
async function loadLog(){
  const name = document.getElementById('logSel').value;
  if(!name) return;
  const r = await fetch('/api/log?file='+encodeURIComponent(name)+'&lines=300');
  const d = await r.json();
  const box = document.getElementById('logbox');
  if(d.error){ box.textContent = '⚠ '+d.error; return; }
  document.getElementById('logInfo').textContent = (d.size/1024).toFixed(1)+' KB · 顯示最後 '+d.lines.length+' 行';
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  box.textContent = d.lines.length ? d.lines.join('\n') : '（目前是空的 — 等新請求進來就會有內容）';
  if(atBottom) box.scrollTop = box.scrollHeight;
}
refresh(); loadLogList().then(loadLog);
setInterval(refresh, 10000);
setInterval(()=>{ if(document.getElementById('autoLog').checked){ loadLogList(); loadLog(); } }, 5000);
document.getElementById('logSel').addEventListener('change', loadLog);
</script></body></html>"""


def main():
    try:
        srv = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    except OSError:
        # 已經有一份在跑 → 直接開瀏覽器
        webbrowser.open(f"http://{BIND_HOST}:{BIND_PORT}/")
        return
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"http://{BIND_HOST}:{BIND_PORT}/")
    print(f"[dashboard] http://{BIND_HOST}:{BIND_PORT}/  (Ctrl+C 結束)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
