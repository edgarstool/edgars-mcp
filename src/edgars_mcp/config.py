"""Cross-platform configuration for Edgar's MCP.

Source code stays immutable. Every mutable data class can be redirected with
an environment variable and otherwise defaults below ``~/runtime/edgars-mcp``.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
from typing import Mapping


VISIBLE_BROWSER_TOOL_NAMES = {
    "browser_visible_open",
    "browser_visible_navigate",
    "browser_visible_click",
    "browser_visible_type",
    "browser_visible_screenshot",
    "browser_visible_close",
}


def _path_from_env(env: Mapping[str, str], name: str, default: Path) -> Path:
    raw = env.get(name, "").strip()
    return Path(raw).expanduser() if raw else default


@dataclass(frozen=True)
class RuntimePaths:
    """Locations for mutable runtime data."""

    root: Path
    run: Path
    state: Path
    logs: Path
    cache: Path
    tmp: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RuntimePaths":
        values = os.environ if env is None else env
        root = _path_from_env(
            values,
            "EDGARS_MCP_RUNTIME_DIR",
            Path.home() / "runtime" / "edgars-mcp",
        )
        return cls(
            root=root,
            run=_path_from_env(values, "EDGARS_MCP_RUN_DIR", root / "run"),
            state=_path_from_env(values, "EDGARS_MCP_STATE_DIR", root / "state"),
            logs=_path_from_env(values, "EDGARS_MCP_LOG_DIR", root / "logs"),
            cache=_path_from_env(values, "EDGARS_MCP_CACHE_DIR", root / "cache"),
            tmp=_path_from_env(values, "EDGARS_MCP_TMP_DIR", root / "tmp"),
        )

    def ensure(self) -> None:
        for directory in (self.root, self.run, self.state, self.logs, self.cache, self.tmp):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "run": str(self.run),
            "state": str(self.state),
            "logs": str(self.logs),
            "cache": str(self.cache),
            "tmp": str(self.tmp),
        }


def tool_capability(
    tool_name: str,
    *,
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return an operator-readable availability result for a tool."""

    current_platform = platform_name or platform.system()
    current_env = os.environ if env is None else env
    has_display = bool(current_env.get("DISPLAY") or current_env.get("WAYLAND_DISPLAY"))

    if tool_name in VISIBLE_BROWSER_TOOL_NAMES and current_platform != "Windows" and not has_display:
        return {
            "status": "unavailable",
            "available": False,
            "reason": "visible browser requires a desktop display",
        }

    return {"status": "available", "available": True, "reason": ""}
