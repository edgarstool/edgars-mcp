export const AUTH_ISSUER = "https://auth.edgars.tools";
export const MCP_RESOURCE = "https://mcp.edgars.tools/mcp";
export const PROTECTED_RESOURCE_METADATA =
  "https://mcp.edgars.tools/.well-known/oauth-protected-resource/mcp";

export const SUPPORTED_SCOPES = ["mcp:read", "mcp:write"] as const;
export type SupportedScope = (typeof SUPPORTED_SCOPES)[number];

export interface AuthProps {
  userId: string;
  email: string;
  clientId: string;
  scopes: SupportedScope[];
}

export interface Env {
  OAUTH_KV: KVNamespace;
  OAUTH_PROVIDER: import("@cloudflare/workers-oauth-provider").OAuthHelpers;
  ACCESS_TEAM_DOMAIN: string;
  ACCESS_AUD: string;
  ALLOWED_EMAILS: string;
  CONSENT_HMAC_SECRET: string;
  EDGE_IDENTITY_SECRET: string;
  MCP_ORIGIN_URL: string;
  ORIGIN_API_TOKEN: string;
}

export function effectiveScopes(requested: readonly string[]): SupportedScope[] {
  const source = requested.length === 0 ? SUPPORTED_SCOPES : requested;
  const granted = SUPPORTED_SCOPES.filter((scope) => source.includes(scope));
  if (!granted.includes("mcp:read")) {
    throw new Error("mcp:read is required");
  }
  return [...granted];
}
