"""
ATLAS PSU - Part 1 tests: curriculum file, groups, meeting expansion, coverage.
Run from the project root:  python -m pytest tests/ -q
"""
import copy
import time

import pytest

import config.settings as cfg
from config.curriculum import load_curriculum, is_in_scope
from services import schedule_service as ss

SEM1, SEM2 = "1st Semester", "2nd Semester"
EXCLUDED_TITLES = {"Mathematics for Data Science", "Fundamentals of Electronics"}
EXCLUDED_PREFIXES = ("GE", "PATHFit", "NSTP")


def meetings_for(sem, class_sizes=None):
    groups, errors = ss.build_groups(sem, class_sizes or cfg.DEFAULT_CLASS_SIZES)
    assert errors == []
    rows = [m for g in groups for m in ss.group_meetings(g)]
    return groups, rows


def count(rows, kind):
    return sum(1 for r in rows if r["class_type"] == kind)


# ── Counts from the brief ─────────────────────────────────────────────────────

def test_semester_1_counts():
    groups, rows = meetings_for(SEM1)
    assert len(groups) == 42
    assert count(rows, "NON_CLASSROOM") == 3          # IT 20 x 3 blocks
    assert {g["course_code"] for g in groups if not g["scheduled"]} == {"IT 20"}
    assert count(rows, "LECTURE") == 39
    assert count(rows, "LAB") == 36


def test_semester_2_counts():
    groups, rows = meetings_for(SEM2)
    assert len(groups) == 40
    assert count(rows, "NON_CLASSROOM") == 3          # IT 22 x 3 blocks
    assert {g["course_code"] for g in groups if not g["scheduled"]} == {"IT 22"}
    assert count(rows, "LECTURE") == 44
    assert count(rows, "LAB") == 24


# ── Scope and row quality ─────────────────────────────────────────────────────

@pytest.mark.parametrize("sem", [SEM1, SEM2])
def test_no_excluded_course_appears(sem):
    groups, rows = meetings_for(sem)
    for r in rows:
        assert r["name"] not in EXCLUDED_TITLES
        assert not r["course_code"].startswith(EXCLUDED_PREFIXES)
        assert r["course_code"].startswith(("CC", "IT"))


def test_curriculum_file_is_in_scope_only_and_uses_prospectus_titles():
    cur = load_curriculum("IT")
    assert all(is_in_scope(c) for c in cur["courses"])
    titles = {c["title"] for c in cur["courses"]}
    assert "Mathematics for Data Science" not in titles
    assert "Social and Professional Issues" in titles
    assert "Integrative Programming and Technologies 1" in titles
    assert "Integrative Programming Technologies 1" not in titles
    assert len(cur["courses"]) == 32
    assert {c["code"] for c in cur["courses"] if not c["scheduled"]} == {"IT 20", "IT 22"}
    # specialization map comes from the file
    assert cfg.SPECIALIZATION_MAP["Social and Professional Issues"] == ["Core Theory"]
    assert "Integrative Programming Technologies 1" not in cfg.SPECIALIZATION_MAP


@pytest.mark.parametrize("sem", [SEM1, SEM2])
def test_every_row_has_section_and_student_count(sem):
    _, rows = meetings_for(sem)
    for r in rows:
        assert r["section"], r
        assert r["group_id"] and r["course_code"] and r["meeting_id"]
        if r["class_type"] != "NON_CLASSROOM":
            assert r["student_count"] > 0, r


def test_example_third_year_block_one_sem_one():
    groups, _ = meetings_for(SEM1)
    codes = sorted(g["course_code"] for g in groups if g["section"] == "IT3B1")
    assert codes == sorted(["IT 8", "IT 9", "IT 10", "IT 11", "IT 12", "IT E3"])


def test_blocks_come_from_class_sizes():
    sizes = copy.deepcopy(cfg.DEFAULT_CLASS_SIZES)
    sizes["IT1B3"] = {"year": "1st Year", "block": "B3", "size": 40}
    groups, _ = ss.build_groups(SEM1, sizes)
    assert len(groups) == 42 + 2                      # CC 1, CC 2 for the new block
    assert {g["student_count"] for g in groups if g["section"] == "IT1B3"} == {40}


def test_lab_meetings_are_two_hours():
    _, rows = meetings_for(SEM1)
    assert {r["hours"] for r in rows} == {2}


# ── Request validation ────────────────────────────────────────────────────────

def test_legacy_request_without_group_ids_is_built_from_curriculum():
    prep = ss.prepare_scheduling_input([{"name": "Introduction to Computing"}], SEM1,
                                       cfg.DEFAULT_CLASS_SIZES)
    assert len(prep["groups"]) == 42 and len(prep["sections"]) == 78
    assert prep["warnings"]


def test_missing_and_unknown_groups_are_reported_not_silent():
    groups, rows = meetings_for(SEM1)
    payload = [dict(r) for r in rows if r["group_id"] != "IT3B1|IT 8"]   # drop one group
    payload.append({"name": "Gen Ed", "class_type": "LECTURE", "group_id": "IT1B1|GE 1"})
    prep = ss.prepare_scheduling_input(payload, SEM1, cfg.DEFAULT_CLASS_SIZES)
    assert len(prep["groups"]) == 42
    assert len(prep["sections"]) == 78                                 # filled back in
    assert any("IT3B1|IT 8" in w for w in prep["warnings"])
    assert any("IT1B1|GE 1" in w for w in prep["warnings"])
    assert all(s["group_id"] != "IT1B1|GE 1" for s in prep["sections"])


def test_full_payload_passes_without_warnings():
    _, rows = meetings_for(SEM1)
    prep = ss.prepare_scheduling_input(rows, SEM1, cfg.DEFAULT_CLASS_SIZES)
    assert prep["warnings"] == [] and len(prep["sections"]) == 78


def test_block_without_class_size_is_a_coverage_error():
    sizes = {k: v for k, v in cfg.DEFAULT_CLASS_SIZES.items() if not k.startswith("IT4")}
    groups, errors = ss.build_groups(SEM1, sizes)
    assert {e["course"] for e in errors} == {"IT 18", "IT 19", "IT E4", "IT 20"}
    assert all("no blocks" in e["reason"] for e in errors)


# ── Engine end to end ─────────────────────────────────────────────────────────

def faculty(extra=None):
    specs = [["Networks & Security"], ["Systems"], ["Programming"], ["Mathematics"],
             ["Networks & Security"], ["Web & App Dev"], ["Systems"], ["Data Management"],
             ["Applied Computing"], ["Data Management"]] + (extra or [])
    return [{"name": f"Prof {i}", "specialization": s, "max_units": 24,
             "absolute_max_units": 30, "availability": ["Mon", "Tue", "Wed", "Thu"]}
            for i, s in enumerate(specs)]


def run_job(sem, fac):
    prep = ss.prepare_scheduling_input([], sem, cfg.DEFAULT_CLASS_SIZES)
    lookup = ss.build_static_lookup([])
    old = cfg.CP_SAT_TIME_LIMIT_SECONDS
    cfg.CP_SAT_TIME_LIMIT_SECONDS = 20
    try:
        ss.run_scheduling_job(fac, prep["sections"], lookup,
                              {"generations": 3, "population": 4},
                              cfg.DEFAULT_CLASS_SIZES, prep["groups"], prep["errors"],
                              prep["warnings"])
    finally:
        cfg.CP_SAT_TIME_LIMIT_SECONDS = old
    return ss.get_progress(), prep


def test_engine_sem1_full_coverage_and_non_classroom_rows():
    p, prep = run_job(SEM1, faculty())
    assert p["phase"] == "done"
    assert p["coverage"] == {"assigned": 42, "total": 42}
    assert p["coverage_errors"] == []
    assert len(p["result"]) == 78
    non = [a for a in p["result"] if a["class_type"] == "NON_CLASSROOM"]
    assert len(non) == 3
    for a in non:
        assert a["slot"] is None and a["room"] == "N/A" and a["faculty"]
    assert all(a["section"] and a["group_id"] for a in p["result"])
    # NON_CLASSROOM rows count 2 load units
    util = {u["faculty"]: u["assigned_units"] for u in p["analytics"]["faculty_utilization"]}
    assert sum(util.values()) == 2 * 78


def test_engine_reports_uncoverable_group_with_reason():
    # default faculty has nobody tagged "Core Theory" -> IT 13 (3 blocks) cannot be staffed
    p, _ = run_job(SEM2, faculty())
    assert p["coverage"]["total"] == 40
    assert p["coverage"]["assigned"] == 37
    errs = {(e["block"], e["course"]): e["reason"] for e in p["coverage_errors"]}
    assert errs == {("IT3B1", "IT 13"): "no qualified faculty",
                    ("IT3B2", "IT 13"): "no qualified faculty",
                    ("IT3B3", "IT 13"): "no qualified faculty"}


def test_engine_sem2_full_coverage_when_core_theory_faculty_exists():
    p, _ = run_job(SEM2, faculty(extra=[["Core Theory"]]))
    assert p["coverage"] == {"assigned": 40, "total": 40}
    assert p["coverage_errors"] == []


# ── HTTP layer ────────────────────────────────────────────────────────────────

def test_progress_and_curriculum_endpoints():
    import app as app_module
    client = app_module.app.test_client()
    body = client.get("/progress").get_json()
    assert "coverage" in body and "coverage_errors" in body
    cur = client.get("/curriculum/IT").get_json()
    assert cur["dept"] == "IT" and len(cur["courses"]) == 32
    assert client.get("/curriculum/XX").status_code == 404


def test_run_ga_endpoint_accepts_old_payload_and_returns_group_count():
    import app as app_module
    client = app_module.app.test_client()
    payload = {"faculty": faculty(), "subjects": [{"name": "Introduction to Computing"}],
               "active_semester": SEM1, "generations": 2, "population": 4,
               "cp_sat_time_limit": 15}
    r = client.post("/run-ga", json=payload).get_json()
    assert r["status"] == "started" and r["groups"] == 42 and r["sections"] == 78
    for _ in range(300):
        p = client.get("/progress").get_json()
        if not p["running"] and p["phase"] == "done":
            break
        time.sleep(0.2)
    assert p["coverage"] == {"assigned": 42, "total": 42}