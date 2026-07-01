const SERVICE_NAME = "edgars-status";
const MCP_EXTERNAL_URL = "https://mcp.edgars.tools/mcp";
const HOOKS_HEALTH_URL = "https://hooks.edgars.tools/health";
const MCP_LOCAL_ORIGIN = "127.0.0.1:8765";
const LOCAL_HOST_ALIAS = "EdgarsTool / edgar-local-01";
const REPO_ROOT = "V:\\projects";
const RUNTIME_ROOT = "G:\\AI_WORK_512";

const json = (data, status = 200) =>
  new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

function textStatus(label, state, detail) {
  return { label, state, detail };
}

async function probeMcpExternal() {
  try {
    const response = await fetch(MCP_EXTERNAL_URL, {
      method: "GET",
      redirect: "manual",
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    const mitigated = response.headers.get("cf-mitigated");
    if (response.status === 401) {
      return textStatus("mcp external", "protected", "401 Unauthorized (expected)");
    }
    if (response.status === 403 && mitigated === "challenge") {
      return textStatus("mcp external", "protected", "403 challenge (Access/WAF protected)");
    }
    return textStatus("mcp external", response.ok ? "ok" : "warning", `${response.status} ${response.statusText}`);
  } catch (error) {
    return textStatus("mcp external", "error", error.message);
  }
}

async function probeHooksHealth() {
  try {
    const response = await fetch(HOOKS_HEALTH_URL, {
      method: "GET",
      redirect: "manual",
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    const mitigated = response.headers.get("cf-mitigated");
    if (response.ok) {
      return textStatus("hooks health", "active", `${response.status} OK`);
    }
    if (response.status === 403 && mitigated === "challenge") {
      return textStatus("hooks health", "warning", "403 challenge at edge");
    }
    return textStatus("hooks health", "warning", `${response.status} ${response.statusText}`);
  } catch (error) {
    return textStatus("hooks health", "error", error.message);
  }
}

function localOriginStatus() {
  return textStatus(
    "mcp local origin",
    "target",
    `${MCP_LOCAL_ORIGIN} (origin target; Cloudflare edge cannot probe localhost directly)`,
  );
}

function verificationStatus(secretValue, label) {
  return textStatus(
    label,
    secretValue ? "enabled" : "pending",
    secretValue ? "enabled" : "pending secret",
  );
}

async function buildStatus(env) {
  const [mcpExternal, hooksHealth] = await Promise.all([
    probeMcpExternal(),
    probeHooksHealth(),
  ]);
  return {
    ok: true,
    service: SERVICE_NAME,
    version: "EDGAR-OS v1.0",
    checks: [
      mcpExternal,
      localOriginStatus(),
      hooksHealth,
      verificationStatus(env.GITHUB_WEBHOOK_SECRET, "hooks github verification"),
      verificationStatus(env.LINEAR_WEBHOOK_SECRET, "hooks linear verification"),
      textStatus("local host alias", "info", LOCAL_HOST_ALIAS),
      textStatus("repo root", "info", REPO_ROOT),
      textStatus("runtime root", "info", RUNTIME_ROOT),
    ],
    updated_at: new Date().toISOString(),
  };
}

function statusClass(state) {
  if (state === "active" || state === "enabled" || state === "ok" || state === "protected") {
    return "ok";
  }
  if (state === "warning" || state === "pending" || state === "target") {
    return "warn";
  }
  return "err";
}

function renderHtml(status) {
  const cards = status.checks
    .map(
      (item) => `
        <div class="card">
          <div class="label">${item.label}</div>
          <div class="value ${statusClass(item.state)}">${item.detail}</div>
        </div>`,
    )
    .join("");

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EDGAR-OS v1.0 Status</title>
  <style>
    :root { color-scheme: dark; }
    body { font-family: Inter, system-ui, sans-serif; background: #0b1020; color: #e8eefc; margin: 0; padding: 32px; }
    .wrap { max-width: 920px; margin: 0 auto; }
    h1 { margin: 0 0 8px; font-size: 32px; }
    .sub { color: #9db0d0; margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
    .card { background: #131b33; border: 1px solid #263252; border-radius: 16px; padding: 16px; }
    .label { font-size: 12px; color: #8da0c6; text-transform: uppercase; letter-spacing: .08em; }
    .value { margin-top: 8px; font-size: 18px; font-weight: 600; word-break: break-word; }
    .ok { color: #7ee787; }
    .warn { color: #ffd866; }
    .err { color: #f85149; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>EDGAR-OS v1.0</h1>
    <div class="sub">Live status · Last updated ${status.updated_at}</div>
    <div class="grid">${cards}</div>
  </div>
</body>
</html>`;
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    const status = await buildStatus(env);

    if (pathname === "/health" || pathname === "/api/health") {
      return json(status);
    }

    if (pathname === "/" || pathname === "") {
      return new Response(renderHtml(status), {
        status: 200,
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }

    return json({ ok: false, error: "not_found", path: pathname }, 404);
  },
};
