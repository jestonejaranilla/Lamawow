"""
ATLAS PSU - routes/run_routes.py
Saved runs (public.schedule_runs). The service client bypasses RLS, so the rules are applied here:
  chairperson : every run of their own department
  faculty     : approved runs of their own department only (anything else answers 404)
  admin       : every department
A run of another department answers 403. Approval calls the approve_run RPC as the signed-in user,
so the database checks the role and department again.
"""

from flask import Blueprint, request

from config.curriculum import UnknownDepartment
from routes.schedule_routes import _err, _ok, request_dept
from services import run_store
from services.audit_service import audit
from services.auth_service import ADMIN, ANY_ROLE, CHAIR, FACULTY, STAFF, current_user, require_user

runs_bp = Blueprint("runs", __name__)
MAX_LABEL = 120


@runs_bp.errorhandler(UnknownDepartment)
def _bad_dept(e):
    return _err(str(e), 400)


@runs_bp.errorhandler(run_store.StoreUnavailable)
def _no_db(e):
    return _err(str(e), 503)


def _can_see(user, run) -> bool:
    """Raise-free visibility check; the caller decides between 403 and 404."""
    return user.get("dev") or user["role"] == ADMIN or run.get("dept") == user.get("dept")


def _load(run_id, full=False):
    """Fetch a run the user may see. 404 when missing (or not approved for faculty), 403 for another department."""
    user = current_user()
    run = run_store.get_run(run_id) if full else run_store.get_run_header(run_id)
    if not run:
        return None, _err("Run not found.", 404)
    if not _can_see(user, run):
        return None, _err("That run belongs to another department.", 403)
    if user["role"] == FACULTY and run.get("status") != "approved":
        return None, _err("Run not found.", 404)
    if user["role"] == FACULTY:
        run.pop("inputs", None)                     # the snapshot lists every professor's preferences and leave dates
    return run, None


@runs_bp.route("/runs", methods=["GET"])
@require_user(ANY_ROLE)
def list_runs():
    dept = request_dept()
    user = current_user()
    statuses = ["approved"] if user["role"] == FACULTY else None
    return _ok({"dept": dept, "runs": run_store.list_runs(dept, statuses)})


@runs_bp.route("/runs/<run_id>", methods=["GET"])
@require_user(ANY_ROLE)
def get_run(run_id):
    run, err = _load(run_id, full=True)
    return err if err else _ok({"run": run})


@runs_bp.route("/runs/<run_id>/save", methods=["POST"])
@require_user(STAFF)
def save_run(run_id):
    run, err = _load(run_id)
    if err:
        return err
    if run["status"] == "approved":
        return _err("An approved run is already saved.", 409)
    body = request.get_json(silent=True) or {}
    label = body.get("label")
    if label is not None:
        if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL:
            return _err(f"label must be 1 to {MAX_LABEL} characters.")
        label = label.strip()
    row = run_store.mark_saved(run_id, label)
    audit(current_user(), "run_saved", "run", run_id, {"labelled": label is not None}, dept=run["dept"])
    return _ok({"run": row})


@runs_bp.route("/runs/<run_id>/approve", methods=["POST"])
@require_user((CHAIR,))
def approve_run(run_id):
    run, err = _load(run_id)
    if err:
        return err
    user = current_user()
    if run["status"] != "approved":
        try:
            run_store.approve(run_id, user.get("token"))
        except run_store.StoreUnavailable:
            raise
        except Exception as e:                                  # noqa: BLE001
            text = str(e)
            if "42501" in text or "not found or not in your department" in text:
                return _err("You cannot approve this run.", 403)
            return _err("Could not approve the run.", 502)
        # the approve_run function writes its own audit row, so none is added here
    return _ok({"run": {"id": run_id, "dept": run["dept"], "status": "approved"}})


@runs_bp.route("/runs/<run_id>", methods=["DELETE"])
@require_user(STAFF)
def delete_run(run_id):
    run, err = _load(run_id)
    if err:
        return err
    if run["status"] == "approved":
        return _err("An approved run cannot be deleted. Approve another run first.", 409)
    run_store.delete_run(run_id)
    audit(current_user(), "run_deleted", "run", run_id, {"status": run["status"]}, dept=run["dept"])
    return _ok({"id": run_id, "deleted": True})