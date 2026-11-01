"""Portable, standard-library-only consumer of the real native AS TLS bridge.

Packaged with the UNMODIFIED native_introspection.py in probe.pyz. Never print
tokens, credentials, cookies, response bodies, or exception details.
"""

import argparse
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import stat
import time
from urllib.parse import urlsplit

import native_introspection


HOST = "10.77.0.11"
RESERVED_PORTS = {18081, 18443, 18444, 18445}


class ProbeFailure(RuntimeError):
    """Only fixed, non-sensitive messages may be supplied."""


def require(condition, message):
    if not condition:
        raise ProbeFailure(message)


def json_digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@contextmanager
def trust_test_ca(cafile):
    # The real adapter uses Python's DEFAULT verified HTTPSConnection, which
    # reads these OpenSSL trust-store variables. No adapter patch or TLS bypass.
    names = ("SSL_CERT_FILE", "SSL_CERT_DIR")
    old = {name: os.environ.get(name) for name in names}
    os.environ["SSL_CERT_FILE"] = str(cafile)
    os.environ["SSL_CERT_DIR"] = str(Path(cafile).parent / "no-system-ca-directory")
    try:
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def get_json(origin, path, context):
    url = urlsplit(origin)
    connection = http.client.HTTPSConnection(
        url.hostname, url.port, timeout=3, context=context,
    )
    try:
        connection.connect()
        source = connection.sock.getsockname()[0]
        peer = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        require(response.status == 200, "native API did not return HTTP 200")
        raw = response.read(65537)
        require(len(raw) <= 65536, "native API response too large")
        return json.loads(raw), source, peer
    finally:
        connection.close()


def run_probe(bundle, credentials=None, expect_source="10.77.0.8"):
    bundle = Path(bundle).resolve()
    require(expect_source in (HOST, "10.77.0.8"), "unsupported client source IP")
    manifest = json.loads((bundle / "manifest.json").read_text())
    require(manifest["schema"] == 1, "unsupported manifest schema")
    url = urlsplit(manifest["origin"])
    require(
        url.scheme == "https" and url.hostname == HOST
        and url.port is not None and 0 < url.port <= 65535
        and url.port not in RESERVED_PORTS and not url.username and not url.password
        and not url.path and not url.query and not url.fragment
        and manifest["issuer"] == manifest["origin"],
        "unsafe bridge origin",
    )
    require(0 < manifest["expires_at"] - time.time() <= 660, "bridge expired or invalid lifetime")
    adapter_source = native_introspection.__loader__.get_data(native_introspection.__file__)
    require(
        hashlib.sha256(adapter_source).hexdigest() == manifest["adapter_sha256"],
        "native adapter source fingerprint mismatch",
    )
    for filename, field in (("ca.crt", "ca_sha256"), ("wrong-ca.crt", "wrong_ca_sha256")):
        require(
            hashlib.sha256((bundle / filename).read_bytes()).hexdigest() == manifest[field],
            "CA fingerprint mismatch",
        )

    good_context = ssl.create_default_context(cafile=str(bundle / "ca.crt"))
    bad_context = ssl.create_default_context(cafile=str(bundle / "wrong-ca.crt"))
    # Only an actual certificate verification error counts as wrong-CA rejection.
    try:
        get_json(manifest["origin"], "/jwks.json", bad_context)
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise ProbeFailure("wrong CA unexpectedly trusted")

    # Same pinned CA and real socket, deliberately wrong hostname/SAN.
    try:
        with socket.create_connection((HOST, url.port), timeout=3) as raw:
            with good_context.wrap_socket(raw, server_hostname="not-aka1.edg478.test"):
                pass
    except ssl.SSLCertVerificationError as error:
        require(error.verify_code in (62, 64), "wrong SAN failed for unexpected reason")
    else:
        raise ProbeFailure("wrong SAN unexpectedly trusted")

    jwks, source, peer = get_json(manifest["origin"], "/jwks.json", good_context)
    require(source == expect_source, "unexpected client source IP")
    require(peer == manifest["server_cert_sha256"], "server certificate fingerprint mismatch")
    require(isinstance(jwks, dict) and len(jwks.get("keys", [])) == 1, "invalid native JWKS")
    require(json_digest(jwks) == manifest["jwks_sha256"], "native JWKS fingerprint mismatch")
    key = jwks["keys"][0]
    require(
        key.get("kty") == "RSA" and key.get("alg") == "RS256"
        and key.get("kid") == manifest["jwks_kid"]
        and not any(name in key for name in ("d", "p", "q")),
        "invalid native public key",
    )
    health, health_source, _ = get_json(manifest["origin"], "/healthz", good_context)
    require(
        health_source == source and health.get("ok") is True
        and health.get("role") == "authorization_server"
        and health.get("identity") == "native" and health.get("issuer") == manifest["issuer"],
        "native AS identity mismatch",
    )

    active = None
    adapter_wrong_ca = None
    if credentials is not None:
        credentials = Path(credentials)
        mode = credentials.stat()
        require(
            stat.S_ISREG(mode.st_mode) and mode.st_mode & 0o777 == 0o600
            and mode.st_uid == os.getuid() and mode.st_size <= 16384,
            "credentials must be an owned mode-0600 regular file",
        )
        private = json.loads(credentials.read_text())
        require(private["run_id"] == manifest["run_id"], "credentials belong to another run")
        adapter = native_introspection.HTTPIntrospectionClient(
            endpoint=manifest["origin"] + "/introspect",
            client_id=private["client_id"], client_secret=private["client_secret"],
            timeout=3,
        )
        with trust_test_ca(bundle / "wrong-ca.crt"):
            try:
                adapter(private["token"])
            except native_introspection.IntrospectionError:
                adapter_wrong_ca = True
            else:
                raise ProbeFailure("native adapter accepted wrong CA")
        with trust_test_ca(bundle / "ca.crt"):
            try:
                status = adapter(private["token"])
            except native_introspection.IntrospectionError:
                raise ProbeFailure("native introspection failed") from None
        require(status.get("active") is True, "native introspection not active")
        require(
            all(status.get(name) == value for name, value in private["claims"].items()),
            "native introspection claims mismatch",
        )
        require(status["exp"] > time.time(), "native token expired")
        active = True

    return {
        "run_id": manifest["run_id"], "origin": manifest["origin"],
        "client_source_ip": source, "tls_chain_verified": True,
        "wrong_ca_rejected": True, "wrong_san_rejected": True,
        "server_cert_sha256": peer, "jwks_sha256": json_digest(jwks),
        "jwks_matches_native_as": True, "adapter_sha256": manifest["adapter_sha256"],
        "native_introspection_active": active,
        "adapter_wrong_ca_rejected": adapter_wrong_ca,
        "cross_host_verified": source == "10.77.0.8",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--credentials", help="Optional private mode-0600 test input; never print it")
    parser.add_argument("--expect-source", default="10.77.0.8", choices=(HOST, "10.77.0.8"))
    args = parser.parse_args()
    try:
        evidence = run_probe(args.bundle, args.credentials, args.expect_source)
    except ProbeFailure as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 1
    except Exception as error:
        # Never emit arbitrary exception messages, bodies or tracebacks.
        print(json.dumps({"ok": False, "error": "probe failed", "type": type(error).__name__}))
        return 1
    print(json.dumps({"ok": True, **evidence}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
