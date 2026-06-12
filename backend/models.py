"""SQLAlchemy ORM models."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, JSON, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user")  # "user" | "admin"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    submissions: Mapped[list["Submission"]] = relationship(back_populates="user")


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # e.g. "ch01_field_add"
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    chapter: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text, default="")      # Markdown
    starter_code: Mapped[dict] = mapped_column(JSON, default=dict)  # Shown to user
    wrapper_code: Mapped[dict] = mapped_column(JSON, default=dict)  # Appended by judge (hidden)
    checker_code: Mapped[str] = mapped_column(Text, default="")     # Checker program source
    time_limit: Mapped[float] = mapped_column(Float, default=5.0)   # seconds
    memory_limit: Mapped[int] = mapped_column(Integer, default=256) # MB
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan", order_by="TestCase.order_index"
    )
    submissions: Mapped[list["Submission"]] = relationship(back_populates="problem")


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    problem_id: Mapped[str] = mapped_column(String(100), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    input: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)  # Shown to users
    points: Mapped[int] = mapped_column(Integer, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    problem: Mapped["Problem"] = relationship(back_populates="test_cases")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        # Optimise the most common query patterns:
        # - user history page: WHERE user_id = X ORDER BY created_at DESC
        # - admin problem filter: WHERE problem_id = X
        # - worker status update: WHERE status IN ('PENDING', 'JUDGING')
        Index("ix_submission_user_created", "user_id", "created_at"),
        Index("ix_submission_problem", "problem_id"),
        Index("ix_submission_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    problem_id: Mapped[str] = mapped_column(String(100), ForeignKey("problems.id"), nullable=False)
    language: Mapped[str] = mapped_column(String(30), default="python3")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING | JUDGING | DONE | ERROR
    verdict: Mapped[str] = mapped_column(String(10), nullable=True)     # AC | WA | TLE | RE | CE
    score: Mapped[float] = mapped_column(Float, default=0.0)
    cases_total: Mapped[int] = mapped_column(Integer, default=0)
    cases_passed: Mapped[int] = mapped_column(Integer, default=0)
    compile_error: Mapped[str] = mapped_column(Text, nullable=True)
    time_ms: Mapped[int] = mapped_column(Integer, default=0)
    # memory_peak_kb: measured by the harness via resource.getrusage() — 0 until instrumented
    memory_peak_kb: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="submissions")
    problem: Mapped["Problem"] = relationship(back_populates="submissions")
