"""
FastAPI wrapper for MCP Server - Phase 2.1: "換外殼、留內臟"

This module provides the FastAPI routing layer while delegating all business logic
to the existing handlers in server_http.py.

Endpoints mirror server_http.py exactly.
"""

import json
import secrets
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional

from fastapi import FastAPI, Request, Response, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

# Import config and helpers from existing server
from server_http import (
    HandcraftServerConfig,
    load_mcp_api_token,
    load_base_url,
    load_webhook_base_url,
    load_bool_env,
    load_cloudflare_access_team_domain,
    load_cloudflare_access_aud,
    load_cloudflare_access_chatgpt_honcho_aud,
    load_cloudflare_access_jwks_url,
    load_package_webhook_token,
    load_linear_webhook_token,
    load_discord_webhook_token,
    load_honcho_mcp_facade_token,
    load_honcho_api_key,
    load_honcho_chatgpt_gateway_enabled,
    load_honcho_chatgpt_write_enabled,
    load_honcho_mcp_hostname,
    # OAuth/Discovery helpers
    build_oauth_authorization_server_metadata,
    build_openid_configuration_metadata,
    build_mcp_resource_url,
    fetch_descope_as_metadata,
    with_openid_scope,
    parse_request_params,
    oauth_error,
    get_oauth_client,
    oauth_redirect_uri_allowed,
    pkce_verifier_matches,
    issue_oauth_access_token,
    is_safe_oauth_redirect_uri,
    parse_basic_client_credentials,
    oauth_client_secret_matches,
    oauth_token_exchange_skips_client_secret,
    # Dispatch and handlers
    dispatch,
    dispatch_chatgpt_honcho,
    handle_discord_webhook_payload,
    verify_linear_webhook_signature,
    linear_oauth_configured,
    linear_oauth_status_payload,
    build_linear_authorize_url,
    issue_linear_oauth_state,
    handle_linear_oauth_callback,
    handle_linear_oauth_bootstrap,
    # Honcho helpers
    build_honcho_mcp_headers,
    normalize_honcho_mcp_response,
    HONCHO_MCP_UPSTREAM_URL,
    LINEAR_WEBHOOK_SECRET,
    # Constants
    SERVER_INFO,
    PROTOCOL_VERSION,
    MCP_PATH,
    OAUTH_SCOPE,
    OAUTH_OIDC_SCOPES,
    OAUTH_AUTH_CODE_TTL_SECONDS,
    OAUTH_CODES,
    OAUTH_CODES_LOCK,
    OAUTH_CLIENTS,
    OAUTH_CLIENTS_LOCK,
    OAUTH_ACCESS_TOKENS,
    OAUTH_TOKENS_LOCK,
    log,
)

# Import adapters
from fastapi_adapters import get_query_string

# ── Origin whitelist (DNS rebinding protection, spec requirement) ─────────────
ALLOWED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "mcp.whoasked.vip",
    "mcp.edgars.tools",
    "auth.edgars.tools",
    "chatgpt.com",
    "chat.openai.com",
    "openai.com",
    "connector.openai.com",
}

# ── CORS allowed headers ──────────────────────────────────────────────────────
ALLOWED_HEADERS = [
    "Content-Type",
    "Authorization",
    "Accept",
    "MCP-Protocol-Version",
    "Mcp-Method",
    "Mcp-Name",
    "Mcp-Session-Id",
    "Cf-Access-Jwt-Assertion",
    "X-Handcraft-Webhook-Token",
    "X-Webhook-Token",
]

# ── Initialize config ─────────────────────────────────────────────────────────
def create_config() -> HandcraftServerConfig:
    """Create server config from environment variables."""
    return HandcraftServerConfig(
        mcp_api_token=load_mcp_api_token(),
        base_url=load_base_url(),
        webhook_base_url=load_webhook_base_url(),
        cloudflare_access_enabled=load_bool_env("MCP_CLOUDFLARE_ACCESS_ENABLED", False),
        cloudflare_access_team_domain=load_cloudflare_access_team_domain(),
        cloudflare_access_aud=load_cloudflare_access_aud(),
        cloudflare_access_chatgpt_honcho_aud=load_cloudflare_access_chatgpt_honcho_aud(),
        cloudflare_access_jwks_url=load_cloudflare_access_jwks_url(),
        cloudflare_access_disable_builtin_oauth=load_bool_env(
            "MCP_CLOUDFLARE_ACCESS_DISABLE_BUILTIN_OAUTH", True
        ),
        cloudflare_access_allow_public_token_fallback=load_bool_env(
            "MCP_CLOUDFLARE_ACCESS_ALLOW_PUBLIC_TOKEN_FALLBACK", False
        ),
        descope_enabled=load_bool_env("MCP_DESCOPE_ENABLED", False),
        descope_project_id=(
            __import__("os").getenv("MCP_DESCOPE_PROJECT_ID", "").strip()
        ),
        descope_audience=__import__("os").getenv("MCP_DESCOPE_AUDIENCE", "").strip(),
        auth_server_url=__import__("os").getenv("MCP_AUTH_SERVER_URL", "").strip(),
        package_webhook_token=load_package_webhook_token(),
        linear_webhook_token=load_linear_webhook_token(),
        discord_webhook_token=load_discord_webhook_token(),
        honcho_mcp_facade_token=load_honcho_mcp_facade_token(),
        honcho_api_key=load_honcho_api_key(),
        honcho_mcp_hostname=load_honcho_mcp_hostname(),
        honcho_chatgpt_gateway_enabled=load_honcho_chatgpt_gateway_enabled(),
        honcho_chatgpt_write_enabled=load_honcho_chatgpt_write_enabled(),
    )


config = create_config()

# ── Create FastAPI app ────────────────────────────────────────────────────────
app = FastAPI(
    title="Edgar's MCP Server",
    description="Streamable HTTP MCP Server with FastAPI",
    version="2.0.0",
)

# ── CORS Middleware ───────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
    allow_headers=ALLOWED_HEADERS,
)


# ── Host-based routing dependency ─────────────────────────────────────────────
def get_is_honcho_host(host: Optional[str] = Header(None)) -> bool:
    """
    Dependency to check if request is targeting Honcho MCP hostname.
    Used for Host-header based routing on /mcp endpoint.
    """
    if not host:
        return False
    # Strip port if present
    hostname = host.split(":")[0].lower()
    return hostname == config.honcho_mcp_hostname


# ── Authorization dependency ──────────────────────────────────────────────────
async def verify_mcp_auth(
    request: Request,
    authorization: str = Header(None),
) -> Optional[str]:
    """
    Verify MCP request authorization.
    Returns the authenticated identity (token/user) or raises 401.
    
    Auth modes (in order):
    1. Descope JWT validation (if descope_enabled)
    2. Static bearer token (mcp_api_token)
    3. OAuth access token (OAUTH_ACCESS_TOKENS)
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")
    
    token = authorization[7:]  # Remove "Bearer " prefix
    
    # Check Descope JWT
    if config.descope_enabled:
        try:
            from server_http import verify_descope_jwt, DescopeAuthError
            claims = verify_descope_jwt(token, config)
            return claims.get("sub", "descope_user")
        except Exception:
            pass  # Fall through to other methods
    
    # Check static token
    if config.mcp_api_token and token == config.mcp_api_token:
        return "static_token"
    
    # Check OAuth token
    with OAUTH_TOKENS_LOCK:
        token_data = OAUTH_ACCESS_TOKENS.get(token)
        if token_data:
            return token_data.get("client_id", "oauth_client")
    
    raise HTTPException(status_code=401, detail="Invalid token")


# ══════════════════════════════════════════════════════════════════════════════
# GET Routes
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/.well-known/oauth-authorization-server")
async def get_oauth_authorization_server(request: Request) -> Response:
    """OAuth 2.0 Authorization Server Metadata (RFC 8414)."""
    if config.descope_enabled and config.descope_issuer:
        # Try fetching live Descope AS metadata
        meta = fetch_descope_as_metadata(config)
        if meta:
            return JSONResponse(content=meta)
        # Fallback to minimal Descope metadata
        return JSONResponse(content={
            "issuer": config.descope_issuer,
            "jwks_uri": config.descope_jwks_url,
            "authorization_endpoint": config.descope_authorization_endpoint,
            "token_endpoint": config.descope_token_endpoint,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        })
    return JSONResponse(content=build_oauth_authorization_server_metadata(config.base_url))


@app.get("/.well-known/oauth-protected-resource")
async def get_oauth_protected_resource(request: Request) -> Response:
    """OAuth 2.0 Protected Resource Metadata."""
    base_url = config.base_url.rstrip("/")
    resource = build_mcp_resource_url(base_url, MCP_PATH)
    
    # Determine authorization server
    if config.auth_server_url:
        auth_server = config.auth_server_url
    elif config.descope_enabled and config.descope_issuer:
        auth_server = config.descope_issuer
    else:
        auth_server = base_url
    
    return JSONResponse(content={
        "resource": resource,
        "authorization_servers": [auth_server],
        "scopes_supported": OAUTH_OIDC_SCOPES,
        "bearer_methods_supported": ["header"],
        "resource_documentation": resource,
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
    })


@app.get("/.well-known/oauth-protected-resource/mcp")
async def get_oauth_protected_resource_mcp(request: Request) -> Response:
    """OAuth 2.0 Protected Resource Metadata for MCP endpoint."""
    base_url = config.base_url.rstrip("/")
    resource = build_mcp_resource_url(base_url, MCP_PATH)
    
    if config.auth_server_url:
        auth_server = config.auth_server_url
    elif config.descope_enabled and config.descope_issuer:
        auth_server = config.descope_issuer
    else:
        auth_server = base_url
    
    return JSONResponse(content={
        "resource": resource,
        "authorization_servers": [auth_server],
        "scopes_supported": OAUTH_OIDC_SCOPES,
        "bearer_methods_supported": ["header"],
        "resource_documentation": resource,
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
    })


@app.get("/.well-known/oauth-protected-resource/chatgpt-honcho")
async def get_oauth_protected_resource_chatgpt_honcho(request: Request) -> Response:
    """OAuth 2.0 Protected Resource Metadata for ChatGPT Honcho endpoint."""
    base_url = config.base_url.rstrip("/")
    resource = build_mcp_resource_url(base_url, "/chatgpt-honcho")
    
    if config.auth_server_url:
        auth_server = config.auth_server_url
    elif config.descope_enabled and config.descope_issuer:
        auth_server = config.descope_issuer
    else:
        auth_server = base_url
    
    return JSONResponse(content={
        "resource": resource,
        "authorization_servers": [auth_server],
        "scopes_supported": OAUTH_OIDC_SCOPES,
        "bearer_methods_supported": ["header"],
        "resource_documentation": resource,
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
    })


@app.get("/.well-known/openid-configuration")
async def get_openid_configuration(request: Request) -> Response:
    """OpenID Connect Discovery document."""
    if config.descope_enabled and config.descope_issuer:
        # Delegate to oauth-authorization-server for Descope
        meta = fetch_descope_as_metadata(config)
        if meta:
            return JSONResponse(content=meta)
        return JSONResponse(content={
            "issuer": config.descope_issuer,
            "jwks_uri": config.descope_jwks_url,
            "authorization_endpoint": config.descope_authorization_endpoint,
            "token_endpoint": config.descope_token_endpoint,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        })
    return JSONResponse(content=build_openid_configuration_metadata(config.base_url))


@app.get("/authorize")
async def get_authorize(request: Request) -> Response:
    """OAuth 2.0 Authorization endpoint."""
    query_string = get_query_string(request)
    params = dict(request.query_params)
    
    response_type = params.get("response_type", "")
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    state = params.get("state", "")
    scope = params.get("scope", OAUTH_SCOPE) or OAUTH_SCOPE
    resource = params.get("resource", "")
    code_challenge = params.get("code_challenge", "")
    code_challenge_method = params.get("code_challenge_method", "")
    
    # If Descope is enabled, redirect to Descope authorization endpoint
    descope_authz = config.descope_authorization_endpoint
    if config.descope_enabled and descope_authz:
        qs = with_openid_scope(query_string)
        if "resource=" not in (qs or ""):
            resource_url = build_mcp_resource_url(config.base_url.rstrip("/"), MCP_PATH)
            extra = "resource=" + urllib.parse.quote(resource_url, safe="")
            qs = f"{qs}&{extra}" if qs else extra
        location = f"{descope_authz}?{qs}" if qs else descope_authz
        log("OAuth /authorize -> Descope official authorization_endpoint")
        return RedirectResponse(url=location, status_code=302)
    
    # Built-in OAuth flow
    client = get_oauth_client(client_id)
    if response_type != "code":
        return JSONResponse(content=oauth_error("unsupported_response_type", "response_type must be code"), status_code=400)
    if not client:
        return JSONResponse(content=oauth_error("invalid_client", "unknown client_id"), status_code=400)
    if not redirect_uri or not oauth_redirect_uri_allowed(client, redirect_uri):
        return JSONResponse(content=oauth_error("invalid_request", "redirect_uri is missing or not registered"), status_code=400)
    
    if code_challenge:
        code_challenge_method = code_challenge_method or "S256"
        if code_challenge_method != "S256":
            return JSONResponse(content=oauth_error("invalid_request", "PKCE S256 code_challenge is required"), status_code=400)
    elif not client.get("client_secret"):
        return JSONResponse(content=oauth_error("invalid_request", "PKCE S256 code_challenge is required for public clients"), status_code=400)
    
    if scope and OAUTH_SCOPE not in scope.split():
        return JSONResponse(content=oauth_error("invalid_scope", f"scope must include {OAUTH_SCOPE}"), status_code=400)
    
    # Generate authorization code
    code = secrets.token_urlsafe(32)
    with OAUTH_CODES_LOCK:
        OAUTH_CODES[code] = {
            "created_at": time.time(),
            "used": False,
            "client_id": client_id,
            "scope": scope,
            "resource": resource,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "redirect_uri": redirect_uri,
        }
    
    sep = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{sep}code={urllib.parse.quote(code)}"
    if state:
        location += f"&state={urllib.parse.quote(state)}"
    log(f"OAuth /authorize -> redirect to {redirect_uri[:60]}...")
    return RedirectResponse(url=location, status_code=302)


@app.get("/health")
async def get_health(request: Request) -> Response:
    """Health check endpoint."""
    from server_http import PORT, HEALTH_PATH, PACKAGE_WEBHOOK_PATH, LINEAR_WEBHOOK_PATH, LINEAR_WEBHOOK_PATH_ALIAS, linear_oauth_status_payload, OAUTH_ACCESS_TOKENS, OAUTH_STATIC_CLIENT_ID
    
    base_url = config.base_url.rstrip("/")
    return JSONResponse(content={
        "ok": True,
        "server": SERVER_INFO,
        "protocolVersion": PROTOCOL_VERSION,
        "local": {
            "host": "0.0.0.0",
            "port": PORT,
            "mcp_path": MCP_PATH,
            "health_path": HEALTH_PATH,
        },
        "public": {
            "base_url": base_url,
            "mcp_url": f"{base_url}{MCP_PATH}",
            "webhook_base_url": (config.webhook_base_url or config.base_url).rstrip("/"),
        },
        "auth": {
            "mcp_api_token_configured": bool(config.mcp_api_token),
            "oauth_public_client_id": OAUTH_STATIC_CLIENT_ID,
            "oauth_active_tokens": len(OAUTH_ACCESS_TOKENS),
            "oauth_mode": "descope" if config.descope_enabled else "handcraft_builtin",
            # Note: Cloudflare Access fields intentionally omitted in FastAPI version
            "descope_enabled": config.descope_enabled,
            "descope_project_configured": bool(config.descope_project_id),
        },
        "webhooks": [
            PACKAGE_WEBHOOK_PATH,
            LINEAR_WEBHOOK_PATH,
            LINEAR_WEBHOOK_PATH_ALIAS,
            "/webhook/discord",
        ],
        "linear_oauth": linear_oauth_status_payload(),
    })


@app.get("/linear/oauth/authorize")
async def get_linear_oauth_authorize(request: Request) -> Response:
    """Linear OAuth authorization initiation."""
    if not linear_oauth_configured():
        return JSONResponse(
            status_code=503,
            content={
                "error": "not_configured",
                "message": "LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET must be set in Doppler",
            },
        )
    try:
        location = build_linear_authorize_url()
    except RuntimeError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "oauth_error", "message": str(exc)},
        )
    log("Linear OAuth /authorize → redirect to Linear")
    return RedirectResponse(url=location, status_code=302)


@app.get("/linear/oauth/callback")
async def get_linear_oauth_callback(request: Request) -> Response:
    """Linear OAuth callback handler."""
    query_string = get_query_string(request)
    status, content_type, body = handle_linear_oauth_callback(query_string)
    return Response(
        content=body.encode("utf-8"),
        status_code=status,
        media_type=content_type,
    )


@app.get("/linear/oauth/status")
async def get_linear_oauth_status(request: Request) -> Response:
    """Linear OAuth status check."""
    return JSONResponse(content=linear_oauth_status_payload())


@app.get("/linear/oauth/bootstrap")
async def get_linear_oauth_bootstrap(request: Request) -> Response:
    """Linear OAuth bootstrap endpoint."""
    status, payload = handle_linear_oauth_bootstrap()
    if payload.get("ok"):
        log(f"Linear OAuth /bootstrap → token saved (grant_type={payload.get('grant_type')})")
    else:
        log(f"Linear OAuth /bootstrap failed: {payload.get('error')}")
    return JSONResponse(content=payload, status_code=status)


@app.get("/mcp")
async def get_mcp(
    request: Request,
    is_honcho_host: bool = Depends(get_is_honcho_host),
) -> Response:
    """
    GET /mcp returns 405 Method Not Allowed with Allow header.
    MCP protocol requires POST for JSON-RPC requests.
    """
    if is_honcho_host:
        # Honcho MCP proxy also returns 405 for GET
        return Response(
            content="Method Not Allowed",
            status_code=405,
            headers={"Allow": "POST, OPTIONS"},
        )
    return Response(
        content="Method Not Allowed",
        status_code=405,
        headers={"Allow": "POST, OPTIONS"},
    )


@app.get("/chatgpt-honcho")
async def get_chatgpt_honcho(request: Request) -> Response:
    """
    GET /chatgpt-honcho returns 405 Method Not Allowed.
    This endpoint only accepts POST requests.
    """
    return Response(
        content="Method Not Allowed",
        status_code=405,
        headers={"Allow": "POST, OPTIONS"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST Routes
# ══════════════════════════════════════════════════════════════════════════════


@app.post("/token")
async def post_token(request: Request) -> Response:
    """OAuth 2.0 Token endpoint."""
    raw = await request.body()
    content_type = request.headers.get("content-type", "")
    params = parse_request_params(raw, content_type)
    
    grant_type = params.get("grant_type", "")
    if grant_type != "authorization_code":
        log("OAuth /token failed: unsupported_grant_type")
        return JSONResponse(content={"error": "unsupported_grant_type"}, status_code=400)
    
    code = params.get("code", "")
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    code_verifier = params.get("code_verifier", "")
    resource = params.get("resource", "")
    
    # Check Basic auth for client_id
    basic_credentials = parse_basic_client_credentials(request.headers.get("authorization", ""))
    if basic_credentials and not client_id:
        client_id = basic_credentials[0]
    
    client = get_oauth_client(client_id)
    if not client:
        log(f"OAuth /token failed: invalid_client (client_id={client_id})")
        return JSONResponse(content={"error": "invalid_client"}, status_code=401)
    
    with OAUTH_CODES_LOCK:
        pending_entry = OAUTH_CODES.get(code)
    
    skip_secret = oauth_token_exchange_skips_client_secret(client, params, code_entry=pending_entry)
    if not skip_secret and not oauth_client_secret_matches(client, params, request.headers.get("authorization", "")):
        log(f"OAuth /token failed: invalid_client - client_secret mismatch (client_id={client_id})")
        return JSONResponse(content={"error": "invalid_client", "error_description": "client_secret mismatch"}, status_code=401)
    
    with OAUTH_CODES_LOCK:
        entry = OAUTH_CODES.get(code)
        if not entry or entry.get("used"):
            log(f"OAuth /token failed: invalid_grant (client_id={client_id})")
            return JSONResponse(content={"error": "invalid_grant"}, status_code=400)
        if time.time() - entry["created_at"] > OAUTH_AUTH_CODE_TTL_SECONDS:
            log(f"OAuth /token failed: invalid_grant - code expired (client_id={client_id})")
            return JSONResponse(content={"error": "invalid_grant", "error_description": "code expired"}, status_code=400)
        if client_id != entry.get("client_id"):
            log(f"OAuth /token failed: invalid_grant - client_id mismatch (client_id={client_id})")
            return JSONResponse(content={"error": "invalid_grant", "error_description": "client_id mismatch"}, status_code=400)
        if redirect_uri != entry.get("redirect_uri"):
            log(f"OAuth /token failed: invalid_grant - redirect_uri mismatch (client_id={client_id})")
            return JSONResponse(content={"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, status_code=400)
        if entry.get("resource") and resource and resource != entry.get("resource"):
            log(f"OAuth /token failed: invalid_grant - resource mismatch (client_id={client_id})")
            return JSONResponse(content={"error": "invalid_grant", "error_description": "resource mismatch"}, status_code=400)
        if entry.get("code_challenge"):
            if not pkce_verifier_matches(
                code_verifier,
                entry.get("code_challenge", ""),
                entry.get("code_challenge_method", ""),
            ):
                log(f"OAuth /token failed: invalid_grant - PKCE verification failed (client_id={client_id})")
                return JSONResponse(content={"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)
        entry["used"] = True
        scope = entry.get("scope", OAUTH_SCOPE)
    
    access_token, expires_in = issue_oauth_access_token(client_id, scope)
    log(f"OAuth /token -> issued access_token (client_id={client_id})")
    return JSONResponse(content={
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": scope,
    })


@app.post("/register")
async def post_register(request: Request) -> Response:
    """OAuth 2.0 Dynamic Client Registration endpoint."""
    raw = await request.body()
    content_type = request.headers.get("content-type", "application/json")
    
    meta = parse_request_params(raw, content_type)
    redirect_uris = meta.get("redirect_uris", [])
    
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return JSONResponse(
            content=oauth_error("invalid_client_metadata", "redirect_uris must be a non-empty list"),
            status_code=400
        )
    if not all(isinstance(uri, str) and is_safe_oauth_redirect_uri(uri) for uri in redirect_uris):
        return JSONResponse(
            content=oauth_error("invalid_client_metadata", "redirect_uris must be HTTPS or localhost HTTP"),
            status_code=400
        )
    
    token_endpoint_auth_method = str(meta.get("token_endpoint_auth_method") or "client_secret_post").strip()
    if token_endpoint_auth_method not in {"client_secret_post", "client_secret_basic", "none"}:
        return JSONResponse(
            content=oauth_error("invalid_client_metadata", "token_endpoint_auth_method must be none, client_secret_post, or client_secret_basic"),
            status_code=400
        )
    
    client_id = secrets.token_urlsafe(24)
    client_secret = "" if token_endpoint_auth_method == "none" else secrets.token_urlsafe(32)
    client = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": str(meta.get("client_name") or "handcraft OAuth client"),
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "created_at": time.time(),
        "source": "dcr",
    }
    with OAUTH_CLIENTS_LOCK:
        OAUTH_CLIENTS[client_id] = client
    
    response = {
        "client_id": client_id,
        "client_id_issued_at": int(client["created_at"]),
        "redirect_uris": redirect_uris,
        "grant_types": meta.get("grant_types") or ["authorization_code"],
        "response_types": meta.get("response_types") or ["code"],
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "scope": str(meta.get("scope") or OAUTH_SCOPE),
    }
    if client_secret:
        response["client_secret"] = client_secret
        response["client_secret_expires_at"] = 0
    
    return JSONResponse(content=response, status_code=201)


def _verify_webhook_token(
    request: Request,
    expected_token: str,
    webhook_name: str,
) -> Optional[str]:
    """
    Extract and verify webhook token from request headers.
    Returns the token if valid, None otherwise.
    """
    token = (
        request.headers.get("x-handcraft-webhook-token")
        or request.headers.get("x-webhook-token")
        or request.headers.get("authorization", "").replace("Bearer ", "")
    )
    if not expected_token:
        # No token configured = allow all
        return token or "no_token_required"
    if not token or token != expected_token:
        return None
    return token


@app.post("/webhook/discord")
async def post_webhook_discord(request: Request) -> Response:
    """Discord webhook handler."""
    token = _verify_webhook_token(request, config.discord_webhook_token, "discord")
    if token is None:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid webhook token"})
    
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"Invalid JSON: {exc}"})
    
    status, response = handle_discord_webhook_payload(payload)
    return JSONResponse(content=response, status_code=status)


@app.post("/webhook/package")
async def post_webhook_package(request: Request) -> Response:
    """Package webhook handler (npm/pypi publish notifications)."""
    token = _verify_webhook_token(request, config.package_webhook_token, "package")
    if token is None:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid webhook token"})
    
    body = await request.body()
    raw_text = body.decode("utf-8", errors="replace")
    log(f"PACKAGE WEBHOOK RECV ← {raw_text}")
    
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "source": "package",
                "accepted": False,
                "error": f"Invalid JSON: {exc}",
            },
        )
    
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "source": "package",
                "accepted": False,
                "error": "Invalid payload: expected JSON object",
            },
        )
    
    return JSONResponse(content={
        "ok": True,
        "source": "package",
        "accepted": True,
        "received": True,
    })


@app.post("/webhook/linear")
async def post_webhook_linear(request: Request) -> Response:
    """Linear webhook handler."""
    # Linear uses both token verification AND HMAC signature
    token = _verify_webhook_token(request, config.linear_webhook_token, "linear")
    if token is None:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid webhook token"})
    
    body = await request.body()
    signature = request.headers.get("linear-signature", "")
    linear_event = request.headers.get("linear-event", "")
    raw_text = body.decode("utf-8", errors="replace")
    log(f"LINEAR WEBHOOK RECV ← event={linear_event!r} body={raw_text}")
    
    # Verify HMAC signature if secret is configured
    if LINEAR_WEBHOOK_SECRET and not verify_linear_webhook_signature(body, signature):
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "source": "linear",
                "accepted": False,
                "error": "Invalid Linear-Signature",
            },
        )
    
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "source": "linear",
                "accepted": False,
                "error": f"Invalid JSON: {exc}",
            },
        )
    
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "source": "linear",
                "accepted": False,
                "error": "Invalid payload: expected JSON object",
            },
        )
    
    return JSONResponse(content={
        "ok": True,
        "source": "linear",
        "accepted": True,
        "received": True,
    })


@app.post("/webhooks/linear")
async def post_webhooks_linear(request: Request) -> Response:
    """Linear webhook handler (alias for /webhook/linear)."""
    return await post_webhook_linear(request)


async def _handle_honcho_mcp_proxy(request: Request) -> Response:
    """Handler for Honcho MCP proxy (internal facade)."""
    # Verify facade token
    token = (
        request.headers.get("authorization", "").replace("Bearer ", "")
        if request.headers.get("authorization", "").lower().startswith("bearer ")
        else ""
    )
    if not config.honcho_mcp_facade_token or token != config.honcho_mcp_facade_token:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid facade token"})
    
    if not config.honcho_api_key:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "honcho_not_configured",
                "error_description": "HONCHO_API_KEY is not configured for the Honcho MCP facade.",
            },
        )
    
    body = await request.body()
    upstream_headers = build_honcho_mcp_headers(
        config,
        content_type=request.headers.get("content-type", "application/json"),
    )
    upstream_headers["Accept"] = request.headers.get("accept", "application/json, text/event-stream")
    upstream_headers["User-Agent"] = "edgars-mcp-honcho-facade/0.1"
    
    req = urllib.request.Request(
        HONCHO_MCP_UPSTREAM_URL,
        data=body,
        headers=upstream_headers,
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            resp_body = response.read()
            content_type = response.headers.get("Content-Type", "application/json")
            status = response.status
    except urllib.error.HTTPError as exc:
        resp_body = exc.read()
        content_type = exc.headers.get("Content-Type", "application/json")
        status = exc.code
    except urllib.error.URLError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "error": "honcho_upstream_unreachable",
                "error_description": str(exc.reason),
            },
        )
    
    resp_body, content_type = normalize_honcho_mcp_response(resp_body, content_type)
    return Response(content=resp_body, status_code=status, media_type=content_type)


@app.post("/honcho-mcp")
async def post_honcho_mcp(request: Request) -> Response:
    """Honcho MCP proxy endpoint (internal facade)."""
    return await _handle_honcho_mcp_proxy(request)


@app.post("/chatgpt-honcho")
async def post_chatgpt_honcho(
    request: Request,
    auth: str = Depends(verify_mcp_auth),
) -> Response:
    """ChatGPT Honcho gateway endpoint (public, auth protected)."""
    if not config.honcho_chatgpt_gateway_enabled:
        return JSONResponse(status_code=404, content={"error": "ChatGPT Honcho gateway not enabled"})
    
    # Validate Content-Type
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return JSONResponse(
            status_code=415,
            content={"error": "Unsupported Media Type", "detail": "Content-Type must be application/json"},
        )
    
    # Validate Accept header for Streamable HTTP
    accept = request.headers.get("accept", "")
    if "application/json" not in accept or "text/event-stream" not in accept:
        return JSONResponse(
            status_code=406,
            content={"error": "Not Acceptable", "detail": "Accept must include both application/json and text/event-stream"},
        )
    
    # Validate Origin
    origin = request.headers.get("origin")
    if origin:
        hostname = urllib.parse.urlparse(origin).hostname
        if hostname and hostname not in ALLOWED_HOSTNAMES:
            return JSONResponse(status_code=403, content={"error": "Forbidden origin"})
    
    body = await request.body()
    try:
        msg = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})
    
    if not isinstance(msg, dict):
        return JSONResponse(status_code=400, content={"error": "Invalid Request: expected JSON object"})
    
    response = dispatch_chatgpt_honcho(msg, config)
    if response is None:
        # Notification → 202 Accepted
        return Response(status_code=202)
    
    return JSONResponse(content=response)


@app.post("/mcp")
async def post_mcp(
    request: Request,
    is_honcho_host: bool = Depends(get_is_honcho_host),
    auth: str = Depends(verify_mcp_auth),
) -> Response:
    """
    Main MCP JSON-RPC endpoint.
    
    When Host header matches honcho_mcp_hostname, routes to Honcho proxy handler
    instead of the main MCP handler.
    """
    if is_honcho_host:
        return await _handle_honcho_mcp_proxy(request)
    
    # Validate Content-Type
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return JSONResponse(
            status_code=415,
            content={"error": "Unsupported Media Type", "detail": "Content-Type must be application/json"},
        )
    
    # Validate Accept header for Streamable HTTP
    accept = request.headers.get("accept", "")
    if "application/json" not in accept or "text/event-stream" not in accept:
        return JSONResponse(
            status_code=406,
            content={"error": "Not Acceptable", "detail": "Accept must include both application/json and text/event-stream"},
        )
    
    # Validate Origin (DNS rebinding protection)
    origin = request.headers.get("origin")
    if origin:
        hostname = urllib.parse.urlparse(origin).hostname
        if hostname and hostname not in ALLOWED_HOSTNAMES:
            log(f"403 Forbidden: Origin={origin!r}")
            return JSONResponse(status_code=403, content={"error": "Forbidden origin"})
    
    # Parse JSON body
    body = await request.body()
    log(f"RECV ← {body.decode('utf-8', errors='replace')}")
    
    try:
        msg = json.loads(body)
    except json.JSONDecodeError as exc:
        return JSONResponse(status_code=400, content={"error": f"Parse error: {exc}"})
    
    if not isinstance(msg, dict):
        return JSONResponse(status_code=400, content={"error": "Invalid Request: expected JSON object"})
    
    # Dispatch to MCP handler
    response = dispatch(msg, config)
    
    if response is None:
        # Notification → 202 Accepted
        return Response(status_code=202)
    
    # Check for method not found error
    if response.get("error", {}).get("code") == -32601:
        return JSONResponse(content=response, status_code=404)
    
    return JSONResponse(content=response)


# ══════════════════════════════════════════════════════════════════════════════
# DELETE Routes
# ══════════════════════════════════════════════════════════════════════════════


@app.delete("/mcp")
async def delete_mcp(request: Request) -> Response:
    """
    DELETE /mcp returns 405 Method Not Allowed.
    MCP protocol does not support DELETE.
    """
    return Response(
        content="Method Not Allowed",
        status_code=405,
        headers={"Allow": "POST, OPTIONS"},
    )


@app.delete("/chatgpt-honcho")
async def delete_chatgpt_honcho(request: Request) -> Response:
    """
    DELETE /chatgpt-honcho returns 405 Method Not Allowed.
    """
    return Response(
        content="Method Not Allowed",
        status_code=405,
        headers={"Allow": "POST, OPTIONS"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Startup
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
