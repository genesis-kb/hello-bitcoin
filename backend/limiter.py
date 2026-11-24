"""
Shared rate limiter instance.

Backed by Redis so limits are enforced globally across all API replicas.
Without a shared backend each process keeps its own counter, allowing
clients to bypass limits by hitting different replicas.

Imported by route modules (routes/auth.py, routes/submissions.py) to avoid
circular imports: main.py → routes → main.py.
"""

import config
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def client_ip(request: Request) -> str:
    """
    Key function for rate limiting.

    `get_remote_address` only sees the socket peer. Behind a reverse proxy that
    is always the proxy, so every user collapses to one key and per-IP limits
    stop working. When RATE_LIMIT_TRUST_PROXY is set (app is behind a proxy you
    control), take the client IP from X-Forwarded-For instead, counting
    RATE_LIMIT_PROXY_HOPS entries from the right so a spoofed left-hand value is
    ignored. Config is read at call time so it can be overridden in tests.
    """
    if config.RATE_LIMIT_TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                idx = max(0, len(parts) - config.RATE_LIMIT_PROXY_HOPS)
                return parts[idx]
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_ip,
    storage_uri=config.REDIS_URL,   # shared across all worker/API processes
    default_limits=[],              # per-endpoint limits set via @limiter.limit()
)
