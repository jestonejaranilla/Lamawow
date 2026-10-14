"""
ATLAS PSU - routes/schedule_routes.py
Every request is department-scoped: `dept` is a query parameter (GET) or a
field of the JSON body (POST; the query parameter also works). A missing or
unknown department is a 400, except GET /curriculum/<dept> which answers 404.
"""

from flask import Blueprint, jsonify, request

from config.curriculum import (
    UnknownDepartment, list_departments, load_curriculum, available_departments,
)
from services.schedule_service import (
    start_scheduling, get_progress, get_soft_constraints, set_soft_constraint, check_dept,
    get_class_sizes, update_class_sizes, update_rooms, get_rooms,
)

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
    d = request.args.get("dept")
    if not d and isinstance(body, dict):
        d = body.get("dept")
    return check_dept(d)


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
def get_rooms_route():
    dept = request_dept()
    return jsonify(_rooms_payload(dept, get_rooms(dept)))


@schedule_bp.route("/rooms", methods=["POST"])
def update_rooms_route():
    data = request.get_json(silent=True) or {}
    dept = request_dept(data)
    rs = update_rooms(dept, data.get("lecture_rooms"), data.get("laboratory_rooms"),
                      data.get("room_capacity"))
    return _ok(_rooms_payload(dept, rs, saved=True))


# ── /class-sizes ──────────────────────────────────────────────────────────────

@schedule_bp.route("/class-sizes", methods=["GET"])
def get_class_sizes_route():
    return jsonify(get_class_sizes(request_dept()))


@schedule_bp.route("/class-sizes", methods=["POST"])
def update_class_sizes_route():
    data = request.get_json(silent=True) or {}
    dept = request_dept(data)
    incoming = {k: v for k, v in data.items() if k != "dept"}
    try:
        sizes = update_class_sizes(dept, incoming)
    except ValueError as e:
        return _err(str(e))
    return _ok({"dept": dept, "class_sizes": sizes})


# ── /run-ga (CP-SAT + GA for one department) ──────────────────────────────────

@schedule_bp.route("/run-ga", methods=["POST"])
def run_ga():
    data = request.get_json(silent=True) or {}
    dept = request_dept(data)
    if len(data) <= 1:
        return _err("Empty payload.")

    # Runtime engine settings (global engine parameters, not department data)
    units_per_assignment = data.get("units_per_assignment")
    cp_sat_time_limit    = data.get("cp_sat_time_limit")
    non_classroom_units  = data.get("non_classroom_units")
    import config.settings as _cfg
    if units_per_assignment:
        _cfg.UNITS_PER_ASSIGNMENT = int(units_per_assignment)
    if non_classroom_units:
        _cfg.NON_CLASSROOM_UNITS = int(non_classroom_units)
    if cp_sat_time_limit:
        _cfg.CP_SAT_TIME_LIMIT_SECONDS = float(cp_sat_time_limit)

    # Room-capacity edits sent with the run belong to this department only
    if data.get("room_capacity"):
        update_rooms(dept, room_capacity=data["room_capacity"])

    result = start_scheduling(
        dept=dept,
        faculty_raw=data.get("faculty", []),
        subjects_raw=data.get("subjects", []),
        active_semester=data.get("active_semester"),
        ga_params={
            "generations": data.get("generations", 50),
            "population":  data.get("population",  20),
            "mutation":    data.get("mutation",     0.15),
            "crossover":   data.get("crossover",    0.8),
        },
        soft_constraints_incoming=data.get("soft_constraints", {}),
        class_sizes=data.get("class_sizes", {}),
    )

    if "error" in result:
        return _err(result["error"])
    return jsonify({"status": "started", "dept": dept, "run_id": result["run_id"],
                    "sections": result.get("sections", 0), "groups": result.get("groups", 0)})


# ── /progress ─────────────────────────────────────────────────────────────────

@schedule_bp.route("/progress", methods=["GET"])
def progress():
    dept = request_dept()
    p = get_progress(dept)
    return jsonify({
        "dept":      dept,
        "run_id":    p["run_id"],
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
def get_sc():
    dept = request_dept()
    fac = request.args.get("faculty")
    if fac:
        return jsonify({fac: get_soft_constraints(dept, fac)})
    return jsonify(get_soft_constraints(dept))


@schedule_bp.route("/soft-constraints", methods=["POST"])
def set_sc():
    data = request.get_json(silent=True) or {}
    dept = request_dept(data)
    fac_name = data.get("faculty")
    if not fac_name:
        return _err("faculty name required.")
    for k, v in data.get("constraints", {}).items():
        set_soft_constraint(dept, fac_name, k, v)
    return _ok({"dept": dept, "faculty": fac_name,
                "constraints": get_soft_constraints(dept, fac_name)})