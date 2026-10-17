"""
ATLAS PSU - Part 27B: warm start for the solver.
Run from the project root:  python -m pytest tests/test_part27b.py -q -p no:cacheprovider
"""
from pathlib import Path

import pytest

import config.settings as cfg
from conftest import dept_faculty, make_faculty
from config.curriculum import load_curriculum
from scripts.evaluate import rooms_for
from services import schedule_service as ss
from solver import cp_sat_solver as cps
from solver.constraints import validate_schedule

ROOT = Path(__file__).resolve().parent.parent
SEM1 = "1st Semester"
ALL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _inputs(dept, extra=None):
    fac = dept_faculty(dept) + (extra or [])
    prep = ss.prepare_scheduling_input(dept, [], SEM1, ss.get_class_sizes(dept))
    return prep, fac, ss.build_static_lookup(dept), rooms_for(dept)


def _universal(dept):
    return make_faculty("Universal", load_curriculum(dept)["specializations"], 50, 50, ALL_DAYS)


@pytest.mark.parametrize("warm", [True, False])
def test_cs_first_semester_plus_a_universal_professor_is_fully_covered_on_one_core_in_3_seconds(monkeypatch, warm):
    monkeypatch.setattr(cps, "_search_workers", lambda: 1)
    prep, fac, lookup, rooms = _inputs("CS", [_universal("CS")])
    with cfg.run_settings(seed=1, cp_sat_time_limit=3, warm_start=warm):
        rows, m = cps.solve(prep["sections"], fac, lookup, rooms=rooms)
    assert m["group_count"] == 38 and m["uncovered_groups"] == {}
    assert all(r["faculty"] for r in rows)
    assert validate_schedule(rows, fac, lookup, rooms) == [] and m["violations"] == []


def test_warm_start_hands_a_complete_hint_to_cp_sat_and_off_hands_none(monkeypatch):
    seen = []
    real = cps._solve_with_ortools

    def spy(meetings, groups, faculty_list, static_lookup, progress_cb=None, hint=None):
        seen.append(hint)
        return real(meetings, groups, faculty_list, static_lookup, progress_cb, hint)

    monkeypatch.setattr(cps, "_solve_with_ortools", spy)
    prep, fac, lookup, rooms = _inputs("IT")
    with cfg.run_settings(seed=1, cp_sat_time_limit=2, warm_start=True):
        cps.solve(prep["sections"], fac, lookup, rooms=rooms)
    with cfg.run_settings(seed=1, cp_sat_time_limit=2, warm_start=False):
        cps.solve(prep["sections"], fac, lookup, rooms=rooms)
    assert seen[0] and all("fac" in p and "slots" in p for p in seen[0].values())
    assert seen[1] is None                                              # off: exactly the old call


def test_warm_start_is_off_by_default_because_it_lowered_jain_in_three_departments_and_a_run_can_turn_it_on():
    assert cfg.WARM_START is False and cfg.warm_start() is False
    with cfg.run_settings(warm_start=True):
        assert cfg.warm_start() is True
    assert cfg.warm_start() is False


def test_a_deterministic_run_is_still_reproducible_with_the_warm_start():
    prep, fac, lookup, rooms = _inputs("IT")
    out = []
    for _ in range(2):
        with cfg.run_settings(seed=7, deterministic=True, cp_sat_time_limit=3, warm_start=True):
            rows, m = cps.solve(prep["sections"], fac, lookup, rooms=rooms)
        out.append([(r["group_id"], r["meeting_id"], r["faculty"], r["slot"], r["room"]) for r in rows])
    assert out[0] == out[1]


def test_the_default_run_hands_no_hint_to_cp_sat(monkeypatch):
    seen = []
    real = cps._solve_with_ortools
    monkeypatch.setattr(cps, "_solve_with_ortools", lambda *a, **k: (seen.append(a[5] if len(a) > 5 else k.get("hint")),
                                                                   real(*a, **k))[1])
    prep, fac, lookup, rooms = _inputs("IT")
    with cfg.run_settings(seed=1, cp_sat_time_limit=2):
        cps.solve(prep["sections"], fac, lookup, rooms=rooms)
    assert seen == [None]


def test_readme_documents_warm_start_and_its_default():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "| `WARM_START` | False |" in text