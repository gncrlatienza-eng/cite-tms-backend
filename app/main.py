from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings  # Add 'app.' prefix
from app.routers import auth_router  # Add 'app.' prefix

app = FastAPI(
    title="CITE-TMS Backend",
    description="Thesis Management System for CITE Department - De La Salle Lipa",
    version="1.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)


@app.get("/")
def read_root():
    return {
        "message": "CITE-TMS Backend is running!",
        "status": "success",
        "version": "1.0.0"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "cite-tms-backend"
    }


@app.get("/test-supabase")
def test_supabase():
    from app.database import get_supabase  # Add 'app.' prefix
    try:
        supabase = get_supabase()
        # Try to query users table
        result = supabase.table("users").select("*").limit(1).execute()
        return {
            "status": "success",
            "message": "Supabase connected!",
            "data": result.data
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)