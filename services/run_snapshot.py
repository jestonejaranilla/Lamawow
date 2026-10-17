"""
ATLAS PSU - services/run_snapshot.py
The `inputs` snapshot stored with every saved run (public.schedule_runs.inputs), so a run can be reproduced
and explained months later. Pure functions, no Flask and no database.

inputs = {
  "schema": 1,
  "data":   everything the schedule depends on (faculty, class sizes, rooms, preferences and leave dates,
            subjects, academic year, semester, solver settings, seed, deterministic flag),
  "sha256": SHA-256 of the canonical JSON of "data",
  "code_version": git commit (or VERSION), "libraries": solver library versions,
}
The hash covers "data" only, so the same inputs hash the same on any machine and code version.
"""

import hashlib
import json
import os
import platform
import subprocess
from functools import lru_cache

import config.settings as cfg

SCHEMA = 1
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Only what the engine reads and the UI can send. No reasons, no free text.
_PREF_KEYS = ("preferred_period", "preferred_room", "preferred_building", "preferred_floor", "restricted_days")


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def code_version() -> str:
    env = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT")
    if env:
        return env[:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=_ROOT, capture_output=True,
                             text=True, timeout=2)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:                                           # noqa: BLE001 - no git is fine
        pass
    return cfg.VERSION


@lru_cache(maxsize=1)
def library_versions() -> dict:
    from importlib import metadata
    out = {"python": platform.python_version()}
    for name in ("ortools", "flask", "supabase"):
        try:
            out[name] = metadata.version(name)
        except Exception:                                       # noqa: BLE001
            out[name] = None
    return out


def _faculty(faculty_list) -> list:
    keep = ("name", "specialization", "max_units", "overload_buffer", "absolute_max_units", "availability")
    return [{k: f.get(k) for k in keep} for f in faculty_list or []]


def _preferences(soft_constraints) -> dict:
    out = {}
    for name, sc in (soft_constraints or {}).items():
        if not isinstance(sc, dict):
            continue
        item = {k: sc[k] for k in _PREF_KEYS if sc.get(k)}
        leave = [{"start": str(x.get("start") or ""), "end": str(x.get("end") or "")}
                 for x in sc.get("leave_dates") or [] if isinstance(x, dict)]
        if leave:
            item["leave_dates"] = leave
        if item:
            out[name] = item
    return out


def _rooms(rs) -> dict:
    return {"lecture_rooms": list(rs.lecture_rooms), "laboratory_rooms": list(rs.lab_rooms),
            "capacity": rs.capacity, "lab_rooms_also_lecture": bool(rs.lab_also_lecture)}


def build_data(dept, faculty_list, class_sizes, rs, soft_constraints, subjects, solver_settings,
               seed, deterministic, active_semester=None, period=None) -> dict:
    """The reproducibility inputs of one run, as plain JSON (academic year and semester are added when it is saved)."""
    data = {
        "dept": dept,
        "faculty": _faculty(faculty_list),
        "class_sizes": class_sizes or {},
        "rooms": _rooms(rs),
        "preferences": _preferences(soft_constraints),
        "subjects": subjects or [],
        "active_semester": active_semester,
        "solver_settings": solver_settings or {},
        "seed": int(seed),
        "deterministic": bool(deterministic),
    }
    if period:                                                  # Part 24: the dates leave was judged against
        data["period"] = {"start": str(period[0]), "end": str(period[1])}
    return json.loads(canonical_json(data))


def finalize(data: dict, academic_year, semester) -> dict:
    """Add the period, hash the data and attach the code and library versions."""
    data = json.loads(canonical_json({**data, "academic_year": academic_year, "semester": semester}))
    return {"schema": SCHEMA, "data": data, "sha256": sha256_of(data),
            "code_version": code_version(), "libraries": library_versions()}


def verify(inputs: dict) -> bool:
    """True when the stored hash matches the stored data."""
    return bool(inputs) and inputs.get("sha256") == sha256_of(inputs.get("data"))