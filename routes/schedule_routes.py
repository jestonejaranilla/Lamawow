"""
ATLAS PSU - routes/schedule_routes.py
Every request is department-scoped: `dept` is a query parameter (GET) or a
field of the JSON body (POST; the query parameter also works). A missing or
unknown department is a 400, except GET /curriculum/<dept> which answers 404.
"""

import logging
import secrets
import time

from flask import Blueprint, jsonify, request

from config.settings import CP_SAT_MAX_TIME_LIMIT_SECONDS, DETERMINISTIC

from config.curriculum import (
    UnknownDepartment, list_departments, load_curriculum, available_departments,
)
from services.schedule_service import (
    start_scheduling, get_progress, get_soft_constraints, set_soft_constraint, check_dept,
    get_class_sizes, update_class_sizes, update_rooms, get_rooms, attach_saved_run,
)
RUN_KEYS = {"dept", "faculty", "subjects", "population", "generations", "mutation", "crossover", "soft_constraints",
            "active_semester", "academic_year", "class_sizes", "room_capacity", "units_per_assignment",
            "non_classroom_units", "cp_sat_time_limit", "seed", "deterministic"}
MAX_FACULTY = 200
MAX_SUBJECTS = 2000
log = logging.getLogger("atlas.runs")

from services.auth_service import CHAIR, STAFF, current_user, require_user, scope_dept
from services.audit_service import audit
from services import run_store

schedule_bp = Blueprint("schedule", __name__)


def _ok(data=None, metrics=None, warnings=None):
    return jsonify({
        "success":  True,
        "data":     data or {},
        "metrics":  metrics or {},
        "warnings": warnings or [],
    })


def _err(msg: str, code: int = 400):
    return jsonify({"success": False, "error": msg, "data": {}, "metrics": {}, "warnings": []}), code


def request_dept(body=None) -> str:
    """The department of this request (query string first, then JSON body)."""
    q = request.args.get("dept") or None
    b = body.get("dept") if isinstance(body, dict) else None
    # Signed-in chairperson / faculty: always their own department; naming another one is a 403.
    # Admin and local dev (ATLAS_AUTH=off): the department named in the request.
    return check_dept(scope_dept(q, b or None))


@schedule_bp.errorhandler(UnknownDepartment)
def _bad_dept(e):
    return _err(str(e), 400)


def _rooms_payload(dept, rs, saved=None):
    out = {
        "dept":             dept,
        "lecture_rooms":    list(rs.lecture_rooms),
        "laboratory_rooms": list(rs.lab_rooms),
        "all_rooms":        rs.all_rooms,
        "room_capacity":    rs.capacity,
        "lab_rooms_also_lecture": rs.lab_also_lecture,
        "capacity_placeholder":   rs.placeholder,
    }
    if saved is not None:
        out["saved"] = saved
    return out


# ── /rooms - this department's rooms ──────────────────────────────────────────

@schedule_bp.route("/rooms", methods=["GET"])
@require_user(STAFF)
def get_rooms_route():
    dept = request_dept()
    return jsonify(_rooms_payload(dept, get_rooms(dept)))


@schedule_bp.route("/rooms", methods=["POST"])
@require_user(STAFF)
def update_rooms_route():
    data = request.get_json(silent=True) or {}
    dept = request_dept(data)
    rs = update_rooms(dept, data.get("lecture_rooms"), data.get("laboratory_rooms"),
                      data.get("room_capacity"))
    audit(current_user(), "rooms_changed", "rooms", dept,
          {"lecture_rooms": len(rs.lecture_rooms), "lab_rooms": len(rs.lab_rooms)})
    return _ok(_rooms_payload(dept, rs, saved=True))


# ── /class-sizes ──────────────────────────────────────────────────────────────

@schedule_bp.route("/class-sizes", methods=["GET"])
@require_user(STAFF)
def get_class_sizes_route():
    return jsonify(get_class_sizes(request_dept()))


@schedule_bp.route("/class-sizes", methods=["POST"])
@require_user(STAFF)
def update_class_sizes_route():
    data = request.get_json(silent=True) or {}
    dept = request_dept(data)
    incoming = {k: v for k, v in data.items() if k != "dept"}
    try:
        sizes = update_class_sizes(dept, incoming)
    except ValueError as e:
        return _err(str(e))
    audit(current_user(), "class_sizes_changed", "class_sizes", dept,
          {"blocks_sent": len(incoming), "blocks_total": len(sizes)})
    return _ok({"dept": dept, "class_sizes": sizes})


# ── /run-ga (CP-SAT + GA for one department) ──────────────────────────────────

class BadNumber(ValueError):
    pass


def _number(data, key, lo, hi, default, integer=False):
    """Missing or null -> default. A non-number (text, bool, NaN) is a 400. A number is clamped to lo..hi."""
    v = data.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise BadNumber(f"'{key}' must be a number.")
    v = min(max(v, lo), hi)
    return int(round(v)) if integer else float(v)

def _faculty_key(faculty):
    """Order-free comparison key of a faculty list (the fields the engine reads)."""
    return sorted((str(f.get("name")), tuple(f.get("specialization") or []), str(f.get("max_units")),
                   str(f.get("absolute_max_units")), tuple(sorted(f.get("availability") or [])))
                  for f in faculty if isinstance(f, dict))


@schedule_bp.route("/run-ga", methods=["POST"])
@require_user(STAFF)
def run_ga():
    data = request.get_json(silent=True) or {}
    dept = request_dept(data)
    if len(data) <= 1:
        return _err("Empty payload.")

    unknown = sorted(set(data) - RUN_KEYS)
    if unknown:
        return _err("Unknown field(s): " + ", ".join(str(k)[:40] for k in unknown[:5]) + ".")
    for key, cap in (("faculty", MAX_FACULTY), ("subjects", MAX_SUBJECTS)):
        v = data.get(key)
        if v is not None and (not isinstance(v, list) or len(v) > cap):
            return _err(f"'{key}' must be a list of at most {cap} items.")

    # Inputs are clamped; the engine settings below apply to this run only (nothing global is changed).
    try:
        ga_params = {
            "generations": _number(data, "generations", 1, 200, 50, integer=True),
            "population":  _number(data, "population", 4, 100, 20, integer=True),
            "mutation":    _number(data, "mutation", 0, 1, 0.15),
            "crossover":   _number(data, "crossover", 0, 1, 0.8),
        }
        run_settings = {
            "units_per_assignment": _number(data, "units_per_assignment", 1, 10, None, integer=True),
            "non_classroom_units":  _number(data, "non_classroom_units", 1, 10, None, integer=True),
            "cp_sat_time_limit":    _number(data, "cp_sat_time_limit", 1, CP_SAT_MAX_TIME_LIMIT_SECONDS, None),
        }
        # Reproducibility: the seed is random unless given, and always stored with the run.
        seed = _number(data, "seed", 0, 2**31 - 1, None, integer=True)
    except BadNumber as e:
        return _err(str(e))
    deterministic = data.get("deterministic")
    if deterministic is not None and not isinstance(deterministic, bool):
        return _err("'deterministic' must be true or false.")
    if seed is None:
        seed = secrets.randbelow(2**31)
    if deterministic is None:
        deterministic = bool(DETERMINISTIC)

    user = current_user()
    faculty_in = data.get("faculty", [])
    prefs_in = data.get("soft_constraints", {})
    sizes_in = data.get("class_sizes", {})
    replace_prefs = False
    extra_warnings = []
    if user and not user.get("dev") and user.get("role") == CHAIR and run_store.enabled():
        # A chairperson's run never trusts the browser: faculty, class sizes, rooms, preferences and leave
        # come from the database for the chair's own department, and a different list sent by the client is ignored.
        try:
            db_in = run_store.load_dept_inputs(dept)
        except Exception as e:                      # noqa: BLE001
            log.warning("could not load run inputs for %s: %s", dept, e)
            return _err("Could not read this department's data from the database. Try again.", 503)
        if not db_in["faculty"]:
            return _err("No faculty are saved for this department. Add faculty or load the sample faculty first.")
        if len(db_in["faculty"]) > MAX_FACULTY:
            return _err(f"Too many faculty (max {MAX_FACULTY}).")
        if faculty_in and _faculty_key(faculty_in) != _faculty_key(db_in["faculty"]):
            extra_warnings.append("The faculty list sent by the browser differs from the saved one; the saved list was used.")
            log.warning("run in %s: client faculty list differs from the database; the database list was used", dept)
        faculty_in, prefs_in, sizes_in, replace_prefs = (db_in["faculty"], db_in["soft_constraints"],
                                                         db_in["class_sizes"], True)
        if db_in["rooms"]:
            update_rooms(dept, db_in["rooms"]["lecture_rooms"], db_in["rooms"]["laboratory_rooms"],
                         db_in["rooms"]["room_capacity"])
    elif data.get("room_capacity"):
        # Local development and admin runs: room-capacity edits sent with the run belong to this department only
        update_rooms(dept, room_capacity=data["room_capacity"])

    started = time.monotonic()

    def finished(d, run_id):
        """Runs after the job ends: audit it and save a successful run as a draft."""
        p = get_progress(d)
        if p.get("run_id") != run_id:
            return                                  # a newer run owns this department now
        done = p.get("phase") == "done"
        audit(user, "run_finished", "run", run_id,
              {"status": "done" if done else "error", "ms": int((time.monotonic() - started) * 1000),
               "assigned": (p.get("coverage") or {}).get("assigned"),
               "total": (p.get("coverage") or {}).get("total")}, dept=d)
        if done and run_store.enabled():
            try:
                solver = {**ga_params, **{k: v for k, v in run_settings.items() if v is not None},
                          "seed": seed, "deterministic": deterministic}
                saved_id = run_store.save_draft(d, (user or {}).get("id"), p, solver,
                                                (time.monotonic() - started) * 1000,
                                                data.get("academic_year"), data.get("active_semester"))
                attach_saved_run(d, run_id, saved_id)
            except Exception as e:                  # noqa: BLE001 - the run itself is fine, only saving failed
                import logging
                logging.getLogger("atlas.runs").warning("could not save run %s: %s", run_id, e)

    result = start_scheduling(
        dept=dept,
        faculty_raw=faculty_in,
        subjects_raw=data.get("subjects", []),
        active_semester=data.get("active_semester"),
        ga_params=ga_params,
        run_settings=run_settings,
        soft_constraints_incoming=prefs_in,
        class_sizes=sizes_in,
        on_finish=finished,
        replace_preferences=replace_prefs,
        seed=seed,
        deterministic=deterministic,
    )

    if "error" in result:
        return _err(result["error"])
    audit(user, "run_started", "run", result["run_id"],
          {"groups": result.get("groups", 0), "faculty": len(data.get("faculty") or [])}, dept=dept)
    return jsonify({"status": "started", "dept": dept, "run_id": result["run_id"],
                    "sections": result.get("sections", 0), "groups": result.get("groups", 0),
                    "seed": seed, "deterministic": deterministic,
                    "warnings": extra_warnings})


# ── /progress ─────────────────────────────────────────────────────────────────

@schedule_bp.route("/progress", methods=["GET"])
@require_user(STAFF)
def progress():
    dept = request_dept()
    p = get_progress(dept)
    return jsonify({
        "dept":      dept,
        "run_id":    p["run_id"],
        "saved_run_id": p.get("saved_run_id"),
        "current":   p["current"],
        "total":     p["total"],
        "running":   p["running"],
        "phase":     p["phase"],
        "result":    p["result"],
        "analytics": p.get("analytics", {}),
        "metrics":   p.get("metrics", {}),
        "warnings":  p.get("warnings", []),
        "coverage":        p.get("coverage", {"assigned": 0, "total": 0}),
        "coverage_errors": p.get("coverage_errors", []),
    })


# ── /curricula and /curriculum/<dept> - the files the frontend reads ──────────

@schedule_bp.route("/curricula", methods=["GET"])
def curricula():
    return jsonify(list_departments())


@schedule_bp.route("/curriculum/<dept>", methods=["GET"])
def get_curriculum(dept):
    if dept not in available_departments():
        return _err(f"Unknown department: {dept}", 404)
    return jsonify(load_curriculum(dept))


# ── /soft-constraints (per department) ────────────────────────────────────────

@schedule_bp.route("/soft-constraints", methods=["GET"])
@require_user(STAFF)
def get_sc():
    dept = request_dept()
    fac = request.args.get("faculty")
    if fac:
        return jsonify({fac: get_soft_constraints(dept, fac)})
    return jsonify(get_soft_constraints(dept))


@schedule_bp.route("/soft-constraints", methods=["POST"])
@require_user(STAFF)
def set_sc():
    data = request.get_json(silent=True) or {}
    dept = request_dept(data)
    fac_name = data.get("faculty")
    if not fac_name:
        return _err("faculty name required.")
    for k, v in data.get("constraints", {}).items():
        set_soft_constraint(dept, fac_name, k, v)
    audit(current_user(), "soft_constraints_changed", "faculty_preferences", None,
          {"fields": len(data.get("constraints", {}))}, dept=dept)
    return _ok({"dept": dept, "faculty": fac_name,
                "constraints": get_soft_constraints(dept, fac_name)})