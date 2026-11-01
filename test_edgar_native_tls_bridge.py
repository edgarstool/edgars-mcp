"""Real native AS TLS on aka1's VPN IP, not a cross-host success claim."""

import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import zipfile

import pytest
from cryptography import x509


HOST = "10.77.0.11"
ROOT = Path(__file__).resolve().parent


def harness():
    # RED must be an actionable failing test, not a collection error or skip.
    return importlib.import_module("scripts.edg478_tls_bridge")


def probe(bridge, *, credentials=True, source=HOST):
    command = [
        sys.executable, "-I", "-S", str(bridge.public_dir / "probe.pyz"),
        "--bundle", str(bridge.public_dir), "--expect-source", source,
    ]
    if credentials:
        command += ["--credentials", str(bridge.credentials_file)]
    return subprocess.run(command, capture_output=True, text=True, timeout=15)


def test_real_native_as_tls_and_portable_actual_adapter(tmp_path, monkeypatch):
    module = harness()
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/inherited-ca")
    monkeypatch.setenv("NO_PROXY", "")
    with module.running_bridge(runtime_parent=tmp_path, ttl=30) as bridge:
        runtime, port = bridge.runtime, bridge.port
        assert bridge.process.pid != os.getpid()
        assert bridge.host == HOST
        assert port not in {18081, 18443, 18444, 18445}
        assert bridge.manifest["origin"] == f"https://{HOST}:{port}"
        assert bridge.manifest["issuer"] == bridge.manifest["origin"]
        actual_source = (ROOT / "native_introspection.py").read_bytes()
        assert bridge.manifest["adapter_sha256"] == hashlib.sha256(actual_source).hexdigest()
        with zipfile.ZipFile(bridge.public_dir / "probe.pyz") as package:
            assert set(package.namelist()) == {"__main__.py", "native_introspection.py"}
            assert package.read("native_introspection.py") == actual_source
        assert {p.name for p in bridge.public_dir.iterdir()} == {
            "ca.crt", "wrong-ca.crt", "manifest.json", "probe.pyz",
        }
        assert runtime.stat().st_mode & 0o777 == 0o700
        assert bridge.credentials_file.stat().st_mode & 0o777 == 0o600
        cert = x509.load_pem_x509_certificate(
            (bridge.public_dir / "ca.crt").read_bytes()
        )
        assert (cert.not_valid_after_utc - cert.not_valid_before_utc).total_seconds() <= 660

        result = probe(bridge)
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(result.stdout)
        assert evidence["tls_chain_verified"] is True
        assert evidence["wrong_ca_rejected"] is True
        assert evidence["wrong_san_rejected"] is True
        assert evidence["jwks_matches_native_as"] is True
        assert evidence["native_introspection_active"] is True
        assert evidence["adapter_wrong_ca_rejected"] is True
        assert evidence["client_source_ip"] == HOST
        assert evidence["cross_host_verified"] is False
        private = json.loads(bridge.credentials_file.read_text())
        for value in (private["token"], private["client_secret"]):
            assert value not in result.stdout + result.stderr
            for public_file in bridge.public_dir.iterdir():
                assert value.encode() not in public_file.read_bytes()
        assert "__Host-edgar-session" not in result.stdout + result.stderr

        # A local run cannot label itself a Contabo cross-host verification.
        refused = probe(bridge, source="10.77.0.8")
        assert refused.returncode == 1
        assert json.loads(refused.stdout)["error"] == "unexpected client source IP"

        # Same real AS token, now revoked. The real adapter must not cache True.
        bridge.revoke()
        with module.trust_test_ca(bridge.public_dir / "ca.crt"):
            from native_introspection import HTTPIntrospectionClient
            status = HTTPIntrospectionClient(
                endpoint=bridge.manifest["origin"] + "/introspect",
                client_id=private["client_id"], client_secret=private["client_secret"],
            )(private["token"])
        assert status == {"active": False}
        rejected = probe(bridge)
        assert rejected.returncode == 1
        assert json.loads(rejected.stdout)["error"] == "native introspection not active"
        print("TLS_LOCAL_EVIDENCE " + json.dumps(evidence, sort_keys=True))

    assert bridge.stopped
    assert not runtime.exists()
    with pytest.raises(OSError):
        socket.create_connection((HOST, port), timeout=0.2)


def test_public_only_probe_needs_no_oauth_secrets(tmp_path):
    with harness().running_bridge(runtime_parent=tmp_path, ttl=30) as bridge:
        result = probe(bridge, credentials=False)
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(result.stdout)
        assert evidence["jwks_matches_native_as"] is True
        assert evidence["native_introspection_active"] is None
        assert evidence["cross_host_verified"] is False
        # A correct TLS connection is insufficient if the API output is wrong.
        manifest_path = bridge.public_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["jwks_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
        rejected = probe(bridge, credentials=False)
        assert rejected.returncode == 1
        assert json.loads(rejected.stdout)["error"] == "native JWKS fingerprint mismatch"


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "::", "139.162.27.153"])
def test_non_vpn_bind_rejected_before_start(tmp_path, host):
    with pytest.raises(ValueError, match="VPN"):
        with harness().running_bridge(runtime_parent=tmp_path, bind_ip=host):
            pytest.fail("unsafe listener started")
    assert not list(tmp_path.iterdir())


def test_private_runtime_must_stay_outside_git_worktrees():
    with pytest.raises(ValueError, match="outside"):
        with harness().running_bridge(runtime_parent=ROOT):
            pytest.fail("private state created in repository")


@pytest.mark.parametrize("ttl", [0, -1, 301, float("inf")])
def test_lifetime_is_bounded(tmp_path, ttl):
    with pytest.raises(ValueError, match="lifetime"):
        with harness().running_bridge(runtime_parent=tmp_path, ttl=ttl):
            pytest.fail("unbounded server started")


def test_child_self_expires_and_cleans_up(tmp_path):
    with harness().running_bridge(runtime_parent=tmp_path, ttl=4) as bridge:
        runtime = bridge.runtime
        bridge.process.join(timeout=8)
        assert not bridge.process.is_alive()
        assert bridge.process.exitcode == 0
    assert bridge.stopped
    assert not runtime.exists()


def test_cli_ready_then_expiry_removes_private_runtime(tmp_path):
    import edgar_auth

    result = subprocess.run([
        sys.executable, str(ROOT / "scripts" / "edg478_tls_bridge.py"),
        "--ttl", "4", "--runtime-parent", str(tmp_path),
    ], capture_output=True, text=True, timeout=15, cwd=ROOT, env={
        "PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(Path(edgar_auth.__file__).resolve().parents[1]),
    })
    assert result.returncode == 0, result.stdout + result.stderr
    ready, expired = [json.loads(line) for line in result.stdout.splitlines()]
    assert ready["event"] == "READY"
    assert ready["cross_host_status"] == "PENDING_CONTROLLER"
    assert ready["local_only_evidence"]["native_introspection_active"] is True
    assert ready["local_only_evidence"]["cross_host_verified"] is False
    assert expired == {"event": "EXPIRED", "cleanup": "complete"}
    assert not Path(ready["public_bundle"]).parent.exists()
    assert not list(tmp_path.iterdir())
