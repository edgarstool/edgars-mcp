import {
  OAuthProvider,
  type AuthRequest,
  type OAuthHelpers,
} from "@cloudflare/workers-oauth-provider";

import { AccessIdentityError, authenticateAccessUser } from "./access";
import {
  AUTH_ISSUER,
  MCP_RESOURCE,
  SUPPORTED_SCOPES,
  effectiveScopes,
  type AuthProps,
  type Env,
} from "./constants";
import { consumeConsentState, createConsentState, renderConsent } from "./consent";
import { McpOriginProxy } from "./proxy";

type EnvWithOAuth = Env & { OAUTH_PROVIDER: OAuthHelpers };

function oauthErrorRedirect(request: AuthRequest, error: string): Response {
  const redirect = new URL(request.redirectUri);
  redirect.searchParams.set("error", error);
  if (request.state) redirect.searchParams.set("state", request.state);
  redirect.searchParams.set("iss", AUTH_ISSUER);
  return Response.redirect(redirect.toString(), 302);
}

function localError(message: string, status = 400): Response {
  return Response.json(
    { error: status === 403 ? "access_denied" : "invalid_request", error_description: message },
    { status, headers: { "cache-control": "no-store" } },
  );
}

async function handleAuthorizeGet(request: Request, env: EnvWithOAuth): Promise<Response> {
  let oauthRequest: AuthRequest;
  try {
    oauthRequest = await env.OAUTH_PROVIDER.parseAuthRequest(request);
  } catch {
    return localError("Invalid OAuth authorization request");
  }

  try {
    const [identity, client] = await Promise.all([
      authenticateAccessUser(request, env),
      env.OAUTH_PROVIDER.lookupClient(oauthRequest.clientId),
    ]);
    if (!client) return localError("Unknown OAuth client");
    const scopes = effectiveScopes(oauthRequest.scope);
    const state = await createConsentState(oauthRequest, env.CONSENT_HMAC_SECRET, env.OAUTH_KV);
    return renderConsent({
      clientName: client.clientName || oauthRequest.clientId,
      email: identity.email,
      scopes,
      state,
    });
  } catch (error) {
    const status = error instanceof AccessIdentityError ? 403 : 400;
    return localError(error instanceof Error ? error.message : "Authorization failed", status);
  }
}

async function handleAuthorizePost(request: Request, env: EnvWithOAuth): Promise<Response> {
  try {
    const form = await request.formData();
    const state = form.get("state");
    const decision = form.get("decision");
    if (typeof state !== "string") return localError("Missing consent state");

    const [oauthRequest, identity] = await Promise.all([
      consumeConsentState(state, env.CONSENT_HMAC_SECRET, env.OAUTH_KV),
      authenticateAccessUser(request, env),
    ]);
    if (decision !== "approve") return oauthErrorRedirect(oauthRequest, "access_denied");

    const scopes = effectiveScopes(oauthRequest.scope);
    const client = await env.OAUTH_PROVIDER.lookupClient(oauthRequest.clientId);
    if (!client) return localError("Unknown OAuth client");

    const props: AuthProps = {
      userId: identity.sub,
      email: identity.email,
      clientId: oauthRequest.clientId,
      scopes,
    };
    const { redirectTo } = await env.OAUTH_PROVIDER.completeAuthorization({
      request: oauthRequest,
      userId: identity.sub,
      metadata: { clientName: client.clientName || oauthRequest.clientId },
      scope: scopes,
      props,
    });
    return Response.redirect(redirectTo, 302);
  } catch (error) {
    const status = error instanceof AccessIdentityError ? 403 : 400;
    return localError(error instanceof Error ? error.message : "Authorization failed", status);
  }
}

const defaultHandler: ExportedHandler<EnvWithOAuth> = {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, issuer: AUTH_ISSUER, resource: MCP_RESOURCE });
    }
    if (url.hostname !== "auth.edgars.tools" || url.pathname !== "/authorize") {
      return new Response("Not found", { status: 404 });
    }
    if (request.method === "GET") return handleAuthorizeGet(request, env);
    if (request.method === "POST") return handleAuthorizePost(request, env);
    return new Response("Method not allowed", { status: 405, headers: { allow: "GET, POST" } });
  },
};

export default new OAuthProvider<Env>({
  apiRoute: "/mcp",
  apiHandler: McpOriginProxy,
  defaultHandler,
  authorizeEndpoint: "/authorize",
  tokenEndpoint: "/oauth/token",
  clientRegistrationEndpoint: "/oauth/register",
  clientIdMetadataDocumentEnabled: true,
  scopesSupported: [...SUPPORTED_SCOPES],
  resourceMetadata: {
    resource: MCP_RESOURCE,
    authorization_servers: [AUTH_ISSUER],
    scopes_supported: [...SUPPORTED_SCOPES],
    bearer_methods_supported: ["header"],
    resource_name: "EDGARS MCP",
  },
});

export { McpOriginProxy };
