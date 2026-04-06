from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


# ─────────────────────────────────────────────
#  PAPERS
# ─────────────────────────────────────────────

class PaperResponse(BaseModel):
    id: str
    title: Optional[str] = None
    authors: Optional[List[str]] = []
    year: Optional[int] = None
    course_or_program: Optional[str] = None
    abstract: Optional[str] = None
    file_path: Optional[str] = None
    public_url: Optional[str] = None
    access_type: Optional[str] = "open"    # "open" | "students_only" | "restricted"
    uploaded_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PapersListResponse(BaseModel):
    total: int
    results: List[PaperResponse]


class PaperCreate(BaseModel):
    title: str
    authors: List[str]
    year: int
    course_or_program: Optional[str] = None
    abstract: Optional[str] = None
    file_path: Optional[str] = None
    access_type: Optional[str] = "open"
    secondary_email: Optional[str] = None


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    year: Optional[int] = None
    course_or_program: Optional[str] = None
    abstract: Optional[str] = None
    file_path: Optional[str] = None
    access_type: Optional[str] = None


# ─────────────────────────────────────────────
#  BOOKMARKS
# ─────────────────────────────────────────────

class BookmarkResponse(BaseModel):
    id: str
    paper_id: str
    user_id: str
    created_at: Optional[datetime] = None


class BookmarkWithPaperResponse(BaseModel):
    bookmark_id: str
    paper_id: str
    title: Optional[str] = None
    authors: Optional[List[str]] = []
    year: Optional[int] = None
    course_or_program: Optional[str] = None
    abstract: Optional[str] = None
    public_url: Optional[str] = None
    access_type: Optional[str] = "open"
    created_at: Optional[datetime] = None


class BookmarkCreate(BaseModel):
    paper_id: str


class BookmarkStatusResponse(BaseModel):
    is_bookmarked: bool
    bookmark_id: Optional[str] = None


# ─────────────────────────────────────────────
#  ACCESS REQUESTS
# ─────────────────────────────────────────────

class AccessRequestCreate(BaseModel):
    paper_id: str
    message: str


class AccessRequestResponse(BaseModel):
    id: str
    paper_id: str
    requester_id: str
    message: Optional[str] = None
    status: str                             # "pending" | "approved" | "rejected"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Flattened paper info
    paper_title: Optional[str] = None
    paper_course_or_program: Optional[str] = None
    paper_year: Optional[int] = None

    # Flattened requester info
    requester_email: Optional[str] = None
    requester_name: Optional[str] = None

    class Config:
        from_attributes = True


class AccessRequestStatusUpdate(BaseModel):
    status: str                             # "approved" | "rejected"


# ─────────────────────────────────────────────
#  AUTHOR WHITELIST
# ─────────────────────────────────────────────

class WhitelistEntry(BaseModel):
    id: str
    email: str
    added_by: Optional[str] = None
    created_at: Optional[datetime] = None


class WhitelistCreate(BaseModel):
    email: str


# ─────────────────────────────────────────────
#  USER PROFILE
# ─────────────────────────────────────────────

class UserProfileUpdate(BaseModel):
    secondary_email: Optional[str] = None
    full_name: Optional[str] = None