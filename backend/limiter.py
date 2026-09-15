"""
Shared rate limiter instance.

Backed by Redis so limits are enforced globally across all API replicas.
Without a shared backend each process keeps its own counter, allowing
clients to bypass limits by hitting different replicas.

Imported by route modules (routes/auth.py, routes/submissions.py) to avoid
circular imports: main.py → routes → main.py.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from config import CLIENT_IP_HEADER, REDIS_URL


def client_ip(request: Request) -> str:
    if CLIENT_IP_HEADER:
        value = request.headers.get(CLIENT_IP_HEADER)
        if value:
            first = value.split(",")[0].strip()
            if first:
                return first
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_ip,
    storage_uri=REDIS_URL,   # shared across all worker/API processes
    default_limits=[],       # per-endpoint limits set via @limiter.limit()
)
