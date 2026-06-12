"""Problem listing and detail routes (user-facing)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_optional
from db import get_db
from models import Problem, Submission, TestCase, User
from schemas import ProblemDetail, ProblemListItem, TestCaseOut

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("", response_model=list[ProblemListItem])
async def list_problems(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List all published problems (admins see unpublished too)."""
    q = select(Problem).order_by(Problem.chapter, Problem.id)
    if not (current_user and current_user.role == "admin"):
        q = q.where(Problem.is_published.is_(True))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{problem_id}", response_model=ProblemDetail)
async def get_problem(
    problem_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    problem = await db.get(Problem, problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found.")
    if not problem.is_published and not (current_user and current_user.role == "admin"):
        raise HTTPException(404, "Problem not found.")

    # Return only sample test cases to the user
    result = await db.execute(
        select(TestCase)
        .where(TestCase.problem_id == problem_id, TestCase.is_sample.is_(True))
        .order_by(TestCase.order_index)
    )
    sample_cases = result.scalars().all()

    return ProblemDetail(
        id=problem.id,
        title=problem.title,
        chapter=problem.chapter,
        description=problem.description,
        starter_code=problem.starter_code,
        time_limit=problem.time_limit,
        memory_limit=problem.memory_limit,
        sample_cases=[TestCaseOut.model_validate(tc) for tc in sample_cases],
    )
