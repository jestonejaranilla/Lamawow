"""
ATLAS PSU - Part 19: one honest definition of workload fairness and specialization match.
Run from the project root:  python -m pytest tests/test_part19.py -q
"""
import math
import os

import config.settings as cfg
from services import run_store
from services.analytics_service import compute_analytics, workload_metrics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def fac(name, spec=("Programming",)):
    return {"name": name, "specialization": list(spec), "max_units": 24, "absolute_max_units": 30}


def rows(name, count, subject="Prog", section="S1"):
    return [{"faculty": name, "subject": subject, "section": section, "class_type": "LECTURE",
             "room": "CL1", "student_count": 30} for _ in range(count)]


def test_hand_computed_jain_gini_cv():
    faculty = [fac(n) for n in "ABCD"]
    a = rows("A", 3) + rows("B", 1) + rows("C", 1)                  # units 6, 2, 2, 0 (2 units per meeting)
    m = workload_metrics(a, faculty)
    assert (m["mean"], m["median"], m["min"], m["max"]) == (2.5 * 2 / 2, 2.0, 0, 6)
    assert math.isclose(m["std"], math.sqrt(4.75), abs_tol=1e-3)
    assert math.isclose(m["cv"], math.sqrt(4.75) / 2.5, abs_tol=1e-3)
    assert math.isclose(m["jain"], 100 / 176, abs_tol=1e-4)
    assert math.isclose(m["gini"], 0.45, abs_tol=1e-4)
    assert m["zero_load_count"] == 1 and m["over_soft_cap_count"] == 0 and m["over_hard_cap_count"] == 0
    assert [p["units"] for p in m["per_professor"]] == [6, 2, 2, 0]


def test_equal_loads_are_perfectly_fair_and_caps_are_counted():
    m = workload_metrics(rows("A", 2) + rows("B", 2), [fac("A"), fac("B")])
    assert m["jain"] == 1.0 and m["gini"] == 0.0 and m["cv"] == 0.0
    big = workload_metrics(rows("A", 16), [fac("A"), fac("B")])     # 32 units: over 24 and over 30
    assert big["over_soft_cap_count"] == 1 and big["over_hard_cap_count"] == 1


def test_three_of_ten_idle_professors_keep_jain_below_one_everywhere():
    faculty = [fac("P%d" % i) for i in range(10)]
    a = [r for i in range(7) for r in rows("P%d" % i, 2)]           # P7..P9 have no class
    m = workload_metrics(a, faculty)
    assert m["zero_load_count"] == 3 and math.isclose(m["jain"], 0.7, abs_tol=1e-4)
    score = run_store.balance_score(a, faculty)
    assert score == round(100 * m["jain_exact"], 1) == 70.0         # Saved runs
    out = compute_analytics(a, faculty, {"Prog": ["Programming"]}, {}, {}, {})
    assert out["workload_metrics"]["jain"] < 1 and out["workload_metrics"]["zero_load_count"] == 3   # Reports data
    assert round(100 * out["workload_metrics"]["jain_exact"], 1) == score


def test_balance_score_uses_units_not_meeting_rows():
    faculty = [fac("A"), fac("B")]
    plain = rows("A", 2)
    lab = [{"faculty": "B", "subject": "Prog", "section": "S1", "class_type": "NON_CLASSROOM"}]
    assert run_store.balance_score(plain + lab, faculty) == round(
        100 * workload_metrics(plain + lab, faculty)["jain_exact"], 1)
    assert run_store.balance_score([], faculty) is None


def test_balance_score_honours_per_run_units():
    faculty = [fac("A"), fac("B")]
    a = rows("A", 1) + [{"faculty": "B", "subject": "X", "class_type": "NON_CLASSROOM"}]
    with cfg.run_settings(units_per_assignment=2, non_classroom_units=6):
        low = run_store.balance_score(a, faculty)
    with cfg.run_settings(units_per_assignment=2, non_classroom_units=2):
        high = run_store.balance_score(a, faculty)
    assert high == 100.0 and low < high


def test_specialization_is_counted_per_course_group_and_electives_are_excluded():
    faculty = [fac("X", ("Mathematics", "Programming")), fac("Y", ("Programming",))]
    lookup = {"Calc": ["Mathematics"], "Prog": ["Programming"], "E1": ["Elective"]}
    a = (rows("X", 2, "Calc", "S1")                                  # two meetings, ONE group, X first tag matches
         + rows("X", 1, "Prog", "S1")                                # qualified, but Programming is not X's first tag
         + rows("Y", 1, "Prog", "S2")                                # first tag matches
         + rows("Y", 1, "E1", "S1"))                                 # elective-only
    sp = compute_analytics(a, faculty, lookup, {}, {}, {})["specialization_metrics"]
    assert sp["group_count"] == 4 and sp["scored_group_count"] == 3 and sp["elective_group_count"] == 1
    assert sp["primary_tag_match_count"] == 2 and sp["primary_tag_match_pct"] == 66.7
    assert sp["any_tag_match_pct"] == 100.0


def test_underload_is_below_the_average_share_not_below_max_units():
    faculty = [fac("A"), fac("B"), fac("C")]
    a = rows("A", 4) + rows("B", 2) + rows("C", 1)                   # 8, 4, 2 units, target 14/3
    wd = compute_analytics(a, faculty, {"Prog": ["Programming"]}, {}, {}, {})["workload_distribution"]
    assert wd["underload_count"] == 2 and wd["underload_target"] == round(14 / 3, 2)


def test_band_thresholds_live_in_settings_and_reach_the_payload():
    assert cfg.JAIN_BAND_GOOD > cfg.JAIN_BAND_WARNING and cfg.LOAD_MODEL == "per_meeting"
    out = compute_analytics(rows("A", 1), [fac("A")], {"Prog": ["Programming"]}, {}, {}, {})
    assert out["workload_metrics"]["bands"] == {"good": cfg.JAIN_BAND_GOOD, "warning": cfg.JAIN_BAND_WARNING}


def test_reports_panel_reads_the_payload_and_has_no_composite_score():
    js = read("assets/js/main-script.js")
    assert "0.6" not in js[js.index("function computeFairnessReport"):js.index("// Per-faculty table")]
    assert "sumSqLoads" not in js and "workload_metrics" in js
    html = read("pages/dashboard.html")
    for needle in ("Primary Tag Match", "Qualified", "Elective Groups", "Professors With No Load", "Lowest / Highest Load"):
        assert needle in html
    assert "Specialization Match Rate" not in html and "Specialization Accuracy" not in js


def test_load_unit_is_documented():
    for rel in ("README.md", "docs/DATA.md"):
        text = read(rel)
        assert "units_per_assignment" in text and "load_model" in text, rel