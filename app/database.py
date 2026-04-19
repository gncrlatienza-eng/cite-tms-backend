from supabase import create_client, Client
from app.config import settings
import httpx
from supabase.lib.client_options import ClientOptions

# Force HTTP/1.1 to fix Railway + Supabase connection drops
http1_transport = httpx.HTTPTransport(http2=False)
httpx_client = httpx.Client(transport=http1_transport)

options = ClientOptions(httpx_client_args={"transport": http1_transport})

# Anon client — for frontend-facing operations that respect RLS
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_ANON_KEY,
    options=options
)

# Service role client — bypasses RLS, used by all backend routers
supabase_admin: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_KEY,
    options=options
)


def get_supabase() -> Client:
    return supabase_admin


def get_supabase_admin() -> Client:
    return supabase_admin