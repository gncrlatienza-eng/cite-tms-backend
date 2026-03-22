from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Optional
from datetime import datetime
from app.database import get_supabase
from app.models.papers import (
    PaperResponse,
    PapersListResponse,
    PaperCreate,
    PaperUpdate,
    AccessRequestResponse,
    AccessRequestStatusUpdate,
    UserProfileUpdate,
)
from app.middleware.auth import get_current_user
from app.models.auth import TokenData
from app.config import settings

router = APIRouter(prefix="/api/author", tags=["author"])

BUCKET = settings.STORAGE_BUCKET

VALID_ACCESS_TYPES = ("open", "students_only", "restricted")


def _get_public_url(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    supabase = get_supabase()
    return supabase.storage.from_(BUCKET).get_public_url(file_path)


def _attach_url(paper: dict) -> dict:
    paper["public_url"] = _get_public_url(paper.get("file_path"))
    return paper


def _require_author(current_user: TokenData):
    """Dependency — verify the current user has is_author = true."""
    supabase = get_supabase()
    result = (
        supabase.table("users")
        .select("is_author")
        .eq("id", current_user.user_id)
        .single()
        .execute()
    )
    if not result.data or not result.data.get("is_author"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Author access required."
        )
    return current_user


# ─────────────────────────────────────────────
#  AUTHOR PROFILE
# ─────────────────────────────────────────────

@router.get("/me")
def get_author_profile(current_user: TokenData = Depends(get_current_user)):
    """
    Return the current user's profile including is_author status.
    Used by the frontend to determine if author nav should be shown.
    """
    current_user = _require_author(current_user)
    supabase = get_supabase()

    result = (
        supabase.table("users")
        .select("id, email, full_name, role, is_author, secondary_email, department, year_level, student_id")
        .eq("id", current_user.user_id)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return result.data


@router.patch("/me")
def update_author_profile(
    body: UserProfileUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    """Author updates their own profile (e.g. secondary_email, full_name)."""
    current_user = _require_author(current_user)
    supabase = get_supabase()

    payload = {}
    if body.secondary_email is not None:
        payload["secondary_email"] = body.secondary_email.lower().strip()
    if body.full_name is not None:
        payload["full_name"] = body.full_name.strip()

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update."
        )

    result = (
        supabase.table("users")
        .update(payload)
        .eq("id", current_user.user_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile."
        )

    return result.data[0]


# ─────────────────────────────────────────────
#  AUTHOR'S OWN PAPERS
# ─────────────────────────────────────────────

@router.post("/papers", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
def author_upload_paper(
    body: PaperCreate,
    current_user: TokenData = Depends(get_current_user),
):
    """
    Author uploads a new paper.

    Paper is inserted with status='pending_review' — admin must approve
    before it becomes publicly visible. A review request is also created
    so the admin sees it in their upgrade-requests queue.
    """
    current_user = _require_author(current_user)
    supabase = get_supabase()

    if body.access_type not in VALID_ACCESS_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"access_type must be one of: {', '.join(VALID_ACCESS_TYPES)}"
        )

    # ── Insert paper as pending_review ────────────────────────────────────────
    payload = {
        "title":             body.title,
        "authors":           body.authors,
        "year":              body.year,
        "course_or_program": body.course_or_program,
        "abstract":          body.abstract,
        "file_path":         body.file_path,
        "access_type":       body.access_type or "open",
        "uploaded_by":       current_user.user_id,
        "status":            "pending_review",  # hidden from public until approved
    }

    result = supabase.table("papers").insert(payload).execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload paper."
        )

    paper = result.data[0]

    # ── Create admin review request (hard failure + rollback) ─────────────────
    # Reuses author_upgrade_requests table so admin sees it in one queue.
    # For existing authors, admin_decide_upgrade_request safely keeps is_author=true.
    upgrade_result = (
        supabase.table("author_upgrade_requests")
        .insert({
            "user_id":  current_user.user_id,
            "paper_id": paper["id"],
            "status":   "pending",
        })
        .execute()
    )

    if not upgrade_result.data:
        # Roll back the paper to keep the DB consistent
        supabase.table("papers").delete().eq("id", paper["id"]).execute()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create review request. Paper upload was rolled back."
        )

    return _attach_url(paper)


@router.get("/papers", response_model=PapersListResponse)
def author_list_papers(current_user: TokenData = Depends(get_current_user)):
    """
    Return all papers uploaded by the current author,
    including pending_review ones so they can track submissions.
    """
    current_user = _require_author(current_user)
    supabase = get_supabase()

    response = (
        supabase.table("papers")
        .select("id, title, authors, year, course_or_program, abstract, file_path, access_type, status, uploaded_by, created_at, updated_at")
        .eq("uploaded_by", current_user.user_id)
        .order("created_at", desc=True)
        .execute()
    )

    papers = [_attach_url(p) for p in (response.data or [])]
    return PapersListResponse(total=len(papers), results=papers)


@router.patch("/papers/{paper_id}", response_model=PaperResponse)
def author_update_paper(
    paper_id: str,
    body: PaperUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    """Author edits their own paper metadata. Cannot edit others' papers."""
    current_user = _require_author(current_user)
    supabase = get_supabase()

    existing = (
        supabase.table("papers")
        .select("id, uploaded_by")
        .eq("id", paper_id)
        .single()
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    if existing.data.get("uploaded_by") != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own papers."
        )

    payload = {}
    if body.title is not None:
        payload["title"] = body.title
    if body.authors is not None:
        payload["authors"] = body.authors
    if body.year is not None:
        payload["year"] = body.year
    if body.course_or_program is not None:
        payload["course_or_program"] = body.course_or_program
    if body.abstract is not None:
        payload["abstract"] = body.abstract
    if body.file_path is not None:
        payload["file_path"] = body.file_path
    if body.access_type is not None:
        if body.access_type not in VALID_ACCESS_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"access_type must be one of: {', '.join(VALID_ACCESS_TYPES)}"
            )
        payload["access_type"] = body.access_type

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update."
        )

    payload["updated_at"] = datetime.utcnow().isoformat()

    result = (
        supabase.table("papers")
        .update(payload)
        .eq("id", paper_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update paper."
        )

    return _attach_url(result.data[0])


@router.delete("/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def author_delete_paper(
    paper_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Author deletes their own paper and removes PDF from storage."""
    current_user = _require_author(current_user)
    supabase = get_supabase()

    existing = (
        supabase.table("papers")
        .select("id, uploaded_by, file_path")
        .eq("id", paper_id)
        .single()
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    if existing.data.get("uploaded_by") != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own papers."
        )

    file_path = existing.data.get("file_path")
    if file_path:
        try:
            supabase.storage.from_(BUCKET).remove([file_path])
        except Exception:
            pass  # Non-fatal — storage cleanup failure shouldn't block DB delete

    supabase.table("papers").delete().eq("id", paper_id).execute()


# ─────────────────────────────────────────────
#  REQUESTS ON AUTHOR'S PAPERS
# ─────────────────────────────────────────────

@router.get("/requests", response_model=List[AccessRequestResponse])
def author_list_requests(
    status_filter: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
):
    """
    Return all access requests on the current author's papers.
    Filter by status: ?status_filter=pending
    """
    current_user = _require_author(current_user)
    supabase = get_supabase()

    owned = (
        supabase.table("papers")
        .select("id")
        .eq("uploaded_by", current_user.user_id)
        .execute()
    )

    if not owned.data:
        return []

    paper_ids = [p["id"] for p in owned.data]

    query = (
        supabase.table("access_requests")
        .select("id, paper_id, requester_id, message, status, created_at, updated_at")
        .in_("paper_id", paper_ids)
        .order("created_at", desc=True)
    )

    if status_filter:
        query = query.eq("status", status_filter)

    response = query.execute()
    rows = response.data or []

    # ── Manual hydration (avoids FK join requirement) ─────────────────────────
    req_paper_ids = list({r["paper_id"]     for r in rows if r.get("paper_id")})
    req_user_ids  = list({r["requester_id"] for r in rows if r.get("requester_id")})

    papers_map = {}
    if req_paper_ids:
        p_res = supabase.table("papers").select("id, title, course_or_program, year").in_("id", req_paper_ids).execute()
        papers_map = {p["id"]: p for p in (p_res.data or [])}

    users_map = {}
    if req_user_ids:
        u_res = supabase.table("users").select("id, email, full_name").in_("id", req_user_ids).execute()
        users_map = {u["id"]: u for u in (u_res.data or [])}

    results = []
    for row in rows:
        paper = papers_map.get(row.get("paper_id"), {})
        user  = users_map.get(row.get("requester_id"), {})
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
            requester_email=user.get("email"),
            requester_name=user.get("full_name"),
        ))

    return results


@router.patch("/requests/{request_id}", response_model=AccessRequestResponse)
def author_update_request(
    request_id: str,
    body: AccessRequestStatusUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    """Author approves or rejects a request on their own paper only."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status must be 'approved' or 'rejected'."
        )

    current_user = _require_author(current_user)
    supabase = get_supabase()

    req = (
        supabase.table("access_requests")
        .select("id, paper_id, requester_id, message, status, created_at")
        .eq("id", request_id)
        .single()
        .execute()
    )

    if not req.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")

    paper = (
        supabase.table("papers")
        .select("id, uploaded_by")
        .eq("id", req.data["paper_id"])
        .single()
        .execute()
    )

    if not paper.data or paper.data.get("uploaded_by") != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage requests for your own papers."
        )

    result = (
        supabase.table("access_requests")
        .update({"status": body.status, "updated_at": datetime.utcnow().isoformat()})
        .eq("id", request_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update request."
        )

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