"""EDG-478 RED-first real native AS authorization-code JWT -> legacy MCP boundary.

These are deliberately narrow token-boundary tests, not a claim of /mcp E2E.
"""
import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

import server_http
from edgar_auth.app import Config, create_app


ISSUER = "https://issuer.edg478.test"
RESOURCE = "https://rs.edg478.test/mcp"
CALLBACK = "https://client.edg478.test/callback"


@pytest.fixture()
def native_token(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    app = create_app(Config(
        issuer=ISSUER, resource=RESOURCE,
        database=str(tmp_path / "edg478.db"), signing_key=pem,
    ))
    app.state.store.register_client("edg478-client", [CALLBACK], "none", None)
    client = TestClient(app, base_url=ISSUER, follow_redirects=False)
    session = app.state.store.create_session("edg478-subject")
    client.cookies.set("__Host-edgar-session", session,
                       domain="issuer.edg478.test", path="/")
    verifier = secrets.token_urlsafe(40)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    query = {
        "client_id": "edg478-client", "response_type": "code",
        "redirect_uri": CALLBACK, "resource": RESOURCE,
        "scope": "mcp:read", "state": "edg478-nonce",
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    authorization = client.get("/authorize", params=query)
    assert authorization.status_code == 303
    request_id = parse_qs(urlparse(authorization.headers["location"]).query)["request_id"][0]
    csrf = app.state.store.get_pending(request_id)["csrf"]
    consent = client.post("/consent", data={"request_id": request_id,
                                            "decision": "approve", "csrf": csrf})
    assert consent.status_code == 303
    code = parse_qs(urlparse(consent.headers["location"]).query)["code"][0]
    exchanged = client.post("/token", data={
        "grant_type": "authorization_code", "client_id": "edg478-client",
        "code": code, "redirect_uri": CALLBACK, "code_verifier": verifier,
        "resource": RESOURCE,
    })
    assert exchanged.status_code == 200
    token = exchanged.json()["access_token"]
    claims = jwt.decode(token, app.state.public_key, algorithms=["RS256"],
                        audience=RESOURCE, issuer=ISSUER)
    assert claims["scope"] == "mcp:read"
    config = server_http.HandcraftServerConfig(
        mcp_api_token="", base_url="https://rs.edg478.test",
        auth_server_url=ISSUER, descope_enabled=False,
        edgar_native_as_enabled=True,
        edgar_native_as_issuer=ISSUER,
        edgar_native_as_audience=RESOURCE,
        edgar_native_as_jwks_json=json.dumps(client.get("/jwks.json").json()),
        edgar_native_as_required_scope="mcp:read",
    )
    return token, config, pem


def test_native_edgar_jwt_accepted_without_descope(native_token):
    """RED in legacy RS: a genuine native AS JWT must pass its bearer boundary."""
    token, config, _pem = native_token
    assert server_http.bearer_token_is_authorized(token, "", config) is True


def test_tampered_native_edgar_jwt_rejected(native_token):
    token, config, _pem = native_token
    signed, sep, sig = token.rpartition(".")
    pos = len(sig) // 2
    altered = signed + sep + sig[:pos] + ("x" if sig[pos] != "x" else "y") + sig[pos + 1:]
    assert server_http.bearer_token_is_authorized(altered, "", config) is False


@pytest.mark.parametrize("field,new_value", [
    ("iss", "https://issuer.other.test"),
    ("aud", "https://another-resource.test/mcp"),
    ("scope", "mcp:write"),
])
def test_native_rejects_wrong_issuer_audience_or_scope(native_token, field, new_value):
    token, config, pem = native_token
    claims = jwt.decode(token, options={"verify_signature": False})
    header = jwt.get_unverified_header(token)
    claims[field] = new_value
    changed = jwt.encode(claims, pem, algorithm="RS256", headers={"kid": header["kid"]})
    assert server_http.bearer_token_is_authorized(changed, "", config) is False


def test_native_mode_does_not_allow_static_fallback(native_token):
    _token, config, _pem = native_token
    assert server_http.bearer_token_is_authorized("old-static-token", "old-static-token", config) is False


def test_native_mode_requires_explicit_trust_configuration(native_token):
    from dataclasses import replace
    token, config, _pem = native_token
    assert not server_http.bearer_token_is_authorized(
        token, "", replace(config, edgar_native_as_jwks_json="")
    )
