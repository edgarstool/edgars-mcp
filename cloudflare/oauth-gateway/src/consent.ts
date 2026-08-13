import type { AuthRequest } from "@cloudflare/workers-oauth-provider";

const STATE_TTL_SECONDS = 10 * 60;
const encoder = new TextEncoder();

interface ConsentPayload {
  request: AuthRequest;
  nonce: string;
  exp: number;
}

function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromBase64url(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function hmac(data: string, secret: string): Promise<Uint8Array> {
  if (secret.length < 32) throw new Error("CONSENT_HMAC_SECRET must be at least 32 characters");
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(data)));
}

function timingSafeEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= (left[index] ?? 0) ^ (right[index] ?? 0);
  }
  return difference === 0;
}

export async function createConsentState(
  request: AuthRequest,
  secret: string,
  kv: KVNamespace,
  now = Date.now(),
): Promise<string> {
  const nonce = crypto.randomUUID();
  const payload: ConsentPayload = {
    request,
    nonce,
    exp: Math.floor(now / 1000) + STATE_TTL_SECONDS,
  };
  const encoded = base64url(encoder.encode(JSON.stringify(payload)));
  const signature = base64url(await hmac(encoded, secret));
  await kv.put(`oauth-consent:${nonce}`, "1", { expirationTtl: STATE_TTL_SECONDS });
  return `${encoded}.${signature}`;
}

export async function consumeConsentState(
  state: string,
  secret: string,
  kv: KVNamespace,
  now = Date.now(),
): Promise<AuthRequest> {
  const [encoded, signature] = state.split(".");
  if (!encoded || !signature) throw new Error("Invalid consent state");
  const expected = await hmac(encoded, secret);
  if (!timingSafeEqual(expected, fromBase64url(signature))) {
    throw new Error("Invalid consent signature");
  }

  let payload: ConsentPayload;
  try {
    payload = JSON.parse(new TextDecoder().decode(fromBase64url(encoded))) as ConsentPayload;
  } catch {
    throw new Error("Invalid consent payload");
  }
  if (!payload.nonce || !payload.request || payload.exp < Math.floor(now / 1000)) {
    throw new Error("Consent state expired");
  }

  const key = `oauth-consent:${payload.nonce}`;
  const marker = await kv.get(key);
  if (marker !== "1") throw new Error("Consent state was already used or expired");
  await kv.delete(key);
  return payload.request;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function renderConsent(input: {
  clientName: string;
  email: string;
  scopes: readonly string[];
  state: string;
}): Response {
  const scopeItems = input.scopes
    .map((scope) => `<li><code>${escapeHtml(scope)}</code></li>`)
    .join("");
  const body = `<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>授權 EDGARS MCP</title>
  <style>
    :root{color-scheme:light dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif}
    body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1020;color:#e8edf8}
    main{width:min(92vw,520px);padding:32px;border:1px solid #283653;border-radius:20px;background:#111a2e;box-shadow:0 24px 80px #0008}
    h1{margin:0 0 8px;font-size:28px}.muted{color:#a8b3c7}ul{padding-left:22px;line-height:1.8}
    .account{padding:12px 14px;border-radius:12px;background:#17243d;margin:20px 0}
    .actions{display:flex;gap:12px;margin-top:24px}button{flex:1;padding:12px;border:0;border-radius:10px;font:inherit;font-weight:700;cursor:pointer}
    .approve{background:#64e6b3;color:#07120e}.deny{background:#283653;color:#e8edf8}
  </style>
</head>
<body>
  <main>
    <p class="muted">EDGARS OAuth</p>
    <h1>允許 ${escapeHtml(input.clientName)} 連線？</h1>
    <p class="muted">此應用程式將可透過 <strong>mcp.edgars.tools</strong> 使用下列權限：</p>
    <ul>${scopeItems}</ul>
    <div class="account">登入帳號：${escapeHtml(input.email)}</div>
    <form method="post" action="/authorize">
      <input type="hidden" name="state" value="${escapeHtml(input.state)}">
      <div class="actions">
        <button class="deny" type="submit" name="decision" value="deny">取消</button>
        <button class="approve" type="submit" name="decision" value="approve">允許</button>
      </div>
    </form>
  </main>
</body>
</html>`;
  return new Response(body, {
    headers: {
      "cache-control": "no-store",
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
      "content-type": "text/html; charset=utf-8",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
      "x-frame-options": "DENY",
    },
  });
}
