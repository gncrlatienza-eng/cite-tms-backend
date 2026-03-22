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
    WhitelistEntry,
    WhitelistCreate,
)
from app.middleware.auth import get_current_user, require_admin
from app.models.auth import TokenData
from app.config import settings
from pydantic import BaseModel
from typing import Literal

router = APIRouter(prefix="/api/admin", tags=["admin"])

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


# ─────────────────────────────────────────────
#  PAPERS
# ─────────────────────────────────────────────

@router.get("/papers", response_model=PapersListResponse, dependencies=[Depends(require_admin)])
def admin_list_papers(q: Optional[str] = None):
    """Return all papers. Admin only."""
    supabase = get_supabase()

    query = supabase.table("papers").select(
        "id, title, authors, year, course_or_program, abstract, file_path, access_type, uploaded_by, created_at, updated_at"
    ).order("created_at", desc=True)

    if q and q.strip():
        term = q.strip()
        query = query.or_(
            f"title.ilike.%{term}%,"
            f"abstract.ilike.%{term}%,"
            f"course_or_program.ilike.%{term}%"
        )

    response = query.execute()

    if response.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch papers."
        )

    papers = [_attach_url(p) for p in response.data]
    return PapersListResponse(total=len(papers), results=papers)


@router.post("/papers", response_model=PaperResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def admin_create_paper(body: PaperCreate):
    """
    Admin adds a new paper.
    Frontend uploads PDF to Supabase storage directly, sends file_path here.
    """
    supabase = get_supabase()

    if body.access_type and body.access_type not in VALID_ACCESS_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"access_type must be one of: {', '.join(VALID_ACCESS_TYPES)}"
        )

    payload = {
        "title": body.title,
        "authors": body.authors,
        "year": body.year,
        "course_or_program": body.course_or_program,
        "abstract": body.abstract,
        "file_path": body.file_path,
        "access_type": body.access_type or "open",
    }

    result = supabase.table("papers").insert(payload).execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create paper."
        )

    return _attach_url(result.data[0])


@router.put("/papers/{paper_id}", response_model=PaperResponse, dependencies=[Depends(require_admin)])
def admin_update_paper(paper_id: str, body: PaperUpdate):
    """Admin updates any paper's metadata and/or access_type."""
    supabase = get_supabase()

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    return _attach_url(result.data[0])


@router.delete("/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def admin_delete_paper(paper_id: str):
    """Admin deletes a paper and removes its PDF from storage."""
    supabase = get_supabase()

    paper = (
        supabase.table("papers")
        .select("id, file_path")
        .eq("id", paper_id)
        .single()
        .execute()
    )

    if not paper.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    file_path = paper.data.get("file_path")
    if file_path:
        try:
            supabase.storage.from_(BUCKET).remove([file_path])
        except Exception:
            pass

    supabase.table("papers").delete().eq("id", paper_id).execute()


# ─────────────────────────────────────────────
#  ACCESS REQUESTS  (paper access by students)
# ─────────────────────────────────────────────

@router.get("/requests", response_model=List[AccessRequestResponse], dependencies=[Depends(require_admin)])
def admin_list_requests(status_filter: Optional[str] = None):
    """
    Return all paper access requests. Admin only.
    Filter by status: ?status_filter=pending
    """
    supabase = get_supabase()

    query = (
        supabase.table("access_requests")
        .select("id, paper_id, requester_id, message, status, created_at, updated_at")
        .order("created_at", desc=True)
    )

    if status_filter:
        query = query.eq("status", status_filter)

    response = query.execute()
    rows = response.data or []

    paper_ids = list({r["paper_id"] for r in rows if r.get("paper_id")})
    user_ids  = list({r["requester_id"] for r in rows if r.get("requester_id")})

    papers_map = {}
    if paper_ids:
        papers_res = supabase.table("papers").select("id, title, course_or_program, year").in_("id", paper_ids).execute()
        papers_map = {p["id"]: p for p in (papers_res.data or [])}

    users_map = {}
    if user_ids:
        users_res = supabase.table("users").select("id, email, full_name").in_("id", user_ids).execute()
        users_map = {u["id"]: u for u in (users_res.data or [])}

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


@router.patch("/requests/{request_id}", response_model=AccessRequestResponse, dependencies=[Depends(require_admin)])
def admin_update_request(request_id: str, body: AccessRequestStatusUpdate):
    """Admin approves or rejects any paper access request."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status must be 'approved' or 'rejected'."
        )

    supabase = get_supabase()

    result = (
        supabase.table("access_requests")
        .update({"status": body.status, "updated_at": datetime.utcnow().isoformat()})
        .eq("id", request_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")

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


# ─────────────────────────────────────────────
#  AUTHOR UPGRADE REQUESTS
#  (student uploads paper → admin approves → student becomes author)
# ─────────────────────────────────────────────

class UpgradeDecision(BaseModel):
    action: Literal["approve", "reject"]


@router.get("/upgrade-requests", dependencies=[Depends(require_admin)])
def admin_list_upgrade_requests(status_filter: Optional[str] = None):
    """
    List all author upgrade requests.
    Optionally filter: ?status_filter=pending
    """
    supabase = get_supabase()

    query = (
        supabase.table("author_upgrade_requests")
        .select(
            "id, status, created_at, user_id, paper_id"
        )
        .order("created_at", desc=True)
    )

    if status_filter:
        query = query.eq("status", status_filter)

    result = query.execute()
    rows = result.data or []

    # Hydrate user and paper info separately
    user_ids  = list({r["user_id"]  for r in rows if r.get("user_id")})
    paper_ids = list({r["paper_id"] for r in rows if r.get("paper_id")})

    users_map = {}
    if user_ids:
        u_res = supabase.table("users").select("id, full_name, email").in_("id", user_ids).execute()
        users_map = {u["id"]: u for u in (u_res.data or [])}

    papers_map = {}
    if paper_ids:
        p_res = supabase.table("papers").select("id, title, abstract, file_path, status").in_("id", paper_ids).execute()
        papers_map = {p["id"]: p for p in (p_res.data or [])}

    enriched = []
    for row in rows:
        enriched.append({
            **row,
            "user":  users_map.get(row["user_id"],  {}),
            "paper": papers_map.get(row["paper_id"], {}),
        })

    return enriched


@router.post("/upgrade-requests/{request_id}/decide", dependencies=[Depends(require_admin)])
def admin_decide_upgrade_request(request_id: str, body: UpgradeDecision):
    """
    Approve or reject a student's author upgrade request.

    approve → is_author = true on user, paper status = 'published'
    reject  → request status = 'rejected', paper stays hidden
    """
    supabase = get_supabase()

    req_result = (
        supabase.table("author_upgrade_requests")
        .select("id, user_id, paper_id, status")
        .eq("id", request_id)
        .single()
        .execute()
    )

    if not req_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upgrade request not found."
        )

    req = req_result.data

    if req["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request is already '{req['status']}' — cannot change it again."
        )

    if body.action == "approve":
        # 1. Mark request approved
        supabase.table("author_upgrade_requests").update(
            {"status": "approved", "updated_at": datetime.utcnow().isoformat()}
        ).eq("id", request_id).execute()

        # 2. Grant author access
        supabase.table("users").update(
            {"is_author": True}
        ).eq("id", req["user_id"]).execute()

        # 3. Publish the paper so it appears publicly
        supabase.table("papers").update(
            {"status": "published", "updated_at": datetime.utcnow().isoformat()}
        ).eq("id", req["paper_id"]).execute()

        return {
            "message": "Approved. User is now an author and their paper is published.",
            "request_id": request_id,
            "action": "approve",
        }

    else:  # reject
        supabase.table("author_upgrade_requests").update(
            {"status": "rejected", "updated_at": datetime.utcnow().isoformat()}
        ).eq("id", request_id).execute()

        return {
            "message": "Rejected. Paper remains hidden from public.",
            "request_id": request_id,
            "action": "reject",
        }


# ─────────────────────────────────────────────
#  AUTHOR WHITELIST
# ─────────────────────────────────────────────

@router.get("/whitelist", response_model=List[WhitelistEntry], dependencies=[Depends(require_admin)])
def admin_list_whitelist():
    """Return all emails in the author whitelist. Admin only."""
    supabase = get_supabase()

    response = (
        supabase.table("author_whitelist")
        .select("id, email, added_by, created_at")
        .order("created_at", desc=True)
        .execute()
    )

    return response.data or []


@router.post("/whitelist", response_model=WhitelistEntry, status_code=status.HTTP_201_CREATED)
def admin_add_to_whitelist(
    body: WhitelistCreate,
    current_user: TokenData = Depends(require_admin),
):
    """
    Add an email to the author whitelist. Admin only.
    If the email belongs to an existing user, immediately sets their is_author = true.
    """
    supabase = get_supabase()

    existing = (
        supabase.table("author_whitelist")
        .select("id")
        .eq("email", body.email.lower().strip())
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in the whitelist."
        )

    result = (
        supabase.table("author_whitelist")
        .insert({"email": body.email.lower().strip(), "added_by": current_user.user_id})
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add email to whitelist."
        )

    # Auto-upgrade any existing user with that email
    try:
        supabase.table("users").update({"is_author": True}).eq("email", body.email.lower().strip()).execute()
        supabase.table("users").update({"is_author": True}).eq("secondary_email", body.email.lower().strip()).execute()
    except Exception as e:
        print(f"[WARN] Could not auto-upgrade existing user: {e}")

    return result.data[0]


@router.delete("/whitelist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def admin_remove_from_whitelist(entry_id: str):
    """Remove an email from the author whitelist. Admin only."""
    supabase = get_supabase()

    existing = (
        supabase.table("author_whitelist")
        .select("id")
        .eq("id", entry_id)
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Whitelist entry not found.")

    supabase.table("author_whitelist").delete().eq("id", entry_id).execute()


# ─────────────────────────────────────────────
#  USER MANAGEMENT
# ─────────────────────────────────────────────

@router.get("/users", dependencies=[Depends(require_admin)])
def admin_list_users():
    """Return all users. Admin only."""
    supabase = get_supabase()

    result = supabase.table("users").select(
        "id, email, full_name, role, is_author, is_active, secondary_email, student_id, department, year_level, created_at, last_login"
    ).execute()

    users = result.data or []
    for u in users:
        u.pop("password_hash", None)

    return {"users": users, "total": len(users)}


@router.patch("/users/{user_id}/toggle-active", dependencies=[Depends(require_admin)])
def admin_toggle_user_active(user_id: str):
    """Toggle a user's active status. Admin only."""
    supabase = get_supabase()

    result = supabase.table("users").select("is_active").eq("id", user_id).execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    new_status = not result.data[0].get("is_active", True)

    supabase.table("users").update({
        "is_active": new_status,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", user_id).execute()

    return {
        "message": f"User {'activated' if new_status else 'deactivated'} successfully.",
        "user_id": user_id,
        "is_active": new_status,
    }


@router.patch("/users/{user_id}/toggle-author", dependencies=[Depends(require_admin)])
def admin_toggle_author(user_id: str):
    """Manually grant or revoke author access for a user. Admin only."""
    supabase = get_supabase()

    result = supabase.table("users").select("is_author, email").eq("id", user_id).execute()

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    new_status = not result.data[0].get("is_author", False)

    supabase.table("users").update({"is_author": new_status}).eq("id", user_id).execute()

    return {
        "message": f"Author access {'granted' if new_status else 'revoked'} successfully.",
        "user_id": user_id,
        "is_author": new_status,
    }