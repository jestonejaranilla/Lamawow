"""
ATLAS PSU - routes/session_routes.py
Login happens in Supabase Auth in the browser. After signing in the page calls POST /auth/session so the
server can audit the login and tell the page the user's role and department. POST /auth/logout audits the
sign-out. POST /audit records a few client-side configuration changes (counts and ids only).
"""

import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from routes.schedule_routes import _err, _ok
from services.audit_service import audit, clean_meta
from services import supabase_client
from services.auth_service import ANY_ROLE, STAFF, clear_profile_cache, current_user, require_user, scope_dept

session_bp = Blueprint("session", __name__)

# Changes that happen in the browser (no server route to audit): action -> entity
CLIENT_EVENTS = {
    "faculty_added": "faculty",
    "faculty_edited": "faculty",
    "faculty_deleted": "faculty",
    "solver_settings_changed": "dept_settings",
}


# Every action the system writes. Used for the filter list of the audit screen (not for validation).
KNOWN_ACTIONS = [
    "login", "logout", "run_started", "run_finished", "run_saved", "approve_run", "run_deleted",
    "rooms_changed", "class_sizes_changed", "soft_constraints_changed",
    "faculty_added", "faculty_edited", "faculty_deleted", "solver_settings_changed",
]
AUDIT_PAGE_DEFAULT = 25
AUDIT_PAGE_MAX = 100
AUDIT_MAX_PAGE_NUMBER = 10000
_ACTION_RE = re.compile(r"^[a-z_]{1,60}$")


def _parse_moment(text: str, end_of_day: bool):
    """A date (YYYY-MM-DD) or an ISO date and time -> an aware UTC datetime. A date given for the end is inclusive."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            d = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return d + timedelta(days=1) if end_of_day else d
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError("Dates must look like 2026-10-16.")


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


@session_bp.route("/audit", methods=["GET"])
@require_user(STAFF)
def read_audit():
    """
    Read-only audit screen data. A chairperson always gets their own department (scope_dept); an admin may pass ?dept=.
    Only four fields leave the server: time, user (the email of the actor), action and entity. No ids, no meta.
    Filters: action, from, to. Paging: page (from 1) and page_size. Newest first.
    """
    user = current_user()
    dept = scope_dept(request.args.get("dept") or None)
    action = (request.args.get("action") or "").strip()
    if action and not _ACTION_RE.match(action):
        return _err("Unknown action filter.")
    try:
        start = _parse_moment(request.args.get("from"), end_of_day=False)
        end = _parse_moment(request.args.get("to"), end_of_day=True)
        page = int(request.args.get("page") or 1)
        size = int(request.args.get("page_size") or AUDIT_PAGE_DEFAULT)
    except ValueError as e:
        return _err(str(e) if "Dates" in str(e) else "page and page_size must be whole numbers.")
    if start and end and start >= end:
        return _err("The start date must be before the end date.")
    if not 1 <= page <= AUDIT_MAX_PAGE_NUMBER or not 1 <= size <= AUDIT_PAGE_MAX:
        return _err("page must be 1 or more and page_size between 1 and %d." % AUDIT_PAGE_MAX)

    # Acts as the signed-in user when there is a token, so the database policy (own department only) also applies.
    client = (supabase_client.get_user_client(user.get("token")) if user.get("token") else None) \
        or supabase_client.get_service_client()
    if client is None:
        return _err("The database is not configured.", 503)
    try:
        q = client.table("audit_log").select("at,email,action,entity")
        if dept:
            q = q.eq("dept", dept)
        if action:
            q = q.eq("action", action)
        if start:
            q = q.gte("at", start.isoformat())
        if end:
            q = q.lt("at", end.isoformat())
        offset = (page - 1) * size
        rows = q.order("at", desc=True).range(offset, offset + size).execute().data or []   # one extra row: is there a next page
    except Exception:                                                                     # noqa: BLE001
        return _err("Could not read the audit log.", 502)
    return _ok({"dept": dept, "page": page, "page_size": size, "has_more": len(rows) > size,
                "actions": KNOWN_ACTIONS,
                "rows": [{"time": r.get("at"), "user": r.get("email"), "action": r.get("action"), "entity": r.get("entity")}
                         for r in rows[:size]]})