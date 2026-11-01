"""Bounded nonproduction native EDGAR AS, listening ONLY on aka1's VPN IP."""

import argparse
import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse
import zipfile

import httpx
import jwt
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edgar_auth.app import Config, create_app
from scripts.edg478_tls_probe import HOST, RESERVED_PORTS, json_digest, trust_test_ca


RESOURCE = "https://rs.edg478.test/mcp"
CALLBACK = "https://client.edg478.test/callback"
PUBLIC_CLIENT = "edg478-tls-public"
RS_CLIENT = "edg478-tls-confidential"


def _write_private(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
        file.write(content)


def _key_bytes(key):
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _make_ca(now):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EDG478 ephemeral test CA")])
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(seconds=30))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _certificates(runtime, public):
    now = datetime.now(timezone.utc)
    ca_key, ca = _make_ca(now)
    _, wrong_ca = _make_ca(now)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EDG478 aka1 test AS")]))
        .issuer_name(ca.subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(seconds=30))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                       critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(HOST))]),
                       critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    # CA keys never leave memory. Only the TLS leaf key is needed by uvicorn.
    _write_private(runtime / "tls-private", _key_bytes(key))
    _write_private(runtime / "tls.crt", cert.public_bytes(serialization.Encoding.PEM))
    (public / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (public / "wrong-ca.crt").write_bytes(wrong_ca.public_bytes(serialization.Encoding.PEM))
    return cert.fingerprint(hashes.SHA256()).hex()


def _serve_native_as(listener, pipe, runtime, origin, secret, ttl):
    # Mirrors native_tcp fixture: genuine create_app, isolated Store, synthetic
    # login session, real consent/PKCE/issuance/introspection. No added routes.
    os.environ.clear()
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = create_app(Config(
        issuer=origin, resource=RESOURCE,
        database=str(Path(runtime) / "as.sqlite3"),
        signing_key=_key_bytes(signing).decode(),
    ))
    store = app.state.store
    store.register_client(PUBLIC_CLIENT, [CALLBACK], "none", None)
    store.register_client(RS_CLIENT, [CALLBACK], "client_secret_post", secret)
    pipe.send(store.create_session("edg478-tls-synthetic-subject"))
    pipe.close()
    server = uvicorn.Server(uvicorn.Config(
        app, host=HOST, port=0, log_level="critical", access_log=False,
        ssl_keyfile=str(Path(runtime) / "tls-private"),
        ssl_certfile=str(Path(runtime) / "tls.crt"),
        timeout_graceful_shutdown=1,
    ))
    # A child-side deadline still stops the listener if the parent is killed.
    timer = threading.Timer(ttl, lambda: setattr(server, "should_exit", True))
    timer.daemon = True
    timer.start()
    try:
        server.run(sockets=[listener])
    finally:
        timer.cancel()
        listener.close()


class _HiddenInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("type") == "hidden":
            self.fields[attrs["name"]] = attrs.get("value", "")


def _check(condition, message):
    if not condition:
        raise RuntimeError(message)


def _issue(client):
    # Same real HTTP flow as NativeTCP.issue; only the seeded login is synthetic.
    verifier = secrets.token_urlsafe(40)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    authorization = client.get("/authorize", params={
        "client_id": PUBLIC_CLIENT, "response_type": "code", "redirect_uri": CALLBACK,
        "resource": RESOURCE, "scope": "mcp:read mcp:write", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    _check(authorization.status_code == 303, "native authorization failed")
    location = authorization.headers["location"]
    _check(location.startswith("/consent?"), "native consent redirect failed")
    request_id = parse_qs(urlparse(location).query)["request_id"][0]
    page = client.get("/consent", params={"request_id": request_id})
    _check(page.status_code == 200, "native consent page failed")
    parser = _HiddenInputs()
    parser.feed(page.text)
    _check(parser.fields.get("request_id") == request_id, "native consent form failed")
    consent = client.post("/consent", data={**parser.fields, "decision": "approve"})
    _check(consent.status_code == 303, "native consent failed")
    redirect = urlparse(consent.headers["location"])
    _check(redirect._replace(query="").geturl() == CALLBACK, "native callback failed")
    query = parse_qs(redirect.query)
    _check(query.get("state") == [state], "native OAuth state failed")
    exchanged = client.post("/token", data={
        "grant_type": "authorization_code", "client_id": PUBLIC_CLIENT,
        "code": query["code"][0], "redirect_uri": CALLBACK,
        "code_verifier": verifier, "resource": RESOURCE,
    })
    _check(exchanged.status_code == 200, "native code exchange failed")
    return exchanged.json()["access_token"]


@dataclass(repr=False)
class Bridge:
    runtime: Path
    public_dir: Path
    credentials_file: Path
    process: object
    client: httpx.Client
    port: int
    manifest: dict
    host: str = HOST
    stopped: bool = False
    _token: str = field(default="", repr=False)

    def revoke(self):
        response = self.client.post("/revoke", data={
            "client_id": PUBLIC_CLIENT, "token": self._token,
            "token_type_hint": "access_token",
        })
        _check(response.status_code == 200, "native revocation failed")


def _stop(process):
    if process.pid is None:
        return
    if process.is_alive():
        process.terminate()
    process.join(timeout=3)
    if process.is_alive():
        process.kill()
        process.join(timeout=3)
    _check(not process.is_alive(), "test AS process did not stop")


@contextmanager
def running_bridge(runtime_parent="/tmp", ttl=180, bind_ip=HOST):
    if bind_ip != HOST:
        raise ValueError("only aka1 VPN IP is allowed")
    if type(ttl) is not int or not 1 <= ttl <= 300:
        raise ValueError("test lifetime must be an integer in [1, 300]")
    parent_dir = Path(runtime_parent).resolve()
    if any((ancestor / ".git").exists() for ancestor in (parent_dir, *parent_dir.parents)):
        raise ValueError("private runtime must be outside Git repositories")
    with tempfile.TemporaryDirectory(prefix="edg478-tls-", dir=parent_dir) as directory:
        runtime = Path(directory)
        public = runtime / "public"
        public.mkdir(mode=0o700)
        cert_hash = _certificates(runtime, public)
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        process = None
        bridge = None
        client = None
        try:
            # Hold the SAME socket across spawn: no probe/rebind race.
            listener.bind((bind_ip, 0))
            listener.listen(32)
            port = listener.getsockname()[1]
            _check(port not in RESERVED_PORTS, "reserved mail port refused")
            origin = f"https://{HOST}:{port}"
            secret = secrets.token_urlsafe(32)
            expires = int(time.time()) + ttl
            process = context.Process(
                target=_serve_native_as,
                args=(listener, child, runtime, origin, secret, ttl),
            )
            process.start()
            child.close()
            listener.close()
            _check(parent.poll(10), "native TLS AS bootstrap timed out")
            session = parent.recv()
            import ssl
            client = httpx.Client(
                base_url=origin, timeout=2, follow_redirects=False, trust_env=False,
                verify=ssl.create_default_context(cafile=str(public / "ca.crt")),
                headers={"Cookie": f"__Host-edgar-session={session}"},
            )
            deadline = time.monotonic() + 10
            while True:
                _check(process.is_alive(), "native TLS AS exited before readiness")
                try:
                    health = client.get("/healthz")
                    if health.status_code == 200 and health.json().get("issuer") == origin:
                        break
                except httpx.TransportError:
                    pass
                _check(time.monotonic() < deadline, "native TLS AS readiness timed out")
                time.sleep(0.02)
            jwks_response = client.get("/jwks.json")
            _check(jwks_response.status_code == 200, "native JWKS failed")
            jwks = jwks_response.json()
            token = _issue(client)
            claims = jwt.decode(
                token, jwt.PyJWK.from_dict(jwks["keys"][0]).key,
                algorithms=["RS256"], issuer=origin, audience=RESOURCE,
            )
            adapter_source = (ROOT / "native_introspection.py").read_bytes()
            with zipfile.ZipFile(public / "probe.pyz", "x", compression=zipfile.ZIP_DEFLATED) as package:
                package.writestr("__main__.py", Path(__file__).with_name("edg478_tls_probe.py").read_bytes())
                package.writestr("native_introspection.py", adapter_source)
            manifest = {
                "schema": 1, "run_id": secrets.token_hex(12), "origin": origin,
                "issuer": origin, "resource": RESOURCE, "expires_at": expires,
                "jwks_sha256": json_digest(jwks), "jwks_kid": jwks["keys"][0]["kid"],
                "server_cert_sha256": cert_hash,
                "adapter_sha256": hashlib.sha256(adapter_source).hexdigest(),
                "ca_sha256": hashlib.sha256((public / "ca.crt").read_bytes()).hexdigest(),
                "wrong_ca_sha256": hashlib.sha256((public / "wrong-ca.crt").read_bytes()).hexdigest(),
                "probe_sha256": hashlib.sha256((public / "probe.pyz").read_bytes()).hexdigest(),
            }
            (public / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
            credentials_file = runtime / "private-probe-input.json"
            _write_private(credentials_file, json.dumps({
                "run_id": manifest["run_id"], "client_id": RS_CLIENT,
                "client_secret": secret, "token": token,
                "claims": {name: claims[name] for name in (
                    "iss", "sub", "aud", "exp", "iat", "scope", "client_id",
                )},
            }).encode())
            bridge = Bridge(runtime, public, credentials_file, process, client, port, manifest, _token=token)
            yield bridge
        finally:
            child.close()
            listener.close()
            parent.close()
            if client is not None:
                client.close()
            if process is not None:
                _stop(process)
                process.close()
            if bridge is not None:
                bridge.stopped = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ttl", type=int, default=180, help="Hard child lifetime, 1..300 seconds")
    parser.add_argument("--runtime-parent", default="/tmp", help="Existing directory outside any Git repository")
    args = parser.parse_args()

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupted)
    try:
        with running_bridge(args.runtime_parent, args.ttl) as bridge:
            local = subprocess.run([
                sys.executable, "-I", "-S", str(bridge.public_dir / "probe.pyz"),
                "--bundle", str(bridge.public_dir), "--expect-source", HOST,
                "--credentials", str(bridge.credentials_file),
            ], capture_output=True, text=True, timeout=15, env={
                "PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
            })
            _check(local.returncode == 0, "portable local TLS self-check failed")
            print(json.dumps({
                "event": "READY", "public_bundle": str(bridge.public_dir),
                "private_input": str(bridge.credentials_file),
                "manifest": bridge.manifest,
                "local_only_evidence": json.loads(local.stdout),
                "cross_host_status": "PENDING_CONTROLLER",
            }, sort_keys=True), flush=True)
            bridge.process.join(timeout=args.ttl + 5)
            _check(not bridge.process.is_alive(), "native TLS AS lifetime exceeded")
            _check(bridge.process.exitcode == 0, "native TLS AS exited unexpectedly")
    except KeyboardInterrupt:
        print(json.dumps({"event": "STOPPED", "cleanup": "complete"}), flush=True)
        return 130
    except Exception as error:
        print(json.dumps({"event": "ERROR", "type": type(error).__name__}), flush=True)
        return 1
    print(json.dumps({"event": "EXPIRED", "cleanup": "complete"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
