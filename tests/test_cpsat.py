"""
ATLAS PSU - CP-SAT output alone (no GA), all 5 departments x 2 semesters.
Run from the project root:  python -m pytest tests/ -q
"""
import copy
import time

import pytest

import config.settings as cfg
from config import curriculum as cur
from conftest import DEPTS, SEMS, SEM1, SEM2, dept_faculty, make_faculty, legacy_subjects
from services import schedule_service as ss
from solver import cp_sat_solver as cps
from solver.constraints import validate_schedule

cfg.CP_SAT_TIME_LIMIT_SECONDS = 15.0      # tests only; the solver never runs past 40 s whatever is asked

# lab groups after splitting (default data)
LAB_GROUPS = {("IT", 1): 34, ("IT", 2): 30, ("CS", 1): 32, ("CS", 2): 27, ("MB", 1): 47, ("MB", 2): 28,
              ("ES", 1): 26, ("ES", 2): 19, ("MedB", 1): 31, ("MedB", 2): 24}
SCIENCE = {"MB", "ES", "MedB"}
pytestmark = pytest.mark.slow
IT_CS_ROOMS = set(cur.rooms_for("IT").all_rooms)
SCI_ROOMS = set(cur.rooms_for("MB").all_rooms)


def run(dept, sem, faculty, **kw):
    ss.reset_state()
    sizes = ss.get_class_sizes(dept)
    prep = ss.prepare_scheduling_input(dept, [], sem, sizes)
    lookup = ss.build_static_lookup(dept)
    rooms = cur.rooms_for(dept)
    t0 = time.time()
    rows, metrics = cps.solve(prep["sections"], faculty, lookup, rooms=rooms, **kw)
    return rows, metrics, prep, lookup, rooms, sizes, time.time() - t0


@pytest.fixture(scope="module", params=[(d, s) for d in DEPTS for s in SEMS],
                ids=[f"{d}-{s[:3]}" for d in DEPTS for s in SEMS])
def solved(request):
    dept, sem = request.param
    fac = dept_faculty(dept)
    return (dept, sem, fac) + run(dept, sem, fac)


def test_full_coverage(solved):
    dept, sem, fac, rows, metrics, prep, *_ = solved
    assert metrics["uncovered_groups"] == {}
    assert all(r["faculty"] for r in rows)
    assert {r["group_id"] for r in rows} == {g["group_id"] for g in prep["groups"]}


def test_validate_schedule_is_clean(solved):
    dept, sem, fac, rows, metrics, prep, lookup, rooms, sizes, secs = solved
    assert validate_schedule(rows, fac, lookup, rooms, sizes, prep["sections"]) == []
    assert metrics["violations"] == []


def test_one_professor_per_group(solved):
    rows = solved[3]
    profs = {}
    for r in rows:
        profs.setdefault(r["group_id"], set()).add(r["faculty"])
    assert all(len(p) == 1 for p in profs.values())


def test_no_block_has_two_meetings_in_one_slot(solved):
    """Also P2: a course's lecture and lab never share a slot."""
    seen = set()
    for r in solved[3]:
        if r["class_type"] == "NON_CLASSROOM" or not r["faculty"]:     # no slot: reported, not scheduled
            continue
        key = (r["section"], r["slot"])
        assert key not in seen, key
        seen.add(key)


def test_lab_groups_after_splitting(solved):
    dept, sem, rows = solved[0], solved[1], solved[3]
    assert sum(1 for r in rows if r["class_type"] == "LAB") == LAB_GROUPS[(dept, SEMS.index(sem) + 1)]
    max_lab = max(solved[7].max_of(r) for r in solved[7].lab_rooms)
    for r in rows:
        if r["class_type"] == "LAB":
            assert r["student_count"] <= max_lab


def test_no_professor_above_30_and_report_those_above_24(solved):
    dept, sem, fac, rows, metrics, *_ = solved
    loads = {f["name"]: 0 for f in fac}
    for r in rows:
        if not r["faculty"]:
            continue
        loads[r["faculty"]] += cfg.NON_CLASSROOM_UNITS if r["class_type"] == "NON_CLASSROOM" else cfg.UNITS_PER_ASSIGNMENT
    assert max(loads.values()) <= 30
    over24 = [n for n, u in loads.items() if u > 24]
    print(f"\n[{dept} {sem}] professors above 24 units: {len(over24)}  max load: {max(loads.values())}")
    assert metrics["faculty_over_max"] == len(over24)


def test_rooms_belong_to_the_department_and_labs_use_lab_rooms(solved):
    dept, rows, rooms = solved[0], solved[3], solved[7]
    allowed = SCI_ROOMS if dept in SCIENCE else IT_CS_ROOMS
    for r in rows:
        if not r["faculty"]:                                           # reported uncovered group
            assert r["room"] == "Unassigned" and r["slot"] is None
            continue
        if r["class_type"] == "NON_CLASSROOM":
            assert r["room"] == "N/A" and r["slot"] is None
            continue
        assert r["room"] in allowed
        assert rooms.max_of(r["room"]) >= r["student_count"]
        if r["class_type"] == "LAB":
            assert r["room"] in rooms.lab_rooms
        elif not rooms.lab_also_lecture:
            assert r["room"] not in rooms.lab_rooms
    seen = set()
    for r in rows:
        if r["faculty"] and r["class_type"] != "NON_CLASSROOM":
            assert (r["room"], r["slot"]) not in seen
            seen.add((r["room"], r["slot"]))


def test_run_time_under_45_seconds(solved):
    assert solved[-1] < 45


# ── Infeasible input: explicit errors, never a silent partial schedule ────────

CORE_THEORY_GROUPS = {f"IT1B{b}|{c}" for b in (1, 2) for c in ("CC 1", "GE-STS")}


def _without(fac, *tags):
    for f in fac:
        f["specialization"] = [t for t in f["specialization"] if t not in tags] or [f["specialization"][0]]
    return fac


def test_a_course_nobody_can_teach_is_reported_not_dropped():
    # CC 1 is tagged ["Core Theory", "Elective"], so it needs one of the two tags
    fac = _without(dept_faculty("IT"), "Core Theory", "Elective")
    rows, metrics, prep, lookup, rooms, sizes, secs = run("IT", SEM1, fac)
    errs = metrics["uncovered_groups"]
    assert set(errs) == CORE_THEORY_GROUPS and set(errs.values()) == {"no qualified faculty"}
    unassigned = [r for r in rows if not r["faculty"]]
    assert {r["group_id"] for r in unassigned} == CORE_THEORY_GROUPS
    assert all(r["room"] == "Unassigned" for r in unassigned)
    assert validate_schedule(rows, fac, lookup, rooms, sizes) == []        # the rest is valid
    assert any(v.startswith("UNCOVERED")
               for v in validate_schedule(rows, fac, lookup, rooms, sizes, prep["sections"]))


@pytest.mark.parametrize("dept,tag,expect", [
    ("CS", "Networks & Security", {"CS3B1|CS 13", "CS3B2|CS 13", "CS3B1|CS 15", "CS3B2|CS 15"}),
    ("MB", "Computing", {"MB1B1|GE-Elect IT", "MB1B2|GE-Elect IT"}),
    ("ES", "Physics", {"ES2B1|ES Phys 1"}),
    ("MedB", "Computing", {"MedB2B1|GE-Elect IT", "MedB2B2|GE-Elect IT"}),
])
def test_every_department_reports_a_group_nobody_can_teach(dept, tag, expect):
    # pick the semester that holds the expected groups
    sems = {1: SEM1, 2: SEM2}
    codes = {g.split("|")[1] for g in expect}
    sem = sems[next(c["semester"] for c in cur.courses_of(dept) if c["code"] in codes)]
    fac = _without(dept_faculty(dept), tag)
    rows, metrics, *_ = run(dept, sem, fac)
    assert set(metrics["uncovered_groups"]) == expect
    assert set(metrics["uncovered_groups"].values()) == {"no qualified faculty"}


def test_strict_mode_returns_no_assignments_when_a_group_is_uncovered():
    rows, metrics, *_ = run("IT", SEM1, _without(dept_faculty("IT"), "Core Theory", "Elective"), strict=True)
    assert rows == [] and metrics["uncovered_groups"]


# ── Hard-rule unit checks ─────────────────────────────────────────────────────

def test_validator_catches_each_hard_rule():
    dept, sem = "ES", SEM2
    fac = dept_faculty(dept)
    rows, metrics, prep, lookup, rooms, sizes, _ = run(dept, sem, fac)
    base = [r for r in rows if r["class_type"] != "NON_CLASSROOM"]

    def kinds(mod):
        bad = copy.deepcopy(rows)
        mod(bad)
        return " ".join(validate_schedule(bad, fac, lookup, rooms, sizes, prep["sections"]))

    lab = next(i for i, r in enumerate(rows) if r["class_type"] == "LAB")
    lec = next(i for i, r in enumerate(rows) if r["class_type"] == "LECTURE")
    assert "ROOM_NOT_IN_DEPARTMENT" in kinds(lambda b: b[lec].update(room="CL1"))
    assert "ROOM_INCOMPATIBLE" in kinds(lambda b: b[lab].update(room="CSLR 1"))
    assert "CAPACITY_EXCEEDED" in kinds(lambda b: b[lec].update(student_count=70))
    other = next(r["faculty"] for r in rows if r["faculty"] != rows[lec]["faculty"])
    assert "GROUP_MULTIPLE_PROFESSORS" in kinds(lambda b: b[lec].update(faculty=other))
    assert "UNCOVERED" in kinds(lambda b: b[lec].update(faculty="", room="Unassigned", slot=None))
    assert "BLOCK_OVERLAP" in kinds(lambda b: b[lec].update(slot=rows[lab]["slot"], section=rows[lab]["section"]))


def test_greedy_fallback_obeys_the_same_hard_rules(monkeypatch):
    monkeypatch.setattr(cps, "_solve_with_ortools", lambda *a, **k: None)
    for dept in ("CS", "MedB"):
        fac = dept_faculty(dept)
        rows, metrics, prep, lookup, rooms, sizes, secs = run(dept, SEM2, fac)
        assert metrics["solver_used"] == "cp_backtracking"
        assert validate_schedule(rows, fac, lookup, rooms, sizes) == []        # whatever it placed is valid
        assert metrics["uncovered_groups"] or {r["group_id"] for r in rows} == {g["group_id"] for g in prep["groups"]}


# ── Rooms belong to the department; lectures prefer lecture rooms ─────────────

@pytest.mark.parametrize("dept,bad_lecture,bad_lab", [
    ("IT", ["CSLR 1", "GE Bldg 1", "Physics Room 1"], ["Physics Room 1", "CSLR 1"]),
    ("CS", ["CSLR 1", "GE Bldg 1", "Physics Room 1"], ["Physics Room 1", "GE Bldg 1"]),
    ("MB", ["CL1", "IT Room 1", "GA Bldg 16"], ["MTC1", "IT101", "NIT1"]),
    ("ES", ["CL1", "IT Room 1", "GA Bldg 16"], ["MTC1", "IT101", "NIT1"]),
    ("MedB", ["CL1", "IT Room 1", "GA Bldg 16"], ["MTC1", "IT101", "NIT1"]),
])
def test_validator_fails_a_room_outside_the_departments_pools(dept, bad_lecture, bad_lab):
    sem = SEM1
    fac = dept_faculty(dept)
    rows, metrics, prep, lookup, rooms, sizes, _ = run(dept, sem, fac)
    assert validate_schedule(rows, fac, lookup, rooms, sizes) == []
    lec = next(i for i, r in enumerate(rows) if r["class_type"] == "LECTURE")
    lab = next(i for i, r in enumerate(rows) if r["class_type"] == "LAB")
    for idx, room in [(lec, r) for r in bad_lecture] + [(lab, r) for r in bad_lab]:
        bad = copy.deepcopy(rows)
        bad[idx]["room"] = room
        out = validate_schedule(bad, fac, lookup, rooms, sizes)
        assert any(v.startswith("ROOM_NOT_IN_DEPARTMENT") for v in out), (dept, room, out)


@pytest.mark.parametrize("dept", ["MB", "ES", "MedB"])
def test_science_labs_only_in_physics_rooms_and_a_lab_in_a_lecture_room_fails(dept):
    fac = dept_faculty(dept)
    rows, metrics, prep, lookup, rooms, sizes, _ = run(dept, SEM1, fac)
    physics = {f"Physics Room {i}" for i in range(1, 6)}
    assert {r["room"] for r in rows if r["class_type"] == "LAB"} <= physics
    lab = next(i for i, r in enumerate(rows) if r["class_type"] == "LAB")
    for room in ("CSLR 1", "GE Bldg 1"):
        bad = copy.deepcopy(rows)
        bad[lab]["room"] = room
        assert any(v.startswith("ROOM_INCOMPATIBLE") for v in validate_schedule(bad, fac, lookup, rooms, sizes))


@pytest.mark.parametrize("dept", ["MB", "ES", "MedB"])
@pytest.mark.parametrize("sem", SEMS)
def test_lectures_prefer_cslr_and_ge_rooms_over_physics_rooms(dept, sem):
    """Physics rooms may host a lecture, at a soft penalty: with 20 lecture rooms free they are not needed."""
    rows, *_ = run(dept, sem, dept_faculty(dept))
    in_physics = [r for r in rows if r["class_type"] == "LECTURE" and r["room"].startswith("Physics")]
    assert in_physics == []


def test_physics_rooms_do_host_a_lecture_when_lecture_rooms_are_gone():
    """The pool is allowed (lab_rooms_also_lecture), it is only penalised."""
    ss.reset_state()
    ss.update_rooms("ES", lecture_rooms=["CSLR 1"])
    rooms = ss.get_rooms("ES")
    prep = ss.prepare_scheduling_input("ES", [], SEM2, ss.get_class_sizes("ES"))
    fac = dept_faculty("ES")
    rows, metrics = cps.solve(prep["sections"], fac, ss.build_static_lookup("ES"), rooms=rooms)
    assert any(r["class_type"] == "LECTURE" and r["room"].startswith("Physics") for r in rows)
    assert validate_schedule(rows, fac, ss.get_static_lookup("ES"), rooms, ss.get_class_sizes("ES")) == []