const HONCHO_MCP_URL = "https://mcp.honcho.dev";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function bearerValue(value) {
  if (!value) return "";
  const trimmed = String(value).trim();
  return trimmed.toLowerCase().startsWith("bearer ") ? trimmed : `Bearer ${trimmed}`;
}

function bearerToken(value) {
  if (!value) return "";
  const trimmed = String(value).trim();
  if (!trimmed.toLowerCase().startsWith("bearer ")) return "";
  return trimmed.slice("bearer ".length).trim();
}

function requireEnv(env, name) {
  const value = env[name];
  if (!value || !String(value).trim()) {
    throw new Error(`Missing required Worker secret: ${name}`);
  }
  return String(value).trim();
}

function loadFacadeToken(env) {
  return String(env.EDGARS_HONCHO_MCP_FACADE_TOKEN || env.EDGARS_INTERNAL_MCP_TOKEN || "").trim();
}

function facadeNotConfiguredResponse() {
  return jsonResponse(
    {
      ok: false,
      error: "honcho_facade_not_configured",
      error_description: "EDGARS_HONCHO_MCP_FACADE_TOKEN is not configured.",
    },
    503,
  );
}

function authorizeRequest(request, env) {
  const expected = loadFacadeToken(env);
  if (!expected) {
    return facadeNotConfiguredResponse();
  }

  const token = bearerToken(request.headers.get("authorization"));
  return token && token === expected ? null : unauthorizedMcpResponse();
}

function unauthorizedMcpResponse() {
  return new Response(
    JSON.stringify({
      ok: false,
      error: "unauthorized",
      error_description: "Missing or invalid facade bearer token.",
    }),
    {
      status: 401,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "www-authenticate": 'Bearer realm="honcho-mcp-facade"',
      },
    },
  );
}

function buildUpstreamHeaders(request, env) {
  const headers = new Headers();

  headers.set("authorization", bearerValue(requireEnv(env, "HONCHO_API_KEY")));
  headers.set("x-honcho-user-name", env.HONCHO_USER_NAME || "Edgar");
  headers.set("x-honcho-workspace-id", env.HONCHO_WORKSPACE_ID || "edgar-team");
  headers.set("x-honcho-assistant-name", env.HONCHO_ASSISTANT_NAME || "codex");
  headers.set("content-type", request.headers.get("content-type") || "application/json");
  headers.set("accept", request.headers.get("accept") || "application/json, text/event-stream");
  headers.set("user-agent", "edgars-mcp-honcho-facade/0.1");

  return headers;
}

async function normalizeHonchoResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/event-stream")) {
    return response;
  }

  const text = await response.text();
  const dataLines = text
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trim())
    .filter(Boolean);

  if (dataLines.length !== 1) {
    return new Response(text, {
      status: response.status,
      headers: response.headers,
    });
  }

  return new Response(dataLines[0], {
    status: response.status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

async function proxyToHoncho(request, env) {
  const authorizationError = authorizeRequest(request, env);
  if (authorizationError) {
    return authorizationError;
  }

  const incomingUrl = new URL(request.url);
  const upstreamUrl = new URL(HONCHO_MCP_URL);
  upstreamUrl.search = incomingUrl.search;

  const upstreamRequest = new Request(upstreamUrl, {
    method: request.method,
    headers: buildUpstreamHeaders(request, env),
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    redirect: "manual",
  });

  const response = await fetch(upstreamRequest);
  return normalizeHonchoResponse(response);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response("ok\n", {
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }

    if (url.pathname !== "/mcp") {
      return jsonResponse(
        {
          ok: false,
          error: "not_found",
          expected_path: "/mcp",
        },
        404,
      );
    }

    try {
      return await proxyToHoncho(request, env);
    } catch (error) {
      return jsonResponse(
        {
          ok: false,
          error: "upstream_proxy_error",
          error_description: error.message,
        },
        502,
      );
    }
  },
};
