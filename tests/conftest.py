import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


"""
Shared test fixtures and the ONE faculty-pool builder used by every test.

dept_faculty(dept): 10 professors, each holding 2 or 3 tags of that
department's `specializations`, every tag covered, available Mon to Thu,
max_units 24, absolute_max_units 30. Deterministic.

IT uses the pool the dashboard starts with (`default_faculty` in IT.json), so
the tests run on the real demo data. IT2B1 has 45 students, so its labs are not
split and it needs 15 meetings in the 20 Mon to Thu slots (with 48 students it
needed 21, which cannot fit: one meeting per block per slot, R4).
"""

import copy

from config.curriculum import load_curriculum
from services import schedule_service as ss

DAYS = ["Mon", "Tue", "Wed", "Thu"]
DEPTS = ["IT", "CS", "MB", "ES", "MedB"]
SEM1, SEM2 = "1st Semester", "2nd Semester"
SEMS = [SEM1, SEM2]
POOL_SIZE = 10


def make_faculty(name, spec, max_units=24, absolute_max=30, days=None):
    return {"name": name, "specialization": list(spec), "max_units": max_units,
            "absolute_max_units": absolute_max, "availability": list(days or DAYS)}


def _tag_demand(dept):
    """Units each tag has to teach (a course's units are shared by its tags), worst semester."""
    worst = {}
    for sem in SEMS:
        prep = ss.prepare_scheduling_input(dept, [], sem, ss.get_class_sizes(dept))
        demand = {}
        for sec in prep["sections"]:
            course = next(c for c in load_curriculum(dept)["courses"] if c["title"] == sec["name"])
            share = [t for t in course["specialization"] if t != "Elective"] or ["Elective"]
            units = 2
            for t in share:
                demand[t] = demand.get(t, 0) + units / len(share)
        for t, d in demand.items():
            worst[t] = max(worst.get(t, 0), d)
    return worst


def dept_faculty(dept, size=POOL_SIZE):
    """
    `size` professors, each holding 2 or 3 tags of the department, every tag of
    the department covered. Primary tags follow the teaching demand
    (largest remainder), so no tag is starved. Deterministic.
    """
    cur = load_curriculum(dept)
    if dept == "IT" and size == POOL_SIZE:
        return copy.deepcopy(cur["default_faculty"])
    tags = list(cur["specializations"])
    demand = {t: _tag_demand(dept).get(t, 0.0) for t in tags}
    holders = {t: 0 for t in tags}
    primaries = []
    for _ in range(size):
        t = max(tags, key=lambda x: (demand[x] / (holders[x] + 1), x))
        holders[t] += 1
        primaries.append(t)
    out = []
    for i, prim in enumerate(primaries):
        spec = [prim]
        want = 2 + (i % 2)                       # 2 or 3 tags
        while len(spec) < want:
            cand = [t for t in tags if t not in spec]
            # least covered first, then busiest, so secondary tags help where it is thin
            cand.sort(key=lambda t: (holders[t] if t != prim else 0, -demand[t], t))
            pick = cand[0]
            spec.append(pick)
            holders[pick] += 1
        out.append(make_faculty(f"Prof {chr(65 + i)}", spec))
    missing = [t for t in tags if holders[t] == 0]
    for t in missing:                            # make sure every tag is held by someone
        f = min((f for f in out if len(f["specialization"]) < 3), key=lambda f: len(f["specialization"]),
                default=out[-1])
        f["specialization"].append(t)
    return out


def legacy_subjects():
    """A non-empty request without group ids: the engine builds every group from the curriculum."""
    return [{"name": "x"}]