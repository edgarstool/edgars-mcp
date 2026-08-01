# EDGARS MCP OAuth Gateway

This Worker is the OAuth 2.1 authorization server and protected-resource edge for:

- issuer: `https://auth.edgars.tools`
- resource: `https://mcp.edgars.tools/mcp`
- scopes: `mcp:read`, `mcp:write`

Cloudflare Access performs the upstream Google login. This Worker validates the Access JWT and permits only:

- `edgar@edgars.tools`
- `edgar@edgar.tw`

The Worker then issues its own MCP-bound token through `@cloudflare/workers-oauth-provider`. End-user OAuth and Access tokens are never forwarded to the Python origin. The origin receives its existing static service token plus signed identity headers.

## Security contract

- OAuth authorization code + PKCE S256
- RFC 8707 exact resource/audience binding
- RFC 9728 protected-resource metadata and RFC 8414 authorization-server metadata
- CIMD enabled, with DCR retained for older MCP clients
- rotating refresh tokens and RFC 7009 revocation handled by the provider
- explicit consent, signed one-time state, owner email allowlist
- `mcp:write` required for JSON-RPC `tools/call`
- end-user `Authorization`, Cookie, Origin, Access JWT, and spoofed identity headers stripped before origin proxying

## Cloudflare setup

1. Create one Workers KV namespace and replace the all-zero placeholder ID in `wrangler.jsonc`.
2. Create a Cloudflare Access self-hosted application for `auth.edgars.tools/authorize*`. Use Google as the identity provider and restrict the policy to the two owner emails above.
3. Do not put Access in front of OAuth machine endpoints (`/.well-known/*`, `/oauth/token`, `/oauth/register`) or the MCP endpoint. The Worker serves the standards-compliant challenge and validates tokens itself.
4. The Worker routes only the OAuth paths on `auth.edgars.tools`; the existing identity site's `/`, `/login`, and `/account` routes remain untouched.
5. Move the current Tunnel origin to a private hostname that does not match either Worker route. Put its full `/mcp` URL in the `MCP_ORIGIN_URL` secret. This prevents proxy recursion and keeps the Python origin out of the public OAuth boundary.
6. Set secrets:

   ```bash
   npx wrangler secret put ACCESS_TEAM_DOMAIN
   npx wrangler secret put ACCESS_AUD
   npx wrangler secret put CONSENT_HMAC_SECRET
   npx wrangler secret put EDGE_IDENTITY_SECRET
   npx wrangler secret put MCP_ORIGIN_URL
   npx wrangler secret put ORIGIN_API_TOKEN
   ```

   `ORIGIN_API_TOKEN` must equal the Python server's `MCP_API_TOKEN`. It is a Worker-to-origin service credential, not an OAuth token.

7. Deploy and verify:

   ```bash
   npm ci
   npm run check
   npm test
   npm run deploy:dry
   npm run deploy
   ```

## Required smoke checks

- `GET https://mcp.edgars.tools/.well-known/oauth-protected-resource/mcp` returns the canonical resource and `https://auth.edgars.tools` authorization server.
- `GET https://auth.edgars.tools/.well-known/oauth-authorization-server` advertises PKCE, token, revocation, CIMD, and DCR metadata.
- unauthenticated `POST https://mcp.edgars.tools/mcp` returns `401` with `resource_metadata`.
- authorization using either allowed email reaches consent; the deprecated email is rejected.
- the access token audience is exactly `https://mcp.edgars.tools/mcp`.
- refresh rotates the refresh token; revocation invalidates the grant.
- `mcp:read` can list tools but cannot call one; `mcp:write` plus `mcp:read` can call tools.

## Rollback

Remove the two Worker routes and restore the prior proxied Tunnel DNS record for `mcp.edgars.tools`. The origin service and its static token are unchanged by this gateway.
