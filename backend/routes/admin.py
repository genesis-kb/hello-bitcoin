"""Admin routes — problem CRUD, test cases, user management, stats."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from db import get_db
from judge.checker import validate_checker_syntax
from models import Problem, Submission, TestCase, User
from schemas import (
    AdminProblemDetail,
    ProblemCreateRequest,
    ProblemListItem,
    ProblemUpdateRequest,
    SubmissionOut,
    TestCaseCreateRequest,
    TestCaseOut,
    UserOut,
    UserRoleUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    problems_total = (await db.execute(select(func.count()).select_from(Problem))).scalar()
    problems_published = (await db.execute(
        select(func.count()).select_from(Problem).where(Problem.is_published.is_(True))
    )).scalar()
    submissions_total = (await db.execute(select(func.count()).select_from(Submission))).scalar()
    users_total = (await db.execute(select(func.count()).select_from(User))).scalar()

    verdicts = {}
    rows = (await db.execute(
        select(Submission.verdict, func.count()).group_by(Submission.verdict)
    )).all()
    for verdict, count in rows:
        verdicts[verdict or "PENDING"] = count

    return {
        "problems_total": problems_total,
        "problems_published": problems_published,
        "submissions_total": submissions_total,
        "users_total": users_total,
        "verdicts": verdicts,
    }


# ── Problems ──────────────────────────────────────────────────────────────────

@router.get("/problems", response_model=list[ProblemListItem])
async def list_all_problems(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Problem).order_by(Problem.chapter, Problem.id))
    return result.scalars().all()


@router.post("/problems", response_model=AdminProblemDetail, status_code=201)
async def create_problem(
    body: ProblemCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    existing = await db.get(Problem, body.id)
    if existing:
        raise HTTPException(409, f"Problem '{body.id}' already exists.")

    # Validate checker syntax before persisting
    if body.checker_code:
        err = validate_checker_syntax(body.checker_code)
        if err:
            raise HTTPException(422, f"Invalid checker code: {err}")
    problem = Problem(
        id=body.id,
        title=body.title,
        chapter=body.chapter,
        description=body.description,
        starter_code=body.starter_code,
        wrapper_code=body.wrapper_code,
        checker_code=body.checker_code,
        time_limit=body.time_limit,
        memory_limit=body.memory_limit,
        is_published=body.is_published,
        created_by=admin.id,
    )
    db.add(problem)
    await db.commit()
    await db.refresh(problem)
    return _problem_with_cases(problem, [])


@router.get("/problems/{problem_id}", response_model=AdminProblemDetail)
async def get_admin_problem(
    problem_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    problem = await db.get(Problem, problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found.")
    tc_result = await db.execute(
        select(TestCase).where(TestCase.problem_id == problem_id).order_by(TestCase.order_index)
    )
    test_cases = tc_result.scalars().all()
    return _problem_with_cases(problem, test_cases)


@router.put("/problems/{problem_id}", response_model=AdminProblemDetail)
async def update_problem(
    problem_id: str,
    body: ProblemUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    problem = await db.get(Problem, problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found.")

    # Validate checker syntax if being updated
    new_checker = body.model_dump(exclude_none=True).get("checker_code")
    if new_checker:
        err = validate_checker_syntax(new_checker)
        if err:
            raise HTTPException(422, f"Invalid checker code: {err}")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(problem, field, value)

    await db.commit()
    await db.refresh(problem)
    tc_result = await db.execute(
        select(TestCase).where(TestCase.problem_id == problem_id).order_by(TestCase.order_index)
    )
    return _problem_with_cases(problem, tc_result.scalars().all())


@router.delete("/problems/{problem_id}", status_code=204)
async def delete_problem(
    problem_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    problem = await db.get(Problem, problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found.")
    await db.delete(problem)
    await db.commit()


# ── Test Cases ────────────────────────────────────────────────────────────────

@router.post("/problems/{problem_id}/testcases", response_model=TestCaseOut, status_code=201)
async def add_test_case(
    problem_id: str,
    body: TestCaseCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    problem = await db.get(Problem, problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found.")

    tc = TestCase(
        problem_id=problem_id,
        input=body.input,
        expected_output=body.expected_output,
        is_sample=body.is_sample,
        points=body.points,
        order_index=body.order_index,
    )
    db.add(tc)
    await db.commit()
    await db.refresh(tc)
    return tc


@router.put("/testcases/{tc_id}", response_model=TestCaseOut)
async def update_test_case(
    tc_id: int,
    body: TestCaseCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    tc = await db.get(TestCase, tc_id)
    if not tc:
        raise HTTPException(404, "Test case not found.")

    tc.input = body.input
    tc.expected_output = body.expected_output
    tc.is_sample = body.is_sample
    tc.points = body.points
    tc.order_index = body.order_index
    await db.commit()
    await db.refresh(tc)
    return tc


@router.delete("/testcases/{tc_id}", status_code=204)
async def delete_test_case(
    tc_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    tc = await db.get(TestCase, tc_id)
    if not tc:
        raise HTTPException(404, "Test case not found.")
    await db.delete(tc)
    await db.commit()


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.put("/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: int,
    body: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    if user_id == current_admin.id:
        raise HTTPException(400, "Cannot change your own role.")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    user.role = body.role
    await db.commit()
    await db.refresh(user)
    return user


# ── All Submissions ───────────────────────────────────────────────────────────

@router.get("/submissions", response_model=list[SubmissionOut])
async def list_all_submissions(
    problem_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(Submission).order_by(Submission.created_at.desc()).limit(limit).offset(offset)
    if problem_id:
        q = q.where(Submission.problem_id == problem_id)
    result = await db.execute(q)
    return result.scalars().all()


# ── Helper ────────────────────────────────────────────────────────────────────

def _problem_with_cases(problem: Problem, test_cases: list) -> AdminProblemDetail:
    return AdminProblemDetail(
        id=problem.id,
        title=problem.title,
        chapter=problem.chapter,
        description=problem.description,
        starter_code=problem.starter_code,
        wrapper_code=problem.wrapper_code,
        checker_code=problem.checker_code,
        time_limit=problem.time_limit,
        memory_limit=problem.memory_limit,
        is_published=problem.is_published,
        test_cases=[TestCaseOut.model_validate(tc) for tc in test_cases],
        created_at=problem.created_at,
        updated_at=problem.updated_at,
    )
