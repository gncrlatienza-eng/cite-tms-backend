from fastapi import APIRouter, Query, HTTPException
from app.services.nlp_search_service import search_papers, suggest_topics

router = APIRouter(prefix="/api", tags=["search"])

@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=200)):
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    results = search_papers(q)
    return {
        "query": q,
        "count": len(results),
        "results": results
    }

@router.get("/search/suggest")
def suggest(q: str = Query(..., min_length=1, max_length=100)):
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    return {
        "query": q,
        "suggestions": suggest_topics(q)
    }