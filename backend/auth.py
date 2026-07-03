"""JWT authentication + password hashing utilities.

Token revocation is implemented via a per-JTI Redis key:
  - On refresh-token creation  → store JTI in Redis with TTL = REFRESH_TOKEN_EXPIRE_DAYS
  - On token refresh (rotate)  → delete old JTI, issue new one
  - On logout                  → delete JTI immediately (token becomes invalid)
  - On validation              → check JTI exists; reject if missing
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
)
from db import get_db
from models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

# Redis client is injected lazily from app.state to avoid import-time coupling.
# All revocation helpers accept an optional `redis` parameter; when None they
# skip revocation silently (safe for unit tests without Redis).


# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Token ─────────────────────────────────────────────────────────────────────

def _create_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    payload.setdefault("jti", uuid.uuid4().hex)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    return _create_token(
        {"sub": str(user_id), "role": role, "type": "access"},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        {"sub": str(user_id), "type": "refresh"},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


# ── JTI revocation helpers ────────────────────────────────────────────────────

_REVOKE_PREFIX = "revoked_jti:"


async def store_refresh_jti(redis, jti: str) -> None:
    """Register a refresh token JTI as valid.  TTL mirrors token lifetime."""
    if redis is None:
        return
    ttl_seconds = REFRESH_TOKEN_EXPIRE_DAYS * 86_400
    await redis.set(f"{_REVOKE_PREFIX}{jti}", "1", ex=ttl_seconds)


async def revoke_refresh_jti(redis, jti: str) -> None:
    """Immediately invalidate a refresh token (logout or rotation)."""
    if redis is None:
        return
    await redis.delete(f"{_REVOKE_PREFIX}{jti}")


async def is_refresh_jti_valid(redis, jti: str) -> bool:
    """Return True only if the JTI was registered and not yet revoked."""
    if redis is None:
        return True  # Skip check when Redis unavailable (dev/test mode)
    result = await redis.get(f"{_REVOKE_PREFIX}{jti}")
    return result is not None


# ── FastAPI dependencies ──────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user_id = int(payload["sub"])
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def get_user_for_sse(
    token: Optional[str] = None,  # ?token= query param — used by EventSource
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Auth dependency for the SSE streaming endpoint.

    The browser's native EventSource API cannot set custom HTTP headers,
    so the access token is accepted either as:
      - Authorization: Bearer <token>  (normal API clients, fetch/axios)
      - ?token=<access_token>          (browser EventSource)

    The Bearer header takes precedence when both are present.
    """
    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(raw_token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = int(payload["sub"])
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user
