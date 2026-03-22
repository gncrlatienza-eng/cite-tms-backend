from supabase import create_client, Client
from app.config import settings

# Anon client — for frontend-facing operations that respect RLS
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_ANON_KEY
)

# Service role client — bypasses RLS, used by all backend routers
supabase_admin: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_KEY
)


def get_supabase() -> Client:
    """
    Returns the SERVICE ROLE client.
    All backend routers use this — it bypasses RLS so inserts/selects
    are never silently blocked by missing policies.
    """
    return supabase_admin  # ← was returning `supabase` (anon), now fixed


def get_supabase_admin() -> Client:
    """Explicit alias — same as get_supabase(), kept for clarity."""
    return supabase_admin