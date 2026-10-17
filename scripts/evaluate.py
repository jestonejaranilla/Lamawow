"""
ATLAS PSU - scripts/evaluate.py
One command that produces the tables of the results chapter. No Flask, no database.

    python scripts/evaluate.py                 full protocol: 5 departments x 2 semesters x 3 methods x 10 seeds + scenarios
    python scripts/evaluate.py --quick         2 seeds, short limits (a smoke test, not for the paper)
    python scripts/evaluate.py --out DIR --seeds 10 --jobs 4

Writes DIR/results.csv (one row per run) and DIR/summary.md (mean, standard deviation, 95% confidence interval).
The protocol is described in evaluation/README.md. Everything runs in deterministic mode: the same seed gives the same
schedule on any machine load, so only the runtime column changes between two invocations.
"""

import argparse
import csv
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config.settings as cfg                                           # noqa: E402
from config.curriculum import load_curriculum, rooms_for                # noqa: E402
from config.rooms import use_rooms                                      # noqa: E402
from services import schedule_service as ss                             # noqa: E402
from services.analytics_service import _specialization_groups, workload_metrics   # noqa: E402
from solver import cp_sat_solver as cps, ga_optimizer                   # noqa: E402
from solver.constraints import get_building, validate_schedule          # noqa: E402
from solver.objective_functions import capacity_term, fitness_terms     # noqa: E402
from tools.faculty_pool import DAYS, DEPTS, SEMS, dept_faculty, make_faculty   # noqa: E402

METHODS = ["random_baseline", "cp_sat", "cp_sat_ga"]
SCENARIOS = ["standard", "remove_one", "days_1", "days_2", "add_with_tags", "add_no_tags"]
COLUMNS = ["scenario", "dept", "semester", "method", "seed", "groups_assigned", "groups_total", "coverage_pct",
           "violations", "jain", "cv", "min_load", "max_load", "zero_load", "primary_tag_match_pct",
           "preference_score", "capacity_penalty", "building_switches", "runtime_sec"]
# (column, label, decimals) in the order of the summary tables
METRICS = [("coverage_pct", "Coverage %", 1), ("violations", "Hard violations", 2), ("jain", "Jain", 4),
           ("cv", "CV of load", 4), ("min_load", "Min load (units)", 1), ("max_load", "Max load (units)", 1),
           ("zero_load", "Zero-load professors", 2), ("primary_tag_match_pct", "Primary tag match %", 1),
           ("preference_score", "Preference score", 1), ("capacity_penalty", "Capacity penalty", 1),
           ("building_switches", "Building switches", 1), ("runtime_sec", "Runtime (s)", 2)]
SCENARIO_METRICS = ["coverage_pct", "violations", "jain", "zero_load", "primary_tag_match_pct", "runtime_sec"]
T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
        2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


# ── inputs ────────────────────────────────────────────────────────────────────

def standard_preferences(faculty: list) -> dict:
    """Synthetic, pseudonymous preferences, the same for every method: a preferred period for everyone and a day to avoid
    for every second professor. Only the GA optimizes them; the baseline and CP-SAT ignore them."""
    periods = ["morning", "afternoon", "evening"]
    out = {}
    for i, f in enumerate(faculty):
        sc = {"preferred_period": periods[i % 3]}
        if i % 2 == 0:
            sc["restricted_days"] = [DAYS[i % len(DAYS)]]
        out[f["name"]] = sc
    return out


def scenario_faculty(dept: str, scenario: str) -> list:
    """The standard pool, changed as the scenario says (see evaluation/README.md)."""
    pool = dept_faculty(dept)
    tags = list(load_curriculum(dept)["specializations"])
    if scenario == "standard":
        return pool
    if scenario == "remove_one":
        return pool[1:]
    if scenario == "days_1":
        pool[0]["availability"] = ["Mon"]
        return pool
    if scenario == "days_2":
        pool[0]["availability"] = ["Mon", "Tue"]
        return pool
    if scenario == "add_with_tags":
        return pool + [make_faculty("Prof New", tags[:2])]
    if scenario == "add_no_tags":
        return pool + [make_faculty("Prof New", [])]
    raise ValueError(f"unknown scenario {scenario}")


# ── measuring one schedule (metric definitions of Part 19, fitness terms of Part 21) ──

def measure(rows, faculty, lookup, rooms, sizes, sections, groups_total, prefs) -> dict:
    fac_map = {f["name"]: f for f in faculty}
    assigned = [r for r in rows if r.get("faculty")]
    wl = workload_metrics(assigned, faculty)
    sp = _specialization_groups(assigned, fac_map, lookup)
    with use_rooms(rooms):
        terms = fitness_terms(rows, prefs, sizes)
        cap_pen = sum(-c for c in (capacity_term(a, sizes) for a in rows) if c < 0)
    switches, seen = 0, {}
    for a in assigned:
        if a.get("slot") and a.get("room") and a["room"] != "Unassigned":
            seen.setdefault((a["faculty"], a["slot"].split(":")[0].strip()), set()).add(get_building(a["room"]))
    switches = sum(len(b) - 1 for b in seen.values())
    gids = {r["group_id"] for r in assigned}
    return {
        "groups_assigned": len(gids), "groups_total": groups_total,
        "coverage_pct": round(100.0 * len(gids) / groups_total, 2) if groups_total else 0.0,
        # Hard-rule breaks only. A group nobody could staff is reported by coverage_pct, not counted here.
        "violations": len([v for v in validate_schedule(rows, faculty, lookup, rooms, sizes, sections)
                           if not str(v).startswith("UNCOVERED")]),
        "jain": round(wl["jain_exact"], 6), "cv": round(wl["cv"], 6), "min_load": wl["min"], "max_load": wl["max"],
        "zero_load": wl["zero_load_count"], "primary_tag_match_pct": sp["primary_tag_match_pct"],
        "preference_score": round(terms["preference"], 2), "capacity_penalty": round(cap_pen, 2),
        "building_switches": switches,
    }


def run_task(task: tuple) -> list:
    """One (scenario, department, semester, seed): the three methods. Top level so worker processes can run it."""
    scenario, dept, sem, seed, o = task
    ss.reset_state()
    faculty = scenario_faculty(dept, scenario)
    sizes = ss.get_class_sizes(dept)
    prep = ss.prepare_scheduling_input(dept, [], sem, sizes)
    sections, total = prep["sections"], len(prep["groups"])
    lookup, rooms = ss.build_static_lookup(dept), rooms_for(dept)
    prefs = standard_preferences(faculty)
    out = []

    def record(method, rows, seconds):
        m = measure(rows, faculty, lookup, rooms, sizes, sections, total, prefs)
        out.append({"scenario": scenario, "dept": dept, "semester": sem, "method": method, "seed": seed,
                    **m, "runtime_sec": round(seconds, 3)})

    with cfg.run_settings(seed=seed, deterministic=True, cp_sat_time_limit=o["cp_time"]):
        t = time.perf_counter()
        rows, _ = cps.solve(sections, faculty, lookup, rooms=rooms, baseline=True)
        record("random_baseline", rows, time.perf_counter() - t)

        t = time.perf_counter()
        cp_rows, _ = cps.solve(sections, faculty, lookup, rooms=rooms)
        cp_time = time.perf_counter() - t
        record("cp_sat", cp_rows, cp_time)

        t = time.perf_counter()
        ga_rows, _ = ga_optimizer.optimize(cp_rows, faculty, lookup, prefs, generations=o["generations"],
                                           population_size=o["population"], class_sizes=sizes, rooms=rooms,
                                           seed=seed, deterministic=True)
        record("cp_sat_ga", ga_rows, cp_time + time.perf_counter() - t)
    return out


# ── statistics and tables ─────────────────────────────────────────────────────

def stats(values: list) -> tuple:
    """(mean, sample standard deviation, 95% CI low, high). The CI uses Student's t."""
    n = len(values)
    if n == 0:
        return (float("nan"),) * 4
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    t = (T975[n - 2] if n - 1 <= len(T975) else 1.96) if n > 1 else 0.0
    half = t * sd / math.sqrt(n) if n > 1 else 0.0
    return mean, sd, mean - half, mean + half


def cell(values: list, dec: int) -> str:
    if not values:
        return "-"
    m, sd, lo, hi = stats(values)
    f = f"{{:.{dec}f}}"
    return f"{f.format(m)} ({f.format(sd)}) [{f.format(lo)}, {f.format(hi)}]"


def table(rows_by_method: dict, metrics: list) -> list:
    lines = ["| Metric | " + " | ".join(METHODS) + " |", "|---|" + "---|" * len(METHODS)]
    for col, label, dec in metrics:
        lines.append(f"| {label} | " + " | ".join(cell([r[col] for r in rows_by_method.get(m, [])], dec) for m in METHODS) + " |")
    return lines


def by_method(rows: list) -> dict:
    out = {m: [] for m in METHODS}
    for r in rows:
        out[r["method"]].append(r)
    return out


def write_summary(path: str, rows: list, o: dict) -> None:
    std = [r for r in rows if r["scenario"] == "standard"]
    scen = [r for r in rows if r["scenario"] != "standard"]
    L = ["# ATLAS PSU evaluation summary", "",
         f"Protocol: {o['seeds']} seeds per cell, deterministic mode, CP-SAT budget {o['cp_time']} deterministic seconds, "
         f"GA {o['generations']} generations x population {o['population']}. Cells show mean (sample SD) [95% CI, Student t]. "
         "Metric definitions: services/analytics_service.py (Part 19). Runtime is the only column that changes between invocations.",
         f"Runs: {len(rows)}. Hard violations over all runs: {sum(r['violations'] for r in rows)}.", ""]
    L += ["## Overall (all department-semesters pooled, standard pool)", ""] + table(by_method(std), METRICS) + [""]
    for dept in sorted({r["dept"] for r in std}):
        for sem in SEMS:
            sub = [r for r in std if r["dept"] == dept and r["semester"] == sem]
            if sub:
                L += [f"## {dept}, {sem}", ""] + table(by_method(sub), METRICS) + [""]
    if scen:
        cells = {(r["dept"], r["semester"]) for r in scen}
        L += ["## Scenarios", "", "Pooled over the department-semesters listed; the standard rows use the same cells. "
              + "Cells: " + ", ".join(f"{d} {s[:3]}" for d, s in sorted(cells)) + ".", ""]
        sm = [m for m in METRICS if m[0] in SCENARIO_METRICS]
        for sc in SCENARIOS:
            sub = [r for r in rows if r["scenario"] == sc and (r["dept"], r["semester"]) in cells]
            if sub:
                L += [f"### {sc}", ""] + table(by_method(sub), sm) + [""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> list:
    ap = argparse.ArgumentParser(description="ATLAS PSU evaluation harness")
    ap.add_argument("--seeds", type=int, default=10, help="seeds per cell (default 10)")
    ap.add_argument("--quick", action="store_true", help="2 seeds, short limits, scenarios on IT 1st semester only")
    ap.add_argument("--out", default=os.path.join(ROOT, "evaluation"), help="output folder")
    ap.add_argument("--depts", nargs="+", default=None, choices=DEPTS, help="departments (default all 5)")
    ap.add_argument("--cp-time", type=float, default=None, help="CP-SAT budget in deterministic seconds (default 15)")
    ap.add_argument("--generations", type=int, default=None)
    ap.add_argument("--population", type=int, default=None)
    ap.add_argument("--scenario-seeds", type=int, default=3, help="seeds per scenario cell (default 3)")
    ap.add_argument("--skip-scenarios", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="worker processes (results do not depend on it)")
    a = ap.parse_args(argv)

    o = {"seeds": 2 if a.quick else a.seeds, "cp_time": a.cp_time or (2.0 if a.quick else 15.0),
         "generations": a.generations or (4 if a.quick else 50), "population": a.population or (6 if a.quick else 20)}
    depts = a.depts or DEPTS
    scen_seeds = 1 if a.quick else a.scenario_seeds
    tasks = [("standard", d, s, seed, o) for d in depts for s in SEMS for seed in range(1, o["seeds"] + 1)]
    if not a.skip_scenarios:
        sd, ssem = ([depts[0]], [SEMS[0]]) if a.quick else (depts, SEMS)
        tasks += [(sc, d, s, seed, o) for sc in SCENARIOS[1:] for d in sd for s in ssem for seed in range(1, scen_seeds + 1)]

    rows, started = [], time.perf_counter()
    if a.jobs > 1:
        with ProcessPoolExecutor(max_workers=a.jobs) as pool:
            for i, part in enumerate(pool.map(run_task, tasks), 1):
                rows += part
                print(f"[{i}/{len(tasks)}] done", file=sys.stderr, flush=True)
    else:
        for i, t in enumerate(tasks, 1):
            rows += run_task(t)
            print(f"[{i}/{len(tasks)}] {t[0]} {t[1]} {t[2][:3]} seed {t[3]}  ({time.perf_counter() - started:.0f}s)",
                  file=sys.stderr, flush=True)

    key = {m: i for i, m in enumerate(METHODS)}
    rows.sort(key=lambda r: (SCENARIOS.index(r["scenario"]), r["dept"], r["semester"], key[r["method"]], r["seed"]))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "results.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    write_summary(os.path.join(a.out, "summary.md"), rows, o)
    print(f"wrote {len(rows)} rows to {a.out}", file=sys.stderr)
    return rows


if __name__ == "__main__":
    main()