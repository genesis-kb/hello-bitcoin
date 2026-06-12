"""App settings — read from environment variables (with sensible defaults)."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ── Database ────────────────────────────────────────────────────────────────
# Switch to PostgreSQL for production:
#   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/oj
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR}/data/judge.db")

# ── JWT ──────────────────────────────────────────────────────────────────────
_DEFAULT_SECRET = "CHANGE_ME_IN_PRODUCTION_super_secret_key_32ch"
SECRET_KEY = os.getenv("SECRET_KEY", _DEFAULT_SECRET)

# Fail fast in any non-development environment with a weak key.
_is_dev = os.getenv("APP_ENV", "development").lower() in ("development", "dev", "test")
if not _is_dev and (not SECRET_KEY or SECRET_KEY == _DEFAULT_SECRET or len(SECRET_KEY) < 32):
    sys.exit(
        "FATAL: SECRET_KEY must be set to a random string of ≥32 characters in production. "
        "Set APP_ENV=development to suppress this check locally."
    )
if SECRET_KEY == _DEFAULT_SECRET:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "SECRET_KEY is using the insecure default. Set a strong random value before deploying."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# ── Bootstrap admin ──────────────────────────────────────────────────────────
# Used ONLY by seed.py to create the initial admin user.
# Registration no longer auto-promotes any email to admin.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")

# ── CORS ─────────────────────────────────────────────────────────────────────
# Comma-separated list of allowed origins. Wildcard "*" is NOT allowed when
# credentials are enabled; explicit origins must be listed.
# Note: do NOT add "null" here — it is the Origin sent by file:// pages and
# sandboxed iframes and would allow any local HTML file to make credentialed requests.
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:5500").split(",")
    if o.strip()
]

# ── Rate Limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_AUTH = os.getenv("RATE_LIMIT_AUTH", "10/minute")
RATE_LIMIT_SUBMIT = os.getenv("RATE_LIMIT_SUBMIT", "20/minute")

# ── Docker judge pool ────────────────────────────────────────────────────────
JUDGE_IMAGE = os.getenv("JUDGE_IMAGE", "bitcoin-oj-runner")

# Global memory limit for the judge sandboxes (in MB)
GLOBAL_MAX_MEMORY_MB = int(os.getenv("GLOBAL_MAX_MEMORY_MB", "8192"))
# Memory limit per sandbox container (in MB)
SANDBOX_MEMORY_MB = int(os.getenv("SANDBOX_MEMORY_MB", "256"))

# Pool size = how many containers can run concurrently on this worker VM.
JUDGE_POOL_SIZE = max(1, GLOBAL_MAX_MEMORY_MB // SANDBOX_MEMORY_MB)

# ── Redis Queue ───────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
