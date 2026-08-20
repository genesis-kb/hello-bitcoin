"""Admin routes — problem CRUD, test cases, user management, stats."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import re

from auth import require_admin
from db import get_db
from judge.checker import validate_checker_syntax
from models import Problem, Submission, TestCase, User, Conference, Book, BookChapter
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
    ConferenceCreateRequest, ConferenceUpdateRequest, ConferenceDetail, ConferenceListItem,
    BookCreateRequest, BookUpdateRequest, BookDetail, BookListItem,
    BookChapterCreateRequest, BookChapterUpdateRequest, BookChapterDetail, BookChapterItem
)

router = APIRouter(prefix="/admin", tags=["admin"])


def generate_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


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


# ── Conferences ───────────────────────────────────────────────────────────────

@router.post("/conferences", response_model=ConferenceListItem, status_code=201)
async def create_conference(
    body: ConferenceCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    existing = (await db.execute(select(Conference).where(Conference.slug == body.slug))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Conference with slug '{body.slug}' already exists.")
    
    conf = Conference(
        name=body.name,
        slug=body.slug,
        description=body.description,
        year=body.year,
        is_published=body.is_published
    )
    db.add(conf)
    await db.commit()
    await db.refresh(conf)
    return conf


@router.put("/conferences/{conf_id}", response_model=ConferenceListItem)
async def update_conference(
    conf_id: int,
    body: ConferenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    conf = await db.get(Conference, conf_id)
    if not conf:
        raise HTTPException(404, "Conference not found.")
        
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(conf, field, value)
        
    await db.commit()
    await db.refresh(conf)
    return conf


@router.delete("/conferences/{conf_id}", status_code=204)
async def delete_conference(
    conf_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    conf = await db.get(Conference, conf_id)
    if not conf:
        raise HTTPException(404, "Conference not found.")
    await db.delete(conf)
    await db.commit()


# ── Books ─────────────────────────────────────────────────────────────────────

@router.post("/books", response_model=BookListItem, status_code=201)
async def create_book(
    body: BookCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    existing = (await db.execute(select(Book).where(Book.slug == body.slug))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Book with slug '{body.slug}' already exists.")
        
    book = Book(
        title=body.title,
        slug=body.slug,
        author=body.author,
        description=body.description,
        is_published=body.is_published
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


@router.put("/books/{book_id}", response_model=BookListItem)
async def update_book(
    book_id: int,
    body: BookUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(404, "Book not found.")
        
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(book, field, value)
        
    await db.commit()
    await db.refresh(book)
    return book


@router.delete("/books/{book_id}", status_code=204)
async def delete_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(404, "Book not found.")
    await db.delete(book)
    await db.commit()


# ── Book Chapters ─────────────────────────────────────────────────────────────

@router.post("/books/{book_id}/chapters", response_model=BookChapterItem, status_code=201)
async def create_chapter(
    book_id: int,
    body: BookChapterCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(404, "Book not found.")

    # Pre-check for duplicate chapter number to give a clear 409 before hitting the DB constraint.
    existing_ch = (await db.execute(
        select(BookChapter).where(
            BookChapter.book_id == book_id,
            BookChapter.number == body.number,
        )
    )).scalar_one_or_none()
    if existing_ch:
        raise HTTPException(409, f"Chapter {body.number} already exists in this book.")

    chapter = BookChapter(
        book_id=book_id,
        number=body.number,
        title=body.title,
        description=body.description
    )
    db.add(chapter)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, f"Chapter {body.number} already exists in this book.")
    await db.refresh(chapter)
    return chapter


@router.put("/chapters/{chapter_id}", response_model=BookChapterItem)
async def update_chapter(
    chapter_id: int,
    body: BookChapterUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    chapter = await db.get(BookChapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found.")
        
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(chapter, field, value)
        
    await db.commit()
    await db.refresh(chapter)
    return chapter


@router.delete("/chapters/{chapter_id}", status_code=204)
async def delete_chapter(
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    chapter = await db.get(BookChapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found.")
    await db.delete(chapter)
    await db.commit()


# ── Problems ──────────────────────────────────────────────────────────────────

@router.get("/problems", response_model=list[ProblemListItem])
async def list_all_problems(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(Problem)
        .options(
            selectinload(Problem.conference),
            selectinload(Problem.book_chapter).selectinload(BookChapter.book),
            selectinload(Problem.test_cases)
        )
        .order_by(Problem.order_index, Problem.id)
    )
    problems = result.scalars().all()
    out = []
    for p in problems:
        item = ProblemListItem.model_validate(p)
        if p.source_type == "conference" and p.conference:
            item.parent_name = p.conference.name
            item.parent_slug = p.conference.slug
        elif p.source_type == "book" and p.book_chapter and p.book_chapter.book:
            item.parent_name = f"{p.book_chapter.book.title} (Ch {p.book_chapter.number})"
            item.parent_slug = p.book_chapter.book.slug
        item.tests_count = len(p.test_cases)
        out.append(item)
    return out


@router.post("/problems", response_model=AdminProblemDetail, status_code=201)
async def create_problem(
    body: ProblemCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    slug_id = generate_slug(body.title)
    existing = await db.get(Problem, slug_id)
    if existing:
        raise HTTPException(409, f"Problem '{slug_id}' already exists.")

    if body.checker_code:
        err = validate_checker_syntax(body.checker_code)
        if err:
            raise HTTPException(422, f"Invalid checker code: {err}")
            
    problem = Problem(
        id=slug_id,
        title=body.title,
        source_type=body.source_type,
        conference_id=body.conference_id,
        book_chapter_id=body.book_chapter_id,
        order_index=body.order_index,
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

    new_checker = body.model_dump(exclude_none=True).get("checker_code")
    if new_checker:
        err = validate_checker_syntax(new_checker)
        if err:
            raise HTTPException(422, f"Invalid checker code: {err}")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(problem, field, value)

    # V1: clear the opposite parent FK so only one relationship remains active
    # when source_type changes (e.g. conference → book or book → conference).
    effective_source_type = body.model_dump(exclude_none=True).get("source_type", problem.source_type)
    if effective_source_type == "conference":
        problem.book_chapter_id = None
    elif effective_source_type == "book":
        problem.conference_id = None

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

    # V3: reject deletion if submissions exist rather than hitting an unhandled
    # DB integrity error from the RESTRICT FK on Submission.problem_id.
    has_submissions = (await db.execute(
        select(Submission.id).where(Submission.problem_id == problem_id).limit(1)
    )).first()
    if has_submissions:
        raise HTTPException(
            409,
            "Cannot delete a problem that has submissions. "
            "Unpublish it instead, or delete all submissions first."
        )

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
        source_type=problem.source_type,
        conference_id=problem.conference_id,
        book_chapter_id=problem.book_chapter_id,
        order_index=problem.order_index,
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
