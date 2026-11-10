"""EDG-478: actual Contabo MCP TCP handler -> aka1 native EDGAR AS HTTPS.

Only synthetic fixture material. Does not access or modify production.
"""
import json
import os
import ssl
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unittest.mock import patch
import httpx
import jwt

from native_introspection import HTTPIntrospectionClient
import server_http
from test_edgar_native_http import assert_unauthorized, rpc, running_mcp

PUBLIC_CLIENT = "edg478-tls-public"


def run(bundle: Path, secret_file: Path):
    manifest = json.loads((bundle / "manifest.json").read_text())
    private = json.loads(secret_file.read_text())
    assert private["run_id"] == manifest["run_id"]
    assert manifest["issuer"] == manifest["origin"]
    assert manifest["resource"] == "https://rs.edg478.test/mcp"
    assert manifest["expires_at"] > time.time() + 10, "bridge expired"
    ca = bundle / "ca.crt"
    assert ca.is_file()
    os.environ["SSL_CERT_FILE"] = str(ca)
    verify_ctx = ssl.create_default_context(cafile=str(ca))
    origin = manifest["origin"]
    token = private["token"]
    assert token.count(".") == 2
    with httpx.Client(base_url=origin, verify=verify_ctx, timeout=3,
                      follow_redirects=False, trust_env=False) as as_client:
        health = as_client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["issuer"] == origin
        jwks_resp = as_client.get("/jwks.json")
        assert jwks_resp.status_code == 200
        jwks = jwks_resp.json()
        claims = jwt.decode(token, jwt.PyJWK.from_dict(jwks["keys"][0]).key,
                            algorithms=["RS256"], audience=manifest["resource"],
                            issuer=origin)
        assert claims["exp"] > time.time() + 10
        assert {"mcp:read", "mcp:write"}.issubset(set(claims["scope"].split()))
        introspection_client = HTTPIntrospectionClient(
            endpoint=origin + "/introspect",
            client_id=private["client_id"],
            client_secret=private["client_secret"], timeout=3)
        config = server_http.HandcraftServerConfig(
            mcp_api_token="", base_url="https://rs.edg478.test",
            auth_server_url=origin,
            edgar_native_as_enabled=True,
            edgar_native_as_issuer=origin,
            edgar_native_as_audience=manifest["resource"],
            edgar_native_as_jwks_json=json.dumps(jwks),
            edgar_native_as_introspect=introspection_client,
        )
        with tempfile.TemporaryDirectory(prefix="edg478-mcp-no-write-") as temp:
            target = Path(temp) / "forbidden.txt"
            with running_mcp(config) as address:
                before = rpc(address, token)
                assert before[0] == 200, f"tools/list pre-revoke={before[0]}"
                assert "tools" in before[2]["result"]
                before_call = rpc(address, token, "tools/call", {
                    "name":"echo", "arguments":{"message":"aka1-contabo-before-revoke"}})
                assert before_call[0] == 200
                assert "echo: aka1-contabo-before-revoke" in before_call[2]["result"]["content"][0]["text"]

                # The same valid JWT must not be accepted with incorrect issuer or audience.
                bad_aud = replace(config, edgar_native_as_audience="https://wrong-resource.edg478.test/mcp")
                with running_mcp(bad_aud) as wrong_listener:
                    assert_unauthorized(rpc(wrong_listener, token))
                bad_iss = replace(config, edgar_native_as_issuer="https://other-issuer.edg478.test")
                with running_mcp(bad_iss) as wrong_listener:
                    assert_unauthorized(rpc(wrong_listener, token))
                bad_confidential = replace(config, edgar_native_as_introspect=HTTPIntrospectionClient(
                    endpoint=origin + "/introspect", client_id=private["client_id"],
                    client_secret="incorrect-synthetic-secret", timeout=3))
                with running_mcp(bad_confidential) as wrong_listener:
                    assert_unauthorized(rpc(wrong_listener, token))

                response = as_client.post("/revoke", data={
                    "client_id": PUBLIC_CLIENT, "token": token,
                    "token_type_hint":"access_token"})
                assert response.status_code == 200, f"revoke={response.status_code}"
                inactive = as_client.post("/introspect", data={
                    "client_id": private["client_id"],
                    "client_secret": private["client_secret"], "token":token})
                assert inactive.status_code == 200
                assert inactive.json()["active"] is False
                assert claims["exp"] > time.time(), "revoked token also expired"
                after = rpc(address, token)
                assert_unauthorized(after)
                with patch.object(server_http, "handle_fs_write", wraps=server_http.handle_fs_write) as spy:
                    forbidden = rpc(address, token, "tools/call",{
                        "name":"fs_write","arguments":{"path":str(target),"content":"must not write"}})
                    assert_unauthorized(forbidden)
                    assert not spy.called and not target.exists()
                receipt={
                    "test":"EDG-478 Contabo actual MCP HTTP to aka1 EDGAR AS over verified WireGuard HTTPS",
                    "transport":"real two-host TLS plus actual Contabo MCPHTTPHandler localhost TCP",
                    "contabo_mcp_source":"edgarstool/edgars-mcp 02f6432",
                    "issuer":origin, "resource":manifest["resource"],
                    "as_health":health.status_code,
                    "before_list":before[0],"before_call":before_call[0],
                    "revoke":response.status_code,"introspect_active_after_revoke":False,
                    "after_list":after[0],"after_call":forbidden[0],
                    "wrong_aud_rejected":True,"wrong_iss_rejected":True,
                    "wrong_client_secret_rejected":True,
                    "unexpired":claims["exp"]>time.time(),
                    "no_write_side_effect":True,"tls_verified":True,
                    "production_changed":False,
                    "important_limitation":"synthetic fixture; MCP listens only on Contabo loopback, NOT public Knowledge MCP",
                }
                print(json.dumps(receipt,sort_keys=True),flush=True)


if __name__ == "__main__":
    if len(sys.argv)!=3:
        print("usage: run_crosshost_mcp.py /private/public_bundle /private/credentials",file=sys.stderr)
        raise SystemExit(2)
    run(Path(sys.argv[1]),Path(sys.argv[2]))
