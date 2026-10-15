"""
ATLAS PSU - services/supabase_client.py
Supabase clients, created lazily from environment variables. Nothing is read at import time and
no key is ever hard-coded. Every function returns None when the project is not configured, so the
app (and the test suite) keeps working without a database.

  SUPABASE_URL          project URL
  SUPABASE_ANON_KEY     public key; used with the signed-in user's JWT so RLS and approve_run() see them
  SUPABASE_SERVICE_KEY  service role key; server only, bypasses RLS. Never send it to the browser.
"""

import os
import threading

_lock = threading.Lock()
_service = None


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def is_configured() -> bool:
    return bool(_env("SUPABASE_URL") and _env("SUPABASE_SERVICE_KEY"))


def get_service_client():
    """One shared service-role client (bypasses RLS), or None when not configured."""
    global _service
    if not is_configured():
        return None
    with _lock:
        if _service is None:
            from supabase import create_client
            _service = create_client(_env("SUPABASE_URL"), _env("SUPABASE_SERVICE_KEY"))
        return _service


def get_user_client(access_token: str):
    """A client that acts as the signed-in user (anon key + their JWT). None when not configured."""
    if not (_env("SUPABASE_URL") and _env("SUPABASE_ANON_KEY") and access_token):
        return None
    from supabase import create_client
    client = create_client(_env("SUPABASE_URL"), _env("SUPABASE_ANON_KEY"))
    client.postgrest.auth(access_token)
    return client