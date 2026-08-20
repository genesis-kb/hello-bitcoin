"""FastAPI application entry point."""

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from arq import create_pool
from arq.connections import RedisSettings

from config import ALLOWED_ORIGINS, JUDGE_IMAGE, REDIS_URL, RATE_LIMIT_AUTH, RATE_LIMIT_SUBMIT
from db import get_db, init_db
from limiter import limiter
from routes import auth, problems, submissions, books, conferences, admin as admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(asctime)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def _redact_url(url: str) -> str:
    """Strip credentials from a connection URL before logging."""
    return re.sub(r"(://)[^@/]+@", r"\1***:***@", url)


# ── Rate limiter ──────────────────────────────────────────────────────────────
# Imported from limiter.py — route modules import from there too to avoid
# circular imports (main → routes → main).


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Initialising database…")
    await init_db()

    # V1: log only the redacted URL so Redis passwords don't appear in logs.
    logger.info("Connecting to Redis queue (%s)…", _redact_url(REDIS_URL))
    # V2: use from_dsn so credentials, TLS (rediss://), and DB index are preserved.
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    app.state.redis_pool = await create_pool(redis_settings)
    app.state.limiter = limiter

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Closing Redis connection…")
    if hasattr(app.state, "redis_pool"):
        await app.state.redis_pool.close()


app = FastAPI(
    title="Hello Bitcoin",
    description="Online judge for exercises from *Programming Bitcoin* by Jimmy Song.",
    version="1.1.0",
    lifespan=lifespan,
)

# ── Rate limiting middleware ───────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Explicit origins only — wildcard "*" is incompatible with allow_credentials=True.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health / readiness endpoint ───────────────────────────────────────────────

@app.get("/health", tags=["ops"], summary="Liveness + readiness probe")
async def health(request: Request):
    """
    Returns 200 when the API, database, and Redis are all reachable.
    Suitable for Kubernetes readiness/liveness probes and load-balancer health checks.
    """
    checks: dict = {}

    # Database check
    try:
        async for db in get_db():
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    # Redis check
    try:
        await request.app.state.redis_pool.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse({"status": "ok" if all_ok else "degraded", "checks": checks}, status_code=status_code)


# ── API routes ────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(problems.router, prefix="/api")
app.include_router(submissions.router, prefix="/api")
app.include_router(books.router, prefix="/api")
app.include_router(conferences.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")

# ── Frontend (served as static files) ────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    logger.info("Serving frontend from %s", FRONTEND_DIR)
else:
    logger.warning("Frontend directory not found at %s — API-only mode.", FRONTEND_DIR)
