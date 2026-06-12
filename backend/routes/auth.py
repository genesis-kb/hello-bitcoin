"""Auth routes: register, login, refresh, logout, me."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import RATE_LIMIT_AUTH
from limiter import limiter
from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from db import get_db
from models import User
from schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut

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

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
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

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
    )





@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
