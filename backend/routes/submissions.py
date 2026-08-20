"""Submission routes: submit code, poll status, SSE live updates, history."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, get_user_for_sse
from config import RATE_LIMIT_SUBMIT
from limiter import limiter
from db import AsyncSessionLocal, get_db
from models import Problem, Submission, User
from schemas import SubmissionDetailOut, SubmissionOut, SubmitRequest
from services.judging import judge_submission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/submissions", tags=["submissions"])

_SSE_TICKET_TTL = 60       # seconds — one-time ticket lifetime
_SSE_TICKET_PREFIX = "sse_ticket:"


# ── Submit ────────────────────────────────────────────────────────────────────

@router.post("", response_model=SubmissionOut, status_code=201)
@limiter.limit(RATE_LIMIT_SUBMIT)
async def submit(
    request: Request,
    body: SubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    problem = await db.get(Problem, body.problem_id)
    if not problem or (not problem.is_published and current_user.role != "admin"):
        raise HTTPException(404, "Problem not found.")

    submission = Submission(
        user_id=current_user.id,
        problem_id=body.problem_id,
        language=body.language,
        source=body.source,
        status="PENDING",
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    # Enqueue to ARQ worker via Redis
    try:
        await request.app.state.redis_pool.enqueue_job("process_submission", submission.id)
    except Exception as exc:
        logger.exception("ARQ enqueue failed for submission %d", submission.id)
        # V1: clean up the orphaned PENDING row so it doesn't stay permanently pending.
        try:
            await db.delete(submission)
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to delete orphaned submission %d after enqueue failure", submission.id
            )
        raise HTTPException(status_code=500, detail=f"Queue error: {exc}") from exc

    return submission


# ── SSE ticket — short-lived one-time credential for the stream ───────────────

@router.post("/{submission_id}/stream-ticket", status_code=201)
async def create_stream_ticket(
    submission_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    V2: Issue a one-time, 60-second SSE ticket so the browser's EventSource
    doesn't put the long-lived access token in the URL (and in Uvicorn/proxy logs).

    Client flow:
      1. POST here (with normal Authorization header) → receive { "ticket": "..." }
      2. Open EventSource(`/api/submissions/{id}/stream?ticket=<ticket>`)
    The ticket is single-use and expires after 60 seconds.
    """
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found.")
    if submission.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Access denied.")

    ticket = uuid.uuid4().hex
    redis = getattr(request.app.state, "redis_pool", None)
    if redis is not None:
        await redis.set(
            f"{_SSE_TICKET_PREFIX}{ticket}",
            str(current_user.id),
            ex=_SSE_TICKET_TTL,
        )

    return {"ticket": ticket}


# ── Server-Sent Events — real-time status stream ──────────────────────────────

@router.get("/{submission_id}/stream")
async def stream_submission(
    submission_id: int,
    req: Request,
    ticket: str | None = None,          # Short-lived one-time SSE ticket
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_user_for_sse),  # validates ticket or Bearer
):
    """
    SSE endpoint.  The client connects once and receives status events until
    the submission reaches a terminal state (DONE or ERROR).  This replaces
    repeated HTTP polling, cutting DB read load proportional to active users.

    Usage (JavaScript):
        // 1. Get a one-time ticket (keeps access token out of server logs)
        const { ticket } = await apiPost(`/submissions/${id}/stream-ticket`, {}).then(r => r.json());
        // 2. Open the stream with the ticket
        const es = new EventSource(`/api/submissions/${id}/stream?ticket=${ticket}`);
        es.onmessage = e => { const data = JSON.parse(e.data); ... };
    """
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found.")
    if submission.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Access denied.")

    async def event_generator():
        poll_interval = 0.75  # seconds between DB checks
        max_wait = 300        # 5-minute timeout before giving up
        elapsed = 0.0

        while elapsed < max_wait:
            async with AsyncSessionLocal() as poll_db:
                fresh = await poll_db.get(Submission, submission_id)

            if fresh is None:
                break

            data = {
                "id": fresh.id,
                "status": fresh.status,
                "verdict": fresh.verdict,
                "score": fresh.score,
                "cases_total": fresh.cases_total,
                "cases_passed": fresh.cases_passed,
                "time_ms": fresh.time_ms,
                "memory_peak_kb": fresh.memory_peak_kb,
            }
            yield f"data: {json.dumps(data)}\n\n"

            if fresh.status in ("DONE", "ERROR"):
                break

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        yield "event: close\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


# ── List user's own submissions ───────────────────────────────────────────────

@router.get("/my", response_model=list[SubmissionOut])
async def my_submissions(
    problem_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(Submission)
        .where(Submission.user_id == current_user.id)
        .order_by(Submission.created_at.desc())
        .limit(100)
    )
    if problem_id:
        q = q.where(Submission.problem_id == problem_id)
    result = await db.execute(q)
    return result.scalars().all()


# ── Get single submission ─────────────────────────────────────────────────────

@router.get("/{submission_id}", response_model=SubmissionDetailOut)
async def get_submission(
    submission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found.")
    if submission.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Access denied.")
    return submission
