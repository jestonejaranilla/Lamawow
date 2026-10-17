"""
ATLAS PSU - Part 22: the evaluation harness and the random-feasible baseline.
Run from the project root:  python -m pytest tests/test_part22.py -q
"""
import csv
import subprocess
import sys
from pathlib import Path

import pytest

import config.settings as cfg
from config.curriculum import rooms_for
from services import schedule_service as ss
from solver import cp_sat_solver as cps
from solver.constraints import validate_schedule

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate as ev   # noqa: E402


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def baseline_rows(seed):
    ss.reset_state()
    fac, sizes = ev.dept_faculty("IT"), ss.get_class_sizes("IT")
    prep = ss.prepare_scheduling_input("IT", [], "1st Semester", sizes)
    lookup, rooms = ss.build_static_lookup("IT"), rooms_for("IT")
    with cfg.run_settings(seed=seed, deterministic=True):
        rows, m = cps.solve(prep["sections"], fac, lookup, rooms=rooms, baseline=True)
    return rows, m, fac, lookup, rooms, sizes, prep


def test_the_baseline_is_random_feasible_and_seeded():
    rows, m, fac, lookup, rooms, sizes, prep = baseline_rows(1)
    assert m["solver_used"] == "random_feasible" and m["uncovered_groups"] == {}
    assert validate_schedule(rows, fac, lookup, rooms, sizes, prep["sections"]) == []
    again, *_ = baseline_rows(1)
    other, *_ = baseline_rows(2)
    key = lambda rs: [(r["group_id"], r["faculty"], r["slot"], r["room"]) for r in rs]
    assert key(rows) == key(again) and key(rows) != key(other)


def test_the_pool_moved_to_tools_and_conftest_still_exports_it():
    import conftest
    from tools import faculty_pool
    assert conftest.dept_faculty is faculty_pool.dept_faculty and conftest.make_faculty is faculty_pool.make_faculty
    assert len(faculty_pool.dept_faculty("CS")) == 10 and "def dept_faculty" not in read("tests/conftest.py")


def test_confidence_interval_and_statistics():
    m, sd, lo, hi = ev.stats([1.0, 2.0, 3.0])
    assert (m, sd) == (2.0, 1.0) and abs((hi - lo) / 2 - 4.303 / 3 ** 0.5) < 1e-3
    assert ev.stats([5.0]) == (5.0, 0.0, 5.0, 5.0)
    assert ev.cell([], 2) == "-"


def test_scenarios_change_the_pool_as_described():
    std = ev.scenario_faculty("IT", "standard")
    assert len(ev.scenario_faculty("IT", "remove_one")) == len(std) - 1
    assert ev.scenario_faculty("IT", "days_1")[0]["availability"] == ["Mon"]
    assert ev.scenario_faculty("IT", "days_2")[0]["availability"] == ["Mon", "Tue"]
    assert ev.scenario_faculty("IT", "add_with_tags")[-1]["specialization"] and len(ev.scenario_faculty("IT", "add_no_tags")) == len(std) + 1
    assert ev.scenario_faculty("IT", "add_no_tags")[-1]["specialization"] == []


def test_docs_describe_the_protocol():
    text = read("evaluation/README.md")
    for needle in ("random_baseline", "cp_sat_ga", "deterministic", "95%", "scenarios", "--quick"):
        assert needle in text.lower() or needle in text
    assert "scripts/evaluate.py" in read("README.md")


@pytest.mark.slow
def test_quick_run_makes_both_files_in_under_three_minutes_with_zero_hard_violations(tmp_path):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate.py"), "--quick", "--depts", "IT", "CS",
                          "--out", str(tmp_path)], capture_output=True, text=True, timeout=180, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr[-1500:]
    rows = list(csv.DictReader(open(tmp_path / "results.csv", encoding="utf-8")))
    assert rows and list(rows[0]) == ev.COLUMNS
    assert {r["method"] for r in rows} == set(ev.METHODS) and {r["scenario"] for r in rows} == set(ev.SCENARIOS)
    assert all(int(r["violations"]) == 0 for r in rows)
    assert {int(r["seed"]) for r in rows if r["scenario"] == "standard"} == {1, 2}
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "## Overall" in summary and "## IT, 1st Semester" in summary and "### add_no_tags" in summary and "[" in summary