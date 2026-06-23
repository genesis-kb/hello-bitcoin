"""Submission routes: submit code, poll status, SSE live updates, history."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import RATE_LIMIT_SUBMIT
from limiter import limiter
from db import AsyncSessionLocal, get_db
from models import Problem, Submission, User
from schemas import SubmissionDetailOut, SubmissionOut, SubmitRequest
from services.judging import judge_submission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/submissions", tags=["submissions"])


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
        raise HTTPException(status_code=500, detail=f"Queue error: {exc}") from exc

    return submission





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
