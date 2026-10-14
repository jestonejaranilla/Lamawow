"""
ATLAS PSU - Part 2 tests: CP-SAT output alone (no GA), constraints, fallback.
Run from the project root:  python -m pytest tests/ -q
"""
import copy
import math
import time

import pytest

import config.settings as cfg
from helpers import default_faculty, make_faculty
from services import schedule_service as ss
from solver import cp_sat_solver as cps
from solver.constraints import (
    faculty_qualifies, is_open_assignment, validate_schedule, lab_split_plan,
)

SEM1, SEM2 = "1st Semester", "2nd Semester"
SIZES = cfg.DEFAULT_CLASS_SIZES


def run(sem, faculty, class_sizes=None, **kw):
    sizes = class_sizes or SIZES
    prep = ss.prepare_scheduling_input([], sem, sizes)
    lookup = ss.build_static_lookup([])
    t0 = time.time()
    rows, metrics = cps.solve(prep["sections"], faculty, lookup, **kw)
    return rows, metrics, prep, lookup, time.time() - t0, sizes


def check(rows, faculty, lookup, prep, sizes):
    return validate_schedule(rows, faculty, lookup, list(cfg.LABORATORY_ROOMS), sizes,
                             prep["sections"])


@pytest.fixture(scope="module", params=[SEM1, SEM2])
def solved(request):
    fac = default_faculty()
    rows, metrics, prep, lookup, secs, sizes = run(request.param, fac)
    return request.param, fac, rows, metrics, prep, lookup, secs, sizes


# ── The Part 2 checklist, both semesters, CP-SAT output alone ─────────────────

def test_full_coverage(solved):
    sem, fac, rows, metrics, prep, *_ = solved
    assert metrics["uncovered_groups"] == {}
    assert all(r["faculty"] for r in rows)
    covered = {r["group_id"] for r in rows}
    assert covered == {g["group_id"] for g in prep["groups"]}


def test_validate_schedule_is_clean(solved):
    sem, fac, rows, metrics, prep, lookup, secs, sizes = solved
    assert check(rows, fac, lookup, prep, sizes) == []
    assert metrics["violations"] == []


def test_one_professor_per_group(solved):
    rows = solved[2]
    profs = {}
    for r in rows:
        profs.setdefault(r["group_id"], set()).add(r["faculty"])
    assert all(len(p) == 1 for p in profs.values()), {g: p for g, p in profs.items() if len(p) > 1}


def test_no_block_has_two_meetings_in_one_slot(solved):
    rows = solved[2]
    seen = set()
    for r in rows:
        if r["class_type"] == "NON_CLASSROOM":
            continue
        key = (r["section"], r["slot"])
        assert key not in seen, key
        seen.add(key)


def test_lecture_and_lab_of_a_course_never_share_a_slot(solved):
    """P2: Introduction to Computing LECTURE and LAB both Mon 07:00-09:00."""
    rows = solved[2]
    slots = {}
    for r in rows:
        if r["class_type"] != "NON_CLASSROOM":
            slots.setdefault((r["group_id"], r["slot"]), 0)
            slots[(r["group_id"], r["slot"])] += 1
    assert max(slots.values()) == 1


def test_lab_groups_after_splitting(solved):
    sem, rows = solved[0], solved[2]
    labs = [r for r in rows if r["class_type"] == "LAB"]
    assert len(labs) == (40 if sem == SEM1 else 28)
    split = [r for r in labs if r["lab_group"]]
    assert len(split) == (8 if sem == SEM1 else 8)            # 2 courses x 2 blocks x 2
    assert {r["lab_group"] for r in split} <= {"IT1B1-L1", "IT1B1-L2", "IT1B2-L1", "IT1B2-L2"}
    assert {r["student_count"] for r in split} == {27}         # ceil(54 / 2)
    # a split lab keeps one professor and uses different slots
    by_group = {}
    for r in split:
        by_group.setdefault(r["group_id"], []).append(r)
    for rs in by_group.values():
        assert len({r["faculty"] for r in rs}) == 1
        assert len({r["slot"] for r in rs}) == len(rs)


def test_rooms_fit_and_are_not_shared(solved):
    rows = solved[2]
    seen = set()
    for r in rows:
        if r["class_type"] == "NON_CLASSROOM":
            continue
        assert r["student_count"] <= cfg.ROOM_CAPACITY[r["room"]]["max"], r
        assert (r["class_type"] == "LAB") == (r["room"] in cfg.LABORATORY_ROOMS), r
        assert (r["room"], r["slot"]) not in seen
        seen.add((r["room"], r["slot"]))


def test_load_cap_and_overload_report(solved, capsys):
    sem, fac, rows, metrics, *_ = solved
    loads = {f["name"]: 0 for f in fac}
    for r in rows:
        loads[r["faculty"]] += 2
    assert max(loads.values()) <= 30
    over24 = [n for n, u in loads.items() if u > 24]
    assert metrics["faculty_over_max"] == len(over24)
    print(f"\n[{sem}] professors above 24 units: {len(over24)}  max load: {max(loads.values())}")


def test_runs_under_45_seconds(solved):
    assert solved[6] < 45


def test_time_limit_is_clamped(monkeypatch):
    monkeypatch.setattr(cfg, "CP_SAT_TIME_LIMIT_SECONDS", 600.0)
    assert cps._time_limit() < 45


# ── Infeasible input: explicit coverage errors, never a silent partial schedule ─

def test_course_nobody_can_teach_is_reported_not_dropped():
    fac = default_faculty()
    for f in fac:                                  # nobody holds "Core Theory" any more
        f["specialization"] = [t for t in f["specialization"] if t != "Core Theory"]
    rows, metrics, prep, lookup, *_ = run(SEM2, fac)
    assert metrics["uncovered_groups"] == {
        f"IT3B{b}|IT 13": "no qualified faculty" for b in (1, 2, 3)}
    # the group stays visible as unassigned rows, nothing else is affected
    it13 = [r for r in rows if r["course_code"] == "IT 13"]
    assert len(it13) == 6 and all(r["faculty"] == "" and r["room"] == "Unassigned" for r in it13)
    # the other staffable groups are still fully valid
    assert validate_schedule(rows, fac, lookup, list(cfg.LABORATORY_ROOMS), SIZES) == []


def test_strict_mode_returns_no_schedule_when_anything_is_uncovered():
    fac = default_faculty(extra_tags=False)
    rows, metrics, *_ = run(SEM2, fac, strict=True)
    assert rows == [] and metrics["uncovered_groups"]


def test_service_turns_solver_reasons_into_coverage_errors():
    fac = default_faculty(extra_tags=False)
    prep = ss.prepare_scheduling_input([], SEM2, SIZES)
    lookup = ss.build_static_lookup([])
    rows, metrics = cps.solve(prep["sections"], fac, lookup)
    cov, errs = ss.compute_coverage(prep["groups"], prep["sections"], rows, fac, lookup,
                                    reasons=metrics["uncovered_groups"])
    assert cov["total"] == 40 and cov["assigned"] < 40
    assert {(e["block"], e["course"], e["reason"]) for e in errs} >= {
        ("IT3B1", "IT 13", "no qualified faculty")}


def test_no_room_large_enough_is_reported():
    sizes = copy.deepcopy(SIZES)
    sizes["IT1B1"]["size"] = 80                    # bigger than every lecture room
    rows, metrics, *_ = run(SEM1, default_faculty(), class_sizes=sizes)
    reasons = {gid: r for gid, r in metrics["uncovered_groups"].items() if gid.startswith("IT1B1|")}
    assert reasons and all("no lecture room fits 80" in r for r in reasons.values())


def test_load_cap_is_a_hard_limit():
    fac = [make_faculty("Solo", ["Programming", "Core Theory", "Research & Capstone"],
                        absolute_max=8)]
    rows, metrics, *_ = run(SEM1, fac)
    load = sum(2 for r in rows if r["faculty"])
    assert load <= 8
    assert metrics["uncovered_groups"]             # the rest is reported, not dropped
    assert all("load cap" in r or "qualified" in r or "conflict" in r
               for r in metrics["uncovered_groups"].values())


# ── P5: qualification ─────────────────────────────────────────────────────────

def test_it_electives_are_open_to_any_faculty():
    lookup = ss.build_static_lookup([])
    nobody = make_faculty("X", ["Mathematics"])
    for title in ("IT Elective 1", "IT Elective 2", "IT Elective 3", "IT Elective 4"):
        assert is_open_assignment(title, lookup)
        assert faculty_qualifies(nobody, title, lookup)


def test_mixed_elective_tag_lists_are_not_open():
    lookup = ss.build_static_lookup([])
    nobody = make_faculty("X", ["Mathematics"])
    for title in ("Introduction to Computing", "Capstone Project and Research 1 (Proposal Writing)",
                  "Practicum (486 hours)", "Social and Professional Issues"):
        assert not is_open_assignment(title, lookup)
        assert not faculty_qualifies(nobody, title, lookup)
    assert faculty_qualifies(make_faculty("Y", ["Core Theory"]), "Introduction to Computing", lookup)
    assert not faculty_qualifies(nobody, "Computer Programming 1", lookup)


# ── validate_schedule catches each new rule ───────────────────────────────────

@pytest.fixture(scope="module")
def good():
    fac = default_faculty()
    rows, metrics, prep, lookup, *_ = run(SEM1, fac)
    return fac, rows, prep, lookup


def _v(good, rows, sections=True):
    fac, _, prep, lookup = good
    return validate_schedule(rows, fac, lookup, list(cfg.LABORATORY_ROOMS), SIZES,
                             prep["sections"] if sections else None)


def test_validator_flags_two_professors_in_a_group(good):
    rows = copy.deepcopy(good[1])
    victim = next(r for r in rows if r["class_type"] == "LECTURE")
    other = next(f["name"] for f in good[0] if f["name"] != victim["faculty"])
    victim["faculty"] = other
    assert any(v.startswith("GROUP_MULTIPLE_PROFESSORS") for v in _v(good, rows))


def test_validator_flags_block_overlap(good):
    rows = copy.deepcopy(good[1])
    a, b = [r for r in rows if r["section"] == "IT3B1" and r["class_type"] != "NON_CLASSROOM"][:2]
    b["slot"] = a["slot"]
    assert any(v.startswith("BLOCK_OVERLAP") for v in _v(good, rows))


def test_validator_flags_lab_group_sizes(good):
    rows = copy.deepcopy(good[1])
    lab = next(r for r in rows if r["lab_group"])
    lab["student_count"] = 54
    out = _v(good, rows)
    assert any(v.startswith("LAB_GROUP_SIZE") for v in out)
    assert any(v.startswith("CAPACITY_EXCEEDED") for v in out)


def test_validator_flags_missing_lab_split(good):
    rows = [r for r in copy.deepcopy(good[1]) if r["lab_group"] != "IT1B1-L2"]
    assert any(v.startswith("LAB_SPLIT_COUNT") for v in _v(good, rows))


def test_validator_flags_uncovered_group_only_when_sections_given(good):
    rows = [r for r in copy.deepcopy(good[1]) if r["group_id"] != "IT3B1|IT 8"]
    assert any(v.startswith("UNCOVERED: IT3B1|IT 8") for v in _v(good, rows))
    assert not any(v.startswith("UNCOVERED") for v in _v(good, rows, sections=False))


def test_validator_flags_room_conflict_and_lecture_in_lab_room(good):
    rows = copy.deepcopy(good[1])
    lec = next(r for r in rows if r["class_type"] == "LECTURE")
    lec["room"] = "MTC1"
    assert any(v.startswith("ROOM_INCOMPATIBLE") for v in _v(good, rows))


def test_lab_split_plan():
    assert lab_split_plan(54, 45) == (2, 27)
    assert lab_split_plan(45, 45) == (1, 45)
    assert lab_split_plan(100, 45) == (3, 34)


# ── Fallback solver obeys the same hard rules ────────────────────────────────

@pytest.mark.parametrize("sem", [SEM1, SEM2])
def test_greedy_fallback_has_no_violations(sem, monkeypatch):
    monkeypatch.setattr(cps, "_solve_with_ortools", lambda *a, **k: None)
    fac = default_faculty()
    rows, metrics, prep, lookup, secs, sizes = run(sem, fac)
    assert metrics["solver_used"] == "cp_backtracking"
    # whatever it covered is fully valid; whatever it could not is reported
    assert validate_schedule(rows, fac, lookup, list(cfg.LABORATORY_ROOMS), sizes) == []
    uncovered_rows = {r["group_id"] for r in rows if not r["faculty"]}
    assert uncovered_rows == set(metrics["uncovered_groups"])
    print(f"\n[greedy {sem}] uncovered groups: {len(metrics['uncovered_groups'])}")