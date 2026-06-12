"""Pydantic schemas for requests and responses."""

from datetime import datetime
from typing import Optional, Dict

from pydantic import BaseModel, EmailStr, Field


# ── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Problems ──────────────────────────────────────────────────────────────────

class TestCaseOut(BaseModel):
    id: int
    input: str
    expected_output: str
    is_sample: bool
    points: int
    order_index: int

    model_config = {"from_attributes": True}


class ProblemListItem(BaseModel):
    id: str
    title: str
    chapter: int
    time_limit: float
    memory_limit: int
    is_published: bool

    model_config = {"from_attributes": True}


class ProblemDetail(BaseModel):
    id: str
    title: str
    chapter: int
    description: str
    starter_code: Dict[str, str]
    time_limit: float
    memory_limit: int
    sample_cases: list[TestCaseOut]

    model_config = {"from_attributes": True}


# ── Submissions ───────────────────────────────────────────────────────────────

class SubmitRequest(BaseModel):
    problem_id: str
    language: str = Field("python3", pattern="^(python3|javascript|rust)$")
    source: str = Field(..., max_length=65536)


class SubmissionOut(BaseModel):
    id: int
    user_id: int
    problem_id: str
    language: str
    status: str
    verdict: Optional[str]
    score: float
    cases_total: int
    cases_passed: int
    compile_error: Optional[str]
    time_ms: int
    memory_peak_kb: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmissionDetailOut(SubmissionOut):
    source: str
    
    model_config = {"from_attributes": True}


# ── Admin ─────────────────────────────────────────────────────────────────────

class ProblemCreateRequest(BaseModel):
    id: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-z0-9_]+$")
    title: str = Field(..., max_length=200)
    chapter: int = 1
    description: str = ""
    starter_code: Dict[str, str] = {}
    wrapper_code: Dict[str, str] = {}
    checker_code: str = ""
    time_limit: float = 5.0
    memory_limit: int = 256
    is_published: bool = False


class ProblemUpdateRequest(BaseModel):
    title: Optional[str] = None
    chapter: Optional[int] = None
    description: Optional[str] = None
    starter_code: Optional[Dict[str, str]] = None
    wrapper_code: Optional[Dict[str, str]] = None
    checker_code: Optional[str] = None
    time_limit: Optional[float] = None
    memory_limit: Optional[int] = None
    is_published: Optional[bool] = None


_TC_MAX = 1_048_576  # 1 MB per test case field


class TestCaseCreateRequest(BaseModel):
    input: str = Field("", max_length=_TC_MAX)
    expected_output: str = Field("", max_length=_TC_MAX)
    is_sample: bool = False
    points: int = Field(1, ge=0)
    order_index: int = Field(0, ge=0)


class AdminProblemDetail(BaseModel):
    id: str
    title: str
    chapter: int
    description: str
    starter_code: Dict[str, str]
    wrapper_code: Dict[str, str]
    checker_code: str
    time_limit: float
    memory_limit: int
    is_published: bool
    test_cases: list[TestCaseOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserRoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(user|admin)$")
