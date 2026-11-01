"""Explicit, default-off RFC 7662 callback for the native MCP verifier.

Only the operator supplies the endpoint and confidential client credentials.
No discovery, token-selected URLs, redirects, proxies, retries or active cache.
HTTPS uses Python's default certificate/hostname verification. Plain HTTP needs
an explicit test-only opt-in and a literal loopback address.
"""

from dataclasses import dataclass
import http.client
import json
import math
from urllib.parse import urlencode, urlsplit


class IntrospectionError(RuntimeError):
    """Sanitized failure; callers must reject the bearer token."""


@dataclass(frozen=True, repr=False)
class HTTPIntrospectionClient:
    endpoint: str
    client_id: str
    client_secret: str
    timeout: float = 2.0
    allow_loopback_http: bool = False

    def __post_init__(self):
        if (not isinstance(self.timeout, (int, float))
                or isinstance(self.timeout, bool)
                or not math.isfinite(self.timeout)
                or not 0 < self.timeout <= 30):
            raise ValueError("introspection timeout must be finite and in (0, 30]")
        if not all(isinstance(value, str) and 0 < len(value) <= 2048
                   for value in (self.client_id, self.client_secret)):
            raise ValueError("confidential client credentials are required")
        if (not isinstance(self.endpoint, str) or len(self.endpoint) > 2048
                or any(c.isspace() or ord(c) < 32 for c in self.endpoint)
                or any(c in self.endpoint for c in ("\\", "?", "#"))):
            raise ValueError("invalid fixed introspection endpoint")
        try:
            url = urlsplit(self.endpoint)
            port = url.port
            valid = (url.scheme in ("https", "http") and url.hostname
                     and url.username is None and url.password is None
                     and (port is None or 0 < port <= 65535))
            if url.scheme == "http":
                valid = (valid and self.allow_loopback_http
                         and url.hostname in ("127.0.0.1", "::1"))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("HTTPS endpoint required (explicit loopback HTTP for tests only)")

    def __call__(self, token: str) -> dict:
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise IntrospectionError("invalid introspection input")
        url = urlsplit(self.endpoint)
        connection_type = (http.client.HTTPSConnection if url.scheme == "https"
                           else http.client.HTTPConnection)
        connection = connection_type(url.hostname, url.port, timeout=self.timeout)
        try:
            body = urlencode({
                "token": token, "token_type_hint": "access_token",
                "client_id": self.client_id, "client_secret": self.client_secret,
            }).encode("ascii")
            if len(body) > 8192:
                raise IntrospectionError("introspection input too large")
            connection.request("POST", url.path or "/", body=body, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            })
            response = connection.getresponse()
            if response.status != 200:
                raise IntrospectionError("introspection request failed")
            raw = response.read(65537)
            if len(raw) > 65536:
                raise IntrospectionError("introspection response too large")
            status = json.loads(raw)
            if not isinstance(status, dict) or type(status.get("active")) is not bool:
                raise IntrospectionError("invalid introspection response")
            return status
        except (OSError, http.client.HTTPException, ValueError):
            # Do not leak bodies, credentials, endpoint details or bearer tokens.
            raise IntrospectionError("introspection request failed") from None
        finally:
            connection.close()
