"""
ATLAS PSU - services/auth_service.py
Verifies the Supabase access token and loads the user's profile (role, dept).

  Authorization: Bearer <jwt>
    -> verify signature, expiry and audience
    -> load profiles row with the service client (cached 60 s)
    -> g.user = {id, email, full_name, role, dept, faculty_id, token}

Verification supports both kinds of Supabase project:
  * asymmetric signing keys (ES256 / RS256): public keys from the project's JWKS URL
      (SUPABASE_JWKS_URL, default <SUPABASE_URL>/auth/v1/.well-known/jwks.json)
  * legacy shared secret (HS256): SUPABASE_JWT_SECRET
The algorithm is chosen from an allow-list, never trusted blindly from the token header.

ATLAS_AUTH=off turns the checks off for local development and tests (default: on).
It is ignored on Render (the RENDER variable is set there): production always checks.
"""

import os
import threading
import time

from flask import g, jsonify, request

PROFILE_TTL_SECONDS = 60
ADMIN = "admin"
CHAIR = "chairperson"
FACULTY = "faculty"
ANY_ROLE = (CHAIR, FACULTY, ADMIN)
STAFF = (CHAIR, ADMIN)                      # may use the engine and edit configuration

_ASYMMETRIC = ("ES256", "RS256")
_cache: dict = {}
_cache_lock = threading.Lock()
_jwks_client = None
_jwks_url = None


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def error_response(err: AuthError):
    return jsonify({"success": False, "error": err.message, "data": {}, "metrics": {}, "warnings": []}), err.status


# ── switches ──────────────────────────────────────────────────────────────────

def auth_enabled() -> bool:
    if os.environ.get("RENDER"):            # production host: cannot be switched off
        return True
    return (os.environ.get("ATLAS_AUTH") or "on").strip().lower() not in ("off", "0", "false", "no")


# ── token verification ────────────────────────────────────────────────────────

def _bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError(401, "Missing bearer token.")
    return parts[1].strip()


def _signing_key(token: str):
    """Return (key, algorithms) for this token, or raise AuthError(401)."""
    import jwt
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError:
        raise AuthError(401, "Invalid token.")
    if alg == "HS256":
        secret = (os.environ.get("SUPABASE_JWT_SECRET") or "").strip()
        if not secret:
            raise AuthError(401, "Invalid token.")
        return secret, ["HS256"]
    if alg in _ASYMMETRIC:
        global _jwks_client, _jwks_url
        url = (os.environ.get("SUPABASE_JWKS_URL") or "").strip()
        if not url:
            base = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
            if not base:
                raise AuthError(503, "Authentication is not configured.")
            url = base + "/auth/v1/.well-known/jwks.json"
        with _cache_lock:
            if _jwks_client is None or _jwks_url != url:
                _jwks_client = jwt.PyJWKClient(url, cache_keys=True, lifespan=600)
                _jwks_url = url
            client = _jwks_client
        try:
            return client.get_signing_key_from_jwt(token).key, [alg]
        except jwt.PyJWTError:
            raise AuthError(401, "Invalid token.")
    raise AuthError(401, "Invalid token.")


def verify_token(token: str) -> dict:
    import jwt
    key, algorithms = _signing_key(token)
    try:
        claims = jwt.decode(token, key, algorithms=algorithms, audience="authenticated",
                            leeway=10, options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise AuthError(401, "Invalid or expired token.")
    return claims


# ── profile (role, dept) ──────────────────────────────────────────────────────

def _load_profile(uid: str):
    """Read the profiles row with the service client. Replaced in tests."""
    from services.supabase_client import get_service_client
    client = get_service_client()
    if client is None:
        raise AuthError(503, "Authentication is not configured.")
    res = (client.table("profiles").select("id,email,full_name,role,dept,faculty_id")
           .eq("id", uid).limit(1).execute())
    rows = res.data or []
    return rows[0] if rows else None


def get_profile(uid: str):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(uid)
        if hit and hit[0] > now:
            return hit[1]
    profile = _load_profile(uid)
    if profile:
        with _cache_lock:
            _cache[uid] = (now + PROFILE_TTL_SECONDS, profile)
    return profile


def clear_profile_cache(uid: str = None) -> None:
    with _cache_lock:
        if uid is None:
            _cache.clear()
        else:
            _cache.pop(uid, None)


def _dev_user() -> dict:
    return {"id": None, "email": None, "full_name": "dev", "role": ADMIN, "dept": None,
            "faculty_id": None, "token": None, "dev": True}


def authenticate() -> dict:
    """The signed-in user for this request (cached on flask.g). Raises AuthError 401/403/503."""
    user = g.get("user")
    if user is not None:
        return user
    if not auth_enabled():
        g.user = _dev_user()
        return g.user
    token = _bearer_token()
    claims = verify_token(token)
    profile = get_profile(claims["sub"])
    if not profile or profile.get("role") not in ANY_ROLE:
        raise AuthError(403, "No ATLAS profile for this account.")
    g.user = {"id": claims["sub"], "email": profile.get("email"), "full_name": profile.get("full_name"),
              "role": profile["role"], "dept": profile.get("dept"),
              "faculty_id": profile.get("faculty_id"), "token": token, "dev": False}
    return g.user


def current_user():
    return g.get("user")


def require_user(roles=None):
    """Route decorator: 401 when the token is missing or invalid, 403 when the role is not allowed."""
    allowed = tuple(roles) if roles else ANY_ROLE

    def deco(fn):
        import functools

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = authenticate()
            if not user.get("dev") and user["role"] not in allowed:
                raise AuthError(403, "Your role is not allowed to do this.")
            return fn(*args, **kwargs)
        return wrapper
    return deco


def scope_dept(*requested):
    """
    The department this request works on.
    Chairperson and faculty: always their profile department; a request that names another one is a 403.
    Admin and local dev: the requested one. Returns None when nothing was requested and the user has no dept.
    """
    user = authenticate()
    named = [d for d in requested if d]
    if user.get("dev") or user["role"] == ADMIN:
        return named[0] if named else user.get("dept")
    if any(d != user["dept"] for d in named):
        raise AuthError(403, "You can only use your own department.")
    return user["dept"]


# Endpoints anyone may call without a token.
PUBLIC_ENDPOINTS = {"index_page", "manifest_file", "static_files", "schedule.curricula", "schedule.get_curriculum"}


def gate():
    """before_request: every endpoint except the public ones needs a valid token (default deny)."""
    if request.method == "OPTIONS" or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if request.endpoint is None:            # unknown URL: let Flask answer 404
        return None
    authenticate()
    return None