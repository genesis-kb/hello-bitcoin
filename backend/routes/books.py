from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload, with_loader_criteria
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_optional
from db import get_db
from models import Book, BookChapter, Problem, User
from schemas import BookListItem, BookDetail, BookChapterDetail, ProblemListItem

router = APIRouter(prefix="/books", tags=["books"])

@router.get("", response_model=list[BookListItem])
async def list_books(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    q = select(Book).order_by(Book.title)
    if not (current_user and current_user.role == "admin"):
        q = q.where(Book.is_published.is_(True))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{slug}", response_model=BookDetail)
async def get_book(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    q = select(Book).options(selectinload(Book.chapters)).where(Book.slug == slug)
    result = await db.execute(q)
    book = result.scalar_one_or_none()
    
    if not book:
        raise HTTPException(404, "Book not found.")
    if not book.is_published and not (current_user and current_user.role == "admin"):
        raise HTTPException(404, "Book not found.")
        
    return book


@router.get("/{slug}/chapters/{chapter_num}", response_model=BookChapterDetail)
async def get_book_chapter(
    slug: str,
    chapter_num: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    book_q = select(Book).where(Book.slug == slug)
    book = (await db.execute(book_q)).scalar_one_or_none()
    if not book:
        raise HTTPException(404, "Book not found.")
    if not book.is_published and not (current_user and current_user.role == "admin"):
        raise HTTPException(404, "Book not found.")

    is_admin = current_user and current_user.role == "admin"

    # V1: filter unpublished problems from the eager-loaded relationship for non-admins
    # so chapter detail doesn't leak unpublished problem titles/metadata.
    if is_admin:
        problems_loader = selectinload(BookChapter.problems)
    else:
        problems_loader = selectinload(BookChapter.problems).options(
            with_loader_criteria(Problem, Problem.is_published.is_(True))
        )

    chapter_q = select(BookChapter).options(problems_loader).where(
        BookChapter.book_id == book.id,
        BookChapter.number == chapter_num
    )
    chapter = (await db.execute(chapter_q)).scalar_one_or_none()
    if not chapter:
        raise HTTPException(404, "Chapter not found.")
        
    return chapter


@router.get("/{slug}/problems", response_model=list[ProblemListItem])
async def get_book_problems(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    book_q = select(Book).where(Book.slug == slug)
    if not (current_user and current_user.role == "admin"):
        book_q = book_q.where(Book.is_published.is_(True))
    book = (await db.execute(book_q)).scalar_one_or_none()
    
    if not book:
        raise HTTPException(404, "Book not found.")
        
    prob_q = select(Problem).join(BookChapter).where(BookChapter.book_id == book.id).order_by(BookChapter.number, Problem.order_index, Problem.id)
    if not (current_user and current_user.role == "admin"):
        prob_q = prob_q.where(Problem.is_published.is_(True))
        
    result = await db.execute(prob_q)
    return result.scalars().all()
