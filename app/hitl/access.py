"""Local-access guardrails for unauthenticated HITL decision routes.

Until real authentication exists, approve / reject / reconcile endpoints refuse
non-loopback clients. ``local-operator`` is an audit label only — not auth.

Limitations (documented intentionally):
- Does not protect against malicious processes or browsers on the same host.
- Does not defend against XSS or compromised local software.
- X-Forwarded-For is ignored so reverse proxies cannot widen access by spoofing.
"""

from __future__ import annotations

from fastapi import Request

# Starlette TestClient reports host as "testclient".
_LOOPBACK_HOSTS = frozenset(
    {
        "127.0.0.1",
        "::1",
        "localhost",
        "testclient",
    }
)


class NonLoopbackAccessError(PermissionError):
    """Raised when a privileged HITL route is called from a non-loopback client."""


def client_host(request: Request) -> str | None:
    """Return the immediate TCP peer host. Does not trust forwarded headers."""
    client = request.client
    if client is None:
        return None
    return (client.host or "").strip().lower() or None


def is_loopback_request(request: Request) -> bool:
    host = client_host(request)
    return host is not None and host in _LOOPBACK_HOSTS


def require_loopback(request: Request) -> None:
    """Fail closed unless the peer is loopback (or the test client)."""
    if not is_loopback_request(request):
        host = client_host(request) or "unknown"
        raise NonLoopbackAccessError(
            f"HITL decision routes are restricted to loopback clients; "
            f"refused peer {host!r}. local-operator is not authentication."
        )
