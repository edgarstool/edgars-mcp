# EDG-478 Native EDGAR Auth JWT -> MCP boundary

Status: nonproduction Draft. Does not demonstrate real HTTP MCP tools/list or tools/call.

## Scope
- Native EDGAR Auth remains the only issuer of EDGAR access tokens.
- Optional native verification is OFF by default. An explicit EDGAR issuer, audience and PUBLIC pinned JWKS are required.
- In native mode, do not silently fall back to Descope, static tokens or the legacy in-memory token store.
- The test fixture invokes actual edgar-auth-server app and its consent, S256 PKCE, authorization-code and token endpoints, with synthetic signing keys and a temporary SQLite database.
- No DNS, deployment or production authentication configuration was changed.

## Reproduction in isolated sibling clones

Install edgar-auth-server[test], jsonschema and MCP Python SDK in a throwaway venv. From edgars-mcp repository root run:

    python -m pytest -q test_edgar_issuer_bridge.py

Proven on Contabo 2026-10-28 from MCP original commit d983a69 and AS integration b8648ee:

- RED on baseline: 1 failed, 1 passed. Genuine native JWT rejected by original bearer_token_is_authorized.
- GREEN with opt-in pinned-JWKS verification: 7 passed. Includes issuer, audience, scope, signature, missing JWKS, and legacy static fallback rejection.
- Unmodified MCP regression suite: 170 passed, 1 skipped, 6 failed.
- Same suite on this branch: 170 passed, 1 skipped, the SAME 6 failed. No additional failures observed.
- AS tests: 43 passed (source code unchanged).

## Hard blockers before merge or production

1. No runtime JWKS discovery, automatic key rotation or pin update path.
2. No grant/token revocation or RFC 7662 introspection in this verifier: valid signed token could remain usable after revoke.
3. One general mcp:read scope is NOT a per-tool policy. Write/admin tools must be guarded at the actual MCP request/handler.
4. No real HTTP POST /mcp initialize, tools/list, tools/call, RFC 9728 discovery, or HeaderMismatch -32020 E2E tested here.
5. Cross-repository CI test setup must install pinned AS package.
6. Existing Cloudflare Access gate can preempt this verifier. Routing, compatibility and real browser consent still require EDG-456 acceptance.

Next action: bounded, test-first revocation/introspection + protected real tools/call enforcement in a nonproduction staging process. Keep this PR Draft until every gate has evidence.
