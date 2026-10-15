"""
ATLAS PSU - routes/analytics_routes.py
"""

from flask import Blueprint, jsonify

from config.curriculum import UnknownDepartment
from routes.schedule_routes import request_dept, _err
from services.schedule_service import (
    get_progress, get_soft_constraints, get_static_lookup, get_faculty, get_class_sizes, get_rooms,
)
from services.analytics_service import compute_analytics
from services.auth_service import STAFF, require_user

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.errorhandler(UnknownDepartment)
def _bad_dept(e):
    return _err(str(e), 400)


def _ok(data=None, metrics=None, warnings=None):
    return jsonify({
        "success":  True,
        "data":     data or {},
        "metrics":  metrics or {},
        "warnings": warnings or [],
    })


@analytics_bp.route("/analytics", methods=["GET"])
@require_user(STAFF)
def get_analytics():
    """Return analytics for the most recent completed schedule."""
    dept = request_dept()
    p = get_progress(dept)
    if p.get("running"):
        return _ok(data={"status": "running"}, warnings=["Schedule still in progress."])
    if not p.get("result"):
        return _ok(data={"status": "no_schedule"}, warnings=["No schedule generated yet."])

    analytics = p.get("analytics")
    if not analytics:
        # Re-compute on demand (e.g. after server restart with cached result)
        from config.rooms import use_rooms
        with use_rooms(get_rooms(dept)):
            analytics = compute_analytics(
                p["result"],
                get_faculty(dept),
                get_static_lookup(dept),
                get_soft_constraints(dept),
                p.get("metrics", {}),
                class_sizes=get_class_sizes(dept),
            )

    return _ok(data=analytics, metrics=p.get("metrics", {}), warnings=p.get("warnings", []))


@analytics_bp.route("/analytics/workload", methods=["GET"])
@require_user(STAFF)
def get_workload():
    """Workload distribution subset."""
    p = get_progress(request_dept())
    analytics = p.get("analytics", {})
    return _ok(data={
        "faculty_utilization":   analytics.get("faculty_utilization", []),
        "workload_distribution": analytics.get("workload_distribution", {}),
    })


@analytics_bp.route("/analytics/specialization", methods=["GET"])
@require_user(STAFF)
def get_specialization():
    p = get_progress(request_dept())
    analytics = p.get("analytics", {})
    return _ok(data=analytics.get("specialization_metrics", {}))


@analytics_bp.route("/analytics/rooms", methods=["GET"])
@require_user(STAFF)
def get_room_analytics():
    p = get_progress(request_dept())
    analytics = p.get("analytics", {})
    return _ok(data=analytics.get("room_utilization", []))


@analytics_bp.route("/analytics/satisfaction", methods=["GET"])
@require_user(STAFF)
def get_satisfaction():
    p = get_progress(request_dept())
    analytics = p.get("analytics", {})
    return _ok(data=analytics.get("satisfaction_metrics", {}))