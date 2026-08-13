import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";

import type { Env } from "./constants";

const jwksByUrl = new Map<string, ReturnType<typeof createRemoteJWKSet>>();

export interface AccessIdentity {
  sub: string;
  email: string;
}

export class AccessIdentityError extends Error {}

function normalizedTeamDomain(raw: string): string {
  const value = raw.trim().replace(/\/$/, "");
  if (!value.startsWith("https://")) {
    throw new AccessIdentityError("ACCESS_TEAM_DOMAIN must use https");
  }
  return value;
}

function getJwks(url: string): ReturnType<typeof createRemoteJWKSet> {
  const cached = jwksByUrl.get(url);
  if (cached) return cached;
  const created = createRemoteJWKSet(new URL(url));
  jwksByUrl.set(url, created);
  return created;
}

export function allowedEmailSet(raw: string): Set<string> {
  return new Set(
    raw
      .split(",")
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function isAllowedEmail(email: string, rawAllowlist: string): boolean {
  return allowedEmailSet(rawAllowlist).has(email.trim().toLowerCase());
}

function identityFromClaims(payload: JWTPayload, allowlist: string): AccessIdentity {
  const sub = typeof payload.sub === "string" ? payload.sub : "";
  const email = typeof payload.email === "string" ? payload.email.toLowerCase() : "";
  if (!sub || !email) {
    throw new AccessIdentityError("Cloudflare Access token is missing sub or email");
  }
  if (!isAllowedEmail(email, allowlist)) {
    throw new AccessIdentityError("This account is not allowed to authorize EDGARS MCP");
  }
  return { sub, email };
}

export async function authenticateAccessUser(
  request: Request,
  env: Pick<Env, "ACCESS_TEAM_DOMAIN" | "ACCESS_AUD" | "ALLOWED_EMAILS">,
): Promise<AccessIdentity> {
  const assertion = request.headers.get("cf-access-jwt-assertion")?.trim();
  if (!assertion) {
    throw new AccessIdentityError("Cloudflare Access login is required");
  }

  const issuer = normalizedTeamDomain(env.ACCESS_TEAM_DOMAIN);
  const jwksUrl = `${issuer}/cdn-cgi/access/certs`;
  try {
    const { payload } = await jwtVerify(assertion, getJwks(jwksUrl), {
      issuer,
      audience: env.ACCESS_AUD,
    });
    return identityFromClaims(payload, env.ALLOWED_EMAILS);
  } catch (error) {
    if (error instanceof AccessIdentityError) throw error;
    throw new AccessIdentityError("Cloudflare Access token validation failed");
  }
}
