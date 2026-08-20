"""
Shared rate limiter instance.

Backed by Redis so limits are enforced globally across all API replicas.
Without a shared backend each process keeps its own counter, allowing
clients to bypass limits by hitting different replicas.

Imported by route modules (routes/auth.py, routes/submissions.py) to avoid
circular imports: main.py → routes → main.py.
"""

from config import REDIS_URL
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL,   # shared across all worker/API processes
    default_limits=[],       # per-endpoint limits set via @limiter.limit()
)
