from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Optional
from datetime import datetime
from app.database import get_supabase
from app.models.papers import (
    PaperResponse, PapersListResponse, PaperCreate, PaperUpdate,
    AccessRequestResponse, AccessRequestStatusUpdate, UserProfileUpdate,
)
from app.middleware.auth import get_current_user
from app.models.auth import TokenData
from app.config import settings

router = APIRouter(prefix="/api/author", tags=["author"])
BUCKET = settings.STORAGE_BUCKET
VALID_ACCESS_TYPES   = ("open", "students_only", "restricted")
VALID_RESEARCH_TYPES = ("qualitative", "quantitative", "mixed_methods")


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def _get_public_url(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    return get_supabase().storage.from_(BUCKET).get_public_url(file_path)

def _attach_url(paper: dict) -> dict:
    paper["public_url"] = _get_public_url(paper.get("file_path"))
    return paper

def _attach_secondary_email_to_papers(supabase, papers: list[dict]) -> list[dict]:
    user_ids = list({p.get("uploaded_by") for p in papers if p.get("uploaded_by")})
    users_map = {}
    if user_ids:
        res = supabase.table("users").select("id, secondary_email").in_("id", user_ids).execute()
        users_map = {u["id"]: u.get("secondary_email") for u in (res.data or [])}
    for paper in papers:
        paper["secondary_email"] = users_map.get(paper.get("uploaded_by"))
    return papers

def _require_author(current_user: TokenData):
    supabase = get_supabase()

    print(f"[_require_author] user_id: {current_user.user_id}, email: {current_user.email}")

    # Try matching by primary user ID first
    result = (
        supabase.table("users")
        .select("id, is_author, email")
        .eq("id", current_user.user_id)
        .maybe_single()
        .execute()
    )

    print(f"[_require_author] primary lookup result: {result.data}")

    # If not found by ID, try matching by secondary email
    if not result.data:
        auth_user  = supabase.auth.admin.get_user_by_id(current_user.user_id)
        auth_email = auth_user.user.email if auth_user and auth_user.user else None
        print(f"[_require_author] falling back to secondary email lookup, auth_email: {auth_email}")
        if auth_email:
            result = (
                supabase.table("users")
                .select("id, is_author, email")
                .eq("secondary_email", auth_email)
                .maybe_single()
                .execute()
            )
            print(f"[_require_author] secondary lookup result: {result.data}")

    if not result.data or not result.data.get("is_author"):
        print(f"[_require_author] DENIED — is_author: {result.data.get('is_author') if result.data else 'no user found'}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Author access required.")

    print(f"[_require_author] APPROVED — overriding user_id to: {result.data['id']}")
    current_user.user_id = result.data["id"]
    return current_user

# ─────────────────────────────────────────────
#  AUTHOR PROFILE
# ─────────────────────────────────────────────

@router.get("/me")
def get_author_profile(current_user: TokenData = Depends(get_current_user)):
    current_user = _require_author(current_user)
    result = (
        get_supabase().table("users")
        .select("id, email, full_name, role, is_author, secondary_email, department, year_level, student_id")
        .eq("id", current_user.user_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return result.data

@router.get("/profile")
def get_author_profile_alias(current_user: TokenData = Depends(get_current_user)):
    return get_author_profile(current_user)


@router.patch("/me")
def update_author_profile(body: UserProfileUpdate, current_user: TokenData = Depends(get_current_user)):
    current_user = _require_author(current_user)

    payload = {}
    if body.secondary_email is not None:
        payload["secondary_email"] = body.secondary_email.lower().strip()
    if body.full_name is not None:
        payload["full_name"] = body.full_name.strip()

    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No fields to update.")

    result = get_supabase().table("users").update(payload).eq("id", current_user.user_id).select().execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update profile.")
    return result.data[0]


# ─────────────────────────────────────────────
#  AUTHOR'S OWN PAPERS
# ─────────────────────────────────────────────

@router.post("/papers", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
def author_upload_paper(body: PaperCreate, current_user: TokenData = Depends(get_current_user)):
    current_user = _require_author(current_user)
    supabase = get_supabase()

    if body.access_type not in VALID_ACCESS_TYPES:
        raise HTTPException(status_code=422, detail=f"access_type must be one of: {', '.join(VALID_ACCESS_TYPES)}")
    if not body.research_type or body.research_type not in VALID_RESEARCH_TYPES:
        raise HTTPException(status_code=422, detail=f"research_type must be one of: {', '.join(VALID_RESEARCH_TYPES)}")
    if not body.grammarian_cert_path:
        raise HTTPException(status_code=422, detail="Grammarian certificate is required.")
    if not body.turnitin_cert_path:
        raise HTTPException(status_code=422, detail="Turnitin/plagiarism report is required.")
    if body.research_type in ("quantitative", "mixed_methods") and not body.statistician_cert_path:
        raise HTTPException(status_code=422, detail="Statistician certificate is required for quantitative or mixed methods research.")

    if body.secondary_email is not None:
        supabase.table("users").update({
            "secondary_email": body.secondary_email.lower().strip() or None
        }).eq("id", current_user.user_id).execute()

    result = supabase.table("papers").insert({
        "title":                  body.title,
        "authors":                body.authors,
        "year":                   body.year,
        "course_or_program":      body.course_or_program,
        "abstract":               body.abstract,
        "file_path":              body.file_path,
        "access_type":            body.access_type or "open",
        "uploaded_by":            current_user.user_id,
        "status":                 "pending_review",
        "research_type":          body.research_type,
        "grammarian_cert_path":   body.grammarian_cert_path,
        "turnitin_cert_path":     body.turnitin_cert_path,
        "statistician_cert_path": body.statistician_cert_path,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to upload paper.")

    paper = result.data[0]

    # Route to correct review table based on existing author status
    user_res = supabase.table("users").select("is_author").eq("id", current_user.user_id).maybe_single().execute()
    review_table = "author_upload_requests" if (user_res.data and user_res.data.get("is_author")) else "author_upgrade_requests"

    review_result = supabase.table(review_table).insert({
        "user_id":  current_user.user_id,
        "paper_id": paper["id"],
        "status":   "pending",
    }).execute()

    if not review_result.data:
        supabase.table("papers").delete().eq("id", paper["id"]).execute()
        raise HTTPException(status_code=500, detail="Failed to create review request. Paper upload was rolled back.")

    return _attach_url(paper)


@router.get("/papers", response_model=PapersListResponse)
def author_list_papers(current_user: TokenData = Depends(get_current_user)):
    current_user = _require_author(current_user)
    supabase = get_supabase()

    response = (
        supabase.table("papers")
        .select("id, title, authors, year, course_or_program, abstract, file_path, access_type, status, uploaded_by, created_at, updated_at")
        .eq("uploaded_by", current_user.user_id)
        .order("created_at", desc=True)
        .execute()
    )

    papers = _attach_secondary_email_to_papers(supabase, response.data or [])
    papers = [_attach_url(p) for p in papers]
    return PapersListResponse(total=len(papers), results=papers)


@router.patch("/papers/{paper_id}", response_model=PaperResponse)
def author_update_paper(paper_id: str, body: PaperUpdate, current_user: TokenData = Depends(get_current_user)):
    current_user = _require_author(current_user)
    supabase = get_supabase()

    existing = supabase.table("papers").select("id, uploaded_by").eq("id", paper_id).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Paper not found.")
    if existing.data.get("uploaded_by") != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own papers.")

    payload = {}
    if body.title is not None:                      payload["title"]                  = body.title
    if body.authors is not None:                    payload["authors"]                = body.authors
    if body.year is not None:                       payload["year"]                   = body.year
    if body.course_or_program is not None:          payload["course_or_program"]      = body.course_or_program
    if body.abstract is not None:                   payload["abstract"]               = body.abstract
    if body.file_path is not None:                  payload["file_path"]              = body.file_path
    if body.research_type is not None:              payload["research_type"]          = body.research_type
    if body.grammarian_cert_path is not None:       payload["grammarian_cert_path"]   = body.grammarian_cert_path
    if body.turnitin_cert_path is not None:         payload["turnitin_cert_path"]     = body.turnitin_cert_path
    if body.statistician_cert_path is not None:     payload["statistician_cert_path"] = body.statistician_cert_path
    if body.access_type is not None:
        if body.access_type not in VALID_ACCESS_TYPES:
            raise HTTPException(status_code=422, detail=f"access_type must be one of: {', '.join(VALID_ACCESS_TYPES)}")
        payload["access_type"] = body.access_type

    if not payload:
        raise HTTPException(status_code=422, detail="No fields to update.")

    payload["updated_at"] = datetime.utcnow().isoformat()

    if body.secondary_email is not None:
        supabase.table("users").update({
            "secondary_email": body.secondary_email.lower().strip() or None
        }).eq("id", current_user.user_id).execute()

    result = supabase.table("papers").update(payload).eq("id", paper_id).select().execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update paper.")
    return _attach_url(result.data[0])


@router.delete("/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def author_delete_paper(paper_id: str, current_user: TokenData = Depends(get_current_user)):
    current_user = _require_author(current_user)
    supabase = get_supabase()

    existing = supabase.table("papers").select("id, uploaded_by, file_path").eq("id", paper_id).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Paper not found.")
    if existing.data.get("uploaded_by") != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own papers.")

    if existing.data.get("file_path"):
        try:
            supabase.storage.from_(BUCKET).remove([existing.data["file_path"]])
        except Exception:
            pass

    supabase.table("papers").delete().eq("id", paper_id).execute()


# ─────────────────────────────────────────────
#  REQUESTS ON AUTHOR'S PAPERS
# ─────────────────────────────────────────────

@router.get("/requests", response_model=List[AccessRequestResponse])
def author_list_requests(status_filter: Optional[str] = None, current_user: TokenData = Depends(get_current_user)):
    current_user = _require_author(current_user)
    supabase = get_supabase()

    owned = supabase.table("papers").select("id").eq("uploaded_by", current_user.user_id).execute()
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

    rows = query.execute().data or []

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

    return [
        AccessRequestResponse(
            id=row["id"], paper_id=row["paper_id"], requester_id=row["requester_id"],
            message=row.get("message"), status=row.get("status", "pending"),
            created_at=row.get("created_at"), updated_at=row.get("updated_at"),
            paper_title=papers_map.get(row.get("paper_id"), {}).get("title"),
            paper_course_or_program=papers_map.get(row.get("paper_id"), {}).get("course_or_program"),
            paper_year=papers_map.get(row.get("paper_id"), {}).get("year"),
            requester_email=users_map.get(row.get("requester_id"), {}).get("email"),
            requester_name=users_map.get(row.get("requester_id"), {}).get("full_name"),
        )
        for row in rows
    ]


@router.patch("/requests/{request_id}", response_model=AccessRequestResponse)
def author_update_request(request_id: str, body: AccessRequestStatusUpdate, current_user: TokenData = Depends(get_current_user)):
    if body.status not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="Status must be 'approved' or 'rejected'.")

    current_user = _require_author(current_user)
    supabase = get_supabase()

    req_res = supabase.table("access_requests").select("id, paper_id, requester_id, message, status, created_at").eq("id", request_id).execute()
    if not req_res.data:
        raise HTTPException(status_code=404, detail="Request not found.")

    req_data  = req_res.data[0]
    paper_res = supabase.table("papers").select("id, uploaded_by").eq("id", req_data["paper_id"]).execute()

    if not paper_res.data or paper_res.data[0].get("uploaded_by") != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only manage requests for your own papers.")

    supabase.table("access_requests").update(
        {"status": body.status, "updated_at": datetime.utcnow().isoformat()}
    ).eq("id", request_id).execute()

    return AccessRequestResponse(
        id=req_data["id"], paper_id=req_data["paper_id"], requester_id=req_data["requester_id"],
        message=req_data.get("message"), status=body.status,
        created_at=req_data.get("created_at"), updated_at=datetime.utcnow().isoformat(),
    )


# ─────────────────────────────────────────────
#  AUTHOR UPLOAD REQUESTS
# ─────────────────────────────────────────────

@router.get("/upload-requests")
def author_list_upload_requests(current_user: TokenData = Depends(get_current_user)):
    current_user = _require_author(current_user)
    supabase = get_supabase()

    result_a = (
        supabase.table("author_upgrade_requests")
        .select("id, status, created_at, updated_at, papers(title, id, year, course_or_program)")
        .eq("user_id", current_user.user_id)
        .execute()
    )
    result_b = (
        supabase.table("author_upload_requests")
        .select("id, status, created_at, updated_at, papers(title, id, year, course_or_program)")
        .eq("user_id", current_user.user_id)
        .execute()
    )

    combined = (result_a.data or []) + (result_b.data or [])
    combined.sort(key=lambda x: x["created_at"], reverse=True)
    return combined