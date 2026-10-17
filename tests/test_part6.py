"""
ATLAS PSU - Part 6: IT demo pool, settings names, no hardcoded IT check, login keys, no CDN.
Run from the project root:  python -m pytest tests/test_part6.py -q
"""
import copy
import os
import re

import pytest

import config.settings as cfg
from app import app
from config.curriculum import load_curriculum
from services import schedule_service as ss
from services.analytics_service import compute_analytics
from solver import cp_sat_solver as cps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_it_default_pool_shape():
    cur = load_curriculum("IT")
    pool = cur["default_faculty"]
    assert 10 <= len(pool) <= 12
    assert len({f["name"] for f in pool}) == len(pool)
    for f in pool:
        assert f["availability"] == ["Mon", "Tue", "Wed", "Thu"]
        assert (f["max_units"], f["absolute_max_units"]) == (24, 30)
        assert 2 <= len(f["specialization"]) <= 3 and set(f["specialization"]) <= set(cur["specializations"])
    assert {t for f in pool for t in f["specialization"]} >= set(cur["specializations"]) - {"Elective"}
    for other in ("CS", "MB", "ES", "MedB"):
        assert "default_faculty" not in load_curriculum(other)


@pytest.mark.slow
@pytest.mark.parametrize("sem", ["1st Semester", "2nd Semester"])
def test_it_default_pool_full_coverage_and_realistic_load(sem, monkeypatch):
    monkeypatch.setattr(cfg, "CP_SAT_TIME_LIMIT_SECONDS", 8.0)
    pool = copy.deepcopy(load_curriculum("IT")["default_faculty"])
    ss.reset_state("IT")
    subj = [{"group_id": g["group_id"]} for g in ss.build_groups("IT", sem, ss.get_class_sizes("IT"))[0]]
    # Part 25: deterministic mode (one worker, a deterministic-time limit, fixed seed), so a loaded machine cannot
    # make the solver run out of wall-clock time and change the result.
    ss.start_scheduling("IT", pool, subj, sem, {"generations": 3, "population": 4}, {}, None, wait=True,
                        seed=1, deterministic=True, run_settings={"cp_sat_time_limit": 8})
    p = ss.get_progress("IT")
    assert p["coverage"]["assigned"] == p["coverage"]["total"] and p["coverage_errors"] == []
    loads = {f["name"]: 0 for f in pool}
    for r in p["result"]:
        loads[r["faculty"]] += 2
    mean = sum(loads.values()) / len(pool)
    assert 13 <= mean <= 20, mean
    assert max(loads.values()) <= 30 and sum(v > 24 for v in loads.values()) == 0


def test_solver_reads_the_names_defined_in_settings(monkeypatch):
    monkeypatch.setattr(cfg, "CP_SAT_TIME_LIMIT_SECONDS", 30.0)
    monkeypatch.setattr(cfg, "CP_SAT_MAX_TIME_LIMIT_SECONDS", 5.0)
    assert cps._time_limit() == 5.0
    for key in ("uncovered_group", "exact_spec", "course_professor", "over_soft_cap", "load_balance",
                "lab_for_lecture", "room_over"):
        assert key in cps._weights(), key
    monkeypatch.setattr(cfg, "CP_WEIGHTS", {"exact_spec": 777})
    assert cps._weights() == {"exact_spec": 777}
    assert not hasattr(cfg, "CP_SAT_MAX_SECONDS") and not hasattr(cfg, "CP_SAT_WEIGHTS")


def test_no_hardcoded_department_check_in_backend():
    for rel in ("services/analytics_service.py", "services/schedule_service.py", "solver/constraints.py",
                "solver/cp_sat_solver.py"):
        assert "IT Elective" not in read(rel), rel


def test_elective_only_course_counts_as_match_in_any_department():
    fac = [{"name": "Prof X", "specialization": ["Mathematics"], "max_units": 24, "absolute_max_units": 30}]
    rows = [{"faculty": "Prof X", "subject": "CS Elective 4", "class_type": "LECTURE", "room": "CL1",
             "section": "CS3B1", "student_count": 30}]
    out = compute_analytics(rows, fac, {"CS Elective 4": ["Elective"]}, {}, {}, {})
    assert out["specialization_metrics"]["exact_match_count"] == 1


def test_login_script_never_reads_an_unsuffixed_data_key():
    js = read("assets/js/login-script.js")
    assert not re.search(r"""readJSON\(\s*['"]facultyData['"]""", js)
    assert "facultyData" not in js and "localStorage" not in js      # Part 15: sign in reads no browser data at all


def test_dashboard_uses_no_cdn_and_chart_is_served():
    html = read("pages/dashboard.html")
    assert not re.search(r"<script[^>]+src=[\"']https?://", html)
    assert "jspdf" not in html.lower()
    r = app.test_client().get("/assets/vendor/chart.umd.min.js")
    assert r.status_code == 200 and b"Chart.js" in r.data[:200]
    assert "typeof Chart === 'undefined'" in read("assets/js/main-script.js")


def test_default_period_and_data_version():
    js = read("assets/js/main-script.js")
    assert "{ year: '2026-2027', semester: '1st Semester' }" in js
    assert "INITIAL_FACULTY" not in js


# ── Part 7 ────────────────────────────────────────────────────────────────────
import time


def _post(client, **over):
    body = {"dept": "IT", "faculty": [{"name": "x"}], "subjects": [{"name": "x"}]}
    body.update(over)
    return client.post("/run-ga", json=body)


@pytest.fixture
def captured(monkeypatch):
    import routes.schedule_routes as rt
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"run_id": "t"}
    monkeypatch.setattr(rt, "start_scheduling", fake)
    return seen


def test_run_ga_clamps_inputs(captured):
    r = _post(app.test_client(), generations=9999, population=1, mutation=5, crossover=-2,
              cp_sat_time_limit=600, units_per_assignment=2, non_classroom_units=2)
    assert r.status_code == 200
    assert captured["ga_params"] == {"generations": 200, "population": 4, "mutation": 1.0, "crossover": 0.0}
    assert captured["run_settings"]["cp_sat_time_limit"] == cfg.CP_SAT_MAX_TIME_LIMIT_SECONDS
    r = _post(app.test_client(), generations=0, population=500)
    assert captured["ga_params"]["generations"] == 1 and captured["ga_params"]["population"] == 100


@pytest.mark.parametrize("key", ["generations", "population", "mutation", "crossover", "cp_sat_time_limit",
                                 "units_per_assignment", "non_classroom_units"])
@pytest.mark.parametrize("bad", ["abc", "10", True, [1], {"a": 1}])
def test_run_ga_rejects_non_numbers(captured, key, bad):
    r = _post(app.test_client(), **{key: bad})
    assert r.status_code == 400 and r.get_json()["success"] is False and "number" in r.get_json()["error"]
    assert captured == {}                      # nothing was started


def test_run_ga_leaves_global_settings_alone(captured):
    before = (cfg.UNITS_PER_ASSIGNMENT, cfg.NON_CLASSROOM_UNITS, cfg.CP_SAT_TIME_LIMIT_SECONDS)
    _post(app.test_client(), units_per_assignment=5, non_classroom_units=4, cp_sat_time_limit=3)
    assert (cfg.UNITS_PER_ASSIGNMENT, cfg.NON_CLASSROOM_UNITS, cfg.CP_SAT_TIME_LIMIT_SECONDS) == before
    assert captured["run_settings"] == {"units_per_assignment": 5, "non_classroom_units": 4, "cp_sat_time_limit": 3.0}


@pytest.mark.slow
def test_it_and_cs_run_together_with_different_settings():
    from tests.conftest import dept_faculty

    def start(d, rs):
        ss.reset_state(d)
        subj = [{"group_id": g["group_id"]} for g in ss.build_groups(d, "1st Semester", ss.get_class_sizes(d))[0]]
        return ss.start_scheduling(d, dept_faculty(d), subj, "1st Semester", {"generations": 2, "population": 4},
                                   {}, None, run_settings=rs)

    before = (cfg.UNITS_PER_ASSIGNMENT, cfg.NON_CLASSROOM_UNITS, cfg.CP_SAT_TIME_LIMIT_SECONDS)
    assert "run_id" in start("IT", {"units_per_assignment": 3, "non_classroom_units": 3, "cp_sat_time_limit": 12})
    assert "run_id" in start("CS", {"units_per_assignment": 2, "non_classroom_units": 2, "cp_sat_time_limit": 8})
    t0 = time.time()
    while any(ss.get_progress(d)["running"] for d in ("IT", "CS")) and time.time() - t0 < 120:
        time.sleep(0.5)
    for d, units in (("IT", 3), ("CS", 2)):
        p = ss.get_progress(d)
        assert not p["running"] and p["result"]
        rows = sum(1 for r in p["result"] if r["faculty"])
        # every professor row of this run counted `units` units, whatever the other department used
        assert p["analytics"]["workload_distribution"]["mean_load"] == round(units * rows / 10, 1), d
    assert (cfg.UNITS_PER_ASSIGNMENT, cfg.NON_CLASSROOM_UNITS, cfg.CP_SAT_TIME_LIMIT_SECONDS) == before


@pytest.mark.parametrize("dept", ["MB", "ES", "MedB"])
def test_science_rooms_are_48_recommended_60_max_and_still_flagged_placeholder(dept):
    from config import curriculum as cur
    rs = cur.rooms_for(dept)
    assert rs.placeholder is True
    assert rs.capacity and all(v["recommended"] == 48 and v["max"] == 60 for v in rs.capacity.values())


def test_repo_housekeeping():
    assert read(".gitattributes").strip() == "* text=auto eol=lf"
    assert "ortools==9.15.6755" in read("requirements.txt")
    assert not os.path.exists(os.path.join(ROOT, "{solver,services,models,routes,config}"))
    for rel in ("pages/dashboard.html", "faculty/dashboard.html"):
        urls = re.findall(r"""(?:src|href)=["'](https?://[^"']+)""", read(rel))
        assert all("fonts.googleapis.com" in u or "fonts.gstatic.com" in u for u in urls), urls
    for f in ("avatar.svg", "ga-evolution.svg"):
        assert os.path.exists(os.path.join(ROOT, "assets", "images", f))