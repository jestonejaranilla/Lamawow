"""
ATLAS PSU - full pipeline (CP-SAT + GA + validation), 5 departments x 2 semesters.
Run from the project root:  python -m pytest tests/ -q
"""
import functools
import math
import time

import pytest

import config.settings as cfg
from config import curriculum as cur
from conftest import DEPTS, SEMS, SEM1, SEM2, dept_faculty
from services import schedule_service as ss
from solver import cp_sat_solver as cps
from solver import ga_optimizer as ga
from solver.constraints import validate_schedule, NON_CLASSROOM, max_room_capacity
from config.rooms import use_rooms

cfg.CP_SAT_TIME_LIMIT_SECONDS = 15.0       # tests only; the solver never runs past 40 s
SCIENCE = {"MB", "ES", "MedB"}
pytestmark = pytest.mark.slow
IT_CS_ROOMS = set(cur.rooms_for("IT").all_rooms)
SCI_ROOMS = set(cur.rooms_for("MB").all_rooms)
PHYSICS = {f"Physics Room {i}" for i in range(1, 6)}
PAIRS = [(d, s) for d in DEPTS for s in SEMS]
IDS = [f"{d}-{s[:3]}" for d, s in PAIRS]


@functools.lru_cache(maxsize=None)
def pipeline(dept, sem):
    """CP-SAT -> GA -> validation for one department and semester, exactly as the service runs them."""
    ss.reset_state()
    fac = dept_faculty(dept)
    sizes = ss.get_class_sizes(dept)
    prep = ss.prepare_scheduling_input(dept, [], sem, sizes)
    lookup = ss.build_static_lookup(dept)
    rooms = cur.rooms_for(dept)
    t0 = time.time()
    cp_rows, metrics = cps.solve(prep["sections"], fac, lookup, rooms=rooms)
    ga_rows, ga_metrics = ga.optimize(cp_rows, fac, lookup, {}, generations=8, population_size=6,
                                      class_sizes=sizes, rooms=rooms)
    secs = time.time() - t0
    kinds = [s["class_type"] for s in prep["sections"]]
    with use_rooms(rooms):
        classroom = [s for s in prep["sections"] if s["class_type"] != NON_CLASSROOM]
        meetings = cps._build_meetings(classroom, max_room_capacity(rooms.lab_rooms))
    loads = {f["name"]: 0 for f in fac}
    for r in ga_rows:
        if r["faculty"]:
            loads[r["faculty"]] += cfg.NON_CLASSROOM_UNITS if r["class_type"] == NON_CLASSROOM else cfg.UNITS_PER_ASSIGNMENT
    return dict(dept=dept, sem=sem, fac=fac, sizes=sizes, prep=prep, lookup=lookup, rooms=rooms,
                cp=cp_rows, ga=ga_rows, metrics=metrics, ga_metrics=ga_metrics, secs=secs, loads=loads,
                block_courses=len(prep["groups"]), meetings=kinds.count("LECTURE") + kinds.count("LAB"),
                lab_groups=sum(1 for m in meetings if m["kind"] == "LAB"),
                uncovered=metrics["uncovered_groups"])


@pytest.fixture(params=PAIRS, ids=IDS)
def p(request):
    return pipeline(*request.param)


# 3. regression: counts table from the Part 2 UPDATE
EXPECTED = {("IT", 1): (30, 31, 26, 34), ("IT", 2): (36, 45, 24, 30),
            ("CS", 1): (38, 49, 26, 32), ("CS", 2): (34, 40, 24, 27),
            ("MB", 1): (42, 61, 47, 47), ("MB", 2): (32, 47, 28, 28),
            ("ES", 1): (27, 44, 26, 26), ("ES", 2): (23, 32, 19, 19),
            ("MedB", 1): (29, 45, 31, 31), ("MedB", 2): (20, 31, 24, 24)}


def test_counts_table_still_holds(p):
    kinds = [s["class_type"] for s in p["prep"]["sections"]]
    got = (p["block_courses"], kinds.count("LECTURE"), kinds.count("LAB"), p["lab_groups"])
    assert got == EXPECTED[(p["dept"], SEMS.index(p["sem"]) + 1)]


# 4. pipeline
def test_full_coverage(p):
    assert p["uncovered"] == {}
    assert all(r["faculty"] for r in p["ga"])
    assert {r["group_id"] for r in p["ga"]} == {g["group_id"] for g in p["prep"]["groups"]}


def test_validate_schedule_is_clean_after_ga(p):
    assert validate_schedule(p["ga"], p["fac"], p["lookup"], p["rooms"], p["sizes"], p["prep"]["sections"]) == []


def test_one_professor_per_block_course(p):
    profs = {}
    for r in p["ga"]:
        profs.setdefault(r["group_id"], set()).add(r["faculty"])
    assert all(len(v) == 1 for v in profs.values())


def test_no_block_double_booked(p):
    seen = set()
    for r in p["ga"]:
        if r["class_type"] == NON_CLASSROOM or not r["faculty"]:
            continue
        key = (r["section"], r["slot"])
        assert key not in seen, key
        seen.add(key)


def test_no_professor_above_30_and_print_those_above_24(p):
    assert max(p["loads"].values()) <= 30
    over = [n for n, u in p["loads"].items() if u > 24]
    print(f"\n[{p['dept']} {p['sem']}] professors above 24 units: {len(over)}  max load: {max(p['loads'].values())}")


def test_ga_keeps_every_professor_of_cp_sat(p):
    assert len(p["ga"]) == len(p["cp"])
    for c, g in zip(p["cp"], p["ga"]):
        assert (c["faculty"], c["meeting_id"], c["group_id"], c["lab_group"]) == \
               (g["faculty"], g["meeting_id"], g["group_id"], g["lab_group"])


def test_runtime_under_60_seconds(p):
    assert p["secs"] < 60


# 5. no empty size or section
def test_no_zero_student_count_or_empty_section(p):
    for r in p["ga"]:
        if r["class_type"] == NON_CLASSROOM:
            continue
        assert r["student_count"] > 0 and r["section"], r


# 6. rooms after GA
def test_rooms_after_ga(p):
    dept, rooms = p["dept"], p["rooms"]
    allowed, forbidden = (SCI_ROOMS, IT_CS_ROOMS) if dept in SCIENCE else (IT_CS_ROOMS, SCI_ROOMS)
    seen = set()
    for r in p["ga"]:
        if not r["faculty"] or r["class_type"] == NON_CLASSROOM:
            continue
        assert r["room"] in allowed and r["room"] not in forbidden
        if r["class_type"] == "LAB":
            assert r["room"] in rooms.lab_rooms
            if dept in SCIENCE:
                assert r["room"] in PHYSICS
        key = (r["room"], r["slot"])
        assert key not in seen, key
        seen.add(key)


# GA unit checks
def test_ga_returns_the_cp_sat_schedule_when_no_child_is_valid(monkeypatch):
    q = pipeline("CS", SEM2)
    monkeypatch.setattr(ga, "validate_schedule", lambda *a, **k: ["X"] if len(a[0]) and a[0] is not q["cp"] else [])
    rows, m = ga.optimize(q["cp"], q["fac"], q["lookup"], {}, generations=3, population_size=4,
                          class_sizes=q["sizes"], rooms=q["rooms"])
    assert rows == q["cp"]


def test_ga_rejects_a_child_that_changes_a_professor():
    q = pipeline("CS", SEM2)
    bad = [dict(r) for r in q["cp"]]
    bad[0]["faculty"] = "Somebody Else"
    assert not ga._faculty_unchanged(bad, q["cp"])
    assert ga._faculty_unchanged([dict(r) for r in q["cp"]], q["cp"])


# 8. infeasible input
def test_a_course_nobody_can_teach_is_reported_by_the_service():
    fac = dept_faculty("IT")
    for f in fac:
        f["specialization"] = [t for t in f["specialization"] if t not in ("Core Theory", "Elective")] or ["Systems"]
    ss.reset_state()
    r = ss.start_scheduling("IT", fac, [{"name": "x"}], SEM1, {"generations": 2, "population": 4}, {}, None, wait=True)
    pr = ss.get_progress("IT")
    assert pr["coverage_errors"] and pr["coverage"]["assigned"] < pr["coverage"]["total"]
    assert {e["reason"] for e in pr["coverage_errors"]} == {"no qualified faculty"}


def test_full_coverage_required_returns_errors_and_no_partial_schedule(monkeypatch):
    monkeypatch.setattr(cfg, "REQUIRE_FULL_COVERAGE", True)
    fac = dept_faculty("CS")
    for f in fac:
        f["specialization"] = [t for t in f["specialization"] if t != "Networks & Security"] or ["Systems"]
    ss.reset_state()
    ss.start_scheduling("CS", fac, [{"name": "x"}], "2nd Semester", {"generations": 2, "population": 4}, {}, None,
                        wait=True)
    pr = ss.get_progress("CS")
    assert pr["result"] == [] and pr["coverage_errors"]
    assert {"CS3B1|CS 13", "CS3B2|CS 13"} <= {e["group_id"] for e in pr["coverage_errors"]}


SCIENCE_PAIRS = [(d, s) for d, s in PAIRS if d in SCIENCE]


@pytest.mark.parametrize("dept,sem", SCIENCE_PAIRS, ids=[f"{d}-{s[:3]}" for d, s in SCIENCE_PAIRS])
def test_no_meeting_over_recommended_in_science_departments(dept, sem):
    q = pipeline(dept, sem)
    cap = q["rooms"].capacity
    over = [r for r in q["ga"] if r["class_type"] != NON_CLASSROOM and r["student_count"] > cap[r["room"]]["recommended"]]
    assert over == []


# final table
def test_zz_print_summary_table():
    lines = [f"{'dept':5} {'sem':4} {'block-courses':>13} {'meetings':>8} {'lab grps':>8} {'coverage':>9} "
             f"{'max load':>8} {'runtime':>8}"]
    for d, s in PAIRS:
        q = pipeline(d, s)
        total = q["block_courses"]
        cov = f"{total - len(q['uncovered'])}/{total}"
        lines.append(f"{d:5} {s[:3]:4} {q['block_courses']:>13} {q['meetings']:>8} {q['lab_groups']:>8} {cov:>9} "
                     f"{max(q['loads'].values()):>8} {q['secs']:>7.1f}s")
    print("\n" + "\n".join(lines))
    for d, s in PAIRS:                       # loads per professor and lab splits of every department and semester
        q = pipeline(d, s)
        ld = q["loads"]
        mean = sum(ld.values()) / len(ld)
        print(f"[{d} {s[:3]}] mean load {mean:.1f}, over 24: {sum(v > 24 for v in ld.values())}, "
              f"split lab sub-groups: {q['metrics']['lab_split_groups']}, loads: "
              + ", ".join(f"{n}={v}" for n, v in sorted(ld.items())))