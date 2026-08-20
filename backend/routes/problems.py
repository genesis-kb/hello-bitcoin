"""Problem listing and detail routes (user-facing)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_optional
from db import get_db
from models import Problem, TestCase, User, BookChapter, Book
from schemas import ProblemDetail, ProblemListItem, TestCaseOut
from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/problems", tags=["problems"])

@router.get("", response_model=list[ProblemListItem])
async def list_problems(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List all published problems (admins see unpublished too)."""
    q = select(Problem).order_by(Problem.order_index, Problem.id)
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
    q = select(Problem).options(
        selectinload(Problem.conference),
        selectinload(Problem.book_chapter).selectinload(BookChapter.book)
    ).where(Problem.id == problem_id)
    problem = (await db.execute(q)).scalar_one_or_none()

    if not problem:
        raise HTTPException(404, "Problem not found.")
    if not problem.is_published and not (current_user and current_user.role == "admin"):
        raise HTTPException(404, "Problem not found.")

    # V1: also hide problems whose parent conference or book is unpublished,
    # matching the behaviour of the book/conference problem list endpoints.
    is_admin = current_user and current_user.role == "admin"
    if not is_admin:
        if problem.source_type == "conference" and problem.conference:
            if not problem.conference.is_published:
                raise HTTPException(404, "Problem not found.")
        elif problem.source_type == "book" and problem.book_chapter and problem.book_chapter.book:
            if not problem.book_chapter.book.is_published:
                raise HTTPException(404, "Problem not found.")

    parent_name = None
    parent_slug = None
    if problem.source_type == "conference" and problem.conference:
        parent_name = problem.conference.name
        parent_slug = problem.conference.slug
    elif problem.source_type == "book" and problem.book_chapter and problem.book_chapter.book:
        parent_name = f"{problem.book_chapter.book.title} (Ch. {problem.book_chapter.number})"
        parent_slug = problem.book_chapter.book.slug

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
        source_type=problem.source_type,
        order_index=problem.order_index,
        description=problem.description,
        starter_code=problem.starter_code,
        time_limit=problem.time_limit,
        memory_limit=problem.memory_limit,
        sample_cases=[TestCaseOut.model_validate(tc) for tc in sample_cases],
        parent_name=parent_name,
        parent_slug=parent_slug,
    )
