from fastapi import APIRouter, Query, HTTPException
from app.database import get_supabase
from app.services.nlp_search_service import expand_query

router = APIRouter(prefix="/api", tags=["search"])

@router.get("/search")
def search_papers(q: str = Query(..., min_length=1, max_length=200)):
    """
    Semantic search across papers using NLP query expansion.
    Searches title, abstract, and course_or_program fields.
    """
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    supabase = get_supabase()
    expanded_terms = expand_query(q)

    results = []
    seen_ids = set()

    for term in expanded_terms:
        response = (
            supabase.table("papers")
            .select("id, title, authors, year, course_or_program, abstract, file_path")
            .or_(f"title.ilike.%{term}%,abstract.ilike.%{term}%,course_or_program.ilike.%{term}%")
            .limit(10)
            .execute()
        )
        for item in response.data:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                results.append(item)

    return {
        "query": q,
        "expanded_terms": expanded_terms,
        "results": results
    }