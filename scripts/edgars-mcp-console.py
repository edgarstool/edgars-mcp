"""edgars-mcp desktop control app: power, status, logs, wrap modes/skills."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from ctypes import windll

    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

REPO = Path(r"V:\projects\edgars-mcp")
RUNTIME = Path(r"G:\AI_WORK_512\run\mcp-handcraft")
PROFILE_PATH = RUNTIME / "wrap-profile.json"
LAUNCHER_PATH = RUNTIME / "handcraft-op-launch.cmd"
PID_FILE = RUNTIME / "handcraft-http.pid"
LOG_DIR = REPO / "logs"
OUT_LOG = LOG_DIR / "handcraft-http.out.log"
ERR_LOG = LOG_DIR / "handcraft-http.err.log"
START_PS1 = REPO / "scripts" / "start-wrap.ps1"
STOP_PS1 = REPO / "scripts" / "stop-wrap.ps1"
HEALTH_URL = "http://127.0.0.1:8765/health"
CONNECT_URL = "http://127.0.0.1:8877/health"

FLAG_KEYS = [
    "MCP_WRAP_ALL",
    "MCP_WRAP_ALLOW_REMOTE",
    "MCP_WRAP_PLAYWRIGHT",
    "MCP_WRAP_WINDOWS",
    "MCP_WRAP_DESKTOP_COMMANDER",
    "MCP_WRAP_DESCOPE",
    "MCP_WRAP_CLOUDFLARED",
    "MCP_WRAP_OP_CONNECT",
    "MCP_WRAP_OPENMONTAGE",
    "MCP_WRAP_HERMES",
    "MCP_WRAP_OPENCLAW",
]

SKILLS = [
    ("MCP_WRAP_PLAYWRIGHT", "Playwright 瀏覽器", "stdio", "會開瀏覽器子程序"),
    ("MCP_WRAP_WINDOWS", "Windows 桌面控制", "stdio", "滑鼠鍵盤與截圖"),
    ("MCP_WRAP_DESKTOP_COMMANDER", "Desktop Commander", "stdio", "本機檔案與終端"),
    ("MCP_WRAP_DESCOPE", "Descope 驗證", "native", "SDK / 管理 MCP"),
    ("MCP_WRAP_CLOUDFLARED", "cloudflared CLI", "native", "不管正式 tunnel 開關"),
    ("MCP_WRAP_OP_CONNECT", "1Password Connect", "native", "健康檢查與 compose"),
    ("MCP_WRAP_OPENMONTAGE", "OpenMontage", "native", "pipeline 與 BaseTools"),
    ("MCP_WRAP_HERMES", "Hermes", "native", "hermes CLI"),
    ("MCP_WRAP_OPENCLAW", "OpenClaw", "native", "openclaw agent"),
]

NATIVE_FLAGS = {
    "MCP_WRAP_DESCOPE",
    "MCP_WRAP_CLOUDFLARED",
    "MCP_WRAP_OP_CONNECT",
    "MCP_WRAP_OPENMONTAGE",
    "MCP_WRAP_HERMES",
    "MCP_WRAP_OPENCLAW",
}
STDIO_FLAGS = {
    "MCP_WRAP_PLAYWRIGHT",
    "MCP_WRAP_WINDOWS",
    "MCP_WRAP_DESKTOP_COMMANDER",
}

BG = "#16181d"
PANEL = "#21252c"
PANEL2 = "#2a2f38"
FG = "#e8eaed"
MUTED = "#9aa3af"
ACCENT = "#3dd68c"
DANGER = "#ff6b6b"
WARN = "#f5c542"
BTN = "#3a404c"
CREATE_NO_WINDOW = 0x08000000


def _on(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def default_flags(mode: str = "local") -> dict[str, str]:
    flags = {key: "0" for key in FLAG_KEYS}
    if mode == "core":
        return flags
    if mode == "full":
        flags["MCP_WRAP_ALL"] = "1"
        for key, _, group, _ in SKILLS:
            flags[key] = "1"
        return flags
    if mode == "local":
        for key in NATIVE_FLAGS:
            flags[key] = "1"
        return flags
    return flags


def load_profile() -> tuple[str, dict[str, str]]:
    if PROFILE_PATH.is_file():
        try:
            data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            mode = str(data.get("mode") or "custom")
            raw = data.get("flags") if isinstance(data.get("flags"), dict) else data
            flags = default_flags("core")
            for key in FLAG_KEYS:
                if key in raw:
                    flags[key] = "1" if _on(raw[key]) else "0"
            return mode, flags
        except Exception:
            pass
    launcher = parse_launcher_flags()
    if launcher:
        return infer_mode(launcher), launcher
    return "local", default_flags("local")


def save_profile(mode: str, flags: dict[str, str]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "flags": {key: flags.get(key, "0") for key in FLAG_KEYS},
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    PROFILE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_launcher_flags() -> dict[str, str]:
    flags = {key: "0" for key in FLAG_KEYS}
    if not LAUNCHER_PATH.is_file():
        return {}
    text = LAUNCHER_PATH.read_text(encoding="utf-8", errors="replace")
    found = False
    for line in text.splitlines():
        line = line.strip()
        if not line.lower().startswith("set "):
            continue
        body = line[4:]
        if "=" not in body:
            continue
        key, _, value = body.partition("=")
        key = key.strip()
        if key in flags:
            flags[key] = "1" if _on(value) else "0"
            found = True
    return flags if found else {}


def infer_mode(flags: dict[str, str]) -> str:
    if _on(flags.get("MCP_WRAP_ALL")) and not _on(flags.get("MCP_WRAP_ALLOW_REMOTE")):
        return "full"
    if all(not _on(flags.get(key)) for key in FLAG_KEYS):
        return "core"
    local = default_flags("local")
    if flags == local:
        return "local"
    return "custom"


BUILTIN_GROUP_RULES = [
    ("Agent", lambda n: n.endswith("_agent") or n.startswith("agent_job") or n.startswith("ollama_")),
    ("檔案 fs", lambda n: n.startswith("fs_")),
    ("系統 sys", lambda n: n.startswith("sys_")),
    ("QMD", lambda n: n.startswith("qmd_")),
    ("Git", lambda n: n.startswith("git_")),
    ("瀏覽器 browser", lambda n: n.startswith("browser_")),
    ("Vault", lambda n: n.startswith("vault_")),
    ("Linear", lambda n: n.startswith("linear_")),
    ("Warp", lambda n: n.startswith("warp_")),
    ("Cursor Agent", lambda n: n.startswith("cursor_")),
    ("Factory", lambda n: n.startswith("factory_")),
]


def load_builtin_tool_names() -> list[str]:
    path = REPO / "server_http.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("TOOLS = [")
    end = text.index("TOOLS = [_normalize_tool_descriptor")
    return re.findall(r'"name": "([^"]+)"', text[start:end])


def grouped_builtin_tools() -> list[tuple[str, list[str]]]:
    names = load_builtin_tool_names()
    used: set[str] = set()
    groups: list[tuple[str, list[str]]] = []
    for title, match in BUILTIN_GROUP_RULES:
        items = [name for name in names if name not in used and match(name)]
        if items:
            groups.append((title, items))
            used.update(items)
    leftover = [name for name in names if name not in used]
    if leftover:
        groups.append(("其他", leftover))
    return groups


def http_ok(url: str, timeout: float = 1.2) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300, str(resp.status)
    except urllib.error.HTTPError as exc:
        return False, str(exc.code)
    except Exception as exc:
        return False, str(exc)


def read_pid() -> str:
    if not PID_FILE.is_file():
        return ""
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8-sig"))
        return str(data.get("pid") or "")
    except Exception:
        return ""


def cloudflared_count() -> int:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            creationflags=CREATE_NO_WINDOW,
        )
        lines = [line for line in result.stdout.splitlines() if "cloudflared.exe" in line.lower()]
        return len(lines)
    except Exception:
        return 0


def tail_file(path: Path, max_bytes: int = 180_000) -> str:
    if not path.is_file():
        return f"（還沒有 {path.name}）"
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read()
        text = data.decode("utf-8", errors="replace")
        if size > max_bytes:
            text = "…（只顯示檔尾）\n" + text.split("\n", 1)[-1]
        return text[-12000:]
    except Exception as exc:
        return f"讀取失敗：{exc}"


def run_ps1(script: Path, extra_args: list[str] | None = None) -> tuple[int, str]:
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *(extra_args or []),
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(REPO),
        creationflags=CREATE_NO_WINDOW,
    )
    output = ((result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")).strip()
    return result.returncode, output


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("edgars-mcp 控制台")
        self.geometry("1280x860")
        self.minsize(1100, 760)
        self.configure(bg=BG)
        self.busy = False
        self._log_job = None
        self._status_job = None
        self.msg_q: queue.Queue[str] = queue.Queue()
        self.mode_var = tk.StringVar(value="local")
        self.flag_vars: dict[str, tk.BooleanVar] = {key: tk.BooleanVar(value=False) for key in FLAG_KEYS}
        self._loading = True
        self._build_style()
        self._build()
        mode, flags = load_profile()
        self._apply_flags_to_ui(mode, flags)
        self._loading = False
        self.after(200, self.refresh_status)
        self.after(400, self.refresh_logs)
        self.after(300, self._drain_messages)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        font = ("Microsoft JhengHei UI", 10)
        style.configure(".", background=BG, foreground=FG, font=font)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=FG, font=font)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=font)
        style.configure("Head.TLabel", background=BG, foreground=FG, font=("Microsoft JhengHei UI", 16, "bold"))
        style.configure("Status.TLabel", background=PANEL, foreground=ACCENT, font=("Microsoft JhengHei UI", 13, "bold"))
        style.configure("TRadiobutton", background=PANEL, foreground=FG, font=font)
        style.configure("TCheckbutton", background=PANEL, foreground=FG, font=font)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL2, foreground=FG, padding=(14, 6))
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT)])
        style.configure("Power.TButton", font=("Microsoft JhengHei UI", 11, "bold"), padding=8)
        style.configure("TButton", background=BTN, foreground=FG, padding=6)
        style.map("TButton", background=[("active", "#4b5362")])

    def _card(self, parent: tk.Widget) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
        return frame

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="edgars-mcp 控制台", style="Head.TLabel").pack(side="left")
        ttk.Button(head, text="重新整理", command=self.refresh_all).pack(side="right", padx=4)
        ttk.Button(head, text="開 log 資料夾", command=self.open_logs).pack(side="right", padx=4)

        self.power_label = ttk.Label(outer, text="狀態載入中…", style="Status.TLabel")
        self.power_label.configure(background=BG)
        self.power_label.pack(anchor="w", pady=(10, 12))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2, minsize=360)
        body.columnconfigure(1, weight=5)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")

        power = self._card(left)
        power.pack(fill="x")
        ttk.Label(power, text="開關機", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor="w")
        row = ttk.Frame(power, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="啟動", style="Power.TButton", command=lambda: self.run_action("start")).pack(side="left")
        ttk.Button(row, text="關閉", command=lambda: self.run_action("stop")).pack(side="left", padx=8)
        ttk.Button(power, text="套用技能並重啟", command=lambda: self.run_action("apply")).pack(fill="x", pady=(10, 0))

        mode_card = self._card(left)
        mode_card.pack(fill="x", pady=(12, 0))
        ttk.Label(mode_card, text="模式", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor="w")
        ttk.Label(mode_card, text="模式會改技能開關；要生效請按「套用技能並重啟」。", style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        for value, label in (
            ("core", "核心 — 原本技能常開，新包 wrap 全關"),
            ("local", "本機常用 — 原本技能 + Hermes / OpenClaw / Connect"),
            ("full", "全開 — 原本技能 + 全部新包，遠端桌面仍關"),
            ("custom", "自訂 — 原本技能常開，下面新包逐項開"),
        ):
            ttk.Radiobutton(
                mode_card,
                text=label,
                value=value,
                variable=self.mode_var,
                command=self._on_mode_change,
            ).pack(anchor="w", pady=2)

        skills = self._card(left)
        skills.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(skills, text="技能", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            skills,
            text="原本技能沒刪、也不能從這裡關。第二頁才是新包進去、可開關的 wrap。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 8))
        skill_tabs = ttk.Notebook(skills)
        skill_tabs.pack(fill="both", expand=True)

        builtin_tab = ttk.Frame(skill_tabs, style="Card.TFrame", padding=8)
        wrap_tab = ttk.Frame(skill_tabs, style="Card.TFrame", padding=8)
        skill_tabs.add(builtin_tab, text="原本技能（常開）")
        skill_tabs.add(wrap_tab, text="新包技能（可開關）")

        builtin_inner = self._scrollable(builtin_tab, height=280)
        groups = grouped_builtin_tools()
        self.builtin_count = sum(len(items) for _, items in groups)
        ttk.Label(
            builtin_inner,
            text=f"共 {self.builtin_count} 個，服務在跑就全部可用。Honcho 連上時另加 honcho__*。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        for title, items in groups:
            ttk.Label(builtin_inner, text=f"{title}  ({len(items)})", font=("Microsoft JhengHei UI", 10, "bold")).pack(anchor="w", pady=(8, 2))
            ttk.Label(builtin_inner, text="、".join(items), style="Muted.TLabel", wraplength=340).pack(anchor="w")

        ttk.Checkbutton(
            wrap_tab,
            text="一次打開全部新包（MCP_WRAP_ALL）",
            variable=self.flag_vars["MCP_WRAP_ALL"],
            command=self._mark_custom,
        ).pack(anchor="w", pady=(0, 2))
        ttk.Checkbutton(
            wrap_tab,
            text="允許遠端呼叫桌面技能（危險）",
            variable=self.flag_vars["MCP_WRAP_ALLOW_REMOTE"],
            command=self._mark_custom,
        ).pack(anchor="w", pady=(0, 8))
        inner = self._scrollable(wrap_tab, height=220)
        last_group = ""
        for key, title, group, hint in SKILLS:
            if group != last_group:
                ttk.Label(
                    inner,
                    text="子程序 MCP" if group == "stdio" else "本機 CLI / SDK",
                    style="Muted.TLabel",
                ).pack(anchor="w", pady=(8, 2))
                last_group = group
            ttk.Checkbutton(
                inner,
                text=f"{title}  — {hint}",
                variable=self.flag_vars[key],
                command=self._mark_custom,
            ).pack(anchor="w")

        status = self._card(right)
        status.pack(fill="x")
        ttk.Label(status, text="狀態", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor="w")
        self.status_text = tk.Text(
            status,
            height=8,
            bg=PANEL2,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            font=("Cascadia Mono", 10),
            wrap="word",
        )
        self.status_text.pack(fill="x", pady=(8, 0))
        self.status_text.configure(state="disabled")

        logs = self._card(right)
        logs.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(logs, text="Log", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor="w")
        notebook = ttk.Notebook(logs)
        notebook.pack(fill="both", expand=True, pady=(8, 0))
        out_frame, self.log_out = self._log_box(notebook)
        err_frame, self.log_err = self._log_box(notebook)
        act_frame, self.log_act = self._log_box(notebook)
        notebook.add(out_frame, text="HTTP 輸出")
        notebook.add(err_frame, text="HTTP 錯誤")
        notebook.add(act_frame, text="控制台動作")

        self.footer = ttk.Label(outer, text="就緒", style="Muted.TLabel")
        self.footer.configure(background=BG)
        self.footer.pack(fill="x", pady=(10, 0))

    def _log_box(self, parent: tk.Widget) -> tuple[ttk.Frame, tk.Text]:
        frame = ttk.Frame(parent, style="Card.TFrame")
        text = tk.Text(
            frame,
            bg="#12141a",
            fg="#d7dde8",
            insertbackground=FG,
            relief="flat",
            font=("Cascadia Mono", 9),
            wrap="word",
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return frame, text

    def _scrollable(self, parent: tk.Widget, height: int = 240) -> ttk.Frame:
        canvas = tk.Canvas(parent, bg=PANEL, highlightthickness=0, height=height)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, style="Card.TFrame")
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(inner_id, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _on_mode_change(self) -> None:
        if self._loading:
            return
        mode = self.mode_var.get()
        if mode == "custom":
            return
        self._apply_flags_to_ui(mode, default_flags(mode), keep_mode=True)

    def _mark_custom(self) -> None:
        if self._loading:
            return
        self.mode_var.set("custom")

    def _apply_flags_to_ui(self, mode: str, flags: dict[str, str], keep_mode: bool = False) -> None:
        self._loading = True
        if not keep_mode:
            self.mode_var.set(mode)
        for key, var in self.flag_vars.items():
            var.set(_on(flags.get(key)))
        if _on(flags.get("MCP_WRAP_ALL")):
            for key, _, _, _ in SKILLS:
                self.flag_vars[key].set(True)
        self._loading = False

    def current_flags(self) -> dict[str, str]:
        flags = {key: ("1" if var.get() else "0") for key, var in self.flag_vars.items()}
        if self.mode_var.get() == "full":
            flags = default_flags("full")
        elif self.mode_var.get() == "core":
            flags = default_flags("core")
        elif self.mode_var.get() == "local":
            flags = default_flags("local")
        return flags

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        self.footer.configure(text=text or ("工作中…" if busy else "就緒"))

    def log_action(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_act.configure(state="normal")
        self.log_act.insert("end", f"[{stamp}] {text}\n")
        self.log_act.see("end")
        self.log_act.configure(state="normal")

    def _drain_messages(self) -> None:
        while True:
            try:
                msg = self.msg_q.get_nowait()
            except queue.Empty:
                break
            self.log_action(msg)
        self.after(400, self._drain_messages)

    def refresh_all(self) -> None:
        self.refresh_status()
        self.refresh_logs()

    def refresh_status(self) -> None:
        http_ok_flag, http_detail = http_ok(HEALTH_URL)
        connect_ok, connect_detail = http_ok(CONNECT_URL)
        pid = read_pid()
        cf_count = cloudflared_count()
        live = parse_launcher_flags()
        wanted = self.current_flags()
        pending = live != wanted and bool(live)
        wrap_all = _on(live.get("MCP_WRAP_ALL")) if live else False
        enabled = []
        if live:
            if wrap_all:
                enabled = ["全部新包"]
            else:
                enabled = [title for key, title, _, _ in SKILLS if _on(live.get(key))]
        if live and _on(live.get("MCP_WRAP_ALLOW_REMOTE")):
            enabled.append("允許遠端桌面")

        if http_ok_flag:
            self.power_label.configure(text=f"運轉中    PID {pid or '—'}", foreground=ACCENT)
        else:
            self.power_label.configure(text="已關機", foreground=DANGER)

        lines = [
            f"HTTP     {'OK' if http_ok_flag else 'DOWN'}   {HEALTH_URL}   {http_detail}",
            f"Connect  {'OK' if connect_ok else 'DOWN'}   {CONNECT_URL}   {connect_detail}",
            f"cloudflared  {cf_count} 個程序（正式 tunnel 不由這裡關）",
            f"原本技能  {getattr(self, 'builtin_count', 80)} 個常開（沒刪）",
            f"目前模式  {infer_mode(live) if live else '（尚未寫入 launcher）'}",
            f"新包已開  {('、'.join(enabled) if enabled else '無')}",
            f"技能套用  {'要重啟才會跟上畫面勾選' if pending else '與畫面一致'}",
            f"profile   {PROFILE_PATH}",
        ]
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.insert("1.0", "\n".join(lines))
        self.status_text.configure(state="disabled")
        if self._status_job:
            self.after_cancel(self._status_job)
        self._status_job = self.after(3000, self.refresh_status)

    def refresh_logs(self) -> None:
        self._set_log(self.log_out, tail_file(OUT_LOG))
        self._set_log(self.log_err, tail_file(ERR_LOG))
        if self._log_job:
            self.after_cancel(self._log_job)
        self._log_job = self.after(2500, self.refresh_logs)

    def _set_log(self, widget: tk.Text, text: str) -> None:
        at_end = float(widget.yview()[1]) >= 0.95
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if at_end:
            widget.see("end")
        widget.configure(state="normal")

    def open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(LOG_DIR))

    def run_action(self, action: str) -> None:
        if self.busy:
            messagebox.showinfo("請稍候", "上一個動作還在跑。")
            return
        if action in {"start", "apply"}:
            save_profile(self.mode_var.get(), self.current_flags())
        self.set_busy(True, "啟動中…" if action != "stop" else "關閉中…")
        self.log_action({"start": "開始啟動", "stop": "開始關閉", "apply": "套用技能並重啟"}[action])
        thread = threading.Thread(target=self._worker, args=(action,), daemon=True)
        thread.start()

    def _worker(self, action: str) -> None:
        try:
            if action == "stop":
                code, output = run_ps1(STOP_PS1, ["-Force"])
            else:
                code, output = run_ps1(START_PS1, ["-ProfileJson", str(PROFILE_PATH)])
            snippet = output[-2500:] if output else "(no output)"
            self.msg_q.put(f"結束 exit={code}\n{snippet}")
        except subprocess.TimeoutExpired:
            self.msg_q.put("逾時：啟動或關閉超過 180 秒。")
            code = 1
        except Exception as exc:
            self.msg_q.put(f"失敗：{exc}")
            code = 1
        self.after(0, lambda: self._done(code))

    def _done(self, code: int) -> None:
        self.set_busy(False, "完成" if code == 0 else f"失敗 exit={code}")
        self.refresh_all()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
