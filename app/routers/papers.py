from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Optional
from app.database import get_supabase
from app.models.papers import (
    PaperResponse,
    PapersListResponse,
    BookmarkResponse,
    BookmarkWithPaperResponse,
    BookmarkCreate,
    BookmarkStatusResponse,
    AccessRequestCreate,
    AccessRequestResponse,
)
from app.middleware.auth import get_current_user
from app.models.auth import TokenData
from app.config import settings

router = APIRouter(prefix="/api", tags=["papers"])

BUCKET = settings.STORAGE_BUCKET


def _get_public_url(file_path: Optional[str]) -> Optional[str]:
    """Generate a public storage URL for a file_path, or None."""
    if not file_path:
        return None
    supabase = get_supabase()
    return supabase.storage.from_(BUCKET).get_public_url(file_path)


def _attach_url(paper: dict) -> dict:
    """Attach public_url to a paper dict in-place."""
    paper["public_url"] = _get_public_url(paper.get("file_path"))
    return paper


# ─────────────────────────────────────────────
#  PAPERS  (public)
# ─────────────────────────────────────────────

@router.get("/papers", response_model=PapersListResponse)
def list_papers(
    q: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    sort_by: Optional[str] = "created_at",
):
    """
    Return all papers with optional filtering.
    Public — no authentication required.
    """
    supabase = get_supabase()

    query = supabase.table("papers").select(
        "id, title, authors, year, course_or_program, abstract, file_path, access_type, uploaded_by, created_at, updated_at"
    )

    if year_from:
        query = query.gte("year", year_from)
    if year_to:
        query = query.lte("year", year_to)

    if q and q.strip():
        term = q.strip()
        query = query.or_(
            f"title.ilike.%{term}%,"
            f"abstract.ilike.%{term}%,"
            f"course_or_program.ilike.%{term}%"
        )

    order_col = "year" if sort_by == "year" else "created_at"
    query = query.order(order_col, desc=True)

    response = query.execute()

    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch papers."
        )

    papers = [_attach_url(p) for p in response.data]
    return PapersListResponse(total=len(papers), results=papers)


@router.get("/papers/{paper_id}", response_model=PaperResponse)
def get_paper(paper_id: str):
    """
    Return a single paper by ID.
    Public — no authentication required.
    NOTE: public_url is always returned here; access enforcement
    is handled on the frontend based on access_type + user state.
    """
    supabase = get_supabase()

    response = (
        supabase.table("papers")
        .select("id, title, authors, year, course_or_program, abstract, file_path, access_type, uploaded_by, created_at, updated_at")
        .eq("id", paper_id)
        .single()
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    return _attach_url(response.data)


# ─────────────────────────────────────────────
#  BOOKMARKS  (auth required)
# ─────────────────────────────────────────────

@router.get("/bookmarks", response_model=List[BookmarkWithPaperResponse])
def get_user_bookmarks(
    current_user: TokenData = Depends(get_current_user),
):
    """Return all bookmarks for the current user, enriched with paper data."""
    supabase = get_supabase()

    response = (
        supabase.table("bookmarks")
        .select("id, paper_id, created_at, papers(id, title, authors, year, course_or_program, abstract, file_path, access_type)")
        .eq("user_id", current_user.user_id)
        .order("created_at", desc=True)
        .execute()
    )

    results = []
    for row in (response.data or []):
        paper = row.get("papers") or {}
        results.append(BookmarkWithPaperResponse(
            bookmark_id=row["id"],
            paper_id=row["paper_id"],
            title=paper.get("title"),
            authors=paper.get("authors") or [],
            year=paper.get("year"),
            course_or_program=paper.get("course_or_program"),
            abstract=paper.get("abstract"),
            public_url=_get_public_url(paper.get("file_path")),
            access_type=paper.get("access_type", "open"),
            created_at=row.get("created_at"),
        ))

    return results


@router.post("/bookmarks", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED)
def add_bookmark(
    body: BookmarkCreate,
    current_user: TokenData = Depends(get_current_user),
):
    """Bookmark a paper for the current user."""
    supabase = get_supabase()

    existing = (
        supabase.table("bookmarks")
        .select("id")
        .eq("user_id", current_user.user_id)
        .eq("paper_id", body.paper_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already bookmarked.")

    result = (
        supabase.table("bookmarks")
        .insert({"user_id": current_user.user_id, "paper_id": body.paper_id})
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create bookmark.")

    return result.data[0]


@router.delete("/bookmarks/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_bookmark(
    bookmark_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Remove a bookmark. Only the owner can delete it."""
    supabase = get_supabase()

    existing = (
        supabase.table("bookmarks")
        .select("id")
        .eq("id", bookmark_id)
        .eq("user_id", current_user.user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found.")

    supabase.table("bookmarks").delete().eq("id", bookmark_id).execute()


# NOTE: /bookmarks/status/{paper_id} MUST come before /bookmarks/{bookmark_id}
@router.get("/bookmarks/status/{paper_id}", response_model=BookmarkStatusResponse)
def bookmark_status(
    paper_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Check if the current user has bookmarked a specific paper."""
    supabase = get_supabase()

    result = (
        supabase.table("bookmarks")
        .select("id")
        .eq("user_id", current_user.user_id)
        .eq("paper_id", paper_id)
        .execute()
    )

    if result.data:
        return BookmarkStatusResponse(is_bookmarked=True, bookmark_id=result.data[0]["id"])
    return BookmarkStatusResponse(is_bookmarked=False, bookmark_id=None)


# ─────────────────────────────────────────────
#  ACCESS REQUESTS  (auth required)
# ─────────────────────────────────────────────

@router.get("/requests", response_model=List[AccessRequestResponse])
def get_user_requests(
    current_user: TokenData = Depends(get_current_user),
):
    """
    Return all access requests submitted by the current user,
    joined with paper info. Used by RequestsPage.
    """
    supabase = get_supabase()

    response = (
        supabase.table("access_requests")
        .select("id, paper_id, requester_id, message, status, created_at, updated_at, papers(title, course_or_program, year)")
        .eq("requester_id", current_user.user_id)
        .order("created_at", desc=True)
        .execute()
    )

    results = []
    for row in (response.data or []):
        paper = row.get("papers") or {}
        results.append(AccessRequestResponse(
            id=row["id"],
            paper_id=row["paper_id"],
            requester_id=row["requester_id"],
            message=row.get("message"),
            status=row.get("status", "pending"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            paper_title=paper.get("title"),
            paper_course_or_program=paper.get("course_or_program"),
            paper_year=paper.get("year"),
        ))

    return results


@router.post("/requests", response_model=AccessRequestResponse, status_code=status.HTTP_201_CREATED)
def create_request(
    body: AccessRequestCreate,
    current_user: TokenData = Depends(get_current_user),
):
    """
    Submit an access request for a restricted paper.
    Re-submits if previously rejected.
    """
    if len(body.message.strip()) < 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message must be at least 20 characters."
        )

    supabase = get_supabase()

    existing = (
        supabase.table("access_requests")
        .select("id, status")
        .eq("requester_id", current_user.user_id)
        .eq("paper_id", body.paper_id)
        .execute()
    )

    if existing.data:
        existing_status = existing.data[0]["status"]
        if existing_status == "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request already pending.")
        if existing_status == "approved":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Access already approved.")
        # Rejected — update back to pending with new message
        if existing_status == "rejected":
            result = (
                supabase.table("access_requests")
                .update({"message": body.message.strip(), "status": "pending"})
                .eq("id", existing.data[0]["id"])
                .execute()
            )
            row = result.data[0] if result.data else {}
            return AccessRequestResponse(
                id=row.get("id", existing.data[0]["id"]),
                paper_id=body.paper_id,
                requester_id=current_user.user_id,
                message=body.message.strip(),
                status="pending",
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )

    result = (
        supabase.table("access_requests")
        .insert({
            "requester_id": current_user.user_id,
            "paper_id": body.paper_id,
            "message": body.message.strip(),
            "status": "pending",
        })
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to submit request.")

    row = result.data[0]
    return AccessRequestResponse(
        id=row["id"],
        paper_id=body.paper_id,
        requester_id=current_user.user_id,
        message=body.message.strip(),
        status="pending",
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# NOTE: /requests/status/{paper_id} MUST come before /requests/{request_id}
@router.get("/requests/status/{paper_id}", response_model=AccessRequestResponse)
def get_request_status(
    paper_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """
    Check if the current user has an existing request for a paper.
    Used by PaperPreviewPage on load.
    Returns 404 if no request exists.
    """
    supabase = get_supabase()

    result = (
        supabase.table("access_requests")
        .select("id, paper_id, requester_id, message, status, created_at, updated_at")
        .eq("requester_id", current_user.user_id)
        .eq("paper_id", paper_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No request found.")

    row = result.data[0]
    return AccessRequestResponse(
        id=row["id"],
        paper_id=row["paper_id"],
        requester_id=row["requester_id"],
        message=row.get("message"),
        status=row["status"],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )