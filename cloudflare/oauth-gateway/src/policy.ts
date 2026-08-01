import type { SupportedScope } from "./constants";

export function requiredScopeForRpc(payload: unknown): SupportedScope {
  const messages = Array.isArray(payload) ? payload : [payload];
  for (const message of messages) {
    if (
      typeof message === "object" &&
      message !== null &&
      "method" in message &&
      (message as { method?: unknown }).method === "tools/call"
    ) {
      return "mcp:write";
    }
  }
  return "mcp:read";
}

export function sanitizedOriginHeaders(request: Request): Headers {
  const headers = new Headers(request.headers);
  for (const name of [
    "authorization",
    "cookie",
    "cf-access-jwt-assertion",
    "cf-access-authenticated-user-email",
    "origin",
    "x-edgar-edge-timestamp",
    "x-edgar-edge-signature",
    "x-edgar-user-id",
    "x-edgar-user-email",
    "x-edgar-oauth-client-id",
    "x-edgar-oauth-scopes",
  ]) {
    headers.delete(name);
  }
  return headers;
}
