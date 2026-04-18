from fastapi import APIRouter, HTTPException, status, Depends
from typing import Optional
from app.database import get_supabase
from app.models.papers import PaperCreate, PaperResponse
from app.middleware.auth import get_current_user
from app.models.auth import TokenData
from app.config import settings

router = APIRouter(prefix="/api/student", tags=["student"])

BUCKET = settings.STORAGE_BUCKET

VALID_RESEARCH_TYPES = ("qualitative", "quantitative", "mixed_methods")


def _get_public_url(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    supabase = get_supabase()
    return supabase.storage.from_(BUCKET).get_public_url(file_path)


def _attach_url(paper: dict) -> dict:
    paper["public_url"] = _get_public_url(paper.get("file_path"))
    return paper


@router.post("/papers", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
def student_upload_paper(
    body: PaperCreate,
    current_user: TokenData = Depends(get_current_user),
):
    supabase = get_supabase()

    if body.access_type not in ("open", "students_only", "restricted"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="access_type must be 'open', 'students_only', or 'restricted'."
        )

    # ── Validate research_type ────────────────────────────────────────────────
    if not body.research_type or body.research_type not in VALID_RESEARCH_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"research_type must be one of: {', '.join(VALID_RESEARCH_TYPES)}"
        )

    # ── Validate required certificates ───────────────────────────────────────
    if not body.grammarian_cert_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Grammarian certificate is required."
        )
    if not body.turnitin_cert_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Turnitin/plagiarism report is required."
        )
    if body.research_type in ("quantitative", "mixed_methods") and not body.statistician_cert_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Statistician certificate is required for quantitative or mixed methods research."
        )

    # ── 1. Block if already an author ─────────────────────────────────────────
    user_result = (
        supabase.table("users")
        .select("is_author")
        .eq("id", current_user.user_id)
        .single()
        .execute()
    )
    if user_result.data and user_result.data.get("is_author"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already an author. Use the author upload endpoint instead."
        )

    # ── 2. Block if a pending upgrade request already exists ──────────────────
    pending = (
        supabase.table("author_upgrade_requests")
        .select("id, status")
        .eq("user_id", current_user.user_id)
        .eq("status", "pending")
        .execute()
    )
    if pending.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending author upgrade request. Please wait for admin approval."
        )

    # ── 3. Insert paper ───────────────────────────────────────────────────────
    paper_payload = {
        "title":                  body.title,
        "authors":                body.authors,
        "year":                   body.year,
        "course_or_program":      body.course_or_program,
        "abstract":               body.abstract,
        "file_path":              body.file_path,
        "access_type":            body.access_type or "open",
        "uploaded_by":            current_user.user_id,
        "status":                 "pending_review",
        # ── certificates ──
        "research_type":          body.research_type,
        "grammarian_cert_path":   body.grammarian_cert_path,
        "turnitin_cert_path":     body.turnitin_cert_path,
        "statistician_cert_path": body.statistician_cert_path,
    }

    paper_result = supabase.table("papers").insert(paper_payload).execute()

    if not paper_result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload paper."
        )

    paper = paper_result.data[0]

    # ── 4. Create author upgrade request ──────────────────────────────────────
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
        supabase.table("papers").delete().eq("id", paper["id"]).execute()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create upgrade request. Paper upload was rolled back."
        )

    # ── 5. Save secondary_email ───────────────────────────────────────────────
    if body.secondary_email and body.secondary_email.strip():
        supabase.table("users").update(
            {"secondary_email": body.secondary_email.strip().lower()}
        ).eq("id", current_user.user_id).execute()

    return _attach_url(paper)


@router.get("/upgrade-status")
def get_upgrade_status(
    current_user: TokenData = Depends(get_current_user),
):
    supabase = get_supabase()

    result = (
        supabase.table("author_upgrade_requests")
        .select("id, status, created_at, papers(title)")
        .eq("user_id", current_user.user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if not result.data:
        return {"status": "none", "request": None}

    return {"status": result.data[0]["status"], "request": result.data[0]}