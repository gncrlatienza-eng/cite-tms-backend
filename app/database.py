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

# Force HTTP/1.1 to fix Railway connection drops
import httpx
supabase.postgrest.session = httpx.Client(
    base_url=str(supabase.postgrest.session.base_url),
    headers=dict(supabase.postgrest.session.headers),
    transport=httpx.HTTPTransport(http2=False)
)
supabase_admin.postgrest.session = httpx.Client(
    base_url=str(supabase_admin.postgrest.session.base_url),
    headers=dict(supabase_admin.postgrest.session.headers),
    transport=httpx.HTTPTransport(http2=False)
)

def get_supabase() -> Client:
    return supabase_admin

def get_supabase_admin() -> Client:
    return supabase_admin