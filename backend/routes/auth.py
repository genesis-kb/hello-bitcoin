"""Auth routes: register, login, refresh, logout, me."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import RATE_LIMIT_AUTH
from limiter import limiter
from auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    is_refresh_jti_valid,
    revoke_refresh_jti,
    store_refresh_jti,
    verify_password,
)
from db import get_db
from models import User
from schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit(RATE_LIMIT_AUTH)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check uniqueness
    existing = await db.execute(
        select(User).where((User.email == body.email) | (User.username == body.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email or username already taken.")

    # All newly registered users are plain "user" role.
    # Admin promotion is done exclusively via PUT /api/admin/users/{id}/role.
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role="user",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    refresh_token = create_refresh_token(user.id)
    refresh_payload = decode_token(refresh_token)
    jti = refresh_payload.get("jti")

    redis = getattr(request.app.state, "redis_pool", None)
    if jti:
        await store_refresh_jti(redis, jti)

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials.")
    if not user.is_active:
        raise HTTPException(403, "Account is disabled.")

    refresh_token = create_refresh_token(user.id)
    refresh_payload = decode_token(refresh_token)
    jti = refresh_payload.get("jti")

    redis = getattr(request.app.state, "redis_pool", None)
    if jti:
        await store_refresh_jti(redis, jti)

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token.")

    jti = payload.get("jti")
    redis = getattr(request.app.state, "redis_pool", None)

    # Validate that this JTI hasn't been revoked
    if jti and not await is_refresh_jti_valid(redis, jti):
        raise HTTPException(401, "Refresh token has been revoked.")

    user = await db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive.")

    # Rotate: revoke old JTI, issue new refresh token
    if jti:
        await revoke_refresh_jti(redis, jti)

    new_refresh = create_refresh_token(user.id)
    new_payload = decode_token(new_refresh)
    new_jti = new_payload.get("jti")
    if new_jti:
        await store_refresh_jti(redis, new_jti)

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=new_refresh,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    body: RefreshRequest,
):
    """Revoke the refresh token immediately — client should discard both tokens."""
    try:
        payload = decode_token(body.refresh_token)
    except HTTPException:
        return  # Already invalid; nothing to revoke

    jti = payload.get("jti")
    if jti:
        redis = getattr(request.app.state, "redis_pool", None)
        await revoke_refresh_jti(redis, jti)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
