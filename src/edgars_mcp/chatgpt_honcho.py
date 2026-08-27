"""DEV-only ChatGPT → Logto → Honcho staging MCP bridge for EDG-313 PASS-C."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

CHATGPT_HONCHO_PATH = "/chatgpt-honcho"
CHATGPT_HONCHO_METADATA_PATH = "/.well-known/oauth-protected-resource/chatgpt-honcho"
LOGTO_SCOPES = ["openid", "profile", "email", "offline_access"]


@dataclass(frozen=True)
class ChatgptHonchoConfig:
    enabled: bool
    resource_url: str
    issuer: str
    userinfo_url: str
    upstream_url: str
    workspace_id: str
    observer_id: str = "chatgpt"
    observed_id: str = "edgar"
    upstream_bearer: str = "noop"


def build_resource_metadata(config: ChatgptHonchoConfig) -> dict:
    return {
        "resource": config.resource_url,
        "authorization_servers": [config.issuer],
        "scopes_supported": list(LOGTO_SCOPES),
        "bearer_methods_supported": ["header"],
    }


def _tool(name: str, title: str, description: str, properties: dict, required: list[str], *, read_only: bool) -> dict:
    security = [{"type": "oauth2", "scopes": list(LOGTO_SCOPES)}]
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required},
        "annotations": {
            "readOnlyHint": read_only,
            "openWorldHint": False,
            "destructiveHint": False,
        },
        "securitySchemes": security,
        "outputSchema": {"type": "object"},
        "_meta": {"securitySchemes": security},
    }


def build_tools() -> list[dict]:
    return [
        _tool(
            "recall_edgar_memory",
            "Recall Edgar Memory",
            "Semantic recall from the isolated EDG-313 Honcho staging workspace.",
            {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 20}},
            ["query"],
            read_only=True,
        ),
        _tool(
            "remember_edgar_memory",
            "Remember Edgar Memory",
            "Write a synthetic DEV memory to the isolated EDG-313 Honcho staging workspace.",
            {"content": {"type": "string"}, "confirm": {"type": "boolean"}},
            ["content", "confirm"],
            read_only=False,
        ),
    ]


def verify_logto_access_token(token: str, userinfo_url: str, *, timeout: float = 8.0) -> dict:
    if not token:
        raise ValueError("missing bearer token")
    request = urllib.request.Request(
        userinfo_url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("sub"):
        raise ValueError("Logto userinfo did not return a subject")
    return payload


class HonchoStagingClient:
    def __init__(self, config: ChatgptHonchoConfig, *, timeout: float = 20.0):
        self.config = config
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.config.upstream_bearer:
            headers["Authorization"] = f"Bearer {self.config.upstream_bearer}"
        req = urllib.request.Request(
            f"{self.config.upstream_url.rstrip('/')}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else None

    def ensure_workspace(self) -> None:
        self._request("POST", "/v3/workspaces", {"id": self.config.workspace_id})
        peers_path = f"/v3/workspaces/{urllib.parse.quote(self.config.workspace_id)}/peers"
        self._request("POST", peers_path, {"id": self.config.observer_id})
        if self.config.observed_id != self.config.observer_id:
            self._request("POST", peers_path, {"id": self.config.observed_id})

    def remember(self, content: str) -> dict:
        self.ensure_workspace()
        _, payload = self._request(
            "POST",
            f"/v3/workspaces/{urllib.parse.quote(self.config.workspace_id)}/conclusions",
            {"conclusions": [{
                "content": content,
                "observer_id": self.config.observer_id,
                "observed_id": self.config.observed_id,
            }]},
        )
        if not isinstance(payload, list) or not payload:
            raise RuntimeError("Honcho did not return the created conclusion")
        return payload[0]

    def recall(self, query: str, *, top_k: int = 5) -> list[dict]:
        self.ensure_workspace()
        _, payload = self._request(
            "POST",
            f"/v3/workspaces/{urllib.parse.quote(self.config.workspace_id)}/conclusions/query",
            {
                "query": query,
                "top_k": max(1, min(int(top_k), 20)),
                "filters": {
                    "observer": self.config.observer_id,
                    "observed": self.config.observed_id,
                },
            },
        )
        if not isinstance(payload, list):
            raise RuntimeError("Honcho recall response was not a list")
        return payload


def _response(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _tool_result(data: object, *, is_error: bool = False) -> dict:
    result = {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        "structuredContent": data if isinstance(data, dict) else {"items": data},
    }
    if is_error:
        result["isError"] = True
    return result


def dispatch(msg: dict, client: HonchoStagingClient) -> dict | None:
    req_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}
    if req_id is None:
        return None
    if method == "initialize":
        return _response(req_id, {
            "protocolVersion": params.get("protocolVersion", "2025-11-25"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "edgars-chatgpt-honcho-dev", "version": "0.1.0"},
        })
    if method == "ping":
        return _response(req_id, {})
    if method == "tools/list":
        return _response(req_id, {"tools": build_tools()})
    if method != "tools/call":
        return {"jsonrpc":"2.0","id":req_id,"error":{"code":-32601,"message":"Method not found"}}

    name = params.get("name")
    arguments = params.get("arguments") or {}
    try:
        if name == "remember_edgar_memory":
            content = str(arguments.get("content") or "").strip()
            if not content:
                return _response(req_id, _tool_result({"error":"content is required"}, is_error=True))
            if arguments.get("confirm") is not True:
                return _response(req_id, _tool_result({"error":"confirm=true is required"}, is_error=True))
            return _response(req_id, _tool_result({"remembered": client.remember(content)}))
        if name == "recall_edgar_memory":
            query = str(arguments.get("query") or "").strip()
            if not query:
                return _response(req_id, _tool_result({"error":"query is required"}, is_error=True))
            top_k = int(arguments.get("top_k", 5))
            return _response(req_id, _tool_result({"memories": client.recall(query, top_k=top_k)}))
        return _response(req_id, _tool_result({"error":f"unknown tool: {name}"}, is_error=True))
    except Exception as exc:
        return _response(req_id, _tool_result({"error":str(exc)}, is_error=True))
