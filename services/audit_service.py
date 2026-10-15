"""
ATLAS PSU - services/audit_service.py
audit(user, action, entity, entity_id, meta) writes one audit_log row with the service client.
It NEVER raises: a failed log must not break a request.

meta holds ids, counts and flags only. It is cleaned here (and checked again by a trigger in the
database): no nested data, no long text, and no key that could carry schedule content or personal data.
"""

import logging

log = logging.getLogger("atlas.audit")

FORBIDDEN_KEYS = {"result", "analytics", "schedule", "assignments", "coverage", "name", "full_name", "email",
                  "phone", "reason", "preferences", "leave", "leave_dates", "professor", "faculty_name",
                  "faculty", "label", "constraints", "rooms", "subjects"}
MAX_META_KEYS = 12
MAX_STR = 64


def clean_meta(meta) -> dict:
    out = {}
    if not isinstance(meta, dict):
        return out
    for k, v in meta.items():
        if len(out) >= MAX_META_KEYS:
            break
        key = str(k)[:40]
        if key.lower() in FORBIDDEN_KEYS:
            continue
        if isinstance(v, bool) or v is None:
            out[key] = v
        elif isinstance(v, (int, float)):
            out[key] = v if v == v else None          # NaN -> null
        elif isinstance(v, str):
            out[key] = v[:MAX_STR]
        # lists, dicts and anything else are dropped on purpose
    return out


def audit(user, action, entity=None, entity_id=None, meta=None, dept=None) -> bool:
    """Returns True when the row was written. Never raises."""
    try:
        from services.supabase_client import get_service_client
        client = get_service_client()
        if client is None:
            return False
        user = user or {}
        client.table("audit_log").insert({
            "user_id": user.get("id"),
            "email": user.get("email"),
            "dept": user.get("dept") or dept,
            "action": str(action)[:60],
            "entity": str(entity)[:60] if entity else None,
            "entity_id": str(entity_id)[:MAX_STR] if entity_id is not None else None,
            "meta": clean_meta(meta),
        }).execute()
        return True
    except Exception as e:                                   # noqa: BLE001 - a log must never break a request
        log.warning("audit log write failed (%s): %s", action, e)
        return False