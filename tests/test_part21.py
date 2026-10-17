"""
ATLAS PSU - Part 21: the GA's role is true. It moves times and rooms only, so its fitness holds only terms it can change.
Run from the project root:  python -m pytest tests/test_part21.py -q
"""
import inspect
from pathlib import Path

from config.rooms import use_rooms
from conftest import dept_faculty
from services import schedule_service as ss
from solver import ga_optimizer, objective_functions as of
from solver.constraints import validate_schedule
from test_part20 import run_cached

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def pushing_preferences(faculty):
    """Preferences that the CP-SAT slots mostly violate, so the GA has a reason to move things."""
    return {f["name"]: {"preferred_period": "evening", "restricted_days": ["Mon", "Tue"], "preferred_building": "zz"}
            for f in faculty}


def test_the_ga_never_changes_a_professor_and_never_breaks_a_hard_rule():
    base = run_cached(7)["result"]
    fac = dept_faculty("IT")
    ss.reset_state("IT")
    lookup, sizes, rooms = ss.build_static_lookup("IT"), ss.get_class_sizes("IT"), ss.get_rooms("IT")
    with use_rooms(rooms):
        base_bad = len(validate_schedule(base, fac, lookup, rooms, sizes))
        for seed in (1, 2, 3):
            best, m = ga_optimizer.optimize(base, fac, lookup, pushing_preferences(fac), generations=12, population_size=8,
                                            seed=seed, deterministic=True, class_sizes=sizes, rooms=rooms)
            assert len(best) == len(base)
            assert [r["faculty"] for r in best] == [r["faculty"] for r in base]            # no professor moved
            assert [(r["subject"], r.get("section")) for r in best] == [(r["subject"], r.get("section")) for r in base]
            assert len(validate_schedule(best, fac, lookup, rooms, sizes)) <= base_bad       # the validator agrees
            assert m["improvement"] >= 0
    assert any(a["slot"] != b["slot"] or a["room"] != b["room"] for a, b in zip(best, base)), "the GA should have moved something"


def test_fitness_has_only_terms_the_ga_can_change():
    assert list(inspect.signature(of.schedule_fitness).parameters) == ["assignments", "soft_constraints", "class_sizes"]
    base = run_cached(7)["result"]
    sc, sizes = pushing_preferences(dept_faculty("IT")), ss.get_class_sizes("IT")
    terms = of.fitness_terms(base, sc, sizes)
    assert set(terms) == {"preference", "capacity", "affinity"}
    assert abs(of.schedule_fitness(base, sc, sizes) - sum(terms.values())) < 1e-9
    swapped = [dict(r) for r in base]
    a, b = next(i for i, r in enumerate(swapped) if r["faculty"]), len(swapped) - 1
    swapped[a]["faculty"], swapped[b]["faculty"] = swapped[b]["faculty"], swapped[a]["faculty"]
    unchanged = of.fitness_terms(swapped, {}, None)["capacity"]
    assert unchanged == 0.0                                                                  # no workload or specialization term inside


def test_assignment_quality_is_reporting_only_and_sees_the_professors():
    fac = dept_faculty("IT")
    lookup = ss.build_static_lookup("IT")
    rows = [{"faculty": fac[0]["name"], "subject": "x", "class_type": "LECTURE", "slot": "Mon: 07:00-08:00", "room": "R"}] * 6
    q = of.assignment_quality(rows, fac, lookup)
    assert set(q) == {"spec_score", "variance_penalty", "underload_penalty", "total"} and q["variance_penalty"] > 0


def test_analytics_reports_ga_improvement_on_ga_terms_only():
    p = run_cached(7)
    om = p["analytics"]["optimization_metrics"]
    assert set(om["ga_improvement_terms"]) == {"preference", "capacity", "affinity"}
    assert abs(om["ga_improvement"] - sum(om["ga_improvement_terms"].values())) < 0.02
    assert set(om["assignment_quality"]) == {"spec_score", "variance_penalty", "underload_penalty", "total"}


def test_wording_matches_the_code():
    readme = read("README.md")
    assert "improves times and rooms" in readme and "without changing any professor" in readme
    assert "tunes that schedule against faculty preferences" not in readme
    assert "assignment_quality()" in readme and "ga_improvement_terms" in readme
    assert "assigns professors under the hard rules and balances the load" in read("app/about.html")
    js = read("assets/js/main-script.js")
    assert "GA: improving times and rooms" in js and "CP-SAT: assigning professors" in js
    ga_src = read("solver/ga_optimizer.py")
    assert "static_lookup, class_sizes)" not in ga_src.split("def fitness(sched):")[1].split("\n")[1]