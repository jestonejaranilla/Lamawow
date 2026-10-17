"""
ATLAS PSU - services/analytics_service.py
Faculty Workload Analytics - Phase 3.
Pure computation - no Flask dependencies.
"""

import config.settings as _cfg_ana
from solver.constraints import (
    is_exact_spec_match, is_open_assignment, is_non_classroom, assignment_units,
    get_room_capacity, room_exceeds_hard_max, room_capacity_penalty,
)
from solver.objective_functions import compute_satisfaction_metrics, assignment_quality


def _gini(values: list) -> float:
    """Gini coefficient of non-negative values (0 = equal, toward 1 = one person has everything)."""
    n = len(values)
    total = sum(values)
    if n == 0 or total <= 0:
        return 0.0
    xs = sorted(values)
    weighted = sum((i + 1) * x for i, x in enumerate(xs))
    return (2.0 * weighted) / (n * total) - (n + 1.0) / n


def workload_metrics(assignments: list, faculty_list: list) -> dict:
    """
    THE one definition of workload fairness. Computed over ALL faculty (zero-load professors
    included) and in load UNITS (assignment_units), never in meeting rows.
    Saved runs (run_store.balance_score), Reports and the analytics payload all read this.
    """
    names = [f["name"] for f in faculty_list]
    loads = {name: 0 for name in names}
    for a in assignments or []:
        fac = a.get("faculty") if isinstance(a, dict) else None
        if fac in loads:
            loads[fac] += assignment_units(a)
    meta = {f["name"]: f for f in faculty_list}
    values = [loads[n] for n in names]
    n = len(values)
    total = sum(values)
    mean = total / n if n else 0.0
    var = sum((v - mean) ** 2 for v in values) / n if n else 0.0
    std = var ** 0.5
    sq = sum(v * v for v in values)
    jain = (total * total) / (n * sq) if n and sq else 0.0
    sorted_v = sorted(values)
    mid = n // 2
    median = 0.0 if not n else (sorted_v[mid] if n % 2 else (sorted_v[mid - 1] + sorted_v[mid]) / 2)
    per = []
    over_soft = over_hard = 0
    for name in names:
        soft = meta[name].get("max_units", 24)
        hard = meta[name].get("absolute_max_units", 30)
        over_soft += 1 if loads[name] > soft else 0
        over_hard += 1 if loads[name] > hard else 0
        per.append({"faculty": name, "units": loads[name], "max_units": soft, "absolute_max": hard})
    return {
        "unit": "load units (one scheduled meeting counts units_per_assignment units)",
        "faculty_count": n,
        "total_units": total,
        "mean": round(mean, 3),
        "median": round(median, 3),
        "min": min(values) if n else 0,
        "max": max(values) if n else 0,
        "std": round(std, 3),
        "cv": round(std / mean, 4) if mean > 0 else 0.0,
        "jain": round(jain, 4),
        "jain_exact": jain,
        "gini": round(_gini(values), 4),
        "zero_load_count": sum(1 for v in values if v == 0),
        "over_soft_cap_count": over_soft,
        "over_hard_cap_count": over_hard,
        "per_professor": per,
    }


def _specialization_groups(assignments: list, fac_map: dict, static_lookup: dict) -> dict:
    """
    Specialization match, counted per COURSE GROUP (year + section + subject), not per meeting row.
    Elective-only groups are excluded from the percentages and counted separately.
      primary_tag_match_pct: the course carries the professor's FIRST listed tag
      any_tag_match_pct:     the professor holds ANY tag of the course ("qualified"; 100 by design,
                             because the solver refuses unqualified professors)
    Both percentages are computed over groups that HAVE a professor. A group with no professor (any meeting without
    one) is counted in unassigned_group_count and left out of every percentage.
    """
    groups: dict = {}
    for a in assignments or []:
        key = (a.get("year", ""), a.get("section", ""), a.get("subject", ""))
        groups.setdefault(key, []).append(a)

    elective = scored = primary = qualified = unassigned = 0
    per_fac: dict = {}
    for (_y, _sec, subj), rows in groups.items():
        if any(not r.get("faculty") for r in rows):          # a group with no professor is reported on its own,
            unassigned += 1                                  # so the percentages describe the groups that have one
            continue
        if is_open_assignment(subj, static_lookup):
            elective += 1
            continue
        required = static_lookup.get(subj, [])
        facs = [fac_map.get(r.get("faculty", "")) for r in rows]
        scored += 1
        ok_any = all(f is not None and is_exact_spec_match(f, subj, static_lookup) for f in facs)
        ok_primary = all(f is not None and (f.get("specialization") or [None])[0] in required for f in facs)
        qualified += 1 if ok_any else 0
        primary += 1 if ok_primary else 0
        first = rows[0].get("faculty", "")
        if first:
            d = per_fac.setdefault(first, {"faculty": first, "groups": 0, "primary": 0, "qualified": 0})
            d["groups"] += 1
            d["primary"] += 1 if ok_primary else 0
            d["qualified"] += 1 if ok_any else 0
    return {
        "group_count": len(groups),
        "scored_group_count": scored,
        "elective_group_count": elective,
        "unassigned_group_count": unassigned,
        "primary_tag_match_count": primary,
        "any_tag_match_count": qualified,
        "primary_tag_match_pct": round(primary / scored * 100, 1) if scored else 0.0,
        "any_tag_match_pct": round(qualified / scored * 100, 1) if scored else 0.0,
        "per_faculty": sorted(per_fac.values(), key=lambda d: d["faculty"]),
    }


def compute_analytics(assignments: list, faculty_list: list, static_lookup: dict,
                       soft_constraints: dict, solver_metrics: dict,
                       class_sizes: dict = None) -> dict:
    """
    Compute all analytics from a completed schedule.

    Returns:
        Full analytics payload matching Phase 3 spec.
    """
    if not assignments or not faculty_list:
        return _empty_analytics()

    fac_map = {f["name"]: f for f in faculty_list}

    # ── Faculty load per person ───────────────────────────────────────────────
    fac_loads: dict = {f["name"]: 0 for f in faculty_list}
    fac_subjects: dict = {f["name"]: [] for f in faculty_list}
    for a in assignments:
        if a.get("faculty"):
            fac_loads[a["faculty"]] = fac_loads.get(a["faculty"], 0) + assignment_units(a)
            fac_subjects.setdefault(a["faculty"], []).append(a)

    # ── Faculty utilization ───────────────────────────────────────────────────
    faculty_utilization = []
    for f in faculty_list:
        name = f["name"]
        assigned = fac_loads.get(name, 0)
        available = f.get("max_units", 24)
        abs_max = f.get("absolute_max_units", 30)
        util_pct = round(assigned / available * 100, 1) if available > 0 else 0.0
        faculty_utilization.append({
            "faculty":         name,
            "assigned_units":  assigned,
            "max_units":       available,
            "absolute_max":    abs_max,
            "utilization_pct": util_pct,   # percent of regular load (max_units)
            "status": (
                "overload"   if assigned > abs_max  else
                "max_load"   if assigned > available else
                "normal"     if assigned > 0         else
                "unassigned"
            ),
        })

    # ── Workload distribution ─────────────────────────────────────────────────
    load_values = [fac_loads[f["name"]] for f in faculty_list]
    n = len(load_values) or 1
    mean_load = sum(load_values) / n
    sorted_loads = sorted(load_values)
    mid = n // 2
    median_load = (sorted_loads[mid] if n % 2 == 1
                   else (sorted_loads[mid - 1] + sorted_loads[mid]) / 2)

    max_units_per_fac = {f["name"]: f.get("max_units", 24) for f in faculty_list}
    abs_max_per_fac = {f["name"]: f.get("absolute_max_units", 30) for f in faculty_list}
    overload_count   = sum(1 for f in faculty_list if fac_loads[f["name"]] > abs_max_per_fac[f["name"]])
    at_max_count     = sum(1 for f in faculty_list if max_units_per_fac[f["name"]] < fac_loads[f["name"]] <= abs_max_per_fac[f["name"]])
    # Underload: 0 < load < target, target = total assigned units / number of professors (not max_units)
    target_load      = sum(load_values) / n
    underload_count  = sum(1 for f in faculty_list if 0 < fac_loads[f["name"]] < target_load)
    unassigned_count = sum(1 for f in faculty_list if fac_loads[f["name"]] == 0)

    workload_distribution = {
        "mean_load":        round(mean_load, 2),
        "median_load":      round(median_load, 2),
        "overload_count":   overload_count,
        "at_max_count":     at_max_count,
        "underload_count":  underload_count,
        "underload_target": round(target_load, 2),
        "unassigned_count": unassigned_count,
        "total_faculty":    len(faculty_list),
    }

    # ── Specialization metrics ────────────────────────────────────────────────
    total_assignments = len(assignments)
    exact_matches = 0
    mismatches = 0

    for a in assignments:
        fac = fac_map.get(a.get("faculty", ""))
        if not fac:
            mismatches += 1
            continue
        subj = a.get("subject", "")
        if is_open_assignment(subj, static_lookup):      # Elective-only courses: any professor
            exact_matches += 1
            continue
        if is_exact_spec_match(fac, subj, static_lookup):
            exact_matches += 1
        else:
            mismatches += 1

    spec_metrics = {
        "total_assignments": total_assignments,
        "exact_match_count": exact_matches,
        "mismatch_count":    mismatches,
        "exact_match_pct":   round(exact_matches / total_assignments * 100, 1) if total_assignments else 0.0,
        "mismatch_pct":      round(mismatches / total_assignments * 100, 1)    if total_assignments else 0.0,
        # exact_match_* above are legacy per-meeting counts (elective-only rows count as matches). The UI uses the group metrics below.
        **_specialization_groups(assignments, fac_map, static_lookup),
    }

    wl = workload_metrics(assignments, faculty_list)
    wl["bands"] = {"good": _cfg_ana.JAIN_BAND_GOOD, "warning": _cfg_ana.JAIN_BAND_WARNING}

    # ── Room utilization ──────────────────────────────────────────────────────
    from config.settings import TIME_SLOTS
    from config.rooms import current_rooms
    ALL_ROOMS = current_rooms().all_rooms
    total_slots = len(TIME_SLOTS)
    room_usage: dict = {}
    for a in assignments:
        if a.get("room") and a["room"] not in ("Unassigned", "N/A") and not is_non_classroom(a):
            room_usage[a["room"]] = room_usage.get(a["room"], 0) + 1

    room_utilization = []
    for room in ALL_ROOMS:
        used = room_usage.get(room, 0)
        occupancy_pct = round(used / total_slots * 100, 1)
        cap = get_room_capacity(room)
        room_utilization.append({
            "room":              room,
            "assigned_count":    used,
            "total_slots":       total_slots,
            "occupancy_pct":     occupancy_pct,
            "recommended_cap":   cap.get("recommended", "N/A"),
            "max_cap":           cap.get("max", "N/A"),
        })
    room_utilization.sort(key=lambda r: r["occupancy_pct"], reverse=True)

    # ── Room capacity metrics ─────────────────────────────────────────────────
    capacity_metrics = _compute_capacity_metrics(assignments, class_sizes)

    # ── Satisfaction metrics ──────────────────────────────────────────────────
    satisfaction = compute_satisfaction_metrics(
        assignments, faculty_list, soft_constraints, class_sizes
    )

    # ── Compose result ────────────────────────────────────────────────────────
    return {
        "faculty_utilization":    faculty_utilization,
        "workload_distribution":  workload_distribution,
        "workload_metrics":       wl,
        "specialization_metrics": spec_metrics,
        "room_utilization":       room_utilization,
        "capacity_metrics":       capacity_metrics,
        "satisfaction_metrics":   satisfaction,
        "optimization_metrics":   {
            "cp_sat_time_sec":   solver_metrics.get("solve_time_sec", 0),
            "ga_time_sec":       solver_metrics.get("ga_time_sec", 0),
            "total_runtime_sec": round(
                solver_metrics.get("solve_time_sec", 0) +
                solver_metrics.get("ga_time_sec", 0), 3
            ),
            "solver_used":       solver_metrics.get("solver_used", "unknown"),
            # GA improvement counts only terms the GA can change (slots and rooms): preference, capacity, affinity.
            "ga_improvement":    solver_metrics.get("improvement", 0),
            "ga_improvement_terms": solver_metrics.get("improvement_terms", {}),
            # CP-SAT decides the professors; this is reporting only and no GA term.
            "assignment_quality": assignment_quality(assignments, faculty_list, static_lookup),
            "ga_generations_run": solver_metrics.get("generations_run", 0),
        },
    }


def _compute_capacity_metrics(assignments: list, class_sizes: dict = None) -> dict:
    """
    Compute room capacity analytics across all assignments.
    Returns counts and per-assignment detail for capacity violations.
    """
    if not assignments:
        return _empty_capacity_metrics()

    within_recommended = 0
    over_recommended = 0
    hard_violations = []
    penalty_total = 0.0
    capacity_details = []

    for a in assignments:
        room = a.get("room", "")
        if not room or room in ("Unassigned", "N/A") or is_non_classroom(a):
            continue

        section_key = a.get("section", "")
        student_count = a.get("student_count", 0)

        # Supplement from class_sizes if not embedded
        if student_count <= 0 and class_sizes and section_key:
            size_entry = class_sizes.get(section_key)
            student_count = size_entry.get("size", 0) if isinstance(size_entry, dict) else 0

        # Year-based fallback when section is empty (per-subject scheduling)
        if student_count <= 0 and class_sizes:
            year = a.get("year", "")
            if year:
                year_sizes = [
                    v.get("size", 0) for v in class_sizes.values()
                    if isinstance(v, dict) and v.get("year") == year and v.get("size", 0) > 0
                ]
                if year_sizes:
                    student_count = max(year_sizes)

        if student_count <= 0:
            continue

        cap = get_room_capacity(room)
        recommended = cap.get("recommended", 9999)
        max_cap = cap.get("max", 9999)
        is_hard_violation = room_exceeds_hard_max(room, student_count)
        penalty = room_capacity_penalty(room, student_count) if not is_hard_violation else -(student_count * 10)

        status = "ok"
        if is_hard_violation:
            status = "hard_violation"
            hard_violations.append({
                "room":          room,
                "section":       section_key,
                "subject":       a.get("subject", ""),
                "student_count": student_count,
                "max_cap":       max_cap,
                "excess":        student_count - max_cap,
            })
        elif student_count > recommended:
            status = "over_recommended"
            over_recommended += 1
        else:
            within_recommended += 1

        penalty_total += penalty

        capacity_details.append({
            "room":            room,
            "section":         section_key,
            "subject":         a.get("subject", ""),
            "student_count":   student_count,
            "recommended_cap": recommended,
            "max_cap":         max_cap,
            "status":          status,
            "capacity_penalty": round(penalty, 2),
        })

    total_evaluated = within_recommended + over_recommended + len(hard_violations)

    return {
        "within_recommended_count": within_recommended,
        "over_recommended_count":   over_recommended,
        "hard_violation_count":     len(hard_violations),
        "total_evaluated":          total_evaluated,
        "within_recommended_pct":   round(within_recommended / total_evaluated * 100, 1) if total_evaluated else 0.0,
        "total_capacity_penalty":   round(penalty_total, 2),
        "hard_violations":          hard_violations,
        "capacity_details":         capacity_details,
    }


def _empty_analytics() -> dict:
    return {
        "faculty_utilization":    [],
        "workload_distribution":  {},
        "workload_metrics":       {},
        "specialization_metrics": {},
        "room_utilization":       [],
        "capacity_metrics":       _empty_capacity_metrics(),
        "satisfaction_metrics":   {},
        "optimization_metrics":   {},
    }


def _empty_capacity_metrics() -> dict:
    return {
        "within_recommended_count": 0,
        "over_recommended_count":   0,
        "hard_violation_count":     0,
        "total_evaluated":          0,
        "within_recommended_pct":   0.0,
        "total_capacity_penalty":   0.0,
        "hard_violations":          [],
        "capacity_details":         [],
    }