const json = (data, status = 200) =>
  new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

const encoder = new TextEncoder();

function timingSafeEqual(left, right) {
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  const max = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < max; i += 1) {
    diff |= (a[i] ?? 0) ^ (b[i] ?? 0);
  }
  return diff === 0;
}

async function hmacSha256Hex(secret, rawBytes) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, rawBytes);
  return Array.from(new Uint8Array(signature), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

async function verifyGitHub(request, env) {
  const signature = request.headers.get("X-Hub-Signature-256")?.trim() ?? "";
  if (!env.GITHUB_WEBHOOK_SECRET) {
    return { ok: false, reason: "secret_not_configured" };
  }
  if (!signature || !signature.startsWith("sha256=")) {
    return { ok: false, reason: "missing_or_malformed_signature" };
  }
  const rawBody = await request.arrayBuffer();
  const expected = `sha256=${await hmacSha256Hex(env.GITHUB_WEBHOOK_SECRET, rawBody)}`;
  return {
    ok: timingSafeEqual(signature, expected),
    reason: "invalid_signature",
  };
}

async function verifyLinear(request, env) {
  const signature = request.headers.get("Linear-Signature")?.trim().toLowerCase() ?? "";
  if (!env.LINEAR_WEBHOOK_SECRET) {
    return { ok: false, reason: "secret_not_configured" };
  }
  if (!/^[0-9a-f]{64}$/.test(signature)) {
    return { ok: false, reason: "missing_or_malformed_signature" };
  }
  const rawBody = await request.arrayBuffer();
  const expected = await hmacSha256Hex(env.LINEAR_WEBHOOK_SECRET, rawBody);
  return {
    ok: timingSafeEqual(signature, expected),
    reason: "invalid_signature",
  };
}

function placeholder(provider) {
  return json({
    ok: true,
    service: "edgar-hooks-inbox",
    provider,
    temporary: true,
    note: "temporary placeholder route",
  });
}

export default {
  async fetch(request, env, ctx) {
    const { pathname } = new URL(request.url);

    if (pathname === "/health" && request.method === "GET") {
      return json({ ok: true, service: "edgar-hooks-inbox" });
    }

    if (pathname === "/test" && request.method === "POST") {
      return json({
        ok: true,
        service: "edgar-hooks-inbox",
        provider: "test",
        temporary: true,
      });
    }

    if (pathname === "/github" && request.method === "POST") {
      const verified = await verifyGitHub(request, env);
      if (!verified.ok) {
        return json(
          {
            ok: false,
            service: "edgar-hooks-inbox",
            provider: "github",
            error: verified.reason,
          },
          401,
        );
      }
      ctx.waitUntil(
        Promise.resolve(
          console.log("GitHub webhook accepted: signature valid"),
        ),
      );
      return json({
        ok: true,
        service: "edgar-hooks-inbox",
        provider: "github",
      });
    }

    if (pathname === "/linear" && request.method === "POST") {
      const verified = await verifyLinear(request, env);
      if (!verified.ok) {
        return json(
          {
            ok: false,
            service: "edgar-hooks-inbox",
            provider: "linear",
            error: verified.reason,
          },
          401,
        );
      }
      ctx.waitUntil(
        Promise.resolve(
          console.log("Linear webhook accepted: signature valid"),
        ),
      );
      return json({
        ok: true,
        service: "edgar-hooks-inbox",
        provider: "linear",
      });
    }

    if (pathname === "/notion" && request.method === "POST") {
      return placeholder("notion");
    }

    if (pathname === "/cloudflare" && request.method === "POST") {
      return placeholder("cloudflare");
    }

    return json({ ok: false, error: "not_found", path: pathname }, 404);
  },
};
