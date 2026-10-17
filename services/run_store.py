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


def balance_score(result, faculty_list=None):
    """Evenness of the teaching load as a 0-100 number: Jain's index over ALL faculty, in load units
    (services.analytics_service.workload_metrics, the single definition). Idle professors lower it.
    Without a faculty list, only the professors named in the result are known. None when nothing is assigned."""
    from services.analytics_service import workload_metrics
    rows = [r for r in result or [] if isinstance(r, dict) and r.get("faculty")]
    if not rows:
        return None
    faculty = faculty_list or [{"name": n} for n in dict.fromkeys(r["faculty"] for r in rows)]
    return round(100.0 * workload_metrics(rows, faculty)["jain_exact"], 1)


def _rows(table, dept=None, ids=None, key="faculty_id"):
    q = _client().table(table).select("*")
    if dept is not None:
        q = q.eq("dept", dept)
    if ids is not None:
        q = q.in_(key, list(ids))
    return q.execute().data or []


def load_dept_inputs(dept: str) -> dict:
    """
    One department's run inputs read from the database with the SERVICE client, in the engine's formats:
    faculty (sorted by name, so the order never depends on the browser), soft_constraints (preferences and
    leave dates, keyed by faculty name), class_sizes ({block_key: {"size": n}}) and rooms (None when the
    department has no room rows, so the curriculum defaults stay). Raises StoreUnavailable / any database error.
    """
    faculty_rows = sorted(_rows("faculty", dept=dept), key=lambda r: str(r.get("name") or ""))
    faculty = []
    for r in faculty_rows:
        mx = int(r.get("max_units") if r.get("max_units") is not None else 24)
        buf = int(r.get("overload_buffer") if r.get("overload_buffer") is not None else 6)
        faculty.append({"name": r["name"], "specialization": list(r.get("specializations") or []),
                        "max_units": mx, "overload_buffer": buf, "absolute_max_units": mx + buf,
                        "availability": list(r.get("availability") or [])})
    ids = [r["id"] for r in faculty_rows]
    prefs = {r["faculty_id"]: r for r in _rows("faculty_preferences", ids=ids)} if ids else {}
    leave: dict = {}
    for r in (_rows("faculty_leave", ids=ids) if ids else []):
        leave.setdefault(r["faculty_id"], []).append({"start": str(r.get("start_date")), "end": str(r.get("end_date"))})
    soft = {}
    for r in faculty_rows:
        p_, sc = prefs.get(r["id"]) or {}, {}
        for k in ("preferred_period", "preferred_room", "preferred_building", "preferred_floor"):
            if p_.get(k):
                sc[k] = p_[k]
        if p_.get("avoid_days"):
            sc["restricted_days"] = list(p_["avoid_days"])
        if leave.get(r["id"]):
            sc["leave_dates"] = sorted(leave[r["id"]], key=lambda x: (x["start"], x["end"]))
        if sc:
            soft[r["name"]] = sc
    st_rows = _rows("dept_settings", dept=dept)
    period = {k: (str(st_rows[0].get(col)) if st_rows and st_rows[0].get(col) else None)
              for k, col in (("start", "period_start"), ("end", "period_end"),
                             ("academic_year", "academic_year"), ("semester", "semester"))} if st_rows else {}
    sizes = {r["block_key"]: {"size": int(r["size"])} for r in _rows("class_sizes", dept=dept)}
    room_rows = _rows("rooms", dept=dept)
    rooms = None
    if room_rows:
        rooms = {"lecture_rooms": [r["name"] for r in room_rows if r.get("kind") == "lecture"],
                 "laboratory_rooms": [r["name"] for r in room_rows if r.get("kind") == "lab"],
                 "room_capacity": {r["name"]: {"recommended": int(r["recommended"]), "max": int(r["max"])} for r in room_rows}}
    return {"faculty": faculty, "soft_constraints": soft, "class_sizes": sizes, "rooms": rooms, "period": period}


def save_draft(dept, user_id, progress, solver_settings, duration_ms, academic_year, active_semester) -> str:
    """Insert the finished run as a draft. Returns the new run's uuid."""
    year, semester = _period(dept, academic_year, active_semester)
    import config.settings as _cfg
    faculty = [{"name": p["faculty"], "max_units": p.get("max_units", 24), "absolute_max_units": p.get("absolute_max", 30)}
               for p in ((progress.get("analytics") or {}).get("workload_metrics") or {}).get("per_professor", [])]
    with _cfg.run_settings(units_per_assignment=(solver_settings or {}).get("units_per_assignment"),
                           non_classroom_units=(solver_settings or {}).get("non_classroom_units")):
        balance = balance_score(progress.get("result"), faculty)
    from services import run_snapshot
    inputs = run_snapshot.finalize(progress.get("inputs_raw") or {}, year, semester) if progress.get("inputs_raw") else None
    row = {
        "dept": dept, "academic_year": year, "semester": semester, "status": "draft",
        "created_by": user_id,
        "solver_settings": _json_safe(solver_settings),
        "metrics": _json_safe({**(progress.get("metrics") or {}), "balance_score": balance}),
        "coverage": _json_safe({"summary": progress.get("coverage") or {},
                                "errors": progress.get("coverage_errors") or []}),
        "duration_ms": int(duration_ms),
        "result": _json_safe(progress.get("result") or []),
        "analytics": _json_safe(progress.get("analytics") or {}),
        "inputs": _json_safe(inputs),
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