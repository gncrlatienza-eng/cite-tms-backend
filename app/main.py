from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import auth_router
from app.routers.search import router as search_router
from app.routers.papers import router as papers_router
from app.routers.admin import router as admin_router
from app.routers.author import router as author_router
from app.routers.student import router as student_router
from app.services.nlp_search_service import build_index  # ← only change

app = FastAPI(
    title="CITE-TMS Backend",
    description="Thesis Management System for CITE Department - De La Salle Lipa",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(search_router)
app.include_router(papers_router)
app.include_router(admin_router)
app.include_router(author_router)
app.include_router(student_router)

@app.on_event("startup")
def startup():
    print("[NLP] Building index...")
    build_index()  # ← only change

@app.get("/")
def read_root():
    return {"message": "CITE-TMS Backend is running!", "status": "success", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "cite-tms-backend"}

@app.get("/test-supabase")
def test_supabase():
    from app.database import get_supabase
    try:
        supabase = get_supabase()
        result = supabase.table("users").select("*").limit(1).execute()
        return {"status": "success", "message": "Supabase connected!", "data": result.data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)