from supabase import create_client, Client
from app.config import settings

# Initialize Supabase client
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_ANON_KEY
)

# Service role client for admin operations (bypass RLS)
supabase_admin: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_KEY
)


def get_supabase() -> Client:
    """Get Supabase client instance"""
    return supabase


def get_supabase_admin() -> Client:
    """Get Supabase admin client instance (bypasses RLS)"""
    return supabase_admin