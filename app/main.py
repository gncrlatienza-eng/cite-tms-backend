from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="CITE-TMS Backend")

# CORS Configuration
origins = os.getenv("CORS_ORIGINS", "").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "CITE-TMS Backend is running!", "status": "success"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "cite-tms-backend"}

@app.get("/test-supabase")
def test_supabase():
    from supabase import create_client
    try:
        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
        # Try to query users table
        result = supabase.table("users").select("*").limit(1).execute()
        return {"status": "success", "message": "Supabase connected!", "data": result.data}
    except Exception as e:
        return {"status": "error", "message": str(e)}