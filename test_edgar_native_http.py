"""Real MCPHTTPHandler TCP requests against an isolated native Auth app.

The AS uses TestClient (in-process ASGI, not a socket/TLS server). Consent,
PKCE exchange, authenticated introspection and revocation are real AS routes.
No auth verifier, MCP handler, tool listing or tool dispatch is mocked.
"""

import base64
import hashlib
import http.client
import json
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from edgar_auth.app import Config, create_app
import server_http


ISSUER = "https://issuer.edg478.test"
RESOURCE = "https://rs.edg478.test/mcp"
CALLBACK = "https://client.edg478.test/callback"
CLIENT_ID = "edg478-http-client"


@dataclass(repr=False)
class NativeAS:
    client: TestClient
    config: server_http.HandcraftServerConfig
    pem: str
    introspection_secret: str

    def issue(self, scope="mcp:read"):
        verifier = secrets.token_urlsafe(40)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        authorization = self.client.get("/authorize", params={
            "client_id": CLIENT_ID, "response_type": "code",
            "redirect_uri": CALLBACK, "resource": RESOURCE, "scope": scope,
            "state": "edg478-http-nonce", "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        assert authorization.status_code == 303
        request_id = parse_qs(urlparse(
            authorization.headers["location"]
        ).query)["request_id"][0]
        pending = self.client.app.state.store.get_pending(request_id)
        consent = self.client.post("/consent", data={
            "request_id": request_id, "decision": "approve", "csrf": pending["csrf"],
        })
        assert consent.status_code == 303
        code = parse_qs(urlparse(consent.headers["location"]).query)["code"][0]
        exchanged = self.client.post("/token", data={
            "grant_type": "authorization_code", "client_id": CLIENT_ID,
            "code": code, "redirect_uri": CALLBACK, "code_verifier": verifier,
            "resource": RESOURCE,
        })
        assert exchanged.status_code == 200
        return exchanged.json()["access_token"]

    def introspect(self, token):
        response = self.client.post("/introspect", data={
            "client_id": "edg478-resource-server",
            "client_secret": self.introspection_secret, "token": token,
        })
        response.raise_for_status()
        return response.json()

    def revoke(self, token):
        response = self.client.post("/revoke", data={
            "client_id": CLIENT_ID, "token": token, "token_type_hint": "access_token",
        })
        assert response.status_code == 200
        return response.status_code

    def claims(self, token):
        return jwt.decode(
            token, self.client.app.state.public_key, algorithms=["RS256"],
            issuer=ISSUER, audience=RESOURCE,
        )


@pytest.fixture
def native_as(tmp_path, monkeypatch):
    # Eliminate inherited runtime settings, including upstream enabling flags.
    for name in tuple(server_http.os.environ):
        monkeypatch.delenv(name)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    app = create_app(Config(
        issuer=ISSUER, resource=RESOURCE,
        database=str(tmp_path / "native-http.db"), signing_key=pem,
    ))
    store = app.state.store
    store.register_client(CLIENT_ID, [CALLBACK], "none", None)
    introspection_secret = secrets.token_urlsafe(32)
    store.register_client("edg478-resource-server", [CALLBACK],
                          "client_secret_post", introspection_secret)
    with TestClient(app, base_url=ISSUER, follow_redirects=False) as client:
        session = store.create_session("edg478-http-subject")
        client.cookies.set("__Host-edgar-session", session,
                           domain="issuer.edg478.test", path="/")
        config = server_http.HandcraftServerConfig(
            mcp_api_token="", base_url="https://rs.edg478.test",
            auth_server_url=ISSUER, edgar_native_as_enabled=True,
            edgar_native_as_issuer=ISSUER, edgar_native_as_audience=RESOURCE,
            edgar_native_as_jwks_json=json.dumps(client.get("/jwks.json").json()),
        )
        native = NativeAS(client, config, pem, introspection_secret)
        native.config = replace(config, edgar_native_as_introspect=native.introspect)
        yield native


@contextmanager
def running_mcp(config):
    server = server_http.ThreadingHTTPServer(
        ("127.0.0.1", 0), server_http.MCPHTTPHandler, config=config,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def rpc(address, token, method="tools/list", params=None):
    connection = http.client.HTTPConnection(*address, timeout=5)
    try:
        connection.request("POST", "/mcp", json.dumps({
            "jsonrpc": "2.0", "id": "edg478-http", "method": method,
            "params": params or {},
        }), headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        response = connection.getresponse()
        body = response.read().decode()
        if response.getheader("Content-Type", "").startswith("application/json"):
            body = json.loads(body)
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


def assert_unauthorized(response):
    status, headers, body = response
    assert status == 401
    assert 'error="invalid_token"' in headers["WWW-Authenticate"]
    assert body == "Unauthorized"


def test_real_http_same_unexpired_token_rejected_after_native_revoke(native_as, tmp_path):
    token = native_as.issue("mcp:read mcp:write")
    claims = native_as.claims(token)
    assert native_as.introspect(token)["active"] is True
    target = tmp_path / "must-not-be-written.txt"
    with running_mcp(native_as.config) as address:
        before = rpc(address, token)
        assert before[0] == 200
        assert before[2]["jsonrpc"] == "2.0"
        assert before[2]["id"] == "edg478-http"
        assert any(tool["name"] == "echo" for tool in before[2]["result"]["tools"])
        before_call = rpc(address, token, "tools/call", {
            "name": "echo", "arguments": {"message": "before-revocation"},
        })
        assert before_call[0] == 200
        assert before_call[2]["result"]["content"][0]["text"] == "echo: before-revocation"
        revoked = native_as.revoke(token)
        assert native_as.introspect(token) == {"active": False}
        assert native_as.claims(token) == claims  # Still valid offline.
        assert claims["exp"] > time.time()
        after = rpc(address, token)
        # Spy only on the mutation boundary, not auth, HTTP or RPC dispatch.
        with patch.object(server_http, "handle_fs_write",
                          wraps=server_http.handle_fs_write) as write:
            call = rpc(address, token, "tools/call", {
                "name": "fs_write", "arguments": {
                    "path": str(target), "content": "forbidden mutation",
                },
            })
            no_write = not write.called and not target.exists()
        evidence = {
            "handler": "MCPHTTPHandler", "transport": "loopback TCP HTTP",
            "before_tools_list": before[0], "as_revoke": revoked,
            "before_tools_call": before_call[0],
            "after_tools_list": after[0], "after_tools_call": call[0],
            "after_body": after[2],
            "after_www_authenticate": after[1]["WWW-Authenticate"],
            "same_token": True, "unexpired": claims["exp"] > time.time(),
            "no_mutation": no_write,
        }
        print("HTTP_EVIDENCE " + json.dumps(evidence, sort_keys=True))
        assert_unauthorized(after)
        assert_unauthorized(call)
        assert no_write


@pytest.mark.parametrize("field,value", [
    ("iss", "https://wrong-issuer.edg478.test"),
    ("aud", "https://wrong-resource.edg478.test/mcp"),
    ("scope", "mcp:write"),
])
def test_http_rejects_signed_wrong_issuer_audience_scope(native_as, field, value):
    original = native_as.issue()
    claims = native_as.claims(original)
    claims[field] = value
    # Negative inputs are re-signed with the fixture key, not toy verifiers.
    token = jwt.encode(claims, native_as.pem, algorithm="RS256",
                       headers=jwt.get_unverified_header(original))
    introspect = Mock(wraps=native_as.introspect)
    config = replace(native_as.config, edgar_native_as_introspect=introspect)
    with running_mcp(config) as address:
        assert_unauthorized(rpc(address, token))
        assert_unauthorized(rpc(address, token, "tools/call", {
            "name": "echo", "arguments": {"message": "must not dispatch"},
        }))
    introspect.assert_not_called()


def test_http_rejects_real_as_token_without_read_scope(native_as):
    token = native_as.issue("knowledge:read")
    assert native_as.introspect(token)["active"] is True
    with running_mcp(native_as.config) as address:
        assert_unauthorized(rpc(address, token))


@pytest.mark.parametrize("failure", [
    "missing", "timeout", "unavailable", "malformed", "inactive",
    "string-active", "integer-active",
])
def test_http_introspection_faults_fail_closed(native_as, failure):
    token = native_as.issue()
    status = {**native_as.claims(token), "active": True}

    # Fault-injection only. The positive/revocation tests use real /introspect.
    def fault(_token):
        if failure == "timeout":
            raise TimeoutError("isolated AS timeout")
        if failure == "unavailable":
            raise OSError("isolated AS unavailable")
        if failure == "malformed":
            return []
        status["active"] = {
            "inactive": False, "string-active": "true", "integer-active": 1,
        }[failure]
        return status

    config = replace(native_as.config,
                     edgar_native_as_introspect=None if failure == "missing" else fault)
    with running_mcp(config) as address:
        assert_unauthorized(rpc(address, token))


@pytest.mark.parametrize("field", ["iss", "sub", "aud", "exp", "iat", "scope", "client_id"])
def test_http_introspection_must_match_signed_token(native_as, field):
    token = native_as.issue()
    status = {**native_as.claims(token), "active": True}
    status[field] = "mismatched-response"
    config = replace(native_as.config, edgar_native_as_introspect=lambda _token: status)
    with running_mcp(config) as address:
        assert_unauthorized(rpc(address, token))


@pytest.mark.parametrize("public_fallback", [False, True])
def test_http_native_never_falls_back_to_static_or_descope(native_as, public_fallback):
    config = replace(native_as.config, mcp_api_token="isolated-old-static",
                     descope_enabled=True, base_url="https://127.0.0.1",
                     cloudflare_access_enabled=public_fallback,
                     cloudflare_access_aud="isolated-aud",
                     cloudflare_access_allow_public_token_fallback=public_fallback)
    with patch.object(server_http, "verify_descope_jwt") as descope:
        with running_mcp(config) as address:
            assert_unauthorized(rpc(address, config.mcp_api_token))
        descope.assert_not_called()


def test_http_unsigned_claims_rejected(native_as):
    original = native_as.issue()
    claims = native_as.claims(original)
    token = jwt.encode(claims, key="", algorithm="none",
                       headers={"kid": jwt.get_unverified_header(original)["kid"]})
    with running_mcp(native_as.config) as address:
        assert_unauthorized(rpc(address, token))


def test_http_never_fetches_token_jku(native_as):
    original = native_as.issue()
    headers = {**jwt.get_unverified_header(original),
               "jku": "http://127.0.0.1:1/attacker-keys"}
    token = jwt.encode(native_as.claims(original), native_as.pem,
                       algorithm="RS256", headers=headers)
    with patch.object(server_http.urllib.request, "urlopen",
                      side_effect=AssertionError("unexpected network")) as network:
        with running_mcp(native_as.config) as address:
            assert rpc(address, token)[0] == 200
        network.assert_not_called()


def test_read_scope_cannot_dispatch_tools_call(native_as, tmp_path):
    token = native_as.issue("mcp:read")
    target = tmp_path / "scope-must-not-write.txt"
    with running_mcp(native_as.config) as address:
        assert rpc(address, token)[0] == 200
        with patch.object(server_http, "handle_fs_write",
                          wraps=server_http.handle_fs_write) as write:
            response = rpc(address, token, "tools/call", {
                "name": "fs_write",
                "arguments": {"path": str(target), "content": "forbidden"},
            })
            assert_unauthorized(response)
            write.assert_not_called()
    assert not target.exists()


def test_http_write_scope_allows_real_safe_tool_call(native_as):
    token = native_as.issue("mcp:read mcp:write")
    with running_mcp(native_as.config) as address:
        status, _headers, body = rpc(address, token, "tools/call", {
            "name": "echo", "arguments": {"message": "edg478-safe-call"},
        })
    assert status == 200
    assert body["id"] == "edg478-http"
    assert body["result"]["content"] == [
        {"type": "text", "text": "echo: edg478-safe-call"},
    ]


def test_native_mode_remains_default_off():
    config = server_http.HandcraftServerConfig(
        mcp_api_token="isolated-legacy-token", base_url="https://127.0.0.1",
    )
    assert config.edgar_native_as_enabled is False
    with running_mcp(config) as address:
        assert rpc(address, config.mcp_api_token)[0] == 200
