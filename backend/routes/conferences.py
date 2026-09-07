from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_optional
from db import get_db
from models import Conference, Problem, User
from schemas import ConferenceListItem, ConferenceDetail, ProblemListItem

router = APIRouter(prefix="/conferences", tags=["conferences"])

@router.get("", response_model=list[ConferenceListItem])
async def list_conferences(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    q = select(Conference).order_by(Conference.year.desc().nulls_last(), Conference.name)
    if not (current_user and current_user.role == "admin"):
        q = q.where(Conference.is_published.is_(True))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{slug}", response_model=ConferenceDetail)
async def get_conference(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    q = select(Conference).options(selectinload(Conference.problems)).where(Conference.slug == slug)
    result = await db.execute(q)
    conference = result.scalar_one_or_none()
    
    if not conference:
        raise HTTPException(404, "Conference not found.")
    if not conference.is_published and not (current_user and current_user.role == "admin"):
        raise HTTPException(404, "Conference not found.")
        
    return conference


@router.get("/{slug}/problems", response_model=list[ProblemListItem])
async def get_conference_problems(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    q = select(Conference).where(Conference.slug == slug)
    if not (current_user and current_user.role == "admin"):
        q = q.where(Conference.is_published.is_(True))
    conference = (await db.execute(q)).scalar_one_or_none()
    
    if not conference:
        raise HTTPException(404, "Conference not found.")
        
    prob_q = select(Problem).where(Problem.conference_id == conference.id).order_by(Problem.order_index, Problem.id)
    if not (current_user and current_user.role == "admin"):
        prob_q = prob_q.where(Problem.is_published.is_(True))
        
    result = await db.execute(prob_q)
    return result.scalars().all()
