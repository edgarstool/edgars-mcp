"""Native full-surface wrappers for non-stdio projects.

Default is off via MCP_WRAP_* flags. Enabled sources expose the complete
command/tool surface, not a reduced subset.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from mcp_upstreams import (
    UpstreamError,
    builtin_upstream_specs,
    call_upstream_tool,
    fetch_prefixed_upstream_tools,
    match_upstream,
    wrap_all_enabled,
    wrap_allow_remote,
)


PROJECTS = Path(r"V:\projects")
CLOUDFLARED_DIR = PROJECTS / "cloudflared"
OPENMONTAGE_DIR = PROJECTS / "OpenMontage"
DESCOPE_SRC = PROJECTS / "descope-mcp" / "python" / "src"

HERMES_KNOWN = [
    r"C:\Users\EdgarsTool\AppData\Local\EdgarOS\bin\hermes.cmd",
    r"C:\Users\EdgarsTool\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe",
]
FLEET_SCRIPT = Path(r"G:\AI_WORK_512\bin\edgar-fleet.ps1")

OPENCLAW_KNOWN = [
    r"C:\Users\EdgarsTool\AppData\Roaming\npm\openclaw.cmd",
    r"C:\Users\EdgarsTool\AppData\Local\EdgarOS\bin\openclaw.cmd",
]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_cli(name: str, env_name: str, known: list[str]) -> str:
    override = os.getenv(env_name, "").strip()
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        found = shutil.which(f"{name}.cmd")
        if found:
            return found
    for path in known:
        if os.path.isfile(path):
            return path
    return name


def _enabled(flag: str) -> bool:
    return wrap_all_enabled() or _env_bool(flag, False)


def _auth_kind() -> str:
    try:
        import server_http
        return server_http._mcp_auth_kind.get("unknown")
    except Exception:
        return "unknown"


def _local_permitted(local_only: bool) -> bool:
    if not local_only or wrap_allow_remote():
        return True
    return _auth_kind() in {"none", "static", "cf_access", "unknown"}


_SECRET_LINE_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization|credential|private[_-]?key)"
)


def _redact_secret_text(text: str) -> str:
    redacted: list[str] = []
    for line in str(text or "").splitlines():
        if _SECRET_LINE_RE.search(line) and (":" in line or "=" in line):
            key = line.split(":", 1)[0].split("=", 1)[0]
            redacted.append(f"{key}: [redacted]")
        else:
            redacted.append(line)
    return "\n".join(redacted)


def _redact_run_output(response: dict) -> dict:
    payload = response.get("structuredContent")
    if not isinstance(payload, dict) or not isinstance(payload.get("output"), str):
        return response
    cleaned = dict(payload)
    cleaned["output"] = _redact_secret_text(str(payload.get("output") or ""))
    return _json(cleaned, is_error=bool(response.get("isError")))


def _text(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _json(data: dict, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
        "structuredContent": data,
        "isError": is_error,
    }


def _run(argv: list[str], *, cwd: str | None = None, timeout: int = 120, env: dict | None = None) -> dict:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env=merged,
            shell=False,
        )
    except FileNotFoundError:
        return _text(f"command not found: {argv[0]}", is_error=True)
    except subprocess.TimeoutExpired:
        return _text(f"timed out after {timeout}s: {' '.join(argv[:6])}", is_error=True)
    output = ((result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")).strip()
    if len(output) > 24000:
        output = output[:24000] + "\n[truncated]"
    return _json({
        "argv": argv,
        "cwd": cwd,
        "exit_code": result.returncode,
        "output": output or "(no output)",
    }, is_error=result.returncode != 0)


def _run_fleet(argv: list[str], *, timeout: int = 180) -> dict:
    """Run the fixed fleet dispatcher without leaking its local argv contract."""
    response = _run(argv, timeout=timeout)
    payload = response.get("structuredContent")
    if not isinstance(payload, dict):
        return response
    safe_payload = dict(payload)
    safe_payload.pop("argv", None)
    output = safe_payload.get("output")
    if isinstance(output, str):
        try:
            safe_payload["result"] = json.loads(output)
        except (TypeError, ValueError):
            # Keep the bounded textual output for diagnostics when the
            # dispatcher fails before it can emit JSON.
            pass
    return _json(safe_payload, is_error=bool(response.get("isError")))


def _as_argv(arguments: dict) -> list[str]:
    raw = arguments.get("args")
    if isinstance(raw, str) and raw.strip():
        return [part for part in raw.split(" ") if part]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    command = str(arguments.get("command") or "").strip()
    extra = arguments.get("extra")
    argv = [command] if command else []
    if isinstance(extra, list):
        argv.extend(str(item) for item in extra)
    return [item for item in argv if item]


def _tool(
    name: str,
    description: str,
    properties: dict,
    required: list[str] | None = None,
    *,
    read_only: bool = False,
    destructive: bool = False,
) -> dict:
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {
        "name": name,
        "description": description,
        "inputSchema": schema,
        "annotations": {
            "readOnlyHint": read_only,
            "openWorldHint": not read_only,
            "destructiveHint": destructive,
        },
    }


def hermes_cmd() -> str:
    return _resolve_cli("hermes", "HERMES_CMD", HERMES_KNOWN)


def openclaw_cmd() -> str:
    return _resolve_cli("openclaw", "OPENCLAW_CMD", OPENCLAW_KNOWN)


def cloudflared_cmd() -> str:
    return _resolve_cli("cloudflared", "CLOUDFLARED_CMD", [
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
    ])


NATIVE_FLAG = {
    "cloudflared": "MCP_WRAP_CLOUDFLARED",
    "openmontage": "MCP_WRAP_OPENMONTAGE",
    "hermes": "MCP_WRAP_HERMES",
    "openclaw": "MCP_WRAP_OPENCLAW",
    "descope": "MCP_WRAP_DESCOPE",
    "fleet": "MCP_WRAP_FLEET",
}


def wrap_catalog_payload() -> dict:
    sources = []
    for spec in builtin_upstream_specs():
        sources.append({
            "id": spec.id,
            "prefix": spec.prefix,
            "title": spec.title,
            "enabled": spec.enabled(),
            "local_only": spec.local_only,
            "status": "enabled" if spec.enabled() else "disabled",
            "tool_count": None,
            "enable_env": spec.env_flag,
        })
    for native_id, flag in NATIVE_FLAG.items():
        sources.append({
            "id": native_id,
            "prefix": native_id + "_",
            "title": native_id,
            "enabled": _enabled(flag),
            "local_only": native_id in {"cloudflared", "openmontage", "hermes", "openclaw"},
            "status": "enabled" if _enabled(flag) else "disabled",
            "tool_count": None,
            "enable_env": flag,
        })
    return {
        "default": "off",
        "wrap_all": wrap_all_enabled(),
        "allow_remote": wrap_allow_remote(),
        "enable_all_env": "MCP_WRAP_ALL=1",
        "allow_remote_env": "MCP_WRAP_ALLOW_REMOTE=1",
        "sources": sources,
        "note": "Full surfaces are registered when enabled. Nothing is stripped; disabled sources stay off until you turn them on.",
    }


def _descope_native_tools() -> list[dict]:
    if not _enabled("MCP_WRAP_DESCOPE"):
        return []
    return [
        _tool(
            "descope__fetch_user_token_by_scopes",
            "[Descope SDK] Fetch user token with specific scopes.",
            {
                "app_id": {"type": "string"},
                "user_id": {"type": "string"},
                "scopes": {"type": "array", "items": {"type": "string"}},
                "tenant_id": {"type": "string"},
                "options": {"type": "object"},
            },
            ["app_id", "user_id", "scopes"],
        ),
        _tool(
            "descope__fetch_user_token",
            "[Descope SDK] Fetch latest user token.",
            {
                "app_id": {"type": "string"},
                "user_id": {"type": "string"},
                "tenant_id": {"type": "string"},
                "options": {"type": "object"},
            },
            ["app_id", "user_id"],
        ),
        _tool(
            "descope__fetch_tenant_token_by_scopes",
            "[Descope SDK] Fetch tenant token with specific scopes.",
            {
                "app_id": {"type": "string"},
                "tenant_id": {"type": "string"},
                "scopes": {"type": "array", "items": {"type": "string"}},
                "options": {"type": "object"},
            },
            ["app_id", "tenant_id", "scopes"],
        ),
        _tool(
            "descope__fetch_tenant_token",
            "[Descope SDK] Fetch latest tenant token.",
            {
                "app_id": {"type": "string"},
                "tenant_id": {"type": "string"},
                "options": {"type": "object"},
            },
            ["app_id", "tenant_id"],
        ),
        _tool(
            "descope__validate_token",
            "[Descope SDK] Validate an MCP access token and return claims (no secret material logged).",
            {"token": {"type": "string"}},
            ["token"],
            read_only=True,
        ),
        _tool(
            "descope__get_connection_token",
            "[Descope SDK] Fetch a stored outbound connection token.",
            {
                "user_id": {"type": "string"},
                "app_id": {"type": "string"},
                "scopes": {"type": "array", "items": {"type": "string"}},
                "access_token": {"type": "string"},
            },
            ["user_id", "app_id"],
        ),
        _tool(
            "descope__sdk_status",
            "[Descope SDK] Report whether the local descope-mcp SDK can load. Does not print secrets.",
            {},
            read_only=True,
        ),
    ]


def _cloudflared_tools() -> list[dict]:
    if not _enabled("MCP_WRAP_CLOUDFLARED"):
        return []
    args_prop = {"args": {"type": "array", "items": {"type": "string"}, "description": "cloudflared argv after the binary"}}
    return [
        _tool("cloudflared_cli", "[cloudflared] Full CLI passthrough. Pass the complete argument list.", args_prop, ["args"], destructive=True),
        _tool("cloudflared_status", "[cloudflared] Process + tunnel info.", {}, read_only=True),
        _tool("cloudflared_version", "[cloudflared] Version string.", {}, read_only=True),
        _tool("cloudflared_list", "[cloudflared] List tunnels.", {}, read_only=True),
        _tool("cloudflared_info", "[cloudflared] tunnel info for a name or id.", {"name": {"type": "string", "description": "Tunnel name or UUID"}}, ["name"], read_only=True),
        _tool("cloudflared_start", "[cloudflared] Start `cloudflared tunnel run <name>`.", {"name": {"type": "string", "description": "Tunnel name (default edgar-local-01-tunnel)"}}),
        _tool("cloudflared_stop", "[cloudflared] Stop cloudflared.exe processes.", {}, destructive=True),
        _tool("cloudflared_restart", "[cloudflared] Stop then start.", {"name": {"type": "string"}}, destructive=True),
        _tool("cloudflared_verify", "[cloudflared] Run scripts/verify-all.cmd when present, else tunnel info + process check.", {}, read_only=True),
        _tool("cloudflared_add_service", "[cloudflared] Run scripts/add-service.cmd with extra args.", args_prop, destructive=True),
        _tool("cloudflared_ddns_update", "[cloudflared] Run scripts/ddns-update.ps1.", args_prop, destructive=True),
    ]


def _hermes_tools() -> list[dict]:
    if not _enabled("MCP_WRAP_HERMES"):
        return []
    return [
        _tool(
            "hermes_cli",
            "[Hermes] Full Hermes CLI passthrough. Pass subcommand args, e.g. [\"status\"] or [\"mcp\", \"list\"].",
            {"args": {"type": "array", "items": {"type": "string"}}, "timeout_seconds": {"type": "integer"}},
            ["args"],
            destructive=True,
        ),
        _tool(
            "hermes_agent",
            "[Hermes] Full non-interactive agent turn (`hermes -z --cli`). All CLI flags are available.",
            {
                "task": {"type": "string"},
                "working_dir": {"type": "string"},
                "model": {"type": "string"},
                "provider": {"type": "string"},
                "reasoning": {"type": "string"},
                "skills": {"type": "string"},
                "yolo": {"type": "boolean", "description": "Maps to --yolo."},
                "resume": {"type": "string", "description": "Maps to --resume/-r. Use latest for the newest session."},
                "continue": {"type": "string", "description": "Maps to --continue/-c session name."},
                "toolsets": {"type": "string", "description": "Maps to -t/--toolsets."},
                "accept_hooks": {"type": "boolean", "description": "Maps to --accept-hooks."},
                "worktree": {"type": "boolean", "description": "Maps to --worktree."},
                "ignore_rules": {"type": "boolean", "description": "Maps to --ignore-rules."},
                "extra_args": {"type": "array", "items": {"type": "string"}},
                "async": {"type": "boolean"},
                "timeout_seconds": {"type": "integer"},
            },
            ["task"],
            destructive=True,
        ),
        _tool("hermes_status", "[Hermes] `hermes status`.", {}, read_only=True),
        _tool("hermes_version", "[Hermes] `hermes --version`.", {}, read_only=True),
        _tool("hermes_doctor", "[Hermes] `hermes doctor`.", {}, read_only=True),
        _tool("hermes_sessions_list", "[Hermes] `hermes sessions list`. Lists recent sessions. Read-only.", {}, read_only=True),
        _tool("hermes_skills_list", "[Hermes] `hermes skills list`. Lists installed skills. Read-only.", {}, read_only=True),
        _tool("hermes_mcp_list", "[Hermes] `hermes mcp list`. Lists configured MCP servers. Read-only.", {}, read_only=True),
        _tool("hermes_memory_status", "[Hermes] `hermes memory status`. Shows the external memory provider. Read-only.", {}, read_only=True),
        _tool(
            "hermes_config_show",
            "[Hermes] `hermes config show`. Secret-like values are redacted before the result is returned.",
            {},
            read_only=True,
        ),
        _tool(
            "hermes_logs",
            "[Hermes] `hermes logs` tail. Does not follow. log_name is agent, errors, gateway, gui, desktop, update, handoff, or list. Flags: -n/--lines, --since, --level, --component.",
            {
                "log_name": {
                    "type": "string",
                    "enum": ["agent", "errors", "gateway", "gui", "desktop", "update", "handoff", "list"],
                },
                "lines": {"type": "integer", "description": "Maps to -n/--lines. Default 50, max 500."},
                "since": {"type": "string", "description": "Maps to --since, for example 30m, 1h, or 2d."},
                "level": {"type": "string", "enum": ["DEBUG", "INFO", "WARNING", "ERROR"]},
                "component": {"type": "string", "enum": ["gateway", "agent", "tools", "cli", "cron", "gui"]},
            },
            read_only=True,
        ),
        _tool("hermes_gateway_status", "[Hermes] `hermes gateway status`. Read-only.", {}, read_only=True),
        _tool("hermes_usage", "[Hermes] `hermes usage`. Rate-limit windows without starting a session. Read-only.", {}, read_only=True),
    ]


def _openclaw_tools() -> list[dict]:
    if not _enabled("MCP_WRAP_OPENCLAW"):
        return []
    return [
        _tool(
            "openclaw_cli",
            "[OpenClaw] Full OpenClaw CLI passthrough. Pass subcommand args, e.g. [\"status\", \"--json\"].",
            {"args": {"type": "array", "items": {"type": "string"}}, "timeout_seconds": {"type": "integer"}},
            ["args"],
            destructive=True,
        ),
        _tool(
            "openclaw_agent",
            "[OpenClaw] Full agent turn (`openclaw agent`). All documented flags are available.",
            {
                "task": {"type": "string"},
                "message": {"type": "string"},
                "working_dir": {"type": "string"},
                "agent": {"type": "string"},
                "model": {"type": "string"},
                "local": {"type": "boolean"},
                "json": {"type": "boolean"},
                "session_id": {"type": "string"},
                "session_key": {"type": "string"},
                "thinking": {
                    "type": "string",
                    "enum": ["off", "minimal", "low", "medium", "high", "xhigh", "adaptive", "max", "ultra"],
                    "description": "Maps to --thinking.",
                },
                "verbose": {"type": "string", "enum": ["on", "off"], "description": "Maps to --verbose."},
                "message_file": {"type": "string", "description": "Maps to --message-file. When set, task/message is not also sent."},
                "turn_timeout": {"type": "integer", "description": "Maps to --timeout seconds."},
                "extra_args": {"type": "array", "items": {"type": "string"}},
                "async": {"type": "boolean"},
                "timeout_seconds": {"type": "integer"},
            },
            ["task"],
            destructive=True,
        ),
        _tool("openclaw_status", "[OpenClaw] `openclaw status --json`.", {}, read_only=True),
        _tool("openclaw_version", "[OpenClaw] `openclaw --version`.", {}, read_only=True),
        _tool("openclaw_health", "[OpenClaw] `openclaw status --all --json`.", {}, read_only=True),
        _tool("openclaw_doctor", "[OpenClaw] `openclaw doctor --json`. Read-only advisory report. Does not pass --fix.", {}, read_only=True),
        _tool(
            "openclaw_gateway_status",
            "[OpenClaw] `openclaw gateway status --json`. Includes the connectivity probe unless no_probe=true (`--no-probe`). Does not accept token or password arguments.",
            {"no_probe": {"type": "boolean"}},
            read_only=True,
        ),
        _tool("openclaw_gateway_health", "[OpenClaw] `openclaw health --json`. Live health probe. Read-only.", {}, read_only=True),
        _tool(
            "openclaw_channels",
            "[OpenClaw] `openclaw channels list --json`. all=true maps to --all.",
            {"all": {"type": "boolean"}},
            read_only=True,
        ),
        _tool(
            "openclaw_sessions",
            "[OpenClaw] `openclaw sessions --json`. Optional --agent, --limit (integer or all), and --active minutes.",
            {
                "agent": {"type": "string"},
                "limit": {"type": "string", "description": "Integer or all. Maps to --limit."},
                "active_minutes": {"type": "integer", "description": "Maps to --active."},
            },
            read_only=True,
        ),
        _tool(
            "openclaw_mcp_doctor",
            "[OpenClaw] `openclaw mcp doctor --json`. Optional server name. probe=true adds --probe.",
            {
                "name": {"type": "string"},
                "probe": {"type": "boolean"},
            },
            read_only=True,
        ),
    ]


def _openmontage_tools() -> list[dict]:
    if not _enabled("MCP_WRAP_OPENMONTAGE"):
        return []
    tools = [
        _tool("om__status", "[OpenMontage] Registry + pipeline discovery status.", {}, read_only=True),
        _tool("om__list_pipelines", "[OpenMontage] List pipeline_defs YAML files.", {}, read_only=True),
        _tool("om__read_pipeline", "[OpenMontage] Read a pipeline YAML by stem name.", {"name": {"type": "string"}}, ["name"], read_only=True),
        _tool(
            "om__execute",
            "[OpenMontage] Execute any registered tool by name with its full input dict.",
            {
                "tool": {"type": "string"},
                "inputs": {"type": "object"},
                "dry_run": {"type": "boolean"},
            },
            ["tool"],
            destructive=True,
        ),
        _tool("om__dry_run", "[OpenMontage] Dry-run any registered tool.", {"tool": {"type": "string"}, "inputs": {"type": "object"}}, ["tool"], read_only=True),
    ]
    try:
        for item in _openmontage_registry_descriptors():
            tools.append(item)
    except Exception as exc:
        tools.append(_tool(
            "om__registry_error",
            f"[OpenMontage] Registry discovery failed: {exc}. om__execute still tries a named import.",
            {},
            read_only=True,
        ))
    return tools


def _openmontage_registry():
    if str(OPENMONTAGE_DIR) not in sys.path:
        sys.path.insert(0, str(OPENMONTAGE_DIR))
    from tools.tool_registry import ToolRegistry
    registry = ToolRegistry()
    registry.ensure_discovered("tools")
    return registry


_OM_NAME_RE = re.compile(r'^\s+name\s*=\s*["\']([A-Za-z0-9_]+)["\']', re.M)
_OM_BASE_RE = re.compile(r"class\s+\w+\(\s*BaseTool\s*\)")


def _openmontage_ast_names() -> list[str]:
    tools_dir = OPENMONTAGE_DIR / "tools"
    names: list[str] = []
    for path in tools_dir.rglob("*.py"):
        if path.name.startswith("_") or path.name in {"base_tool.py", "tool_registry.py"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _OM_BASE_RE.search(text):
            continue
        names.extend(_OM_NAME_RE.findall(text))
    return sorted(set(names))


def _openmontage_registry_descriptors() -> list[dict]:
    names = _openmontage_ast_names()
    if not names:
        raise RuntimeError("OpenMontage tool discovery found no BaseTool names")
    descriptors = []
    for name in names:
        descriptors.append(_tool(
            f"om__{name}",
            f"[OpenMontage] {name}. Call this tool or om__execute with the real BaseTool inputs.",
            {"inputs": {"type": "object"}},
            destructive=True,
        ))
    return descriptors


def catalog_tool_descriptor() -> dict:
    return _tool(
        "wrap_catalog",
        "List every wrapped source (Playwright, Kapture, Windows-MCP, Desktop Commander, Descope, cloudflared, OpenMontage, Hermes, OpenClaw, Fleet). Default is off; this catalog is always visible.",
        {},
        read_only=True,
    )


def list_wrap_tools() -> list[dict]:
    tools = [catalog_tool_descriptor()]
    for spec in builtin_upstream_specs():
        prefixed, _status = fetch_prefixed_upstream_tools(spec)
        tools.extend(prefixed)
    tools.extend(_descope_native_tools())
    tools.extend(_cloudflared_tools())
    tools.extend(_openmontage_tools())
    tools.extend(_hermes_tools())
    tools.extend(_openclaw_tools())
    tools.extend(_fleet_tools())
    return tools



def _fleet_tools() -> list[dict]:
    if not _enabled("MCP_WRAP_FLEET"):
        return []
    direct_target = {
        "type": "string",
        "enum": ["all", "kamatera", "ovh-main", "ovh-sidecar", "azure"],
        "description": "Allowed fleet target.",
    }
    dispatch_target = {
        "type": "string",
        "enum": ["auto", "all", "kamatera", "ovh-main", "ovh-sidecar", "azure"],
        "description": "Allowed fleet target. auto performs a fresh bounded route before dispatch.",
    }
    task_type = {
        "type": "string",
        "enum": ["general", "website-audit", "event", "lightweight"],
        "default": "general",
        "description": "Bounded routing class used by fleet_route and fleet_dispatch target=auto.",
    }
    return [
        _tool(
            "fleet_health",
            "[EDGAR Fleet] Check one allowed worker target or the whole fleet.",
            {"target": direct_target},
            read_only=True,
        ),
        _tool(
            "fleet_benchmark",
            "[EDGAR Fleet] Run the bounded benchmark contract on one allowed target or the whole fleet.",
            {"target": direct_target},
            read_only=True,
        ),
        _tool(
            "fleet_route",
            "[EDGAR Fleet] Read-only live route decision with health, capacity checks, finite OVH-credit guard, ordered fallbacks, and reason.",
            {"task_type": task_type},
            read_only=True,
        ),
        _tool(
            "fleet_dispatch",
            "[EDGAR Fleet] Dispatch a bounded text canary/task message. target=auto performs a fresh route. No shell/argv input or local argv output is exposed.",
            {
                "target": dispatch_target,
                "task_type": task_type,
                "message": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                    "description": "Plain text task/canary message; not a shell command.",
                },
            },
            ["target", "message"],
        ),
    ]


def _handle_fleet(name: str, arguments: dict) -> dict:
    allowed_targets = {"all", "auto", "kamatera", "ovh-main", "ovh-sidecar", "azure"}
    target = str(arguments.get("target") or ("auto" if name == "fleet_route" else "all")).strip()
    if target not in allowed_targets:
        return _text(f"invalid fleet target: {target}", is_error=True)
    if target == "auto" and name not in {"fleet_dispatch", "fleet_route"}:
        return _text("fleet target auto is only supported by fleet_dispatch or fleet_route", is_error=True)
    task_type = str(arguments.get("task_type") or "general").strip()
    allowed_task_types = {"general", "website-audit", "event", "lightweight"}
    if task_type not in allowed_task_types:
        return _text(f"invalid fleet task_type: {task_type}", is_error=True)
    if not FLEET_SCRIPT.is_file():
        return _text(f"fleet dispatcher missing: {FLEET_SCRIPT}", is_error=True)

    action_by_tool = {
        "fleet_health": "health",
        "fleet_benchmark": "benchmark",
        "fleet_route": "route",
        "fleet_dispatch": "dispatch",
    }
    action = action_by_tool.get(name)
    if not action:
        return _text(f"unknown fleet tool: {name}", is_error=True)

    argv = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(FLEET_SCRIPT),
        "-Target",
        target,
        "-Action",
        action,
    ]
    if action in {"route", "dispatch"}:
        argv.extend(["-TaskType", task_type])
    if action == "dispatch":
        message = str(arguments.get("message") or "").strip()
        if not message:
            return _text("fleet_dispatch requires a non-empty message", is_error=True)
        if len(message) > 1000:
            return _text("fleet_dispatch message exceeds 1000 characters", is_error=True)
        argv.extend(["-Message", message])

    return _run_fleet(argv, timeout=180)

def _handle_descope(name: str, arguments: dict) -> dict:
    if name == "descope__sdk_status":
        src_ok = DESCOPE_SRC.is_dir()
        loaded = False
        error = ""
        if src_ok:
            try:
                if str(DESCOPE_SRC) not in sys.path:
                    sys.path.insert(0, str(DESCOPE_SRC))
                import descope_mcp
                loaded = True
                version = getattr(descope_mcp, "__version__", "unknown")
            except Exception as exc:
                version = "unloadable"
                error = str(exc)
        else:
            version = "missing"
        return _json({
            "src": str(DESCOPE_SRC),
            "src_exists": src_ok,
            "loaded": loaded,
            "version": version,
            "well_known_configured": bool(os.getenv("DESCOPE_MCP_WELL_KNOWN_URL", "").strip()),
            "management_key_configured": bool(os.getenv("DESCOPE_MANAGEMENT_KEY", "").strip()),
            "error": error,
        }, is_error=not loaded)
    if str(DESCOPE_SRC) not in sys.path:
        sys.path.insert(0, str(DESCOPE_SRC))
    from descope_mcp import (
        DescopeConfig,
        fetch_tenant_token,
        fetch_tenant_token_by_scopes,
        fetch_user_token,
        fetch_user_token_by_scopes,
        get_connection_token,
        validate_token,
    )
    well_known = os.getenv("DESCOPE_MCP_WELL_KNOWN_URL", "").strip()
    management_key = os.getenv("DESCOPE_MANAGEMENT_KEY", "").strip() or None
    if not well_known:
        return _text("DESCOPE_MCP_WELL_KNOWN_URL is not set", is_error=True)
    config = DescopeConfig(well_known_url=well_known, management_key=management_key)

    async def _invoke(coro):
        import asyncio
        return await coro

    def _run_async(coro):
        import asyncio
        return asyncio.run(coro)

    try:
        if name == "descope__validate_token":
            result = validate_token(arguments.get("token", ""))
            if hasattr(result, "model_dump"):
                return _json(result.model_dump(mode="json"))
            return _json(dict(result) if isinstance(result, dict) else {"result": str(result)})
        if name == "descope__get_connection_token":
            token = get_connection_token(
                user_id=arguments.get("user_id"),
                app_id=arguments.get("app_id"),
                scopes=arguments.get("scopes") or [],
                access_token=arguments.get("access_token"),
            )
            return _json({"configured": True, "token_present": bool(token)})
        mapping = {
            "descope__fetch_user_token_by_scopes": lambda: fetch_user_token_by_scopes(
                config,
                arguments.get("app_id"),
                arguments.get("user_id"),
                arguments.get("scopes") or [],
                arguments.get("options"),
                arguments.get("tenant_id"),
            ),
            "descope__fetch_user_token": lambda: fetch_user_token(
                config,
                arguments.get("app_id"),
                arguments.get("user_id"),
                arguments.get("tenant_id"),
                arguments.get("options"),
            ),
            "descope__fetch_tenant_token_by_scopes": lambda: fetch_tenant_token_by_scopes(
                config,
                arguments.get("app_id"),
                arguments.get("tenant_id"),
                arguments.get("scopes") or [],
                arguments.get("options"),
            ),
            "descope__fetch_tenant_token": lambda: fetch_tenant_token(
                config,
                arguments.get("app_id"),
                arguments.get("tenant_id"),
                arguments.get("options"),
            ),
        }
        factory = mapping.get(name)
        if factory is None:
            return _text(f"Unknown Descope tool: {name}", is_error=True)
        result = _run_async(factory())
        if isinstance(result, str):
            try:
                return _json(json.loads(result))
            except json.JSONDecodeError:
                return _text(result)
        return _json(result if isinstance(result, dict) else {"result": result})
    except Exception as exc:
        return _text(f"Descope SDK error: {exc}", is_error=True)


def _handle_cloudflared(name: str, arguments: dict) -> dict:
    binary = cloudflared_cmd()
    if name == "cloudflared_cli":
        return _run([binary, *_as_argv(arguments)])
    if name == "cloudflared_version":
        return _run([binary, "--version"])
    if name == "cloudflared_list":
        return _run([binary, "tunnel", "list"])
    if name == "cloudflared_info":
        return _run([binary, "tunnel", "info", str(arguments.get("name") or "")])
    if name == "cloudflared_status":
        version = _run([binary, "--version"], timeout=10)
        procs = _run(["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV", "/NH"], timeout=10)
        payload = {
            "version": version.get("structuredContent") or version,
            "processes": procs.get("structuredContent") or procs,
        }
        return _json(payload)
    if name == "cloudflared_stop":
        return _run(["taskkill", "/IM", "cloudflared.exe", "/F"])
    tunnel_name = str(arguments.get("name") or os.getenv("CLOUDFLARED_TUNNEL_NAME", "edgar-local-01-tunnel"))
    if name in {"cloudflared_start", "cloudflared_restart"}:
        if name == "cloudflared_restart":
            _run(["taskkill", "/IM", "cloudflared.exe", "/F"])
        log_path = os.path.join(os.getenv("TEMP", r"G:\AI_WORK_512"), "cloudflared.log")
        with open(log_path, "a", encoding="utf-8") as log_file:
            subprocess.Popen(
                [binary, "tunnel", "run", tunnel_name],
                stdout=log_file,
                stderr=log_file,
                cwd=str(CLOUDFLARED_DIR) if CLOUDFLARED_DIR.is_dir() else None,
            )
        return _json({"started": True, "name": tunnel_name, "log": log_path})
    if name == "cloudflared_verify":
        script = CLOUDFLARED_DIR / "scripts" / "verify-all.cmd"
        if script.is_file():
            return _run(["cmd.exe", "/c", str(script)], cwd=str(CLOUDFLARED_DIR), timeout=180)
        return _run([binary, "tunnel", "list"])
    if name == "cloudflared_add_service":
        script = CLOUDFLARED_DIR / "scripts" / "add-service.cmd"
        return _run(["cmd.exe", "/c", str(script), *_as_argv(arguments)], cwd=str(CLOUDFLARED_DIR))
    if name == "cloudflared_ddns_update":
        script = CLOUDFLARED_DIR / "scripts" / "ddns-update.ps1"
        return _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *_as_argv(arguments)])
    return _text(f"Unknown cloudflared tool: {name}", is_error=True)


def _handle_openmontage(name: str, arguments: dict) -> dict:
    if name == "om__list_pipelines":
        names = sorted(path.stem for path in (OPENMONTAGE_DIR / "pipeline_defs").glob("*.yaml"))
        return _json({"pipelines": names, "root": str(OPENMONTAGE_DIR / "pipeline_defs")})
    if name == "om__read_pipeline":
        stem = str(arguments.get("name") or "").strip()
        path = OPENMONTAGE_DIR / "pipeline_defs" / f"{stem}.yaml"
        if not path.is_file():
            return _text(f"pipeline not found: {stem}", is_error=True)
        return _text(path.read_text(encoding="utf-8"))
    if name == "om__status":
        pipelines = sorted(path.stem for path in (OPENMONTAGE_DIR / "pipeline_defs").glob("*.yaml"))
        ast_names = _openmontage_ast_names()
        return _json({
            "root": str(OPENMONTAGE_DIR),
            "pipelines": pipelines,
            "tools": ast_names,
            "tool_count": len(ast_names),
            "discovery": "ast",
            "error": "",
        }, is_error=not ast_names)
    if name in {"om__execute", "om__dry_run"} or name.startswith("om__"):
        tool_name = arguments.get("tool") if name in {"om__execute", "om__dry_run"} else name[len("om__"):]
        inputs = arguments.get("inputs") if name in {"om__execute", "om__dry_run"} else {
            key: value for key, value in arguments.items() if key != "name"
        }
        if not isinstance(inputs, dict):
            inputs = {}
        try:
            registry = _openmontage_registry()
            tool = registry._tools.get(str(tool_name))
            if tool is None:
                return _text(f"OpenMontage tool not found: {tool_name}", is_error=True)
            if name == "om__dry_run" or arguments.get("dry_run") is True:
                return _json(tool.dry_run(inputs))
            result = tool.execute(inputs)
            payload = {
                "success": result.success,
                "data": result.data,
                "artifacts": result.artifacts,
                "error": result.error,
                "cost_usd": result.cost_usd,
                "duration_seconds": result.duration_seconds,
                "model": result.model,
            }
            return _json(payload, is_error=not result.success)
        except Exception as exc:
            return _text(f"OpenMontage error: {exc}\n{traceback.format_exc()[-1500:]}", is_error=True)
    return _text(f"Unknown OpenMontage tool: {name}", is_error=True)


def _handle_hermes(name: str, arguments: dict) -> dict:
    binary = hermes_cmd()
    timeout = int(arguments.get("timeout_seconds") or 300)
    if name == "hermes_cli":
        return _run([binary, *_as_argv(arguments)], timeout=timeout)
    if name == "hermes_version":
        return _run([binary, "--version"])
    if name == "hermes_status":
        return _run([binary, "status"], timeout=60)
    if name == "hermes_doctor":
        return _run([binary, "doctor"], timeout=120)
    if name == "hermes_agent":
        task = str(arguments.get("task") or "").strip()
        if not task:
            return _text("task is required", is_error=True)
        argv = [binary, "-z", task, "--cli"]
        working_dir = str(arguments.get("working_dir") or r"V:\projects").strip()
        argv.extend(["--in", working_dir])
        if arguments.get("model"):
            argv.extend(["-m", str(arguments["model"])])
        if arguments.get("provider"):
            argv.extend(["--provider", str(arguments["provider"])])
        if arguments.get("reasoning"):
            argv.extend(["--reasoning", str(arguments["reasoning"])])
        if arguments.get("skills"):
            argv.extend(["--skills", str(arguments["skills"])])
        if arguments.get("toolsets"):
            argv.extend(["-t", str(arguments["toolsets"])])
        if arguments.get("yolo") is True:
            argv.append("--yolo")
        if arguments.get("accept_hooks") is True:
            argv.append("--accept-hooks")
        if arguments.get("worktree") is True:
            argv.append("--worktree")
        if arguments.get("ignore_rules") is True:
            argv.append("--ignore-rules")
        if arguments.get("resume"):
            argv.extend(["--resume", str(arguments["resume"])])
        if arguments.get("continue"):
            argv.extend(["--continue", str(arguments["continue"])])
        extra = arguments.get("extra_args")
        if isinstance(extra, list):
            argv.extend(str(item) for item in extra)
        return _run(argv, cwd=working_dir, timeout=timeout)
    if name == "hermes_sessions_list":
        return _run([binary, "sessions", "list"], timeout=60)
    if name == "hermes_skills_list":
        return _run([binary, "skills", "list"], timeout=60)
    if name == "hermes_mcp_list":
        return _run([binary, "mcp", "list"], timeout=60)
    if name == "hermes_memory_status":
        return _run([binary, "memory", "status"], timeout=60)
    if name == "hermes_config_show":
        return _redact_run_output(_run([binary, "config", "show"], timeout=60))
    if name == "hermes_logs":
        log_name = str(arguments.get("log_name") or "agent").strip()
        allowed_logs = {"agent", "errors", "gateway", "gui", "desktop", "update", "handoff", "list"}
        if log_name not in allowed_logs:
            return _text("log_name must be agent, errors, gateway, gui, desktop, update, handoff, or list", is_error=True)
        argv = [binary, "logs"]
        if log_name != "agent":
            argv.append(log_name)
        lines = arguments.get("lines", 50)
        if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1 or lines > 500:
            return _text("lines must be an integer from 1 to 500", is_error=True)
        argv.extend(["-n", str(lines)])
        since = str(arguments.get("since") or "").strip()
        if since:
            if not re.fullmatch(r"\d+[smhd]", since):
                return _text("since must look like 30m, 1h, or 2d", is_error=True)
            argv.extend(["--since", since])
        level = str(arguments.get("level") or "").strip()
        if level:
            if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
                return _text("level must be DEBUG, INFO, WARNING, or ERROR", is_error=True)
            argv.extend(["--level", level])
        component = str(arguments.get("component") or "").strip()
        if component:
            if component not in {"gateway", "agent", "tools", "cli", "cron", "gui"}:
                return _text("component must be gateway, agent, tools, cli, cron, or gui", is_error=True)
            argv.extend(["--component", component])
        return _run(argv, timeout=60)
    if name == "hermes_gateway_status":
        return _run([binary, "gateway", "status"], timeout=60)
    if name == "hermes_usage":
        return _run([binary, "usage"], timeout=60)
    return _text(f"Unknown Hermes tool: {name}", is_error=True)


def _handle_openclaw(name: str, arguments: dict) -> dict:
    binary = openclaw_cmd()
    timeout = int(arguments.get("timeout_seconds") or 300)
    if name == "openclaw_cli":
        return _run([binary, *_as_argv(arguments)], timeout=timeout)
    if name == "openclaw_version":
        return _run([binary, "--version"])
    if name == "openclaw_status":
        return _run([binary, "status", "--json"], timeout=60)
    if name == "openclaw_health":
        return _run([binary, "status", "--all", "--json"], timeout=120)
    if name == "openclaw_agent":
        message = str(arguments.get("message") or arguments.get("task") or "").strip()
        message_file = str(arguments.get("message_file") or "").strip()
        if message_file and any(ch in message_file for ch in "\r\n"):
            return _text("message_file must be a single line", is_error=True)
        if message_file:
            argv = [binary, "agent", "--message-file", message_file]
        else:
            if not message:
                return _text("task/message is required", is_error=True)
            argv = [binary, "agent", "--message", message]
        if arguments.get("local") is not False:
            argv.append("--local")
        if arguments.get("json") is not False:
            argv.append("--json")
        if arguments.get("agent"):
            argv.extend(["--agent", str(arguments["agent"])])
        if arguments.get("model"):
            argv.extend(["--model", str(arguments["model"])])
        if arguments.get("session_id"):
            argv.extend(["--session-id", str(arguments["session_id"])])
        if arguments.get("session_key"):
            argv.extend(["--session-key", str(arguments["session_key"])])
        thinking = str(arguments.get("thinking") or "").strip()
        if thinking:
            allowed_thinking = {"off", "minimal", "low", "medium", "high", "xhigh", "adaptive", "max", "ultra"}
            if thinking not in allowed_thinking:
                return _text("thinking must be a documented OpenClaw level", is_error=True)
            argv.extend(["--thinking", thinking])
        verbose = str(arguments.get("verbose") or "").strip()
        if verbose:
            if verbose not in {"on", "off"}:
                return _text("verbose must be on or off", is_error=True)
            argv.extend(["--verbose", verbose])
        turn_timeout = arguments.get("turn_timeout")
        if turn_timeout is not None:
            if isinstance(turn_timeout, bool) or not isinstance(turn_timeout, int) or turn_timeout < 0:
                return _text("turn_timeout must be an integer number of seconds", is_error=True)
            argv.extend(["--timeout", str(turn_timeout)])
        extra = arguments.get("extra_args")
        if isinstance(extra, list):
            argv.extend(str(item) for item in extra)
        working_dir = str(arguments.get("working_dir") or r"V:\projects").strip()
        return _run(argv, cwd=working_dir, timeout=timeout)
    if name == "openclaw_doctor":
        return _run([binary, "doctor", "--json"], timeout=120)
    if name == "openclaw_gateway_status":
        argv = [binary, "gateway", "status", "--json"]
        if arguments.get("no_probe") is True:
            argv.append("--no-probe")
        return _run(argv, timeout=90)
    if name == "openclaw_gateway_health":
        return _run([binary, "health", "--json"], timeout=90)
    if name == "openclaw_channels":
        argv = [binary, "channels", "list", "--json"]
        if arguments.get("all") is True:
            argv.append("--all")
        return _run(argv, timeout=60)
    if name == "openclaw_sessions":
        argv = [binary, "sessions", "--json"]
        agent = str(arguments.get("agent") or "").strip()
        if agent:
            if any(ch in agent for ch in "\r\n"):
                return _text("agent must be a single line", is_error=True)
            argv.extend(["--agent", agent])
        limit = arguments.get("limit")
        if limit is not None and str(limit).strip():
            limit_text = str(limit).strip()
            if limit_text != "all" and not limit_text.isdigit():
                return _text("limit must be an integer or all", is_error=True)
            argv.extend(["--limit", limit_text])
        active = arguments.get("active_minutes")
        if active is not None:
            if isinstance(active, bool) or not isinstance(active, int) or active < 1:
                return _text("active_minutes must be a positive integer", is_error=True)
            argv.extend(["--active", str(active)])
        return _run(argv, timeout=60)
    if name == "openclaw_mcp_doctor":
        argv = [binary, "mcp", "doctor"]
        server_name = str(arguments.get("name") or "").strip()
        if server_name:
            if any(ch in server_name for ch in "\r\n \t"):
                return _text("name must be a single token", is_error=True)
            argv.append(server_name)
        if arguments.get("probe") is True:
            argv.append("--probe")
        argv.append("--json")
        return _run(argv, timeout=120)
    return _text(f"Unknown OpenClaw tool: {name}", is_error=True)


def dispatch_wrap_tool(name: str, arguments: dict | None) -> dict | None:
    arguments = arguments or {}
    if name == "wrap_catalog":
        return _json(wrap_catalog_payload())

    matched = match_upstream(name)
    if matched:
        spec, upstream_name = matched
        if spec.local_only and not _local_permitted(True):
            return _text(
                f"{spec.title} is local-only unless MCP_WRAP_ALLOW_REMOTE=1",
                is_error=True,
            )
        try:
            return call_upstream_tool(spec, upstream_name, arguments)
        except UpstreamError as exc:
            return _text(str(exc), is_error=True)
        except Exception as exc:
            return _text(f"{spec.id} call failed: {exc}", is_error=True)

    groups = (
        ("descope__", "descope", _handle_descope),
        ("cloudflared_", "cloudflared", _handle_cloudflared),
        ("om__", "openmontage", _handle_openmontage),
        ("hermes_", "hermes", _handle_hermes),
        ("openclaw_", "openclaw", _handle_openclaw),
        ("fleet_", "fleet", _handle_fleet),
    )
    for prefix, native_id, handler in groups:
        if not name.startswith(prefix):
            continue
        flag = NATIVE_FLAG[native_id]
        if not _enabled(flag):
            return _text(f"{native_id} wrappers are off. Set {flag}=1 or MCP_WRAP_ALL=1.", is_error=True)
        local_only = native_id in {"cloudflared", "openmontage", "hermes", "openclaw"}
        if local_only and not _local_permitted(True):
            return _text(f"{native_id} is local-only unless MCP_WRAP_ALLOW_REMOTE=1", is_error=True)
        return handler(name, arguments)
    return None
