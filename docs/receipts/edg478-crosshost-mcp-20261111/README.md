# EDG-478 | Two-machine native EDGAR Auth to actual MCP HTTP consumer

2026-11-11 Asia/Taipei: isolated E2E PASS; NOT production Auth, not a deployed Knowledge MCP verification.

## Architecture and pinned sources
- Native handcraft EDGAR Authorization Server is the only EDGAR token issuer.
- This Draft branch stacks on edgars-mcp PR #63 at 33fc7134b5283d15f3b3ab903a605b6d9f178858; tested native AS source b8648ee.
- PR #62 scripts/edg478_tls_bridge.py supplies synthetic consent+PKCE-issued JWT, ephemeral JWKS/private signing key, temporary HTTPS native AS on aka1 WireGuard 10.77.0.11 and synthetic confidential introspection client.
- New scripts/edg478_crosshost_mcp_consumer.py runs on Contabo, starts a real MCPHTTPHandler TCP listener on 127.0.0.1 (random port), and uses the real HTTPIntrospectionClient to call aka1 over verified HTTPS with client_id/client_secret.
- Before native AS revoke, real MCP JSON-RPC POST /mcp tools/list and safe tools/call echo return 200.
- After revoke, the same unexpired JWT returns 401 for tools/list and tools/call fs_write, with no write side effects. Wrong issuer/audience and wrong confidential secret also rejected.

## Reproduction / safety
Requires two authorized hosts and WireGuard. Use SYNTHETIC TEST DATA ONLY; never production credentials or current user sessions.

1. Start PR #62 scripts/edg478_tls_bridge.py --ttl 240 in private aka1 sandbox with sibling edgar-auth-server source. It outputs the temporary public_bundle and private_input paths.
2. Allow only Contabo source 10.77.0.8 on aka1 wg0 to reach the temporary test port, never public inbound.
3. Copy ca.crt, manifest and synthetic private input over StrictHostKeyChecking authenticated SSH into a chmod0700 temporary Contabo folder. NEVER print JWT/secret or commit it.
4. Use isolated Python environment and the repository test dependencies. The sibling edgar-auth-server package is needed for test fixture imports. Set PYTHONPATH to the edgars-mcp repository and sibling edgar-auth-server directory, and SSL_CERT_FILE to the temporary ca.crt, then execute:
    python scripts/edg478_crosshost_mcp_consumer.py /private/tmp/public /private/tmp/credentials.json
5. Verify exit0 and machine JSON; remove the narrow firewall rule, stop the bridge and verify no socket, private runtime or fixture remains.

This test does not fake the native AS introspection response, disable TLS certificate verification or follow token-supplied endpoints.

## Actual evidence
- Contabo Gateway job_01M73RSW9Q00FTG9W2BEH7XBB4 succeeded exit0.
- AS /healthz 200; before-revoke tools/list 200, tools/call echo 200; AS /revoke 200, /introspect active:false; same JWT still unexpired, post-revoke tools/list 401, tools/call fs_write 401. No filesystem side effect. Wrong iss/aud/secret all rejected.
- Contabo readback JSON receipt /home/edgar/EDGAR-OPS/research/edg478-crosshost-mcp-20261111/contabo-crosshost-result.json SHA256 46e0cbd00a271c5026e5a3b7c075c3bdb61dcb5425c7af1d6100b5a7f4a09f.
- Initial trial failed ModuleNotFoundError because PYTHONPATH did not include the local isolated repo; fixed import path and observed full PASS. The import error is not evidence of an OAuth RED failure.
- Temporary aka1 UFW rule deleted job_01M73RW6PZ00SN6C4AAXV3S8PE; bridge stopped, no listener/temporary private runtime (job_01M73RY8B9003D4EYQA9YN6ZEN); Contabo synthetic fixture removed by trap.
- YouTrack source receipt https://edgars.youtrack.cloud/issue/EDG-478#focus=Comments-7-3743.0-0.

## Outstanding gates
MCP HTTP test server is a local Contabo process, not the deployed Knowledge MCP; synthetic user/session, not real ChatGPT callback, real public browser login, production PRM, JWKS rollover, fine-grained tool RBAC or production key rotation. Production unchanged; zero new recurring cost. Keep this Draft.

Next bounded action: prove JWKS old/new kid rotation and real deployed Knowledge MCP / ChatGPT user OAuth, then request explicit production cutover gate.
