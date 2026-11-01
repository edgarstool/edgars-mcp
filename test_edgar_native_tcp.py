"""Cross-process native AS -> real MCP TCP, using only ephemeral test state.

The HTTPS issuer is a claim, NOT the transport. Actual transport is loopback
HTTP. A seeded synthetic session bypasses login, not authorize/consent/PKCE.
"""

import base64
import hashlib
from html.parser import HTMLParser
import importlib
import json
import multiprocessing
import os
import secrets
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from edgar_auth.app import Config, create_app
import server_http
from test_edgar_native_http import assert_unauthorized, rpc, running_mcp


ISSUER = "https://issuer.edg478.test"
RESOURCE = "https://rs.edg478.test/mcp"
CALLBACK = "https://client.edg478.test/callback"
PUBLIC_CLIENT = "edg478-tcp-public"
RS_CLIENT = "edg478-tcp-confidential"


def _serve_native_as(listener, pipe, database, pem, secret):
    """Spawn target: create the real app and all credentials only in the fixture."""
    app = create_app(Config(
        issuer=ISSUER, resource=RESOURCE, database=database, signing_key=pem,
    ))
    store = app.state.store
    store.register_client(PUBLIC_CLIENT, [CALLBACK], "none", None)
    store.register_client(RS_CLIENT, [CALLBACK], "client_secret_post", secret)
    pipe.send(store.create_session("edg478-tcp-synthetic-subject"))
    pipe.close()
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="critical",
        access_log=False, timeout_graceful_shutdown=1,
    ))
    server.run(sockets=[listener])


def _stop_process(process):
    if process.is_alive():
        process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
    assert not process.is_alive(), "native AS process did not stop"


class _HiddenInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("type") == "hidden":
            self.fields[attrs["name"]] = attrs.get("value", "")


def _adapter(endpoint, secret, timeout=1.0, **kwargs):
    # Lazy import keeps RED a test failure after genuine TCP issuance, rather
    # than a collection failure or a skipped test when the adapter is missing.
    module = importlib.import_module("native_introspection")
    return module.HTTPIntrospectionClient(
        endpoint=endpoint, client_id=RS_CLIENT, client_secret=secret,
        timeout=timeout, **kwargs,
    )


@dataclass(repr=False)
class NativeTCP:
    client: httpx.Client
    process: object
    pem: str
    secret: str
    endpoint: str
    jwks: dict

    def adapter(self, secret=None):
        return _adapter(self.endpoint, self.secret if secret is None else secret,
                        allow_loopback_http=True)

    def config(self, secret=None):
        return server_http.HandcraftServerConfig(
            mcp_api_token="", base_url="https://rs.edg478.test",
            auth_server_url=ISSUER, edgar_native_as_enabled=True,
            edgar_native_as_issuer=ISSUER, edgar_native_as_audience=RESOURCE,
            edgar_native_as_jwks_json=json.dumps(self.jwks),
            edgar_native_as_introspect=self.adapter(secret),
        )

    def issue(self, scope="mcp:read mcp:write"):
        verifier = secrets.token_urlsafe(40)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        authorization = self.client.get("/authorize", params={
            "client_id": PUBLIC_CLIENT, "response_type": "code",
            "redirect_uri": CALLBACK, "resource": RESOURCE, "scope": scope,
            "state": "edg478-tcp-state", "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        assert authorization.status_code == 303
        location = authorization.headers["location"]
        assert location.startswith("/consent?")
        request_id = parse_qs(urlparse(location).query)["request_id"][0]
        page = self.client.get("/consent", params={"request_id": request_id})
        assert page.status_code == 200
        parser = _HiddenInputs()
        parser.feed(page.text)
        assert parser.fields["request_id"] == request_id
        consent = self.client.post("/consent", data={
            **parser.fields, "decision": "approve",
        })
        assert consent.status_code == 303
        redirect = urlparse(consent.headers["location"])
        assert redirect._replace(query="").geturl() == CALLBACK
        query = parse_qs(redirect.query)
        assert query["state"] == ["edg478-tcp-state"]
        exchanged = self.client.post("/token", data={
            "grant_type": "authorization_code", "client_id": PUBLIC_CLIENT,
            "code": query["code"][0], "redirect_uri": CALLBACK,
            "code_verifier": verifier, "resource": RESOURCE,
        })
        assert exchanged.status_code == 200
        return exchanged.json()["access_token"]

    def claims(self, token):
        key = jwt.PyJWK.from_dict(self.jwks["keys"][0]).key
        return jwt.decode(token, key, algorithms=["RS256"],
                          issuer=ISSUER, audience=RESOURCE)

    def introspect(self, token, secret=None, client_id=RS_CLIENT):
        return self.client.post("/introspect", data={
            "client_id": client_id,
            "client_secret": self.secret if secret is None else secret,
            "token": token,
        })

    def stop(self):
        _stop_process(self.process)


@pytest.fixture
def native_tcp(tmp_path, monkeypatch):
    # No inherited provider flags, credentials, proxies or production config.
    for name in tuple(os.environ):
        monkeypatch.delenv(name)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    secret = secrets.token_urlsafe(32)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    process = context.Process(
        target=_serve_native_as,
        args=(listener, child, str(tmp_path / "as.sqlite3"), pem, secret),
    )
    try:
        process.start()
        child.close()
        listener.close()  # Child owns the socket; no port-probe/rebind race.
        assert process.pid != os.getpid()
        assert parent.poll(10), "native AS bootstrap timed out"
        session = parent.recv()
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=1,
            follow_redirects=False, trust_env=False,
            # Test-only raw cookie on HTTP. This is NOT Secure-cookie/TLS proof.
            headers={"Cookie": f"__Host-edgar-session={session}"},
        ) as client:
            deadline = time.monotonic() + 10
            while True:
                assert process.is_alive(), "native AS exited before readiness"
                try:
                    health = client.get("/healthz")
                    if health.status_code == 200:
                        assert health.json()["issuer"] == ISSUER
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "AS readiness timed out"
                time.sleep(0.02)
            jwks = client.get("/jwks.json")
            assert jwks.status_code == 200
            yield NativeTCP(client, process, pem, secret,
                            f"http://127.0.0.1:{port}/introspect", jwks.json())
    finally:
        child.close()
        listener.close()
        parent.close()
        if process.pid is not None:
            _stop_process(process)
        process.close()
        for suffix in ("", "-wal", "-shm"):
            (tmp_path / f"as.sqlite3{suffix}").unlink(missing_ok=True)


def test_cross_process_same_unexpired_jwt_revoked(native_tcp, tmp_path):
    token = native_tcp.issue()
    claims = native_tcp.claims(token)
    active = native_tcp.introspect(token)
    assert active.status_code == 200
    assert active.json()["active"] is True
    target = tmp_path / "revoked-must-not-write.txt"
    with running_mcp(native_tcp.config()) as address:
        before = rpc(address, token)
        echo = rpc(address, token, "tools/call", {
            "name": "echo", "arguments": {"message": "cross-process"},
        })
        assert before[0] == echo[0] == 200
        assert any(t["name"] == "echo" for t in before[2]["result"]["tools"])
        assert echo[2]["result"]["content"] == [
            {"type": "text", "text": "echo: cross-process"},
        ]
        revoked = native_tcp.client.post("/revoke", data={
            "client_id": PUBLIC_CLIENT, "token": token,
            "token_type_hint": "access_token",
        })
        assert revoked.status_code == 200
        inactive = native_tcp.introspect(token)
        assert inactive.status_code == 200
        assert inactive.json() == {"active": False}
        assert native_tcp.claims(token) == claims
        assert claims["exp"] > time.time()
        after = rpc(address, token)
        write = rpc(address, token, "tools/call", {
            "name": "fs_write",
            "arguments": {"path": str(target), "content": "must not write"},
        })
        assert_unauthorized(after)
        assert_unauthorized(write)
        assert not target.exists()
    print("TCP_EVIDENCE " + json.dumps({
        "separate_as_process": native_tcp.process.pid != os.getpid(),
        "as_transport": "loopback HTTP, not TLS",
        "claimed_issuer": ISSUER, "authenticated_introspect": active.status_code,
        "before_list": before[0], "before_echo": echo[0],
        "as_revoke": revoked.status_code,
        "after_list": after[0], "after_fs_write": write[0],
        "same_unexpired_jwt": claims["exp"] > time.time(),
        "no_write": not target.exists(),
    }, sort_keys=True))


def test_confidential_credentials_control_over_tcp(native_tcp):
    token = native_tcp.issue()
    assert native_tcp.introspect(token).json()["active"] is True
    wrong = native_tcp.introspect(token, secret="synthetic-wrong-secret")
    public = native_tcp.introspect(token, client_id=PUBLIC_CLIENT)
    bearer_only = native_tcp.client.post("/introspect", data={"token": token},
                                         headers={"Authorization": f"Bearer {token}"})
    assert wrong.status_code == public.status_code == bearer_only.status_code == 401
    with running_mcp(native_tcp.config(secret="synthetic-wrong-secret")) as address:
        denied = rpc(address, token)
        assert_unauthorized(denied)
    print("CREDENTIAL_EVIDENCE " + json.dumps({
        "valid_confidential": 200, "wrong_secret_as": wrong.status_code,
        "public_client_as": public.status_code, "bearer_only_as": bearer_only.status_code,
        "wrong_secret_mcp": denied[0],
    }, sort_keys=True))


def test_real_as_process_outage_fails_closed(native_tcp, tmp_path):
    token = native_tcp.issue()
    target = tmp_path / "outage-must-not-write.txt"
    with running_mcp(native_tcp.config()) as address:
        assert rpc(address, token)[0] == 200
        native_tcp.stop()
        assert not native_tcp.process.is_alive()
        with pytest.raises(httpx.TransportError):
            native_tcp.client.get("/healthz")
        started = time.monotonic()
        denied = rpc(address, token)
        write = rpc(address, token, "tools/call", {
            "name": "fs_write",
            "arguments": {"path": str(target), "content": "must not write"},
        })
        elapsed = time.monotonic() - started
        assert_unauthorized(denied)
        assert_unauthorized(write)
        assert elapsed < 4
        assert not target.exists()
    print("OUTAGE_EVIDENCE " + json.dumps({
        "as_stopped": True, "before_list": 200,
        "after_list": denied[0], "after_fs_write": write[0],
        "no_write": not target.exists(), "bounded_under_4s": elapsed < 4,
    }, sort_keys=True))


@pytest.mark.parametrize("field,value", [
    ("iss", "https://wrong-issuer.edg478.test"),
    ("aud", "https://wrong-resource.edg478.test/mcp"),
    ("scope", "mcp:write"),
])
def test_cross_process_wrong_signed_claims_denied(native_tcp, field, value):
    original = native_tcp.issue()
    claims = native_tcp.claims(original)
    claims[field] = value
    token = jwt.encode(claims, native_tcp.pem, algorithm="RS256",
                       headers=jwt.get_unverified_header(original))
    with running_mcp(native_tcp.config()) as address:
        assert_unauthorized(rpc(address, token))
        assert_unauthorized(rpc(address, token, "tools/call", {
            "name": "echo", "arguments": {"message": "must not dispatch"},
        }))


def test_cross_process_read_scope_cannot_call(native_tcp, tmp_path):
    token = native_tcp.issue("mcp:read")
    assert native_tcp.introspect(token).json()["active"] is True
    target = tmp_path / "read-must-not-write.txt"
    with running_mcp(native_tcp.config()) as address:
        assert rpc(address, token)[0] == 200
        assert_unauthorized(rpc(address, token, "tools/call", {
            "name": "echo", "arguments": {"message": "must not dispatch"},
        }))
        assert_unauthorized(rpc(address, token, "tools/call", {
            "name": "fs_write",
            "arguments": {"path": str(target), "content": "must not write"},
        }))
    assert not target.exists()


def test_token_header_url_does_not_select_transport(native_tcp):
    original = native_tcp.issue()
    token = jwt.encode(
        native_tcp.claims(original), native_tcp.pem, algorithm="RS256",
        headers={**jwt.get_unverified_header(original),
                 "jku": "http://127.0.0.1:1/attacker-keys"},
    )
    # Genuine AS introspection accepts the signature. An adapter following jku
    # would connect to the wrong endpoint and fail this positive TCP request.
    with running_mcp(native_tcp.config()) as address:
        assert rpc(address, token)[0] == 200


@pytest.mark.parametrize("endpoint,kwargs", [
    ("http://127.0.0.1:1/introspect", {}),
    ("http://example.test/introspect", {"allow_loopback_http": True}),
    ("http://localhost:1/introspect", {"allow_loopback_http": True}),
    ("https://user:password@example.test/introspect", {}),
    ("https://example.test/introspect?token=bad", {}),
    ("https://example.test/introspect#fragment", {}),
    ("file:///tmp/introspect", {}),
    ("https://example.test:0/introspect", {}),
    ("https://example.test:99999/introspect", {}),
    ("https://example.test/\nintrospect", {}),
])
def test_adapter_rejects_unsafe_operator_endpoint(endpoint, kwargs):
    with pytest.raises(ValueError):
        _adapter(endpoint, "synthetic-only", **kwargs)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), 31])
def test_adapter_requires_finite_bounded_timeout(timeout):
    with pytest.raises(ValueError):
        _adapter("https://issuer.edg478.test/introspect", "synthetic-only",
                 timeout=timeout)


@contextmanager
def _protocol_fault_server(kind):
    """Real TCP fault peer, never used as native AS success evidence."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append((self.path, dict(self.headers), parse_qs(raw.decode())))
            if kind == "timeout":
                time.sleep(0.3)
            if kind == "redirect":
                self.send_response(307)
                self.send_header("Location", "/credential-sink")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            body = {
                "malformed": b"not JSON",
                "array": b"[]",
                "string-active": b'{"active":"true"}',
                "oversized": b"x" * 65537,
            }.get(kind, b'{"active":false}')
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/introspect", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize("kind", [
    "redirect", "timeout", "malformed", "array", "string-active", "oversized",
])
def test_adapter_real_tcp_protocol_faults_fail_closed(kind, monkeypatch):
    module = importlib.import_module("native_introspection")
    # Proxy environment must not receive credentials or tokens.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with _protocol_fault_server(kind) as (endpoint, received):
        adapter = _adapter(endpoint, "synthetic-test-secret", timeout=0.1,
                           allow_loopback_http=True)
        started = time.monotonic()
        with pytest.raises(module.IntrospectionError) as error:
            adapter("synthetic-test-token")
        assert time.monotonic() - started < 2
        assert "synthetic-test-secret" not in str(error.value)
        assert "synthetic-test-token" not in str(error.value)
        assert "synthetic-test-secret" not in repr(adapter)
        assert len(received) == 1  # No redirects, retries or proxy.
        path, headers, form = received[0]
        assert path == "/introspect"
        assert "Authorization" not in headers  # Not bearer passthrough.
        assert form == {
            "client_id": [RS_CLIENT], "client_secret": ["synthetic-test-secret"],
            "token": ["synthetic-test-token"], "token_type_hint": ["access_token"],
        }


def test_adapter_does_not_auto_enable_native_mode():
    adapter = _adapter("https://issuer.edg478.test/introspect", "synthetic-only")
    config = server_http.HandcraftServerConfig(
        mcp_api_token="", base_url="https://rs.edg478.test",
    )
    assert config.edgar_native_as_enabled is False
    assert replace(config, edgar_native_as_introspect=adapter).edgar_native_as_enabled is False
