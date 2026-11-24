"""
Unit tests for the proxy-aware rate-limit key and the SSE concurrency cap.

Neither needs Docker or a running server: the rate-limit key function is pure,
and the SSE slot helpers are exercised against a tiny in-memory fake Redis.
"""

import asyncio
import os

os.environ.setdefault("APP_ENV", "test")

import config
from limiter import client_ip
from routes import submissions


# ── Fakes ───────────────────────────────────────────────────────────────────

class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, host, headers=None):
        self.client = _FakeClient(host)
        # Starlette headers are case-insensitive; client_ip looks up the lower-case key.
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def incr(self, k):
        self.store[k] = self.store.get(k, 0) + 1
        return self.store[k]

    async def decr(self, k):
        self.store[k] = self.store.get(k, 0) - 1
        return self.store[k]

    async def expire(self, k, ttl):
        return True


# ── Rate-limit key function ──────────────────────────────────────────────────

def test_without_trust_proxy_uses_socket_ip(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_TRUST_PROXY", False)
    req = _FakeRequest("10.0.0.9", {"X-Forwarded-For": "1.2.3.4"})
    # XFF must be ignored when we don't trust a proxy.
    assert client_ip(req) == "10.0.0.9"


def test_trust_proxy_single_hop_takes_real_client(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_TRUST_PROXY", True)
    monkeypatch.setattr(config, "RATE_LIMIT_PROXY_HOPS", 1)
    # Client spoofs a left-hand value; the single trusted proxy appends the real IP.
    req = _FakeRequest("172.16.0.1", {"X-Forwarded-For": "9.9.9.9, 203.0.113.7"})
    assert client_ip(req) == "203.0.113.7"


def test_trust_proxy_distinct_clients_get_distinct_keys(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_TRUST_PROXY", True)
    monkeypatch.setattr(config, "RATE_LIMIT_PROXY_HOPS", 1)
    a = client_ip(_FakeRequest("172.16.0.1", {"X-Forwarded-For": "203.0.113.1"}))
    b = client_ip(_FakeRequest("172.16.0.1", {"X-Forwarded-For": "203.0.113.2"}))
    # The whole point: two users behind the same proxy must not share one bucket.
    assert a != b


def test_trust_proxy_two_hops(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_TRUST_PROXY", True)
    monkeypatch.setattr(config, "RATE_LIMIT_PROXY_HOPS", 2)
    # spoof , realclient , proxy1   (two trusted proxies in front)
    req = _FakeRequest("172.16.0.1", {"X-Forwarded-For": "9.9.9.9, 203.0.113.7, 172.16.0.2"})
    assert client_ip(req) == "203.0.113.7"


def test_trust_proxy_without_header_falls_back(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_TRUST_PROXY", True)
    req = _FakeRequest("10.0.0.5")
    assert client_ip(req) == "10.0.0.5"


# ── SSE concurrency cap ──────────────────────────────────────────────────────

def test_sse_slots_capped_per_user(monkeypatch):
    monkeypatch.setattr(submissions, "SSE_MAX_STREAMS_PER_USER", 3)
    redis = _FakeRedis()

    async def scenario():
        # First 3 acquisitions succeed.
        assert all([await submissions._acquire_stream_slot(redis, 42) for _ in range(3)])
        # The 4th is rejected.
        assert await submissions._acquire_stream_slot(redis, 42) is False
        # Count did not creep past the cap (rejected acquire rolled back its incr).
        assert redis.store["sse_active:42"] == 3
        # Releasing one frees a slot again.
        await submissions._release_stream_slot(redis, 42)
        assert await submissions._acquire_stream_slot(redis, 42) is True

    asyncio.run(scenario())


def test_sse_slots_are_per_user(monkeypatch):
    monkeypatch.setattr(submissions, "SSE_MAX_STREAMS_PER_USER", 1)
    redis = _FakeRedis()

    async def scenario():
        assert await submissions._acquire_stream_slot(redis, 1) is True
        assert await submissions._acquire_stream_slot(redis, 1) is False   # user 1 at cap
        assert await submissions._acquire_stream_slot(redis, 2) is True    # user 2 unaffected

    asyncio.run(scenario())


def test_sse_without_redis_allows_streaming():
    async def scenario():
        assert await submissions._acquire_stream_slot(None, 1) is True
        await submissions._release_stream_slot(None, 1)  # must not raise

    asyncio.run(scenario())
