"""
FastAPI Adapters - Phase 2.1

Helper functions to extract request context and adapt between FastAPI
Request/Response objects and the existing server_http.py handler logic.
"""

from typing import Any
import urllib.parse

from fastapi import Request


async def extract_request_context(request: Request) -> dict[str, Any]:
    """
    Extract request context for handler functions.
    Returns a dict with standardized request data.
    """
    body = None
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
    
    return {
        "path": request.url.path,
        "method": request.method,
        "headers": dict(request.headers),
        "query_params": dict(request.query_params),
        "query_string": str(request.url.query),
        "body": body,
        "client_ip": request.client.host if request.client else None,
    }


def get_query_string(request: Request) -> str:
    """Get raw query string from request."""
    return str(request.url.query)


def get_header(request: Request, name: str, default: str = "") -> str:
    """Get a header value from request."""
    return request.headers.get(name, default)


def get_content_type(request: Request) -> str:
    """Get Content-Type header."""
    return request.headers.get("content-type", "")


def get_authorization_header(request: Request) -> str:
    """Get Authorization header."""
    return request.headers.get("authorization", "")


async def get_body(request: Request) -> bytes:
    """Get request body as bytes."""
    return await request.body()


def parse_query_params(query_string: str) -> dict[str, str]:
    """Parse query string into single-value dict."""
    parsed = urllib.parse.parse_qs(query_string)
    return {k: v[0] for k, v in parsed.items()}
