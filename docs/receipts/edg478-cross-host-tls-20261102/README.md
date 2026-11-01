# EDG-478 | Isolated TLS Auth→MCP cross-host experiment | 2026-11-02

Scope: a candidate nonproduction test harness only. **DO NOT MERGE OR DEPLOY** this stacked change; production Auth, MCP, mail, DNS, and firewall untouched. Uses synthetic auth account/client/signing material, a temporary CA with IP SAN, and time-bounded WireGuard-only AS listener. All temporary secrets stay out of Git.

## Source and test
- Base GitHub PR #61 `a7e2d6f85a9a5778895d9f8f15e98a4c8e6895ca`.
- Source: `scripts/edg478_tls_bridge.py`, `scripts/edg478_tls_probe.py`; tests `test_edgar_native_tls_bridge.py` in isolated worktree `test/edg478-cross-host-tls-aka1-20261102`.
- RED/GREEN not independently collected from initial Droid because it aborted at the Factory permission boundary. Controller independently executed the final focused test under the existing venv with sibling native AS `PYTHONPATH`; actual terminal **13/13 PASS in 16.02s**. This is isolated local TLS proof, not cross-host acceptance.
- Actual short-lived aka1 bridge run via Gateway job `job_01M6BY7THC003G94YPZYHMPY5V`, returned READY with signed native AS JWKS, adapter and certificate SHA manifest; local probe `native_introspection_active=true`, `tls_chain_verified=true`, `wrong_ca_rejected=true`, `wrong_san_rejected=true`, `cross_host_verified=false`. Automatic expiry & cleanup succeeded. No private test key/token copied into repo.

## Actual cross-host negative evidence
- Existing WireGuard aka1 `10.77.0.11` and Contabo `10.77.0.8` ping/SSH reachable. Contabo to aka1 SSH `edgar@10.77.0.11` strict host key & BatchMode succeeded.
- Contabo attempted to run portable TLS+introspection probe using copied synthetic ephemeral fixture (transfer over authenticated SSH, private file chmod 0600, cleaned by trap). Gateway job `job_01M6BY8XBA00FTKBTJC6BCC911` returned `TimeoutError`, NOT cross-host PASS.
- aka1 test listener `10.77.0.11:35187` was observed LISTENING, local HTTPS JWKS returned HTTP200; Contabo direct TCP to this ephemeral port timed out (`TCP_BLOCKED`, HTTPS status 000/no TLS handshake), Gateway job `job_01M6BYATBS005FSBPMRZ90AV9Y`. Root cause of blocked port is not yet established (host/edge rule/policy). No firewall changes performed.
- An SSH-local-forward alternative failed to open the local forwarding socket (Contabo Gateway job `job_01M6BYETSJ006WYHP6TNS2A0Y2`, curl connect refused at 127.0.0.1:43587); no bypass or reconfiguration was made.
- This test did not perform an actual cross-host successful TLS handshake, JWKS retrieval or introspection; do not claim those. It also does not prove public browser/OIDC/MFA/Knowledge MCP prod.

## Verdict and next check
LOCAL_SYNTHETIC_TLS_AND_NATIVE_INTROSPECTION=PASS (13/13); CROSS_HOST_DIRECT_TLS=BLOCKED (TCP_TIMEOUT); CROSS_HOST_SSH_FORWARD=BLOCKED; REAL_KNOWLEDGE_MCP_AND_PRODUCTION=UNVERIFIED. First next probe: read-only compare aka1/Contabo actual INPUT/OUTPUT firewall/route policy and SSHD AllowTcpForwarding/PermitOpen with approved host rules, pick one safe isolated test transport, then repeat the actual Contabo probe; no production change without separate approval. Prefer not to spend aka1 trial budget on duplicate local tests.
