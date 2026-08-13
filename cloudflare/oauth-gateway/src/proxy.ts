import { WorkerEntrypoint } from "cloudflare:workers";

import {
  PROTECTED_RESOURCE_METADATA,
  type AuthProps,
  type Env,
  type SupportedScope,
} from "./constants";
import { requiredScopeForRpc, sanitizedOriginHeaders } from "./policy";

const encoder = new TextEncoder();

async function requiredScope(request: Request): Promise<SupportedScope> {
  if (request.method !== "POST") return "mcp:read";
  try {
    return requiredScopeForRpc(await request.clone().json());
  } catch {
    // Fail closed for malformed/opaque POST bodies. The origin still owns JSON-RPC validation.
    return "mcp:write";
  }
}

function insufficientScope(scope: SupportedScope): Response {
  return Response.json(
    { error: "insufficient_scope", error_description: `${scope} is required` },
    {
      status: 403,
      headers: {
        "cache-control": "no-store",
        "www-authenticate": `Bearer error="insufficient_scope", scope="${scope}", resource_metadata="${PROTECTED_RESOURCE_METADATA}"`,
      },
    },
  );
}

async function signIdentity(canonical: string, secret: string): Promise<string> {
  if (secret.length < 32) throw new Error("EDGE_IDENTITY_SECRET must be at least 32 characters");
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, encoder.encode(canonical)),
  );
  return Array.from(signature, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function originUrl(raw: string, incoming: URL): URL {
  const target = new URL(raw);
  if (target.protocol !== "https:" && target.hostname !== "127.0.0.1" && target.hostname !== "localhost") {
    throw new Error("MCP_ORIGIN_URL must use https outside local development");
  }
  target.search = incoming.search;
  return target;
}

export class McpOriginProxy extends WorkerEntrypoint<Env, AuthProps> {
  override async fetch(request: Request): Promise<Response> {
    const props = this.ctx.props;
    const needed = await requiredScope(request);
    if (!props.scopes.includes(needed)) return insufficientScope(needed);

    const incoming = new URL(request.url);
    const target = originUrl(this.env.MCP_ORIGIN_URL, incoming);
    const headers = sanitizedOriginHeaders(request);
    headers.set("authorization", `Bearer ${this.env.ORIGIN_API_TOKEN}`);

    const timestamp = Math.floor(Date.now() / 1000).toString();
    const scopes = [...props.scopes].sort().join(" ");
    const canonical = [
      timestamp,
      request.method,
      target.pathname,
      props.userId,
      props.email,
      props.clientId,
      scopes,
    ].join("\n");
    headers.set("x-edgar-edge-timestamp", timestamp);
    headers.set("x-edgar-edge-signature", await signIdentity(canonical, this.env.EDGE_IDENTITY_SECRET));
    headers.set("x-edgar-user-id", props.userId);
    headers.set("x-edgar-user-email", props.email);
    headers.set("x-edgar-oauth-client-id", props.clientId);
    headers.set("x-edgar-oauth-scopes", scopes);

    return fetch(
      new Request(target, {
        method: request.method,
        headers,
        body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
        redirect: "manual",
      }),
    );
  }
}
