"""
ATLAS PSU - routes/session_routes.py
Login happens in Supabase Auth in the browser. After signing in the page calls POST /auth/session so the
server can audit the login and tell the page the user's role and department. POST /auth/logout audits the
sign-out. POST /audit records a few client-side configuration changes (counts and ids only).
"""

from flask import Blueprint, request

from routes.schedule_routes import _err, _ok
from services.audit_service import audit, clean_meta
from services.auth_service import ANY_ROLE, STAFF, clear_profile_cache, current_user, require_user, scope_dept

session_bp = Blueprint("session", __name__)

# Changes that happen in the browser (no server route to audit): action -> entity
CLIENT_EVENTS = {
    "faculty_added": "faculty",
    "faculty_edited": "faculty",
    "faculty_deleted": "faculty",
    "solver_settings_changed": "dept_settings",
}


def _public(user: dict) -> dict:
    return {k: user.get(k) for k in ("id", "email", "full_name", "role", "dept", "faculty_id")}


@session_bp.route("/auth/session", methods=["POST"])
@require_user(ANY_ROLE)
def session():
    user = current_user()
    audit(user, "login", "session", user.get("id"), {"role": user["role"]})
    return _ok({"user": _public(user)})


@session_bp.route("/auth/logout", methods=["POST"])
@require_user(ANY_ROLE)
def logout():
    user = current_user()
    audit(user, "logout", "session", user.get("id"))
    if user.get("id"):
        clear_profile_cache(user["id"])
    return _ok({"logged_out": True})


@session_bp.route("/audit", methods=["POST"])
@require_user(STAFF)
def client_event():
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in CLIENT_EVENTS:
        return _err("Unknown audit action.")
    dept = scope_dept(request.args.get("dept") or None, body.get("dept"))
    entity_id = body.get("entity_id")
    if entity_id is not None and not isinstance(entity_id, str):
        return _err("entity_id must be text.")
    audit(current_user(), action, CLIENT_EVENTS[action], entity_id, clean_meta(body.get("meta")), dept=dept)
    return _ok({"logged": True})