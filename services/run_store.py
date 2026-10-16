"""
ATLAS PSU - services/run_store.py
Saves finished runs to public.schedule_runs (service client) and reads them back.
Every function is a no-op / empty when Supabase is not configured, so the engine never depends on it.
The service client bypasses RLS, so the access rules are enforced in routes/run_routes.py.
"""

import json
import logging

from services import schedule_service as ss
from services.supabase_client import get_service_client, get_user_client, is_configured

log = logging.getLogger("atlas.runs")

LIST_COLUMNS = ("id,dept,academic_year,semester,label,status,created_by,created_at,updated_at,"
                "duration_ms,solver_settings,metrics,coverage")


class StoreUnavailable(Exception):
    pass


def enabled() -> bool:
    return is_configured()


def _client():
    c = get_service_client()
    if c is None:
        raise StoreUnavailable("Database is not configured.")
    return c


def _json_safe(value):
    """Round-trip through JSON so numpy numbers, tuples and sets never reach the database."""
    return json.loads(json.dumps(value, default=str))


def _period(dept: str, academic_year, active_semester):
    """(academic_year, semester) of a run: the request first, then the department's saved period."""
    sem_no = ss.parse_semester(active_semester)
    semester = ss.semester_label(sem_no) if sem_no else None
    year = (str(academic_year).strip() if academic_year else None) or None
    if not (year and semester):
        try:
            rows = _client().table("dept_settings").select("academic_year,semester").eq("dept", dept).limit(1).execute().data
            if rows:
                year = year or rows[0].get("academic_year")
                semester = semester or rows[0].get("semester")
        except Exception as e:                                   # noqa: BLE001
            log.warning("could not read dept_settings: %s", e)
    return year or "unspecified", semester or "unspecified"


def balance_score(result):
    """Evenness of the teaching load as a 0-100 number (Jain's fairness index over the faculty that have classes).
    Stored in metrics so the Saved runs list can show it without loading the large result. None when nothing is assigned."""
    loads = {}
    for item in result or []:
        name = item.get("faculty") if isinstance(item, dict) else None
        if name:
            loads[name] = loads.get(name, 0) + 1
    if not loads:
        return None
    total = sum(loads.values())
    squares = sum(v * v for v in loads.values())
    return round(100.0 * total * total / (len(loads) * squares), 1)


def save_draft(dept, user_id, progress, solver_settings, duration_ms, academic_year, active_semester) -> str:
    """Insert the finished run as a draft. Returns the new run's uuid."""
    year, semester = _period(dept, academic_year, active_semester)
    row = {
        "dept": dept, "academic_year": year, "semester": semester, "status": "draft",
        "created_by": user_id,
        "solver_settings": _json_safe(solver_settings),
        "metrics": _json_safe({**(progress.get("metrics") or {}), "balance_score": balance_score(progress.get("result"))}),
        "coverage": _json_safe({"summary": progress.get("coverage") or {},
                                "errors": progress.get("coverage_errors") or []}),
        "duration_ms": int(duration_ms),
        "result": _json_safe(progress.get("result") or []),
        "analytics": _json_safe(progress.get("analytics") or {}),
    }
    res = _client().table("schedule_runs").insert(row).execute()
    return res.data[0]["id"]


def list_runs(dept: str, statuses=None) -> list:
    q = _client().table("schedule_runs").select(LIST_COLUMNS).eq("dept", dept)
    if statuses:
        q = q.in_("status", list(statuses))
    return q.order("created_at", desc=True).limit(200).execute().data or []


def get_run(run_id: str):
    rows = _client().table("schedule_runs").select("*").eq("id", run_id).limit(1).execute().data or []
    return rows[0] if rows else None


def get_run_header(run_id: str):
    rows = (_client().table("schedule_runs").select("id,dept,status,academic_year,semester")
            .eq("id", run_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def mark_saved(run_id: str, label):
    """draft or saved -> saved, with a label. Returns the updated header row."""
    patch = {"status": "saved"}
    if label is not None:
        patch["label"] = label
    rows = _client().table("schedule_runs").update(patch).eq("id", run_id).execute().data or []
    return rows[0] if rows else None


def delete_run(run_id: str) -> None:
    _client().table("schedule_runs").delete().eq("id", run_id).execute()


def approve(run_id: str, token) -> None:
    """Call the approve_run RPC AS THE SIGNED-IN USER so the database checks their role and department."""
    client = get_user_client(token)
    if client is None:
        raise StoreUnavailable("Approving needs a signed-in user and SUPABASE_ANON_KEY.")
    client.rpc("approve_run", {"run_id": run_id}).execute()