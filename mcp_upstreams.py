"""Full-surface MCP upstream proxy for edgars-mcp.

Default is off. When a source is enabled, every upstream tools/list entry is
exposed with a prefix. This module does not subset or drop upstream tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _windows_cmd(name: str) -> str:
    if sys.platform == "win32":
        for candidate in (f"{name}.cmd", f"{name}.exe", name):
            found = shutil.which(candidate)
            if found:
                return found
    return shutil.which(name) or name


def wrap_all_enabled() -> bool:
    return _env_bool("MCP_WRAP_ALL", False)


def wrap_allow_remote() -> bool:
    return _env_bool("MCP_WRAP_ALLOW_REMOTE", False)


@dataclass(frozen=True)
class UpstreamSpec:
    id: str
    prefix: str
    title: str
    env_flag: str
    command: str
    args: tuple[str, ...] = ()
    cwd: str | None = None
    url: str | None = None
    local_only: bool = True
    timeout_seconds: float = 120.0
    extra_env_keys: tuple[str, ...] = ()

    def enabled(self) -> bool:
        return wrap_all_enabled() or _env_bool(self.env_flag, False)

    def resolved_command(self) -> str:
        if self.url:
            return ""
        return _windows_cmd(self.command)

    def spawn_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in self.extra_env_keys:
            value = os.getenv(key, "")
            if value:
                env[key] = value
        return env


def _playwright_spec() -> UpstreamSpec:
    return UpstreamSpec(
        id="playwright",
        prefix="pw__",
        title="Playwright MCP",
        env_flag="MCP_WRAP_PLAYWRIGHT",
        command="npx",
        args=("-y", "@playwright/mcp"),
        cwd=r"V:\projects\playwright",
        local_only=True,
        extra_env_keys=("PLAYWRIGHT_BROWSERS_PATH",),
    )


def _windows_spec() -> UpstreamSpec:
    uv = _windows_cmd("uv")
    return UpstreamSpec(
        id="windows",
        prefix="win__",
        title="Windows-MCP",
        env_flag="MCP_WRAP_WINDOWS",
        command=uv,
        args=("--directory", r"V:\projects\Windows-MCP", "run", "windows-mcp", "serve"),
        cwd=r"V:\projects\Windows-MCP",
        local_only=True,
    )


def _desktop_commander_spec() -> UpstreamSpec:
    local_js = r"V:\projects\DesktopCommanderMCP\dist\index.js"
    if os.path.isfile(local_js):
        return UpstreamSpec(
            id="desktop_commander",
            prefix="dc__",
            title="Desktop Commander MCP",
            env_flag="MCP_WRAP_DESKTOP_COMMANDER",
            command=_windows_cmd("node"),
            args=(local_js,),
            cwd=r"V:\projects\DesktopCommanderMCP",
            local_only=True,
        )
    return UpstreamSpec(
        id="desktop_commander",
        prefix="dc__",
        title="Desktop Commander MCP",
        env_flag="MCP_WRAP_DESKTOP_COMMANDER",
        command="npx",
        args=("-y", "@wonderwhy-er/desktop-commander"),
        cwd=r"V:\projects\DesktopCommanderMCP",
        local_only=True,
    )


def _descope_mcp_spec() -> UpstreamSpec | None:
    url = os.getenv("DESCOPE_MCP_URL", "").strip()
    command = os.getenv("DESCOPE_MCP_COMMAND", "").strip()
    raw_args = os.getenv("DESCOPE_MCP_ARGS", "").strip()
    args = tuple(part for part in raw_args.split(" ") if part) if raw_args else ()
    if url:
        return UpstreamSpec(
            id="descope_mgmt",
            prefix="descope_mgmt__",
            title="Descope management MCP",
            env_flag="MCP_WRAP_DESCOPE",
            command="",
            url=url,
            local_only=False,
            extra_env_keys=("DESCOPE_MCP_TOKEN", "DESCOPE_MANAGEMENT_KEY"),
        )
    if command:
        return UpstreamSpec(
            id="descope_mgmt",
            prefix="descope_mgmt__",
            title="Descope management MCP",
            env_flag="MCP_WRAP_DESCOPE",
            command=command,
            args=args,
            cwd=r"V:\projects\descope-mcp",
            local_only=False,
            extra_env_keys=("DESCOPE_MANAGEMENT_KEY", "DESCOPE_MCP_WELL_KNOWN_URL"),
        )
    return None


def builtin_upstream_specs() -> list[UpstreamSpec]:
    specs = [_playwright_spec(), _windows_spec(), _desktop_commander_spec()]
    descope = _descope_mcp_spec()
    if descope is not None:
        specs.append(descope)
    return specs


class UpstreamError(RuntimeError):
    pass


@dataclass
class _LiveStdio:
    spec: UpstreamSpec
    stack: AsyncExitStack
    session: ClientSession
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    tools: list[dict] = field(default_factory=list)
    last_error: str = ""
    started_at: float = 0.0


_SESSIONS: dict[str, _LiveStdio] = {}
_SESSIONS_LOCK = threading.Lock()
_HTTP_CACHE: dict[str, dict[str, Any]] = {}
_HTTP_CACHE_LOCK = threading.Lock()


def _run_on(loop: asyncio.AbstractEventLoop, coro, timeout: float):
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout)


def _new_loop() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_runner, name="edgars-mcp-upstream", daemon=True)
    thread.start()
    return loop, thread


def _tool_to_dict(tool: Any) -> dict:
    if hasattr(tool, "model_dump"):
        payload = tool.model_dump(mode="json", exclude_none=True)
    elif isinstance(tool, dict):
        payload = dict(tool)
    else:
        payload = {"name": str(getattr(tool, "name", "")), "description": str(tool)}
    return payload


def _call_result_to_dict(result: Any) -> dict:
    content: list[dict] = []
    raw_content = getattr(result, "content", None) or []
    for block in raw_content:
        if hasattr(block, "model_dump"):
            content.append(block.model_dump(mode="json", exclude_none=True))
        elif isinstance(block, dict):
            content.append(block)
        else:
            content.append({"type": "text", "text": str(block)})
    payload: dict[str, Any] = {
        "content": content or [{"type": "text", "text": ""}],
        "isError": bool(getattr(result, "isError", False)),
    }
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload["structuredContent"] = structured
    return payload


def prefix_tool_descriptor(spec: UpstreamSpec, upstream_tool: dict) -> dict | None:
    upstream_name = str(upstream_tool.get("name") or "").strip()
    if not upstream_name or upstream_name.startswith(spec.prefix):
        return None
    descriptor = dict(upstream_tool)
    title = str(descriptor.get("title") or upstream_name.replace("_", " ").title())
    description = str(descriptor.get("description") or "").strip()
    descriptor["name"] = f"{spec.prefix}{upstream_name}"
    descriptor["title"] = f"{spec.title}: {title}"
    descriptor["description"] = (
        f"[{spec.title}] {description}"
        if description
        else f"{spec.title} tool proxied through edgars-mcp."
    )
    meta = dict(descriptor.get("_meta") or {})
    meta["edgars_mcp_proxy"] = {
        "upstream": spec.id,
        "upstream_name": upstream_name,
        "local_only": spec.local_only,
    }
    descriptor["_meta"] = meta
    return descriptor


async def _list_all_tools(session: ClientSession) -> list[Any]:
    tools: list[Any] = []
    result = await session.list_tools()
    tools.extend(result.tools or [])
    cursor = getattr(result, "nextCursor", None)
    while cursor:
        result = await session.list_tools(cursor)
        tools.extend(result.tools or [])
        cursor = getattr(result, "nextCursor", None)
    return tools


async def _boot_stdio(spec: UpstreamSpec):
    command = spec.resolved_command()
    if not command:
        raise UpstreamError(f"{spec.id}: command {spec.command!r} not found")
    params = StdioServerParameters(
        command=command,
        args=list(spec.args),
        env=spec.spawn_env() or None,
        cwd=spec.cwd,
    )
    stack = AsyncExitStack()
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(
        ClientSession(read, write, read_timeout_seconds=timedelta(seconds=spec.timeout_seconds))
    )
    await session.initialize()
    tools = [_tool_to_dict(tool) for tool in await _list_all_tools(session)]
    return stack, session, tools


async def _stop_stdio(live: _LiveStdio) -> None:
    try:
        await live.stack.aclose()
    except Exception:
        pass


def _get_stdio(spec: UpstreamSpec) -> _LiveStdio:
    with _SESSIONS_LOCK:
        live = _SESSIONS.get(spec.id)
        if live is not None:
            return live
    loop, thread = _new_loop()
    try:
        stack, session, tools = _run_on(loop, _boot_stdio(spec), spec.timeout_seconds)
    except Exception as exc:
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        raise UpstreamError(f"{spec.id} stdio start failed: {exc}") from exc
    live = _LiveStdio(
        spec=spec,
        stack=stack,
        session=session,
        loop=loop,
        thread=thread,
        tools=tools,
        started_at=time.time(),
    )
    with _SESSIONS_LOCK:
        _SESSIONS[spec.id] = live
    return live


def _http_headers(spec: UpstreamSpec) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": f"edgars-mcp-{spec.id}/0.1",
    }
    token = os.getenv("DESCOPE_MCP_TOKEN", "").strip() or os.getenv("DESCOPE_MANAGEMENT_KEY", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _normalize_sse(body: bytes, content_type: str) -> bytes:
    if "text/event-stream" not in (content_type or "").lower():
        return body
    text = body.decode("utf-8", errors="replace")
    data_lines = [
        line[len("data:"):].strip()
        for line in text.splitlines()
        if line.startswith("data:") and line[len("data:"):].strip()
    ]
    if len(data_lines) != 1:
        return body
    return data_lines[0].encode("utf-8")


def call_http_jsonrpc(spec: UpstreamSpec, method: str, params: dict | None = None, *, req_id: object = "edgars-mcp") -> dict:
    if not spec.url:
        raise UpstreamError(f"{spec.id} has no HTTP URL")
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(spec.url, data=body, headers=_http_headers(spec), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=spec.timeout_seconds) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        content_type = exc.headers.get("Content-Type", "application/json")
        detail = _normalize_sse(raw, content_type).decode("utf-8", errors="replace")[:800]
        raise UpstreamError(f"{spec.id} HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(f"{spec.id} unreachable: {exc.reason}") from exc
    payload = json.loads(_normalize_sse(raw, content_type).decode("utf-8"))
    if not isinstance(payload, dict):
        raise UpstreamError(f"{spec.id} returned a non-object JSON-RPC payload")
    if payload.get("error"):
        raise UpstreamError(json.dumps(payload["error"], ensure_ascii=False))
    return payload


def list_upstream_tools(spec: UpstreamSpec) -> list[dict]:
    if spec.url:
        identity = spec.url
        now = time.time()
        with _HTTP_CACHE_LOCK:
            cached = _HTTP_CACHE.get(spec.id)
            if cached and cached.get("identity") == identity and float(cached.get("expires_at") or 0) > now:
                return list(cached.get("tools") or [])
        payload = call_http_jsonrpc(spec, "tools/list", {}, req_id=f"edgars-mcp-{spec.id}-tools-list")
        tools = (payload.get("result") or {}).get("tools") or []
        with _HTTP_CACHE_LOCK:
            _HTTP_CACHE[spec.id] = {
                "identity": identity,
                "expires_at": now + 30,
                "tools": list(tools),
            }
        return list(tools)
    live = _get_stdio(spec)
    return list(live.tools)


def call_upstream_tool(spec: UpstreamSpec, upstream_name: str, arguments: dict | None) -> dict:
    if spec.url:
        payload = call_http_jsonrpc(
            spec,
            "tools/call",
            {"name": upstream_name, "arguments": arguments or {}},
            req_id=f"edgars-mcp-{spec.id}",
        )
        result = payload.get("result")
        if isinstance(result, dict):
            return result
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": False,
        }
    live = _get_stdio(spec)
    result = _run_on(
        live.loop,
        live.session.call_tool(upstream_name, arguments or {}),
        spec.timeout_seconds,
    )
    return _call_result_to_dict(result)


def fetch_prefixed_upstream_tools(spec: UpstreamSpec) -> tuple[list[dict], str]:
    if not spec.enabled():
        return [], "disabled"
    try:
        descriptors = [
            descriptor
            for descriptor in (prefix_tool_descriptor(spec, tool) for tool in list_upstream_tools(spec))
            if descriptor is not None
        ]
        return descriptors, "ok"
    except Exception as exc:
        return [], str(exc)


def match_upstream(name: str, specs: list[UpstreamSpec] | None = None) -> tuple[UpstreamSpec, str] | None:
    for spec in specs or builtin_upstream_specs():
        if spec.enabled() and isinstance(name, str) and name.startswith(spec.prefix):
            return spec, name[len(spec.prefix):]
    return None
