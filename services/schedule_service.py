"""
ATLAS PSU - services/schedule_service.py
Orchestrates Phase 1 (CP-SAT) → Phase 2 (GA) → Phase 3 (Analytics).
Thread-safe progress store for polling endpoint.
"""

import copy
import math
import re
import threading
import uuid
from typing import Optional

import config.settings as _settings_cfg
from config.curriculum import (
    load_curriculum, courses_of, specialization_lookup, class_sizes_for, rooms_for,
    UnknownDepartment,
)
from config.rooms import use_rooms
from solver.cp_sat_solver import solve as cp_solve
from solver.ga_optimizer import optimize as ga_optimize
from services.analytics_service import compute_analytics
from solver.constraints import (
    faculty_qualifies, assignment_units, NON_CLASSROOM, validate_schedule,
)

# ── Per-department state ──────────────────────────────────────────────────────
# Everything a department owns lives in its own _DeptState: progress, last
# result, analytics, warnings, soft constraints, class sizes, room edits and
# the static lookup. Each state has its own lock. Two departments can run at
# the same time and never see or overwrite each other's data.


def _blank_progress(dept: str) -> dict:
    return {
        "dept":      dept,
        "run_id":    None,
        "current":   0,
        "total":     0,
        "running":   False,
        "phase":     "",        # "cp_sat" | "ga" | "analytics" | "done" | "error"
        "result":    [],
        "analytics": {},
        "metrics":   {},
        "warnings":  [],
        "coverage":        {"assigned": 0, "total": 0},
        "coverage_errors": [],
    }


class _DeptState:
    def __init__(self, dept: str):
        self.dept = dept
        self.lock = threading.RLock()
        self.progress = _blank_progress(dept)
        self.static_lookup: dict = {}
        self.soft_constraints: dict = {}
        self.class_sizes: dict = class_sizes_for(dept)
        self.room_override: dict = {}
        self.faculty: list = []


_states: dict = {}
_states_lock = threading.Lock()


def check_dept(dept) -> str:
    """Return a valid department id or raise UnknownDepartment (routes answer 400)."""
    if not dept or not isinstance(dept, str):
        raise UnknownDepartment("Missing department.")
    load_curriculum(dept)          # raises UnknownDepartment when unknown
    return dept


def _state(dept: str) -> _DeptState:
    check_dept(dept)
    with _states_lock:
        if dept not in _states:
            _states[dept] = _DeptState(dept)
        return _states[dept]


def reset_state(dept: str = None) -> None:
    """Forget a department's (or every department's) runtime state. Used by tests."""
    with _states_lock:
        if dept is None:
            _states.clear()
        else:
            _states.pop(dept, None)


def get_progress(dept: str) -> dict:
    st = _state(dept)
    with st.lock:
        return copy.deepcopy(st.progress)


def is_running(dept: str) -> bool:
    st = _state(dept)
    with st.lock:
        return st.progress["running"]


def _set_progress(dept: str, run_id: str = None, **kwargs) -> None:
    st = _state(dept)
    with st.lock:
        if run_id is not None and st.progress.get("run_id") != run_id:
            return                    # a newer run owns this department now
        st.progress.update(kwargs)


def attach_saved_run(dept: str, run_id: str, saved_run_id: str) -> None:
    """Remember the database id of the saved copy of run `run_id` (shown in /progress)."""
    _set_progress(dept, run_id, saved_run_id=saved_run_id)


# ── Static lookup (per department) ────────────────────────────────────────────

def build_static_lookup(dept: str) -> dict:
    """{course title: tags} built from the active department's file only."""
    st = _state(dept)
    lookup = specialization_lookup(dept)
    with st.lock:
        st.static_lookup = lookup
    return copy.deepcopy(lookup)


def get_static_lookup(dept: str) -> dict:
    st = _state(dept)
    with st.lock:
        return copy.deepcopy(st.static_lookup) or specialization_lookup(dept)


# ── Class sizes and rooms (per department) ────────────────────────────────────

def _block_key_ok(dept: str, key: str) -> bool:
    return re.match(rf"^{re.escape(dept)}\d+B\d+$", str(key)) is not None


def get_class_sizes(dept: str) -> dict:
    st = _state(dept)
    with st.lock:
        return copy.deepcopy(st.class_sizes)


def update_class_sizes(dept: str, incoming: dict) -> dict:
    """Merge size edits. Only this department's block keys are accepted (ValueError otherwise)."""
    st = _state(dept)
    bad = [k for k in incoming if not _block_key_ok(dept, k)]
    if bad:
        raise ValueError(f"Not {dept} blocks: {', '.join(map(str, bad[:5]))}")
    with st.lock:
        for key, val in incoming.items():
            if isinstance(val, dict):
                st.class_sizes.setdefault(key, {}).update(val)
            elif isinstance(val, (int, float)):
                st.class_sizes.setdefault(key, {})["size"] = int(val)
        return copy.deepcopy(st.class_sizes)


def get_room_override(dept: str) -> dict:
    st = _state(dept)
    with st.lock:
        return copy.deepcopy(st.room_override)


def update_rooms(dept: str, lecture_rooms=None, laboratory_rooms=None, room_capacity=None):
    """Store this department's runtime room edits and return its resulting RoomSet."""
    st = _state(dept)
    with st.lock:
        if lecture_rooms is not None:
            st.room_override["lecture_rooms"] = [str(r).strip() for r in lecture_rooms if str(r).strip()]
        if laboratory_rooms is not None:
            st.room_override["laboratory_rooms"] = [str(r).strip() for r in laboratory_rooms if str(r).strip()]
        if room_capacity:
            cur = st.room_override.setdefault("room_capacity", {})
            cur.update({k: v for k, v in room_capacity.items() if isinstance(v, dict)})
        return rooms_for(dept, copy.deepcopy(st.room_override))


def get_rooms(dept: str):
    st = _state(dept)
    with st.lock:
        return rooms_for(dept, copy.deepcopy(st.room_override))


def set_faculty(dept: str, faculty: list) -> None:
    st = _state(dept)
    with st.lock:
        st.faculty = copy.deepcopy(faculty)


def get_faculty(dept: str) -> list:
    st = _state(dept)
    with st.lock:
        return copy.deepcopy(st.faculty)


# ── Groups: one (block, course) pair, one professor ───────────────────────────

_YEAR_LABELS = {1: "1st Year", 2: "2nd Year", 3: "3rd Year", 4: "4th Year"}
_SEM_LABELS = {1: "1st Semester", 2: "2nd Semester"}


def year_label(n: int) -> str:
    return _YEAR_LABELS.get(n, f"{n}th Year")


def semester_label(n: int) -> str:
    return _SEM_LABELS.get(n, "Summer" if n == 3 else str(n))


def parse_semester(value) -> Optional[int]:
    """'1st Semester' / '2nd Semester' / 1 / '1' -> 1 or 2. Anything else -> None."""
    if value in (None, ""):
        return None
    m = re.match(r"\s*(\d)", str(value))
    return int(m.group(1)) if m else None


def _size_of(entry) -> int:
    if isinstance(entry, dict):
        try:
            return int(entry.get("size", 0) or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(entry, (int, float)):
        return int(entry)
    return 0


def blocks_for_year(class_sizes: dict, dept: str, year_no: int) -> list:
    """[(block_key, size)] for a year, read from class sizes (e.g. IT3B1 .. IT3B3)."""
    pat = re.compile(rf"^{re.escape(dept)}(\d+)B(\d+)$")
    found = []
    for key, entry in (class_sizes or {}).items():
        m = pat.match(str(key))
        if not m or int(m.group(1)) != year_no:
            continue
        found.append((int(m.group(2)), key, _size_of(entry)))
    return [(key, size) for _, key, size in sorted(found)]


def group_id_for(block_key: str, course_code: str) -> str:
    return f"{block_key}|{course_code}"


def build_groups(dept: str, active_semester, class_sizes: dict):
    """
    R1: every block of every year gets every course of its year and the active
    semester, from this department's file only. Returns (groups, errors).
    `active_semester` None means both semesters.
    """
    check_dept(dept)
    sem = parse_semester(active_semester)
    groups, errors = [], []
    for course in courses_of(dept, semester=sem):
        blocks = blocks_for_year(class_sizes, dept, course["year"])
        if not blocks:
            errors.append({
                "block": "", "course": course["code"], "title": course["title"],
                "group_id": "",
                "reason": f"no blocks defined for {year_label(course['year'])} in class sizes",
            })
            continue
        for block_key, size in blocks:
            groups.append({
                "group_id":      group_id_for(block_key, course["code"]),
                "section":       block_key,
                "course_code":   course["code"],
                "title":         course["title"],
                "year":          year_label(course["year"]),
                "semester":      semester_label(course["semester"]),
                "type":          (course.get("specialization") or ["Elective"])[0],
                "category":      course.get("category", ""),
                "lec":           int(course["lec"]),
                "lab":           int(course["lab"]),
                "scheduled":     bool(course.get("scheduled", True)),
                "student_count": size,
            })
    return groups, errors


def _meeting(group: dict, class_type: str, n: int) -> dict:
    return {
        "name":          group["title"],
        "type":          group["type"],
        "class_type":    class_type,
        "hours":         2,                      # labs stay 2-hour slots
        "semester":      group["semester"],
        "year":          group["year"],
        "section":       group["section"],
        "student_count": group["student_count"],
        "group_id":      group["group_id"],
        "course_code":   group["course_code"],
        "meeting_id":    f"{group['group_id']}#{n}",
    }


def group_meetings(group: dict) -> list:
    """
    ceil(lec/2) two-hour LECTURE meetings plus LAB_MEETINGS_PER_LAB_UNIT LAB
    meetings per lab unit. Unscheduled courses (IT 20, Practicum, ...) give one
    NON_CLASSROOM row: one professor, no slot, no room.
    """
    if not group["scheduled"]:
        return [_meeting(group, NON_CLASSROOM, 0)]
    kinds = ["LECTURE"] * math.ceil(group["lec"] / 2)
    kinds += ["LAB"] * (group["lab"] * int(_settings_cfg.LAB_MEETINGS_PER_LAB_UNIT))
    return [_meeting(group, k, i) for i, k in enumerate(kinds)]


def prepare_scheduling_input(dept: str, subjects_raw: list, active_semester,
                             class_sizes: dict) -> dict:
    """
    Validate the request against the curriculum and build the meeting list.

    Requests that carry `group_id` rows (the dashboard) are validated: groups
    that are not in the curriculum scope are ignored, required groups missing
    from the request are added from the curriculum. Requests without group ids
    (older clients) are built from the curriculum entirely.

    Returns {sections, groups, errors, warnings}.
    """
    groups, errors = build_groups(dept, active_semester, class_sizes)
    warnings = []

    by_gid = {}
    for row in subjects_raw or []:
        gid = row.get("group_id")
        if gid:
            by_gid.setdefault(gid, []).append(row)

    required_ids = {g["group_id"] for g in groups}
    if by_gid:
        unknown = sorted(set(by_gid) - required_ids)
        if unknown:
            warnings.append(
                f"{len(unknown)} group(s) in the request are out of scope or not in the "
                f"curriculum and were ignored: {', '.join(unknown[:5])}"
                + (" ..." if len(unknown) > 5 else "")
            )
    else:
        warnings.append("Request carried no group ids; groups were built from the curriculum.")

    sections, filled = [], []
    for g in groups:
        rows = by_gid.get(g["group_id"])
        meetings = None
        if rows:
            if not g["scheduled"]:
                meetings = [_meeting(g, NON_CLASSROOM, 0)]
            else:
                kinds = [r.get("class_type") for r in rows
                         if r.get("class_type") in ("LECTURE", "LAB")]
                if kinds:
                    meetings = [_meeting(g, k, i) for i, k in enumerate(kinds)]
        if meetings is None:
            meetings = group_meetings(g)
            if by_gid:
                filled.append(g["group_id"])
        sections.extend(meetings)

    if filled:
        warnings.append(
            f"{len(filled)} required group(s) were missing from the request and were "
            f"added from the curriculum: {', '.join(filled[:5])}" + (" ..." if len(filled) > 5 else "")
        )

    return {"sections": sections, "groups": groups, "errors": errors, "warnings": warnings}


# ── Coverage (R3) ─────────────────────────────────────────────────────────────

def _diagnose_group(group: dict, faculty_list: list, static_lookup: dict,
                    loads: dict) -> str:
    qualified = [f for f in faculty_list
                 if faculty_qualifies(f, group["title"], static_lookup)]
    if not qualified:
        return "no qualified faculty"
    if group["scheduled"]:
        from config.settings import DAYS
        if not any(d in DAYS for f in qualified for d in f.get("availability", [])):
            return "no available day"
    probe = {"class_type": "LECTURE" if group["scheduled"] else NON_CLASSROOM}
    need = assignment_units(probe)
    if all(loads.get(f["name"], 0) + need > f.get("absolute_max_units", 30) for f in qualified):
        return "load cap reached"
    return "no conflict-free slot and room found"


def compute_coverage(groups: list, sections: list, assignments: list,
                     faculty_list: list, static_lookup: dict, prep_errors: list = None,
                     reasons: dict = None):
    """
    A group is covered when every one of its meetings has a professor.
    `reasons` ({group_id: reason}) comes from the solver; groups without an
    entry are diagnosed here.
    Returns ({"assigned": n, "total": n}, coverage_errors).
    """
    reasons = reasons or {}
    expected = {}
    for sec in sections:
        expected[sec.get("group_id", "")] = expected.get(sec.get("group_id", ""), 0) + 1

    covered_rows, loads = {}, {}
    for a in assignments:
        if a.get("faculty"):
            covered_rows[a.get("group_id", "")] = covered_rows.get(a.get("group_id", ""), 0) + 1
            loads[a["faculty"]] = loads.get(a["faculty"], 0) + assignment_units(a)

    assigned, errors = 0, list(prep_errors or [])
    for g in groups:
        gid = g["group_id"]
        want = expected.get(gid, 0)
        have = covered_rows.get(gid, 0)
        if want and have >= want:
            assigned += 1
            continue
        errors.append({
            "block":    g["section"],
            "course":   g["course_code"],
            "title":    g["title"],
            "group_id": gid,
            "reason":   reasons.get(gid) or _diagnose_group(g, faculty_list, static_lookup, loads),
            "missing_meetings": max(0, want - have),
        })
    return {"assigned": assigned, "total": len(groups)}, errors


# ── Soft constraint store (per department) ────────────────────────────────────

def get_soft_constraints(dept: str, faculty_name: str = None) -> dict:
    st = _state(dept)
    with st.lock:
        if faculty_name:
            return copy.deepcopy(st.soft_constraints.get(faculty_name, {}))
        return copy.deepcopy(st.soft_constraints)


def set_soft_constraint(dept: str, faculty_name: str, key: str, value) -> None:
    st = _state(dept)
    with st.lock:
        st.soft_constraints.setdefault(faculty_name, {})[key] = value


def load_soft_constraints(dept: str, incoming: dict) -> None:
    st = _state(dept)
    with st.lock:
        for fac_name, constraints in incoming.items():
            if isinstance(constraints, dict):
                st.soft_constraints.setdefault(fac_name, {}).update(constraints)


# ── Main scheduling job ───────────────────────────────────────────────────────

def run_scheduling_job(
    dept: str,
    run_id: str,
    faculty_list: list,
    sections: list,
    static_lookup: dict,
    ga_params: dict,
    class_sizes: dict,
    groups: Optional[list] = None,
    prep_errors: Optional[list] = None,
    prep_warnings: Optional[list] = None,
    rooms=None,
) -> None:
    """
    CP-SAT -> GA -> Analytics for ONE department, under that department's
    rooms. Writes only that department's progress.
    """
    def put(**kw):
        _set_progress(dept, run_id, **kw)

    try:
        rooms = rooms if rooms is not None else get_rooms(dept)
        put(running=True, phase="cp_sat", current=0, result=[], analytics={}, metrics={},
            warnings=[], coverage={"assigned": 0, "total": len(groups or [])},
            coverage_errors=list(prep_errors or []))
        sc = get_soft_constraints(dept)

        with use_rooms(rooms):
            # ── Phase 1: CP-SAT ───────────────────────────────────────────────
            def cp_progress(done, total):
                put(current=int(done / total * 40) if total else 0, total=100)

            cp_assignments, cp_metrics = cp_solve(sections, faculty_list, static_lookup,
                                                  cp_progress, strict=bool(_settings_cfg.REQUIRE_FULL_COVERAGE),
                                                  rooms=rooms)
            uncovered = cp_metrics.pop("uncovered_groups", {})
            cp_violations = cp_metrics.pop("violations", [])

            put(phase="ga", current=40)

            # ── Phase 2: GA optimizer ─────────────────────────────────────────
            generations    = max(1, ga_params.get("generations", 50))
            population     = max(4, ga_params.get("population", 20))
            mutation_rate  = float(ga_params.get("mutation", 0.15))
            crossover_rate = float(ga_params.get("crossover", 0.8))

            def ga_progress(gen, total):
                put(current=40 + int(gen / total * 50) if total else 40, total=100)

            best_assignments, ga_metrics = ga_optimize(
                base_schedule=cp_assignments,
                faculty_list=faculty_list,
                static_lookup=static_lookup,
                soft_constraints=sc,
                generations=generations,
                population_size=population,
                mutation_rate=mutation_rate,
                crossover_rate=crossover_rate,
                progress_cb=ga_progress,
                class_sizes=class_sizes,
                rooms=rooms,
            )

            # R8: the GA may only move slots and rooms. If anything it produced
            # breaks a hard rule, keep the CP-SAT schedule instead.
            ga_warning = None
            ga_violations = validate_schedule(best_assignments, faculty_list, static_lookup,
                                              rooms, class_sizes)
            if len(ga_violations) > len(cp_violations):
                best_assignments = cp_assignments
                ga_warning = "GA result broke a hard rule and was discarded; showing the CP-SAT schedule."

            put(current=90, phase="analytics")

            # ── Phase 3: Analytics ────────────────────────────────────────────
            combined_metrics = {**cp_metrics, **ga_metrics}
            analytics = compute_analytics(
                best_assignments, faculty_list, static_lookup, sc, combined_metrics,
                class_sizes=class_sizes,
            )

        # ── Coverage (R3) ─────────────────────────────────────────────────────
        coverage, coverage_errors = compute_coverage(
            groups or [], sections, best_assignments, faculty_list, static_lookup, prep_errors,
            reasons=uncovered,
        )

        warnings = list(prep_warnings or [])
        if rooms.placeholder:
            warnings.append("Room capacities for this department are placeholders.")
        if ga_warning:
            warnings.append(ga_warning)
        if cp_violations:
            warnings.append(f"{len(cp_violations)} hard-rule violation(s) found in the schedule: "
                            + "; ".join(cp_violations[:3]))
        if coverage_errors:
            warnings.append(
                f"{len(coverage_errors)} group(s) could not be fully covered "
                f"({coverage['assigned']}/{coverage['total']} assigned). See coverage_errors."
            )
        unassigned = sum(1 for a in best_assignments if not a.get("faculty"))
        if unassigned:
            warnings.append(f"{unassigned} section(s) could not be assigned to any faculty.")
        if cp_metrics.get("solver_fallback"):
            warnings.append("The optimizer ran out of time on this server, so the simpler fallback solver built this "
                            "schedule. It is valid but less balanced. Run again, or raise the time limit in Application Settings.")
        elif cp_metrics.get("solver_used") == "cp_backtracking":
            warnings.append("OR-Tools not available - used the greedy fallback solver (not optimal).")
        # Professors who ended with no class: say why, so adding a professor never looks like a silent failure.
        taught = {a.get("faculty") for a in best_assignments if a.get("faculty")}
        for f in faculty_list:
            if f["name"] in taught:
                continue
            if not [t for t in f.get("specialization", []) if t != "Elective"]:
                why = "no specialization selected, so only electives can be assigned"
            elif not f.get("availability"):
                why = "no available days selected"
            elif len(f.get("availability", [])) <= 2:
                why = f"only {len(f['availability'])} available day(s)"
            else:
                why = "other professors with the same specializations already cover those courses"
            warnings.append(f"{f['name']} has no classes: {why}.")

        cap_analytics = analytics.get("capacity_metrics", {})
        hard_violations = cap_analytics.get("hard_violations", [])
        over_recommended = cap_analytics.get("over_recommended_count", 0)
        if hard_violations:
            warnings.append(f"{len(hard_violations)} assignment(s) exceed room hard capacity limits.")
        if over_recommended > 0:
            warnings.append(f"{over_recommended} assignment(s) exceed recommended room capacity.")

        put(current=100, total=100, running=False, phase="done", result=best_assignments,
            analytics=analytics, metrics=combined_metrics, warnings=warnings,
            coverage=coverage, coverage_errors=coverage_errors)

    except Exception as e:
        import traceback
        traceback.print_exc()
        put(running=False, phase="error", warnings=[f"Scheduling engine error: {str(e)}"])


def start_scheduling(
    dept: str,
    faculty_raw: list,
    subjects_raw: list,
    active_semester,
    ga_params: dict,
    soft_constraints_incoming: dict,
    class_sizes: dict = None,
    wait: bool = False,
    run_settings: dict = None,
    on_finish=None,
) -> dict:
    """
    Validate inputs, build the department's meetings, start the background job.
    Returns {status, run_id, dept, sections, groups} or {error}.
    `class_sizes` edits are merged over the department's stored sizes.
    `run_settings` ({units_per_assignment, non_classroom_units, cp_sat_time_limit}) applies to
    this run only; nothing global is changed.
    wait=True runs the job in the caller's thread (tests).
    `on_finish(dept, run_id)` is called after the job ends (done or error); it cannot change the result
    and its errors are only printed.
    """
    st = _state(dept)
    with st.lock:
        if st.progress["running"]:
            return {"error": f"Scheduling is already running for {dept}."}

        if not faculty_raw:
            return {"error": "No faculty provided."}
        if not subjects_raw:
            return {"error": "No subjects provided."}

        if soft_constraints_incoming:
            load_soft_constraints(dept, soft_constraints_incoming)
        if class_sizes:
            update_class_sizes(dept, {k: v for k, v in class_sizes.items() if _block_key_ok(dept, k)})
        sizes = copy.deepcopy(st.class_sizes)
        set_faculty(dept, faculty_raw)

        prep = prepare_scheduling_input(dept, subjects_raw, active_semester, sizes)
        sections = prep["sections"]
        if not sections:
            return {"error": "No sections generated. Check semester and subject data."}

        static_lookup = build_static_lookup(dept)
        rooms = get_rooms(dept)
        run_id = uuid.uuid4().hex[:12]
        st.progress = _blank_progress(dept)
        st.progress.update(run_id=run_id, running=True, phase="cp_sat",
                           coverage={"assigned": 0, "total": len(prep["groups"])})

    args = (dept, run_id, faculty_raw, sections, static_lookup, ga_params, sizes,
            prep["groups"], prep["errors"], prep["warnings"], rooms)
    def job(*a):
        with _settings_cfg.run_settings(**(run_settings or {})):
            run_scheduling_job(*a)
        if on_finish:
            try:
                on_finish(dept, run_id)
            except Exception:
                import traceback
                traceback.print_exc()

    if wait:
        job(*args)
    else:
        threading.Thread(target=job, args=args, daemon=True).start()

    return {"status": "started", "run_id": run_id, "dept": dept,
            "sections": len(sections), "groups": len(prep["groups"])}