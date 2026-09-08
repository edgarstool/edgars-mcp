"""Live verification for wrapped surfaces. Enable flags in this process only."""

from __future__ import annotations

import json
import os
import sys
import traceback

os.environ.setdefault("MCP_WRAP_CLOUDFLARED", "1")
os.environ.setdefault("MCP_WRAP_OP_CONNECT", "1")
os.environ.setdefault("MCP_WRAP_HERMES", "1")
os.environ.setdefault("MCP_WRAP_OPENCLAW", "1")
os.environ.setdefault("MCP_WRAP_DESCOPE", "1")
os.environ.setdefault("MCP_WRAP_OPENMONTAGE", "1")
os.environ.setdefault("MCP_WRAP_PLAYWRIGHT", os.getenv("MCP_WRAP_PLAYWRIGHT", "0"))
os.environ.setdefault("MCP_WRAP_WINDOWS", os.getenv("MCP_WRAP_WINDOWS", "0"))
os.environ.setdefault("MCP_WRAP_DESKTOP_COMMANDER", os.getenv("MCP_WRAP_DESKTOP_COMMANDER", "0"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from edgar_wrappers import dispatch_wrap_tool, list_wrap_tools  # noqa: E402
from mcp_upstreams import builtin_upstream_specs, fetch_prefixed_upstream_tools  # noqa: E402


def _ok(result: dict) -> bool:
    return isinstance(result, dict) and not result.get("isError")


def _text(result: dict) -> str:
    content = result.get("content") or []
    if content and isinstance(content[0], dict):
        return str(content[0].get("text") or "")
    return str(result)


def main() -> int:
    rows = []

    catalog = dispatch_wrap_tool("wrap_catalog", {})
    rows.append(("wrap_catalog", _ok(catalog), _text(catalog)[:300]))

    safe_calls = [
        ("cloudflared_version", {}),
        ("cloudflared_status", {}),
        ("op_connect_status", {}),
        ("hermes_version", {}),
        ("openclaw_version", {}),
        ("descope__sdk_status", {}),
        ("om__list_pipelines", {}),
        ("om__status", {}),
    ]
    for name, args in safe_calls:
        try:
            result = dispatch_wrap_tool(name, args)
            rows.append((name, _ok(result), _text(result)[:400]))
        except Exception as exc:
            rows.append((name, False, f"{exc}\n{traceback.format_exc()[-400:]}"))

    names = [tool["name"] for tool in list_wrap_tools()]
    rows.append(("listed_wrap_tools", True, f"count={len(names)}"))

    for spec in builtin_upstream_specs():
        if not spec.enabled():
            rows.append((f"upstream:{spec.id}", True, "skipped-disabled"))
            continue
        try:
            tools, status = fetch_prefixed_upstream_tools(spec)
            rows.append((f"upstream:{spec.id}", status == "ok" and len(tools) > 0, f"status={status} count={len(tools)}"))
        except Exception as exc:
            rows.append((f"upstream:{spec.id}", False, str(exc)))

    failed = [row for row in rows if not row[1]]
    print(json.dumps({"ok": not failed, "results": rows}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
