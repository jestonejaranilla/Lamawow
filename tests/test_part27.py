"""
ATLAS PSU - Part 27A: complete schedules on slow hosts (repair, CPU quota, time limit, honest labels).
Run from the project root:  python -m pytest tests/test_part27a.py -q -p no:cacheprovider
"""
import subprocess
import sys
from pathlib import Path

import pytest

import config.settings as cfg
from conftest import dept_faculty
from scripts.evaluate import rooms_for
from services import analytics_service as an
from services import schedule_service as ss
from solver import cp_sat_solver as cps
from solver.constraints import validate_schedule

ROOT = Path(__file__).resolve().parent.parent
SEM1 = "1st Semester"
REPAIR_TEXT = "groups were completed by the repair step because the solver ran out of time"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ── (c) CPU quota parser ──────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("max 100000", None), ("max 100000\n", None), ("50000 100000", 1), ("10000 100000\n", 1),
    ("100000 100000", 1), ("150000 100000", 2), ("400000 100000", 4), ("", None), ("junk", None),
    ("0 100000", None), ("50000 0", None),
])
def test_cgroup_v2_cpu_max(text, expected):
    assert cps.parse_cpu_max(text) == expected


@pytest.mark.parametrize("quota,period,expected", [
    ("-1", "100000", None), ("50000\n", "100000\n", 1), ("100000", "100000", 1),
    ("250000", "100000", 3), ("x", "100000", None), ("50000", "0", None),
])
def test_cgroup_v1_quota(quota, period, expected):
    assert cps.parse_cfs(quota, period) == expected


def _point_cgroup_files(monkeypatch, tmp_path, v2=None, v1=None):
    paths = {"v2": tmp_path / "cpu.max", "q": tmp_path / "quota", "p": tmp_path / "period"}
    if v2 is not None:
        paths["v2"].write_text(v2)
    if v1 is not None:
        paths["q"].write_text(v1[0])
        paths["p"].write_text(v1[1])
    monkeypatch.setattr(cps, "_CG2_CPU_MAX", str(paths["v2"]))
    monkeypatch.setattr(cps, "_CG1_QUOTA", str(paths["q"]))
    monkeypatch.setattr(cps, "_CG1_PERIOD", str(paths["p"]))


def test_search_workers_follow_the_quota_never_below_one_never_above_eight(monkeypatch, tmp_path):
    monkeypatch.setattr(cps, "_host_cpus", lambda: 8)
    _point_cgroup_files(monkeypatch, tmp_path, v2="10000 100000")
    assert cps._search_workers() == 1                                   # a tenth of a CPU still gets one worker
    _point_cgroup_files(monkeypatch, tmp_path, v2="300000 100000")
    assert cps._search_workers() == 3
    _point_cgroup_files(monkeypatch, tmp_path, v2="max 100000")
    assert cps._search_workers() == 8
    monkeypatch.setattr(cps, "_host_cpus", lambda: 64)
    assert cps._search_workers() == 8
    monkeypatch.setattr(cps, "_host_cpus", lambda: 2)
    assert cps._search_workers() == 2                                   # the host count still limits


def test_search_workers_cgroup_v1_and_missing_files(monkeypatch, tmp_path):
    monkeypatch.setattr(cps, "_host_cpus", lambda: 8)
    (tmp_path / "no_v2").mkdir()
    monkeypatch.setattr(cps, "_CG2_CPU_MAX", str(tmp_path / "no_v2" / "cpu.max"))     # missing: v1 is read
    (tmp_path / "q").write_text("50000")
    (tmp_path / "p").write_text("100000")
    monkeypatch.setattr(cps, "_CG1_QUOTA", str(tmp_path / "q"))
    monkeypatch.setattr(cps, "_CG1_PERIOD", str(tmp_path / "p"))
    assert cps._search_workers() == 1
    monkeypatch.setattr(cps, "_CG1_QUOTA", str(tmp_path / "gone"))
    assert cps.cpu_quota_cpus() is None
    assert cps._search_workers() == 8                                   # old behaviour when the files are missing


# ── Environment variables for the time limit ──────────────────────────────────
def _settings_in_new_process(**env):
    code = "import config.settings as c; print(c.CP_SAT_TIME_LIMIT_SECONDS, c.CP_SAT_MAX_TIME_LIMIT_SECONDS)"
    import os
    e = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_CP_SAT")}
    e.update(env)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=e, capture_output=True, text=True, check=True)
    a, b = out.stdout.split()
    return float(a), float(b)


def test_time_limit_environment_variables():
    assert _settings_in_new_process() == (30.0, 40.0)
    assert _settings_in_new_process(ATLAS_CP_SAT_MAX_TIME_LIMIT="90", ATLAS_CP_SAT_TIME_LIMIT="60") == (60.0, 90.0)
    assert _settings_in_new_process(ATLAS_CP_SAT_MAX_TIME_LIMIT="500") == (30.0, 120.0)       # ceiling capped at 120
    assert _settings_in_new_process(ATLAS_CP_SAT_TIME_LIMIT="100") == (40.0, 40.0)            # never above the ceiling
    assert _settings_in_new_process(ATLAS_CP_SAT_TIME_LIMIT="abc", ATLAS_CP_SAT_MAX_TIME_LIMIT="nan") == (30.0, 40.0)


def test_solver_uses_a_ceiling_above_44_and_clamps_the_browser_value(monkeypatch):
    monkeypatch.setattr(cfg, "CP_SAT_MAX_TIME_LIMIT_SECONDS", 100.0)
    with cfg.run_settings(cp_sat_time_limit=90):
        assert cps._time_limit() == 90.0
    with cfg.run_settings(cp_sat_time_limit=500):
        assert cps._time_limit() == 100.0
    monkeypatch.setattr(cfg, "CP_SAT_MAX_TIME_LIMIT_SECONDS", 40.0)
    with cfg.run_settings(cp_sat_time_limit=500):
        assert cps._time_limit() == 40.0


def test_docs_name_both_variables():
    for rel in ("README.md", "docs/DEPLOY.md"):
        text = read(rel)
        assert "ATLAS_CP_SAT_TIME_LIMIT" in text and "ATLAS_CP_SAT_MAX_TIME_LIMIT" in text
        assert "--timeout 120" in text and "60 s" in text


# ── Helpers: a CP-SAT run that "ran out of time" with half of the groups uncovered ──
def _inputs(dept="IT", sem=SEM1):
    sizes = ss.get_class_sizes(dept)
    prep = ss.prepare_scheduling_input(dept, [], sem, sizes)
    return prep, dept_faculty(dept), ss.build_static_lookup(dept), rooms_for(dept)


@pytest.fixture
def partial_cp_sat(monkeypatch):
    """CP-SAT answers FEASIBLE but leaves every second group without a professor (what a 3 s limit does)."""
    real = cps._solve_with_ortools
    box = {"kept": {}, "dropped": []}

    def partial(meetings, groups, faculty_list, static_lookup, progress_cb=None):
        plan, info = real(meetings, groups, faculty_list, static_lookup, progress_cb)
        gids = sorted(plan)
        box["dropped"] = gids[::2]
        for gid in box["dropped"]:
            del plan[gid]
        box["kept"] = {gid: {"fac": p["fac"], "slots": dict(p["slots"])} for gid, p in plan.items()}
        info = {**info, "status": "FEASIBLE"}
        return plan, info

    monkeypatch.setattr(cps, "_solve_with_ortools", partial)
    return box


def _solve(dept="IT", sem=SEM1, seconds=4, seed=1):
    prep, faculty, lookup, rooms = _inputs(dept, sem)
    with cfg.run_settings(seed=seed, cp_sat_time_limit=seconds):
        rows, m = cps.solve(prep["sections"], faculty, lookup, rooms=rooms)
    return rows, m, prep, faculty, lookup, rooms


# ── (b) the repair never changes what CP-SAT assigned ─────────────────────────
def test_repair_completes_every_group_without_touching_the_cp_sat_assignments(partial_cp_sat):
    rows, m, prep, faculty, lookup, rooms = _solve()
    box = partial_cp_sat
    assert box["dropped"] and box["kept"]
    assert m["uncovered_groups"] == {}
    assert all(r["faculty"] for r in rows)
    assert m["unassigned_count"] == 0
    assert m["violations"] == []
    assert validate_schedule(rows, faculty, lookup, rooms) == []
    # every group CP-SAT did not assign was repaired (the real 3 s run may have left more out than the ones dropped here)
    all_gids = {r["group_id"] for r in rows}
    assert set(m["repaired_group_ids"]) == all_gids - set(box["kept"])
    assert set(box["dropped"]) <= set(m["repaired_group_ids"]) and m["repaired_groups"] == len(m["repaired_group_ids"])
    assert m["solver_fallback"] is True and m["solver_used"] == "cp_sat_ortools"

    names = [f["name"] for f in faculty]
    by_group = {}
    for r in rows:
        by_group.setdefault(r["group_id"], []).append(r)
    for gid, p in box["kept"].items():                                  # same professor and same slots as CP-SAT chose
        got = by_group[gid]
        assert {r["faculty"] for r in got} == {names[p["fac"]]}
        want_slots = sorted(cps.ALL_SLOT_STRINGS[t] for t in p["slots"].values())
        assert sorted(r["slot"] for r in got if r["slot"]) == want_slots


def test_repair_does_nothing_when_cp_sat_covered_everything(monkeypatch):
    prep, faculty, lookup, rooms = _inputs()
    with cfg.run_settings(seed=1, cp_sat_time_limit=30):
        rows, m = cps.solve(prep["sections"], faculty, lookup, rooms=rooms)
    assert m["repaired_groups"] == 0 and m["solver_fallback"] is False
    assert m["uncovered_groups"] == {} and m["violations"] == []


# ── (a) tiny time limit on IT 1st semester ────────────────────────────────────
def test_tiny_time_limit_covers_every_group_with_zero_violations_through_the_service():
    ss.reset_state("IT")
    subj = [{"group_id": g["group_id"]} for g in ss.build_groups("IT", SEM1, ss.get_class_sizes("IT"))[0]]
    out = ss.start_scheduling("IT", dept_faculty("IT"), subj, SEM1, {"generations": 2, "population": 4}, {}, None,
                              run_settings={"cp_sat_time_limit": 3}, seed=1, wait=True)
    assert "run_id" in out, out
    p = ss.get_progress("IT")
    assert p["phase"] == "done"
    assert p["coverage"]["assigned"] == p["coverage"]["total"] > 0 and p["coverage_errors"] == []
    assert all(r["faculty"] for r in p["result"])
    assert not any("hard-rule violation" in w for w in p["warnings"])
    if p["metrics"].get("repaired_groups"):                             # depends on the speed of this machine
        assert any(REPAIR_TEXT in w for w in p["warnings"])


def test_repair_warning_is_in_the_run_result(partial_cp_sat):
    ss.reset_state("IT")
    subj = [{"group_id": g["group_id"]} for g in ss.build_groups("IT", SEM1, ss.get_class_sizes("IT"))[0]]
    out = ss.start_scheduling("IT", dept_faculty("IT"), subj, SEM1, {"generations": 2, "population": 4}, {}, None,
                              run_settings={"cp_sat_time_limit": 4}, seed=1, wait=True)
    assert "run_id" in out, out
    p = ss.get_progress("IT")
    n = p["metrics"]["repaired_groups"]
    assert n >= len(partial_cp_sat["dropped"]) > 0
    assert any(w.startswith(f"{n} {REPAIR_TEXT}") for w in p["warnings"]), p["warnings"]
    assert not any("simpler fallback solver" in w for w in p["warnings"])
    assert p["coverage"]["assigned"] == p["coverage"]["total"] and p["coverage_errors"] == []
    assert p["metrics"]["repaired_groups"] == n


@pytest.mark.slow
@pytest.mark.parametrize("dept", ["IT", "CS", "MB", "ES", "MedB"])
@pytest.mark.parametrize("sem", ["1st Semester", "2nd Semester"])
@pytest.mark.parametrize("seconds", [1, 3])
def test_standard_pool_is_fully_covered_on_a_tiny_budget(dept, sem, seconds):
    rows, m, prep, faculty, lookup, rooms = _solve(dept, sem, seconds)
    assert m["uncovered_groups"] == {}, m["uncovered_groups"]
    assert all(r["faculty"] for r in rows)
    assert validate_schedule(rows, faculty, lookup, rooms) == []


# ── 4 and 6: honest reasons, each group named ─────────────────────────────────
def test_uncovered_reason_says_out_of_time_only_when_the_solver_stopped_on_its_limit():
    fac = [{"name": "A", "absolute_max_units": 30}]
    g = {"reason": None, "units": 4, "fac": [0]}
    assert cps._uncovered_reason(g, fac, {"A": 0}, timed_out=True, room_free=True) == "the solver ran out of time"
    assert cps._uncovered_reason(g, fac, {"A": 0}, timed_out=False, room_free=True) == "no conflict-free slot and room found"
    assert cps._uncovered_reason(g, fac, {"A": 0}, timed_out=True, room_free=False) == "no conflict-free slot and room found"
    assert cps._uncovered_reason(g, fac, {"A": 28}, timed_out=True, room_free=True) == "load cap reached"
    fixed = {"reason": "no qualified faculty", "units": 4, "fac": []}
    assert cps._uncovered_reason(fixed, fac, {}, timed_out=True, room_free=True) == "no qualified faculty"


def test_without_repair_the_uncovered_groups_get_the_out_of_time_reason_and_the_warning_names_them(partial_cp_sat,
                                                                                                   monkeypatch):
    monkeypatch.setattr(cps, "_repair", lambda meetings, groups, fl, sl, plan, info: (plan, info, []))
    rows, m, *_ = _solve()
    assert m["uncovered_groups"] and set(m["uncovered_groups"].values()) == {"the solver ran out of time"}
    assert set(partial_cp_sat["dropped"]) <= set(m["uncovered_groups"])

    ss.reset_state("IT")
    subj = [{"group_id": g["group_id"]} for g in ss.build_groups("IT", SEM1, ss.get_class_sizes("IT"))[0]]
    ss.start_scheduling("IT", dept_faculty("IT"), subj, SEM1, {"generations": 2, "population": 4}, {}, None,
                        run_settings={"cp_sat_time_limit": 4}, seed=1, wait=True)
    p = ss.get_progress("IT")
    warn = next(w for w in p["warnings"] if "could not be fully covered" in w)
    for e in p["coverage_errors"]:                                      # every group and its reason is in the warning
        assert f"{e['block']} {e['course']} ({e['reason']})" in warn
    assert "the solver ran out of time" in warn


def test_a_group_with_no_qualified_professor_keeps_its_real_reason():
    prep, faculty, lookup, rooms = _inputs()
    some_tag = next(t for t in lookup.values() if t and t != ["Elective"])
    only = [f for f in faculty if not set(f["specialization"]) & set(some_tag)]
    with cfg.run_settings(seed=1, cp_sat_time_limit=3):
        rows, m = cps.solve(prep["sections"], only, lookup, rooms=rooms)
    assert "no qualified faculty" in set(m["uncovered_groups"].values())
    assert m["violations"] == []


# ── 5: qualified and primary percentages describe only groups that have a professor ──
def test_percentages_ignore_groups_without_a_professor():
    lookup = {"Prog": ["Programming"], "Nets": ["Networks"], "Math": ["Mathematics"]}
    fac = [{"name": "P1", "specialization": ["Programming", "Networks"]}]
    fac_map = {f["name"]: f for f in fac}

    def row(subject, who, sec="B1"):
        return {"year": "1st Year", "section": sec, "subject": subject, "faculty": who}

    rows = [row("Prog", "P1"), row("Prog", "P1"), row("Nets", "P1"), row("Math", ""), row("Math", "", "B2")]
    sp = an._specialization_groups(rows, fac_map, lookup)
    assert sp["unassigned_group_count"] == 2
    assert sp["group_count"] == 4 and sp["scored_group_count"] == 2          # B1 Prog and B1 Nets
    assert sp["any_tag_match_pct"] == 100.0 and sp["primary_tag_match_pct"] == 50.0
    full = an._specialization_groups(rows[:3], fac_map, lookup)
    assert full["unassigned_group_count"] == 0 and full["any_tag_match_pct"] == 100.0


def test_a_partly_unassigned_group_counts_as_unassigned():
    lookup = {"Prog": ["Programming"]}
    fac_map = {"P1": {"name": "P1", "specialization": ["Programming"]}}
    rows = [{"year": "1", "section": "B1", "subject": "Prog", "faculty": "P1"},
            {"year": "1", "section": "B1", "subject": "Prog", "faculty": ""}]
    sp = an._specialization_groups(rows, fac_map, lookup)
    assert sp["unassigned_group_count"] == 1 and sp["scored_group_count"] == 0 and sp["any_tag_match_pct"] == 0.0


def test_reports_show_one_incomplete_line_above_the_fairness_cards():
    html, js = read("pages/dashboard.html"), read("assets/js/main-script.js")
    assert html.index('id="fairnessIncomplete"') < html.index('id="fairnessReport"')
    assert "Incomplete schedule: ${n} of ${sp.group_count} groups have no professor, so the numbers below describe a partial schedule." in js
    assert "unassigned_group_count" in js