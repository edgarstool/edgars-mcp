"""
FastMCP authentication provider configuration for MCP Server.
Phase 2.2: Use FastMCP's RemoteAuthProvider for OAuth discovery metadata.

This module provides:
1. Factory function to create FastMCP auth provider for Descope JWT validation
2. Helper to extract route handlers for generating PRM metadata
3. Functions to build protected resource metadata using MCP SDK

Note: RemoteAuthProvider only generates path-aware PRM (/.well-known/oauth-protected-resource/{path}).
AS metadata and root PRM are still hand-crafted in server_fastapi.py.
"""

from typing import Optional, List, Dict, Any

from pydantic import AnyHttpUrl

# Import FastMCP auth components
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier

# Import MCP SDK route helpers
from mcp.server.auth.routes import create_protected_resource_routes


def create_auth_provider(
    base_url: str,
    descope_enabled: bool = False,
    descope_project_id: Optional[str] = None,
    descope_audience: Optional[str] = None,
    auth_server_url: Optional[str] = None,
) -> Optional[RemoteAuthProvider]:
    """
    Create a FastMCP RemoteAuthProvider for OAuth discovery.
    
    This provider generates:
    - /.well-known/oauth-protected-resource/{mcp_path} (path-aware PRM)
    
    Note: AS metadata and root PRM are still hand-crafted because
    RemoteAuthProvider doesn't generate those.
    
    Args:
        base_url: Public base URL of this server (e.g., https://mcp.edgars.tools)
        descope_enabled: Whether Descope JWT validation is enabled
        descope_project_id: Descope project ID (for JWKS URL construction)
        descope_audience: Expected audience claim in JWTs
        auth_server_url: Override authorization server URL
    
    Returns:
        RemoteAuthProvider instance, or None if no auth configured
    """
    if not descope_enabled or not descope_project_id:
        # Not using Descope - return None to use hand-crafted fallbacks
        return None
    
    # Descope JWT verification
    descope_issuer = f"https://api.descope.com/{descope_project_id}"
    jwks_uri = f"{descope_issuer}/.well-known/jwks.json"
    
    verifier = JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=descope_issuer,
        audience=descope_audience or None,  # Pass None instead of empty string
        # Note: required_scopes not used - Descope doesn't use scopes the same way
    )
    
    # Use override auth_server_url if provided, otherwise use Descope issuer
    authorization_server = auth_server_url if auth_server_url else descope_issuer
    
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(authorization_server)],
        base_url=AnyHttpUrl(base_url.rstrip("/")),
        resource_base_url=AnyHttpUrl(base_url.rstrip("/")),  # Explicit to avoid bug #1348
        resource_name="Edgar's MCP Server",
        scopes_supported=["mcp:read", "mcp:write", "mcp:admin", "openid", "profile", "email"],
    )


def build_protected_resource_metadata(
    base_url: str,
    mcp_path: str,
    authorization_servers: List[str],
    scopes_supported: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build protected resource metadata dict for a specific MCP endpoint.
    
    This generates the JSON response for:
    - /.well-known/oauth-protected-resource
    - /.well-known/oauth-protected-resource/{path}
    
    The `resource` field MUST equal the actual MCP endpoint URL 
    (e.g., https://mcp.edgars.tools/mcp), NOT just the root URL.
    
    Args:
        base_url: Public base URL of this server
        mcp_path: Path to MCP endpoint (e.g., "/mcp" or "/chatgpt-honcho")
        authorization_servers: List of authorization server URLs
        scopes_supported: Optional list of supported scopes
    
    Returns:
        Dict containing protected resource metadata (RFC 9728)
    """
    base_url = base_url.rstrip("/")
    resource_url = f"{base_url}{mcp_path}"
    
    default_scopes = ["mcp:read", "mcp:write", "mcp:admin", "openid", "profile", "email"]
    
    return {
        "resource": resource_url,
        "authorization_servers": authorization_servers,
        "scopes_supported": scopes_supported or default_scopes,
        "bearer_methods_supported": ["header"],
        "resource_documentation": resource_url,
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic",
            "none",
        ],
    }


def get_starlette_routes_for_prm(
    auth_provider: Optional[RemoteAuthProvider],
    mcp_path: str = "/mcp",
):
    """
    Get Starlette routes from auth provider for path-aware PRM.
    
    Returns list of Starlette Route objects that can be mounted on FastAPI.
    
    Args:
        auth_provider: FastMCP RemoteAuthProvider instance (or None)
        mcp_path: Path to MCP endpoint (e.g., "/mcp")
    
    Returns:
        List of Starlette Route objects, empty if no provider
    """
    if auth_provider is None:
        return []
    
    # get_well_known_routes returns Starlette Route objects
    return auth_provider.get_well_known_routes(mcp_path=mcp_path)


def get_prm_routes_from_mcp_sdk(
    base_url: str,
    mcp_path: str,
    authorization_servers: List[str],
    scopes_supported: Optional[List[str]] = None,
    resource_name: Optional[str] = None,
):
    """
    Get Starlette routes for path-aware PRM using MCP SDK directly.
    
    This is an alternative to using RemoteAuthProvider that doesn't require
    setting up the full JWT verifier.
    
    Args:
        base_url: Public base URL of this server
        mcp_path: Path to MCP endpoint (e.g., "/mcp")
        authorization_servers: List of authorization server URLs
        scopes_supported: Optional list of supported scopes
        resource_name: Optional resource name
    
    Returns:
        List of Starlette Route objects for the path-aware PRM endpoint
    """
    base_url = base_url.rstrip("/")
    resource_url = f"{base_url}{mcp_path}"
    
    return create_protected_resource_routes(
        resource_url=AnyHttpUrl(resource_url),
        authorization_servers=[AnyHttpUrl(s) for s in authorization_servers],
        scopes_supported=scopes_supported,
        resource_name=resource_name,
    )
