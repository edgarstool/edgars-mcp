# EDG-478 | ChatGPT-like DCR -> native EDGAR AS -> MCP real HTTP acceptance

Date: 2026-11-05 Asia/Taipei. Isolated staging only, no production mutation.

## Authority and source versions

- YouTrack: https://edgars.youtrack.cloud/issue/EDG-478
- Canonical native AS source in separate aka1 test worktree: edgarstool/edgar-auth-server integration branch `b8648ee3a83143ac30ec779098fcc33abc1bab43` (not deployed).
- This test branch builds on edgarstool/edgars-mcp PR #62 commit `02f6432c829dabce9415ca68bdcf77dfc2aed858` (unmerged).
- Public live check: `https://auth.edgars.tools/.well-known/oauth-authorization-server` returns HTTP **410**; `https://honcho.edgars.tools/mcp` without session returned HTTP **400** and earlier anonymous POST HTTP **401**. These are NOT a working OAuth login E2E.

## RED / GREEN / runtime

- RED: first new test ran without DCR-enabled fixture; AS discovery `registration_endpoint` was `null` rather than usable; **1 failed**. This is an expected test configuration fail, not a regression in production.
- GREEN: same real-process AS started with synthetic signing keys and `dcr_enabled=true` only in the indirect parametrized fixture. Actual HTTP `/.well-known/oauth-authorization-server` advertises `/register`, registering a public client returns a previously unregistered `client_id` (201, no client secret).
- Missing client_id / wrong registered redirect / insecure registration redirect rejected before consent. The new dynamic ID is used in real native AS authorization, consent form, code + PKCE S256 exchange and signed JWT. Signed client_id matches registered identity.
- Actual in-process TCP resource server independently serves `/.well-known/oauth-protected-resource/mcp` with exact resource and `authorization_servers=[ISSUER]`. Real MCP HTTP `tools/list` and harmless `tools/call echo` return 200. AS revocation produces inactive introspection and blocks subsequent list/call with 401.
- Isolated suite was **70/70 PASS** after the feature test, prior to additional PRM assertions; focused PRM test **1/1 PASS** after adding assertions. Full suite rerun prior to commit required for final receipt.
- Uses synthetic user/session, signing key, redirect host, confidential RS introspection key, ephemeral SQLite and loopback listener. Test cleans up process and ephemeral state. No real users or Honcho messages and no production AS/server/gateway deployment.

## Important limitation

The verified Resource Server is **edgars-mcp**, not the real official `honcho-native-mcp` container. Real ChatGPT registration, browser consent, runtime Token verification at the actual Honcho MCP, and public HTTPS discovery are still **UNVERIFIED**. The production native Auth metadata remains HTTP 410, which blocks a correct ChatGPT OAuth exchange. The test validates the DCR path as one *existing* implementation, not a proposed independent second AS.

Official sources:
- https://developers.openai.com/plugins/build/auth
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

## Next bounded acceptance

Implement a thin staging-only OAuth protection adapter for **official Honcho MCP**: RFC9728 PRM at `https://honcho.edgars.tools/.well-known/oauth-protected-resource[/mcp]` that points to a verified HTTPS EDGAR AS issuer; validate Edgars JWT iss/aud/scope + revocation before scoped forwarding to native Honcho backend, map client identity to allowed workspace/peer server-side, reject cross-workspace and no token. Test with genuine synthetic HTTPS ChatGPT-like discovery/registration/consent/token and real official Honcho MCP `initialize`, `tools/list`, a safe read, and unauthorized denial. Keep real production routing/auth keys untouched until explicit release gate.
