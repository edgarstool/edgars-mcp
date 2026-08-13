import assert from "node:assert/strict";
import test from "node:test";

import worker from "./index.mjs";

test("returns 503 when facade token is not configured", async () => {
  const response = await worker.fetch(
    new Request("https://honcho-mcp.edgars.tools/mcp", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    }),
    { HONCHO_API_KEY: "honcho-secret" },
  );

  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {
    ok: false,
    error: "honcho_facade_not_configured",
    error_description: "EDGARS_HONCHO_MCP_FACADE_TOKEN is not configured.",
  });
});

test("accepts lowercase bearer tokens and forwards only proxy headers", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  let upstreamRequest;
  globalThis.fetch = async (request) => {
    upstreamRequest = request;
    return new Response('{"ok":true}', {
      status: 200,
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  };

  const response = await worker.fetch(
    new Request("https://honcho-mcp.edgars.tools/mcp?view=full", {
      method: "GET",
      headers: {
        authorization: "bearer facade-token",
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        "mcp-session-id": "session-123",
        cookie: "session=secret",
        "cf-ray": "ray-id",
        "x-portal-token": "portal-secret",
      },
    }),
    {
      EDGARS_HONCHO_MCP_FACADE_TOKEN: "facade-token",
      HONCHO_API_KEY: "honcho-secret",
    },
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
  assert.equal(upstreamRequest.url, "https://mcp.honcho.dev/?view=full");
  assert.equal(upstreamRequest.headers.get("authorization"), "Bearer honcho-secret");
  assert.equal(upstreamRequest.headers.get("x-honcho-user-name"), "Edgar");
  assert.equal(upstreamRequest.headers.get("x-honcho-workspace-id"), "edgar-team");
  assert.equal(upstreamRequest.headers.get("x-honcho-assistant-name"), "codex");
  assert.equal(upstreamRequest.headers.get("content-type"), "application/json");
  assert.equal(upstreamRequest.headers.get("accept"), "application/json, text/event-stream");
  assert.equal(upstreamRequest.headers.get("user-agent"), "edgars-mcp-honcho-facade/0.1");
  assert.equal(upstreamRequest.headers.get("mcp-session-id"), "session-123");
  assert.equal(upstreamRequest.headers.get("cookie"), null);
  assert.equal(upstreamRequest.headers.get("cf-ray"), null);
  assert.equal(upstreamRequest.headers.get("x-portal-token"), null);
});

test("preserves multi-event SSE responses", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  const body =
    'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"cursor":"page-1"}}\n\n' +
    'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"cursor":"page-2"}}\n\n';

  globalThis.fetch = async () =>
    new Response(body, {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    });

  const response = await worker.fetch(
    new Request("https://honcho-mcp.edgars.tools/mcp", {
      method: "GET",
      headers: {
        authorization: "Bearer facade-token",
        "content-type": "application/json",
      },
    }),
    {
      EDGARS_HONCHO_MCP_FACADE_TOKEN: "facade-token",
      HONCHO_API_KEY: "honcho-secret",
    },
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/event-stream");
  assert.equal(await response.text(), body);
});
