"""edgars-mcp 人類控制台：開關機、狀態、log、wrap 技能（Windows native + Descope）。"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
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
LAUNCHER_PATHS = (
    RUNTIME / "handcraft-native-launch.cmd",
    RUNTIME / "handcraft-op-launch.cmd",
)
PID_FILE = RUNTIME / "handcraft-http.pid"
LOG_DIR = REPO / "logs"
OUT_LOG = LOG_DIR / "handcraft-http.out.log"
ERR_LOG = LOG_DIR / "handcraft-http.err.log"
START_PS1 = REPO / "scripts" / "start-wrap.ps1"
STOP_PS1 = REPO / "scripts" / "stop-wrap.ps1"
START_MCP_PS1 = REPO / "scripts" / "start-mcp.ps1"
HEALTH_URL = "http://127.0.0.1:8765/health"
PUBLIC_HEALTH_URL = "https://mcp.edgars.tools/health"
LOGIN_TASK = "edgars-mcp-http"

FLAG_KEYS = [
    "MCP_WRAP_ALL",
    "MCP_WRAP_ALLOW_REMOTE",
    "MCP_WRAP_PLAYWRIGHT",
    "MCP_WRAP_KAPTURE",
    "MCP_WRAP_WINDOWS",
    "MCP_WRAP_DESKTOP_COMMANDER",
    "MCP_WRAP_DESCOPE",
    "MCP_WRAP_CLOUDFLARED",
    "MCP_WRAP_OPENMONTAGE",
    "MCP_WRAP_HERMES",
    "MCP_WRAP_OPENCLAW",
    "MCP_WRAP_FLEET",
    "MCP_WRAP_YOUTRACK",
    "MCP_WRAP_CHROME_DEVTOOLS",
]

SKILLS = [
    ("MCP_WRAP_PLAYWRIGHT", "Playwright 瀏覽器", "stdio", "自己開一個瀏覽器"),
    ("MCP_WRAP_KAPTURE", "Kapture 瀏覽器", "stdio", "接到已經開著的 Chrome"),
    ("MCP_WRAP_WINDOWS", "Windows 桌面控制", "stdio", "滑鼠、鍵盤、截圖"),
    ("MCP_WRAP_DESKTOP_COMMANDER", "Desktop Commander", "stdio", "本機檔案和終端"),
    ("MCP_WRAP_DESCOPE", "Descope", "native", "登入和權限"),
    ("MCP_WRAP_CLOUDFLARED", "cloudflared", "native", "看通道，不關正式那條"),
    ("MCP_WRAP_OPENMONTAGE", "OpenMontage", "native", "影片製作管線"),
    ("MCP_WRAP_HERMES", "Hermes", "native", "本機 Hermes 助手"),
    ("MCP_WRAP_OPENCLAW", "OpenClaw", "native", "本機 OpenClaw 助手"),
    ("MCP_WRAP_FLEET", "Fleet 調度", "native", "看哪一台比較適合"),
    ("MCP_WRAP_YOUTRACK", "YouTrack", "stdio", "工作單。不再使用 Linear"),
    ("MCP_WRAP_CHROME_DEVTOOLS", "Chrome DevTools", "stdio", "看網頁怎麼跑"),
]

NATIVE_FLAGS = {
    "MCP_WRAP_DESCOPE",
    "MCP_WRAP_CLOUDFLARED",
    "MCP_WRAP_OPENMONTAGE",
    "MCP_WRAP_HERMES",
    "MCP_WRAP_OPENCLAW",
    "MCP_WRAP_FLEET",
}

BG = "#10141c"
PANEL = "#171d28"
PANEL2 = "#202838"
FG = "#f4f7fb"
MUTED = "#8e9bb0"
ACCENT = "#3dcc8e"
ACCENT_SOFT = "#17362b"
BLUE = "#8eb7ff"
BLUE_SOFT = "#1c2944"
DANGER = "#ff8d8d"
DANGER_SOFT = "#3a2226"
WARN = "#e7c36a"
BTN = "#2a3344"
LINE = "#2c3648"
FONT = "Microsoft JhengHei UI"
CREATE_NO_WINDOW = 0x08000000


def _on(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def default_flags(mode: str = "local") -> dict[str, str]:
    flags = {key: "0" for key in FLAG_KEYS}
    if mode == "core":
        return flags
    if mode == "full":
        flags["MCP_WRAP_ALL"] = "1"
        for key, _, _, _ in SKILLS:
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
            flags["MCP_WRAP_FLEET"] = "1"
            for key in FLAG_KEYS:
                if key in raw:
                    flags[key] = "1" if _on(raw[key]) else "0"
            # Hard policy: no 1Password Connect on startup path.
            flags.pop("MCP_WRAP_OP_CONNECT", None)
            return mode, flags
        except Exception:
            pass
    launcher = parse_launcher_flags()
    if launcher:
        return infer_mode(launcher), launcher
    return "local", default_flags("local")


def save_profile(mode: str, flags: dict[str, str]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    clean = {key: flags.get(key, "0") for key in FLAG_KEYS}
    payload = {
        "mode": mode,
        "flags": clean,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "notes": "native startup; no Docker / 1Password Connect",
    }
    PROFILE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_launcher_flags() -> dict[str, str]:
    flags = {key: "0" for key in FLAG_KEYS}
    path = next((p for p in LAUNCHER_PATHS if p.is_file()), None)
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
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
    if flags == default_flags("local"):
        return "local"
    return "custom"


BUILTIN_GROUP_RULES = [
    ("助手", lambda n: n.endswith("_agent") or n.startswith(("agent_job", "ollama_", "codex_"))),
    ("檔案", lambda n: n.startswith("fs_")),
    ("系統", lambda n: n.startswith("sys_")),
    ("搜尋", lambda n: n.startswith("qmd_")),
    ("Git", lambda n: n.startswith("git_")),
    ("瀏覽器", lambda n: n.startswith("browser_")),
    ("筆記本", lambda n: n.startswith("vault_")),
    ("Warp", lambda n: n.startswith("warp_")),
    ("Cursor", lambda n: n.startswith("cursor_")),
    ("Factory", lambda n: n.startswith("factory_")),
]


def load_builtin_tool_names() -> list[str]:
    """Parse raw TOOLS descriptors from server_http.py (before normalize reassignment)."""
    path = REPO / "server_http.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("TOOLS = [")
    # Second TOOLS = [ is the normalized reassignment; keep only the raw list between them.
    end = text.find("TOOLS = [", start + 1)
    if end < 0:
        end = text.find("CHATGPT_HONCHO_TOOLS", start + 1)
    if end < 0:
        raise ValueError("找不到 server_http.py 的 TOOLS 原始清單結束位置")
    names = re.findall(r'"name": "([^"]+)"', text[start:end])
    # Match server_http.py: drop retired Linear tools from the public TOOLS surface.
    return [name for name in names if not name.startswith("linear_")]


def load_builtin_tool_details() -> dict[str, str]:
    """Best-effort description for each public base tool."""
    path = REPO / "server_http.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("TOOLS = [")
    end = text.find("TOOLS = [", start + 1)
    if end < 0:
        end = text.find("CHATGPT_HONCHO_TOOLS", start + 1)
    block = text[start:end]
    details: dict[str, str] = {}
    for name in load_builtin_tool_names():
        marker = f'"name": "{name}"'
        idx = block.find(marker)
        if idx < 0:
            details[name] = ""
            continue
        window = block[idx:idx + 1200]
        immediate = re.match(r'[\s\S]*?"description":\s*(\(|")', window)
        if not immediate:
            details[name] = ""
            continue
        if immediate.group(1) == '"':
            quoted = re.search(r'"description":\s*"((?:\\.|[^"\\])*)"', window)
            details[name] = quoted.group(1) if quoted else ""
            continue
        paren = re.search(r'"description":\s*\(', window)
        chunk = window[paren.end():]
        stop = chunk.find("),")
        if stop > 0:
            chunk = chunk[:stop]
        details[name] = "".join(re.findall(r'"((?:\\.|[^"\\])*)"', chunk))
    return details


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
    wrapper_names = load_wrapper_agent_tool_names()
    hermes = [name for name in wrapper_names if name.startswith("hermes_")]
    openclaw = [name for name in wrapper_names if name.startswith("openclaw_")]
    if hermes:
        groups.append(("Hermes", hermes))
    if openclaw:
        groups.append(("OpenClaw", openclaw))
    return groups


def load_wrapper_agent_tool_names() -> list[str]:
    text = (REPO / "edgar_wrappers.py").read_text(encoding="utf-8")
    return re.findall(r'_tool\(\s*"((?:hermes_|openclaw_)[^"]+)"', text)


def load_wrapper_agent_tool_details() -> dict[str, str]:
    text = (REPO / "edgar_wrappers.py").read_text(encoding="utf-8")
    details: dict[str, str] = {}
    for name, description in re.findall(r'_tool\(\s*"((?:hermes_|openclaw_)[^"]+)"\s*,\s*"([^"]*)"', text):
        details[name] = description
    return details


def fetch_json(url: str, timeout: float = 2.0) -> tuple[bool, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return True, json.loads(raw)
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
        return len([line for line in result.stdout.splitlines() if "cloudflared.exe" in line.lower()])
    except Exception:
        return 0


def login_task_state() -> str:
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"(Get-ScheduledTask -TaskName '{LOGIN_TASK}' -ErrorAction Stop).State",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
        text = (result.stdout or "").strip()
        return text or f"查詢失敗 exit={result.returncode}"
    except Exception as exc:
        return str(exc)


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
        self.geometry("1360x900")
        self.minsize(1180, 760)
        self.configure(bg=BG)
        self.busy = False
        self._log_job = None
        self._status_job = None
        self._status_running = False
        self.msg_q: queue.Queue[str] = queue.Queue()
        self.mode_var = tk.StringVar(value="local")
        self.search_var = tk.StringVar()
        self.log_filter_var = tk.StringVar()
        self.page_var = tk.StringVar(value="overview")
        self.flag_vars: dict[str, tk.BooleanVar] = {key: tk.BooleanVar(value=False) for key in FLAG_KEYS}
        self.mode_buttons: dict[str, dict[str, tk.Widget]] = {}
        self.nav_buttons: dict[str, dict[str, tk.Widget]] = {}
        self.pages: dict[str, ttk.Frame] = {}
        self.metrics: dict[str, tuple[tk.Label, tk.Label]] = {}
        self.tool_details = load_builtin_tool_details()
        self.tool_details.update(load_wrapper_agent_tool_details())
        self._loading = True
        self._build_style()
        self._build()
        mode, flags = load_profile()
        self._apply_flags_to_ui(mode, flags)
        self._loading = False
        self.show_page("overview")
        self.after(200, self.refresh_status)
        self.after(400, self.refresh_logs)
        self.after(300, self._drain_messages)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        font = (FONT, 10)
        style.configure(".", background=BG, foreground=FG, font=font)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=FG, font=font)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=font)
        style.configure("TCheckbutton", background=PANEL, foreground=FG, font=font)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=PANEL2, foreground=MUTED, padding=(18, 10), font=(FONT, 10))
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])
        style.configure("Treeview", background="#1a2130", fieldbackground="#1a2130", foreground=FG, borderwidth=0, rowheight=32, font=font)
        style.configure("Treeview.Heading", background=PANEL, foreground=MUTED, relief="flat")
        style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", FG)])
        style.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=BG, borderwidth=0, arrowsize=12)

    def _card(self, parent: tk.Widget, **pack) -> tk.Frame:
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1, padx=18, pady=16)
        if pack:
            frame.pack(**pack)
        return frame

    def _ghost_button(self, parent: tk.Widget, text: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=PANEL,
            fg=FG,
            activebackground=PANEL2,
            activeforeground=FG,
            relief="flat",
            padx=14,
            pady=7,
            cursor="hand2",
            font=(FONT, 10),
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=LINE,
        )

    def _build(self) -> None:
        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True)

        top = tk.Frame(shell, bg=BG, padx=24, pady=12)
        top.pack(fill="x")
        mark = tk.Frame(top, bg=ACCENT, width=10, height=36)
        mark.pack(side="left")
        mark.pack_propagate(False)
        titles = tk.Frame(top, bg=BG)
        titles.pack(side="left", padx=(14, 0))
        tk.Label(titles, text="edgars-mcp", bg=BG, fg=FG, font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(titles, text="本機控制台", bg=BG, fg=MUTED, font=(FONT, 10)).pack(anchor="w")
        self.power_chip = tk.Label(
            top,
            text="  讀取中  ",
            bg=PANEL2,
            fg=MUTED,
            font=(FONT, 10, "bold"),
            padx=14,
            pady=8,
        )
        self.power_chip.pack(side="right", pady=4)
        self._ghost_button(top, "重新整理", self.refresh_all).pack(side="right", padx=(0, 10))
        self._ghost_button(top, "開 log 資料夾", self.open_logs).pack(side="right", padx=(0, 8))

        tk.Frame(shell, bg=LINE, height=1).pack(fill="x", padx=24)

        body = tk.Frame(shell, bg=BG, padx=20, pady=16)
        body.pack(fill="both", expand=True)
        rail = tk.Frame(body, bg=PANEL, width=188, highlightbackground=LINE, highlightthickness=1)
        rail.pack(side="left", fill="y", padx=(0, 16))
        rail.pack_propagate(False)
        tk.Label(rail, text="導覽", bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(anchor="w", padx=18, pady=(18, 10))
        for key, label in (("overview", "總覽"), ("skills", "技能"), ("logs", "日誌")):
            row = tk.Frame(rail, bg=PANEL)
            row.pack(fill="x", padx=10, pady=3)
            indicator = tk.Frame(row, bg=PANEL, width=3)
            indicator.pack(side="left", fill="y", padx=(0, 2))
            indicator.pack_propagate(False)
            btn = tk.Button(
                row,
                text=label,
                command=lambda k=key: self.show_page(k),
                bg=PANEL,
                fg=FG,
                activebackground=PANEL2,
                activeforeground=FG,
                relief="flat",
                anchor="w",
                padx=12,
                pady=11,
                cursor="hand2",
                font=(FONT, 13),
            )
            btn.pack(side="left", fill="x", expand=True)
            self.nav_buttons[key] = {"row": row, "mark": indicator, "btn": btn}

        content = tk.Frame(body, bg=BG)
        content.pack(side="left", fill="both", expand=True)
        for key in ("overview", "skills", "logs"):
            page = ttk.Frame(content)
            self.pages[key] = page
        self._build_overview(self.pages["overview"])
        self._build_skills(self.pages["skills"])
        self._build_logs(self.pages["logs"])

        tk.Frame(shell, bg=LINE, height=1).pack(fill="x")
        self.footer = tk.Label(shell, text="就緒", bg=BG, fg=MUTED, anchor="w", padx=24, pady=10, font=(FONT, 9))
        self.footer.pack(fill="x")

    def show_page(self, key: str) -> None:
        self.page_var.set(key)
        for name, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for name, parts in self.nav_buttons.items():
            selected = name == key
            bg = PANEL2 if selected else PANEL
            parts["row"].configure(bg=bg)
            parts["mark"].configure(bg=ACCENT if selected else PANEL)
            parts["btn"].configure(bg=bg, fg=ACCENT if selected else FG, activebackground=PANEL2)

    def _metric(self, parent: tk.Widget, key: str, title: str, stripe: str) -> None:
        card = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        card.pack(side="left", fill="both", expand=True, padx=6)
        tk.Frame(card, bg=stripe, height=3).pack(fill="x")
        body = tk.Frame(card, bg=PANEL, padx=14, pady=10)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=title, bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        value = tk.Label(body, text="…", bg=PANEL, fg=FG, font=(FONT, 14, "bold"))
        value.pack(anchor="w", pady=(8, 0))
        hint = tk.Label(body, text=" ", bg=PANEL, fg=MUTED, font=(FONT, 9), wraplength=280, justify="left")
        hint.pack(anchor="w", pady=(6, 0))
        self.metrics[key] = (value, hint)

    def _build_overview(self, page: ttk.Frame) -> None:
        metrics = tk.Frame(page, bg=BG)
        metrics.pack(fill="x", pady=(0, 10))
        for key, title, stripe in (
            ("http", "本機 HTTP", ACCENT),
            ("public", "公開位址", BLUE),
            ("tunnel", "cloudflared", WARN),
            ("task", "登入排程", "#c4b5fd"),
        ):
            self._metric(metrics, key, title, stripe)

        actions = self._card(page, fill="x", pady=(0, 10))
        tk.Label(actions, text="開關機", bg=PANEL, fg=FG, font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(
            actions,
            text="啟動會套用左邊技能頁的勾選。關閉只停本機 HTTP，不關正式 tunnel。",
            bg=PANEL,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(anchor="w", pady=(4, 10))
        row = tk.Frame(actions, bg=PANEL)
        row.pack(fill="x")
        self._action_button(row, "啟動", ACCENT, "#062117", lambda: self.run_action("start")).pack(side="left")
        self._action_button(row, "關閉", DANGER_SOFT, DANGER, lambda: self.run_action("stop")).pack(side="left", padx=10)
        self._action_button(row, "只開核心", BTN, FG, lambda: self.run_action("start_core")).pack(side="left")
        self._action_button(row, "套用技能並重啟", BLUE_SOFT, BLUE, lambda: self.run_action("apply")).pack(side="left", padx=10)

        lower = tk.Frame(page, bg=BG)
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=6, minsize=560)
        lower.columnconfigure(1, weight=4, minsize=320)
        lower.rowconfigure(0, weight=1)

        mode_card = tk.Frame(lower, bg=PANEL, highlightbackground=LINE, highlightthickness=1, padx=14, pady=12)
        mode_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(mode_card, text="模式", bg=PANEL, fg=FG, font=(FONT, 14, "bold")).pack(anchor="w", pady=(0, 8))
        grid = tk.Frame(mode_card, bg=PANEL)
        grid.pack(fill="both", expand=True)
        for col in range(2):
            grid.columnconfigure(col, weight=1, uniform="mode")
        for row in range(2):
            grid.rowconfigure(row, weight=1, minsize=58)
        for index, (value, label, hint) in enumerate(
            (
                ("core", "核心", "只留基本功能"),
                ("local", "本機常用", "這台平常會用的"),
                ("full", "全開", "能開的都打開"),
                ("custom", "自訂", "自己一項一項勾"),
            )
        ):
            cell = tk.Frame(grid, bg=PANEL2, highlightbackground=LINE, highlightthickness=1, padx=10, pady=6, cursor="hand2")
            cell.grid(row=index // 2, column=index % 2, sticky="nsew", padx=4, pady=3)
            title = tk.Label(cell, text=label, bg=PANEL2, fg=FG, font=(FONT, 12, "bold"), anchor="w", cursor="hand2")
            title.grid(row=0, column=0, sticky="w")
            sub = tk.Label(cell, text=hint, bg=PANEL2, fg=MUTED, font=(FONT, 9), anchor="w", cursor="hand2")
            sub.grid(row=1, column=0, sticky="w", pady=(2, 0))
            for widget in (cell, title, sub):
                widget.bind("<Button-1>", lambda _e, v=value: self._select_mode(v))
            self.mode_buttons[value] = {"frame": cell, "title": title, "hint": sub}

        note = tk.Frame(lower, bg=PANEL, highlightbackground=LINE, highlightthickness=1, padx=18, pady=16)
        note.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(note, text="現在這台", bg=PANEL, fg=FG, font=(FONT, 14, "bold")).pack(anchor="w")
        self.summary = tk.Text(
            note,
            height=8,
            width=8,
            bg="#141a24",
            fg=FG,
            insertbackground=FG,
            relief="flat",
            font=(FONT, 12),
            wrap="word",
            highlightthickness=0,
            padx=12,
            pady=12,
            spacing1=2,
            spacing3=6,
        )
        self.summary.pack(fill="both", expand=True, pady=(12, 0))
        self.summary.configure(state="disabled")

    def _action_button(self, parent: tk.Widget, text: str, bg: str, fg: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief="flat",
            padx=18,
            pady=10,
            cursor="hand2",
            font=(FONT, 11, "bold"),
        )

    def _build_skills(self, page: ttk.Frame) -> None:
        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True)
        builtin = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        wraps = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        notebook.add(builtin, text="原本技能")
        notebook.add(wraps, text="可開關的 wrap")

        groups = grouped_builtin_tools()
        self.builtin_count = sum(len(items) for _, items in groups)
        bar = tk.Frame(builtin, bg=PANEL)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text=f"常開 {self.builtin_count} 個，服務在跑就能用。",
            bg=PANEL,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(side="left", padx=4)
        search_box = tk.Frame(bar, bg=LINE, padx=1, pady=1)
        search_box.pack(side="right")
        search = tk.Entry(
            search_box,
            textvariable=self.search_var,
            bg="#141a24",
            fg=FG,
            insertbackground=FG,
            relief="flat",
            font=(FONT, 11),
            width=28,
        )
        search.pack(ipady=7, ipadx=10)
        search.bind("<KeyRelease>", lambda _e: self._fill_tool_tree())
        tk.Label(bar, text="搜尋", bg=PANEL, fg=MUTED, font=(FONT, 10)).pack(side="right", padx=(0, 8))

        tree_wrap = tk.Frame(builtin, bg=PANEL)
        tree_wrap.pack(fill="both", expand=True, pady=(10, 0))
        self.tool_tree = ttk.Treeview(tree_wrap, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tool_tree.yview)
        self.tool_tree.configure(yscrollcommand=scroll.set)
        self.tool_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tool_tree.bind("<<TreeviewSelect>>", self._on_tool_select)
        desc_box = tk.Frame(builtin, bg="#141a24", highlightbackground=LINE, highlightthickness=1, padx=12, pady=10)
        desc_box.pack(fill="x", pady=(10, 0))
        self.tool_desc = tk.Label(
            desc_box,
            text="點一個工具看它做什麼。",
            bg="#141a24",
            fg=FG,
            justify="left",
            anchor="w",
            wraplength=980,
            font=(FONT, 10),
        )
        self.tool_desc.pack(fill="x")
        self._fill_tool_tree()

        tk.Label(wraps, text="這些開關要重啟才生效。1Password Connect 不在這條啟動路徑。", bg=PANEL, fg=MUTED).pack(anchor="w")
        toggles = tk.Frame(wraps, bg=PANEL)
        toggles.pack(fill="x", pady=(8, 4))
        ttk.Checkbutton(
            toggles,
            text="一次打開全部新包",
            variable=self.flag_vars["MCP_WRAP_ALL"],
            command=self._mark_custom,
        ).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(
            toggles,
            text="允許遠端呼叫桌面技能（危險）",
            variable=self.flag_vars["MCP_WRAP_ALLOW_REMOTE"],
            command=self._mark_custom,
        ).pack(side="left")

        grid = tk.Frame(wraps, bg=PANEL)
        grid.pack(fill="both", expand=True, pady=(8, 0))
        for index, (key, title, group, hint) in enumerate(SKILLS):
            card = tk.Frame(grid, bg=PANEL2, highlightbackground=LINE, highlightthickness=1)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
            grid.columnconfigure(index % 2, weight=1)
            stripe = ACCENT if group == "native" else BLUE
            tk.Frame(card, bg=stripe, width=4).pack(side="left", fill="y")
            body = tk.Frame(card, bg=PANEL2, padx=14, pady=12)
            body.pack(side="left", fill="both", expand=True)
            kind = "本機" if group == "native" else "子程序"
            tk.Label(body, text=kind, bg=PANEL2, fg=stripe, font=(FONT, 8, "bold")).pack(anchor="w")
            tk.Checkbutton(
                body,
                text=title,
                variable=self.flag_vars[key],
                command=self._mark_custom,
                bg=PANEL2,
                fg=FG,
                activebackground=PANEL2,
                activeforeground=FG,
                selectcolor="#10141c",
                font=(FONT, 12, "bold"),
                anchor="w",
                cursor="hand2",
            ).pack(anchor="w", pady=(6, 2))
            tk.Label(body, text=hint, bg=PANEL2, fg=MUTED, font=(FONT, 9), wraplength=430, justify="left").pack(anchor="w")

    def _fill_tool_tree(self) -> None:
        query = self.search_var.get().strip().lower()
        self.tool_tree.delete(*self.tool_tree.get_children())
        for title, items in grouped_builtin_tools():
            shown = []
            for name in items:
                desc = self.tool_details.get(name, "")
                if not query or query in name.lower() or query in title.lower() or query in desc.lower():
                    shown.append(name)
            if not shown:
                continue
            parent = self.tool_tree.insert("", "end", text=f"{title}    {len(shown)}", open=bool(query))
            for name in shown:
                self.tool_tree.insert(parent, "end", text=name, values=(name,))

    def _on_tool_select(self, _event=None) -> None:
        selected = self.tool_tree.selection()
        if not selected:
            return
        label = self.tool_tree.item(selected[0], "text")
        name = label.split()[0]
        desc = self.tool_details.get(name)
        if not desc:
            self.tool_desc.configure(text=label)
            return
        self.tool_desc.configure(text=f"{name}\n{desc}")

    def _build_logs(self, page: ttk.Frame) -> None:
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(0, 8))
        tk.Label(bar, text="過濾", bg=BG, fg=MUTED).pack(side="left")
        entry_box = tk.Frame(bar, bg=LINE, padx=1, pady=1)
        entry_box.pack(side="left", padx=8)
        entry = tk.Entry(
            entry_box,
            textvariable=self.log_filter_var,
            bg="#141a24",
            fg=FG,
            insertbackground=FG,
            relief="flat",
            font=("Cascadia Mono", 10),
            width=36,
        )
        entry.pack(ipady=6, ipadx=8)
        entry.bind("<KeyRelease>", lambda _e: self.refresh_logs())
        tk.Label(bar, text="只顯示含這段字的列。空白等於看全部。", bg=BG, fg=MUTED).pack(side="left")

        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True)
        out_frame, self.log_out = self._log_box(notebook)
        err_frame, self.log_err = self._log_box(notebook)
        act_frame, self.log_act = self._log_box(notebook)
        notebook.add(out_frame, text="HTTP 輸出")
        notebook.add(err_frame, text="HTTP 錯誤")
        notebook.add(act_frame, text="控制台動作")

    def _log_box(self, parent: tk.Widget) -> tuple[ttk.Frame, tk.Text]:
        frame = ttk.Frame(parent, style="Card.TFrame")
        text = tk.Text(
            frame,
            bg="#121820",
            fg="#d5deea",
            insertbackground=FG,
            relief="flat",
            font=("Cascadia Mono", 10),
            wrap="word",
            padx=8,
            pady=8,
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return frame, text

    def _select_mode(self, mode: str) -> None:
        if self._loading:
            return
        self.mode_var.set(mode)
        if mode != "custom":
            self._apply_flags_to_ui(mode, default_flags(mode), keep_mode=True)
        self._paint_modes()

    def _paint_modes(self) -> None:
        current = self.mode_var.get()
        for value, parts in self.mode_buttons.items():
            selected = value == current
            bg = ACCENT_SOFT if selected else PANEL2
            edge = ACCENT if selected else LINE
            parts["frame"].configure(bg=bg, highlightbackground=edge)
            parts["title"].configure(bg=bg, fg="#eafff4" if selected else FG)
            parts["hint"].configure(bg=bg, fg="#d7efe4" if selected else MUTED)

    def _mark_custom(self) -> None:
        if self._loading:
            return
        self.mode_var.set("custom")
        self._paint_modes()

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
        self._paint_modes()

    def current_flags(self) -> dict[str, str]:
        mode = self.mode_var.get()
        if mode == "full":
            return default_flags("full")
        if mode == "core":
            return default_flags("core")
        if mode == "local":
            return default_flags("local")
        return {key: ("1" if var.get() else "0") for key, var in self.flag_vars.items()}

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        self.footer.configure(text=text or ("工作中…" if busy else "就緒"))

    def log_action(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_act.configure(state="normal")
        self.log_act.insert("end", f"[{stamp}] {text}\n")
        self.log_act.see("end")

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
        if self._status_job:
            self.after_cancel(self._status_job)
            self._status_job = None
        if not self._status_running:
            self._status_running = True
            threading.Thread(target=self._status_worker, daemon=True).start()
        self._status_job = self.after(4000, self.refresh_status)

    def _status_worker(self) -> None:
        try:
            ok, payload = fetch_json(HEALTH_URL)
            public_ok, public_payload = fetch_json(PUBLIC_HEALTH_URL, timeout=3.0)
            snapshot = {
                "ok": ok,
                "payload": payload,
                "public_ok": public_ok,
                "public_payload": public_payload,
                "pid": read_pid(),
                "cf_count": cloudflared_count(),
                "task_state": login_task_state(),
                "live": parse_launcher_flags(),
            }
        except Exception as exc:
            snapshot = {"error": str(exc)}
        self.after(0, lambda: self._apply_status(snapshot))

    def _apply_status(self, snapshot: dict) -> None:
        self._status_running = False
        if snapshot.get("error"):
            self.power_chip.configure(text="  狀態失敗  ", bg="#3a2428", fg=DANGER)
            return
        ok = bool(snapshot["ok"])
        payload = snapshot["payload"]
        pid = snapshot["pid"]
        live = snapshot["live"] or {}
        wanted = self.current_flags()
        pending = bool(live) and live != wanted
        auth = (payload.get("auth") or {}) if ok and isinstance(payload, dict) else {}
        descope = bool(auth.get("descope_enabled"))
        oauth_mode = str(auth.get("oauth_mode") or "—")
        if ok:
            self.power_chip.configure(text="  運轉中  ", bg="#163528", fg=ACCENT)
            self.metrics["http"][0].configure(text="正常", fg=ACCENT)
            self.metrics["http"][1].configure(text=f"PID {pid}" if pid else "本機服務")
        else:
            self.power_chip.configure(text="  已關機  ", bg="#3a2428", fg=DANGER)
            self.metrics["http"][0].configure(text="關機", fg=DANGER)
            self.metrics["http"][1].configure(text=str(payload)[:80])
        self.metrics["public"][0].configure(
            text="可連" if snapshot["public_ok"] else "連不到",
            fg=ACCENT if snapshot["public_ok"] else WARN,
        )
        self.metrics["public"][1].configure(text="mcp.edgars.tools")
        cf_count = snapshot["cf_count"]
        self.metrics["tunnel"][0].configure(text=f"{cf_count} 個", fg=ACCENT if cf_count else WARN)
        self.metrics["tunnel"][1].configure(text="正式 tunnel 不由這裡關閉")
        task_state = snapshot["task_state"]
        task_ok = task_state.lower() in {"ready", "running"}
        self.metrics["task"][0].configure(text=task_state or "—", fg=ACCENT if task_ok else WARN)
        self.metrics["task"][1].configure(text=LOGIN_TASK)

        wrap_all = _on(live.get("MCP_WRAP_ALL")) if live else False
        enabled = []
        if live:
            enabled = ["全部新包"] if wrap_all else [title for key, title, _, _ in SKILLS if _on(live.get(key))]
            if _on(live.get("MCP_WRAP_ALLOW_REMOTE")):
                enabled.append("允許遠端桌面")
        lines = [
            f"授權    {'Descope 開' if descope else 'Descope 關'}    {oauth_mode}",
            f"原本技能    {getattr(self, 'builtin_count', 0)} 個常開",
            f"目前模式    {infer_mode(live) if live else '尚未寫入 launcher'}",
            f"已開 wrap    {'、'.join(enabled) if enabled else '無'}",
            f"套用狀態    {'勾選還沒寫進正在跑的服務' if pending else '跟畫面一致'}",
        ]
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", "\n\n".join(lines))
        self.summary.configure(state="disabled")

    def refresh_logs(self) -> None:
        needle = self.log_filter_var.get().strip().lower()
        self._set_log(self.log_out, self._filter_log(tail_file(OUT_LOG), needle))
        self._set_log(self.log_err, self._filter_log(tail_file(ERR_LOG), needle))
        if self._log_job:
            self.after_cancel(self._log_job)
        self._log_job = self.after(2500, self.refresh_logs)

    def _filter_log(self, text: str, needle: str) -> str:
        if not needle:
            return text
        lines = [line for line in text.splitlines() if needle in line.lower()]
        return "\n".join(lines) if lines else f"（沒有含「{needle}」的列）"

    def _set_log(self, widget: tk.Text, text: str) -> None:
        at_end = float(widget.yview()[1]) >= 0.95
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if at_end:
            widget.see("end")

    def open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(LOG_DIR))

    def run_action(self, action: str) -> None:
        if self.busy:
            messagebox.showinfo("請稍候", "上一個動作還在跑。")
            return
        if action in {"start", "apply", "start_core"}:
            if action == "start_core":
                self.mode_var.set("core")
                self._apply_flags_to_ui("core", default_flags("core"), keep_mode=True)
            save_profile(self.mode_var.get(), self.current_flags())
        labels = {
            "start": "開始啟動（含 wrap）",
            "start_core": "開始啟動（只開核心）",
            "stop": "開始關閉",
            "apply": "套用技能並重啟",
        }
        self.set_busy(True, "關閉中…" if action == "stop" else "啟動中…")
        self.show_page("logs")
        self.log_action(labels[action])
        threading.Thread(target=self._worker, args=(action,), daemon=True).start()

    def _worker(self, action: str) -> None:
        try:
            if action == "stop":
                code, output = run_ps1(STOP_PS1, ["-Force"])
            elif action == "start_core":
                code, output = run_ps1(START_MCP_PS1, ["-SkipCloudflared", "-Force"])
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
