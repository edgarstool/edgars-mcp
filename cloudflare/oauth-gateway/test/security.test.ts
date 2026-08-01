import { describe, expect, it } from "vitest";

import { isAllowedEmail } from "../src/access";
import { effectiveScopes } from "../src/constants";
import { consumeConsentState, createConsentState } from "../src/consent";
import { requiredScopeForRpc, sanitizedOriginHeaders } from "../src/policy";

class MemoryKv {
  readonly values = new Map<string, string>();

  async get(key: string): Promise<string | null> {
    return this.values.get(key) ?? null;
  }

  async put(key: string, value: string): Promise<void> {
    this.values.set(key, value);
  }

  async delete(key: string): Promise<void> {
    this.values.delete(key);
  }
}

const secret = "0123456789abcdef0123456789abcdef";
const authRequest = {
  clientId: "client-123",
  redirectUri: "https://chatgpt.com/aip/callback",
  responseType: "code",
  scope: ["mcp:read", "mcp:write"],
  state: "client-state",
  codeChallenge: "challenge",
  codeChallengeMethod: "S256",
  resource: "https://mcp.edgars.tools/mcp",
  issuer: "https://auth.edgars.tools",
} as never;

describe("OAuth gateway security boundaries", () => {
  it("allows only the two canonical owner emails", () => {
    const allowlist = "edgar@edgars.tools,edgar@edgar.tw";
    expect(isAllowedEmail("EDGAR@EDGARS.TOOLS", allowlist)).toBe(true);
    expect(isAllowedEmail("edgar@edgar.tw", allowlist)).toBe(true);
    expect(isAllowedEmail("edgar@edgarbeyourself.com", allowlist)).toBe(false);
  });

  it("uses both documented scopes as the OAuth default", () => {
    expect(effectiveScopes([])).toEqual(["mcp:read", "mcp:write"]);
    expect(effectiveScopes(["mcp:read"])).toEqual(["mcp:read"]);
    expect(() => effectiveScopes(["mcp:write"])).toThrow("mcp:read is required");
  });

  it("requires write scope for tool invocation", () => {
    expect(requiredScopeForRpc({ method: "tools/list" })).toBe("mcp:read");
    expect(requiredScopeForRpc({ method: "tools/call" })).toBe("mcp:write");
    expect(requiredScopeForRpc([{ method: "ping" }, { method: "tools/call" }])).toBe("mcp:write");
  });

  it("strips end-user credentials before proxying to the origin", () => {
    const request = new Request("https://mcp.edgars.tools/mcp", {
      headers: {
        authorization: "Bearer end-user-token",
        cookie: "private=1",
        origin: "https://chatgpt.com",
        "cf-access-jwt-assertion": "access-jwt",
        "x-edgar-user-email": "spoofed@example.com",
        accept: "application/json",
      },
    });
    const headers = sanitizedOriginHeaders(request);
    expect(headers.has("authorization")).toBe(false);
    expect(headers.has("cookie")).toBe(false);
    expect(headers.has("origin")).toBe(false);
    expect(headers.has("cf-access-jwt-assertion")).toBe(false);
    expect(headers.has("x-edgar-user-email")).toBe(false);
    expect(headers.get("accept")).toBe("application/json");
  });

  it("signs consent state and permits one use only", async () => {
    const kv = new MemoryKv();
    const state = await createConsentState(authRequest, secret, kv as never, 1_000_000);
    await expect(consumeConsentState(state, secret, kv as never, 1_000_000)).resolves.toMatchObject({
      clientId: "client-123",
    });
    await expect(consumeConsentState(state, secret, kv as never, 1_000_000)).rejects.toThrow(
      "already used or expired",
    );
  });

  it("rejects tampered consent state", async () => {
    const kv = new MemoryKv();
    const state = await createConsentState(authRequest, secret, kv as never, 1_000_000);
    const tampered = `${state.slice(0, -1)}${state.endsWith("a") ? "b" : "a"}`;
    await expect(consumeConsentState(tampered, secret, kv as never, 1_000_000)).rejects.toThrow(
      "Invalid consent signature",
    );
  });
});
