"""
ATLAS PSU - solver/ga_optimizer.py

Phase 2: Genetic Algorithm Preference Optimizer

INPUT:  Valid CP-SAT schedule (all hard constraints satisfied)
OUTPUT: Improved schedule (higher preference satisfaction score)

Rules:
  - NEVER generates schedules from scratch
  - NEVER violates hard constraints
  - ONLY optimizes slots and rooms within valid assignments
  - Faculty assignments from CP-SAT are authoritative
"""

import copy
import random
import time
from typing import Callable, Optional

from solver.constraints import (
    faculty_available_at,
    room_exceeds_hard_max, get_building,
    validate_schedule, is_non_classroom,
)
from solver.objective_functions import schedule_fitness, fitness_terms
from config.rooms import current_rooms, use_rooms


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_fixed(a: dict) -> bool:
    """Rows the GA never touches: no slot/room (non-classroom) or no professor."""
    return is_non_classroom(a) or not a.get("faculty") or not a.get("slot")


def _faculty_unchanged(child: list, base: list) -> bool:
    """R8: the GA never changes who teaches what (same rows, same professor per row)."""
    return (len(child) == len(base) and
            all(c.get("faculty") == b.get("faculty") and c.get("meeting_id") == b.get("meeting_id")
                and c.get("group_id") == b.get("group_id") and c.get("lab_group") == b.get("lab_group")
                for c, b in zip(child, base)))


def _build_fac_slot_map(assignments: list) -> dict:
    """Returns {faculty_name: set of occupied slots}."""
    fsm: dict = {}
    for a in assignments:
        if _is_fixed(a):
            continue
        fsm.setdefault(a["faculty"], set()).add(a["slot"])
    return fsm


def _build_affinity_maps(assignments: list) -> tuple[dict, dict]:
    """
    Returns:
        fac_day_building  : {(fac_name, day) → dominant building}
        section_day_building: {(sec_key, day) → dominant building}

    Dominant building = most-used building for that faculty/section on that day.
    Used to guide _mutate_room toward building continuity.
    """
    from collections import Counter
    fac_day_counts:  dict = {}  # (fac, day) → Counter of buildings
    sec_day_counts:  dict = {}  # (sec, day) → Counter of buildings

    for a in assignments:
        slot = a.get("slot", "")
        room = a.get("room", "")
        if not slot or not room or room == "Unassigned" or _is_fixed(a):
            continue
        day = slot.split(":")[0].strip()
        bld = get_building(room)

        fac = a.get("faculty", "")
        if fac:
            fac_day_counts.setdefault((fac, day), Counter())[bld] += 1

        sec = a.get("section", "")
        if sec:
            sec_day_counts.setdefault((sec, day), Counter())[bld] += 1

    fac_day_building  = {k: v.most_common(1)[0][0] for k, v in fac_day_counts.items()}
    sec_day_building  = {k: v.most_common(1)[0][0] for k, v in sec_day_counts.items()}
    return fac_day_building, sec_day_building


def _slot_to_12h(slot_str: str) -> str:
    try:
        day_part, time_part = slot_str.split(":", 1)
        start_str, end_str = time_part.strip().split("-")
        def fmt(t: str) -> str:
            h, m = map(int, t.strip().split(":"))
            period = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"{h12}:{m:02d} {period}"
        return f"{day_part.strip()}: {fmt(start_str)} - {fmt(end_str)}"
    except Exception:
        return slot_str


def _all_slot_strings() -> list:
    from config.settings import TIME_SLOTS
    return [f"{d}: {h0:02d}:00-{h1:02d}:00" for d, h0, h1 in TIME_SLOTS]


ALL_SLOTS = _all_slot_strings()


# ── Mutation operators (hard-constraint-preserving) ───────────────────────────

def _mutate_slot_swap(assignments: list, faculty_list: list, soft_constraints: dict, rng=None) -> list:
    """
    Swap slots between two assignments of the SAME faculty.
    Preserves no-overlap hard constraint for that faculty.
    """
    rng = rng or random
    fac_map = {f["name"]: f for f in faculty_list}
    result = copy.deepcopy(assignments)

    # Group by faculty
    fac_indices: dict = {}
    for i, a in enumerate(result):
        if _is_fixed(a):
            continue
        fac_indices.setdefault(a["faculty"], []).append(i)

    for fac_name, idxs in fac_indices.items():
        if len(idxs) < 2:
            continue
        if rng.random() > 0.3:
            continue

        fac = fac_map.get(fac_name)
        if not fac:
            continue

        i, j = rng.sample(idxs, 2)
        a_i, a_j = result[i], result[j]

        # Hard: both new slots must be on available days
        if (faculty_available_at(fac, a_j["slot"]) and
                faculty_available_at(fac, a_i["slot"])):
            a_i["slot"], a_j["slot"] = a_j["slot"], a_i["slot"]
            a_i["slot_display"] = _slot_to_12h(a_i["slot"])
            a_j["slot_display"] = _slot_to_12h(a_j["slot"])

    return result


def _mutate_slot_shift(assignments: list, faculty_list: list, soft_constraints: dict, rng=None) -> list:
    """
    Relocate a single assignment to a different available slot for that faculty,
    ensuring no collision with that faculty's other assignments.
    Biases toward slots matching the faculty's preferred_period.
    """
    rng = rng or random
    fac_map = {f["name"]: f for f in faculty_list}
    result = copy.deepcopy(assignments)

    fsm = _build_fac_slot_map(result)
    movable = [i for i, x in enumerate(result) if not _is_fixed(x)]
    if not movable:
        return result
    idx = rng.choice(movable)
    a = result[idx]
    fac = fac_map.get(a["faculty"])
    if not fac:
        return result

    sc = soft_constraints.get(a["faculty"], {})
    preferred_period = sc.get("preferred_period")

    occupied = fsm.get(a["faculty"], set()) - {a["slot"]}
    candidates = [
        s for s in ALL_SLOTS
        if s not in occupied and faculty_available_at(fac, s)
    ]
    if not candidates:
        return result

    # Prefer slots matching preferred_period
    def period_score(s: str) -> int:
        try:
            h = int(s.split(":")[1].strip().split("-")[0].strip().split(":")[0])
        except Exception:
            return 0
        if preferred_period == "morning"   and 7  <= h < 12: return 1
        if preferred_period == "afternoon" and 12 <= h < 17: return 1
        if preferred_period == "evening"   and h >= 17:       return 1
        return 0

    if preferred_period:
        preferred = [s for s in candidates if period_score(s) > 0]
        if preferred:
            candidates = preferred

    new_slot = rng.choice(candidates)
    result[idx]["slot"] = new_slot
    result[idx]["slot_display"] = _slot_to_12h(new_slot)
    return result


def _mutate_room(assignments: list, soft_constraints: dict,
                 class_sizes: dict = None, rng=None) -> list:
    """
    Reassign room for a single assignment, respecting:
      - Room type compatibility (LAB → lab rooms only)
      - Capacity hard max (fall back to best available for labs - batch-split)
      - Room-slot conflicts
      - Per-day building affinity (faculty and section)
      - Explicit faculty room/building preferences
    """
    rng = rng or random
    import config.settings as _cfg
    result = copy.deepcopy(assignments)

    # Build affinity maps from current schedule
    fac_day_building, sec_day_building = _build_affinity_maps(result)

    room_slot_used = {f"{a['room']}|{a['slot']}" for a in result
                      if a["room"] != "Unassigned" and not _is_fixed(a)}
    movable = [i for i, x in enumerate(result) if not _is_fixed(x)]
    if not movable:
        return result
    idx = rng.choice(movable)
    a = result[idx]

    sc = soft_constraints.get(a["faculty"], {})
    preferred_room     = sc.get("preferred_room")
    preferred_building = sc.get("preferred_building")

    pool = current_rooms().pool(a["class_type"])
    current_key = f"{a['room']}|{a['slot']}"
    free_pool = [r for r in pool if f"{r}|{a['slot']}" not in room_slot_used - {current_key}]
    if not free_pool:
        return result

    # Student count
    student_count = a.get("student_count", 0)
    if student_count <= 0 and class_sizes:
        size_entry = class_sizes.get(a.get("section", ""))
        student_count = size_entry.get("size", 0) if isinstance(size_entry, dict) else 0

    # Hard capacity: a room whose max is below the student count is never chosen
    if student_count > 0:
        free_pool = [r for r in free_pool if not room_exceeds_hard_max(r, student_count)]
        if not free_pool:
            return result

    # Composite sort: capacity fit → building affinity → preference → usage
    slot = a.get("slot", "")
    day  = slot.split(":")[0].strip() if slot else ""
    fac_name = a.get("faculty", "")
    sec_key  = a.get("section", "")

    def _room_sort_key(r: str):
        from solver.constraints import get_room_capacity
        cap = get_room_capacity(r)
        rec = cap.get("recommended", 9999)
        if student_count > 0:
            over = max(0, student_count - rec)
            gap  = (rec - student_count) if student_count <= rec else -rec
        else:
            over, gap = 0, 0

        bld = get_building(r)

        # Building affinity (faculty + section)
        fac_bld = fac_day_building.get((fac_name, day))
        sec_bld = sec_day_building.get((sec_key, day))
        affinity = 1  # neutral
        if fac_bld:
            affinity = 0 if fac_bld == bld else 2
        if sec_bld:
            affinity = min(affinity, 0) if sec_bld == bld else max(affinity, 2)

        # Soft preference overrides
        pref_match = 0
        if preferred_room and r == preferred_room:
            pref_match = -2
        elif preferred_building and preferred_building.lower() in r.lower():
            pref_match = -1

        lab_for_lecture = 1 if (a["class_type"] != "LAB" and r in current_rooms().lab_rooms) else 0
        return (lab_for_lecture, over, affinity + pref_match, gap)

    free_pool.sort(key=_room_sort_key)
    new_room = free_pool[0]

    room_slot_used.discard(current_key)
    room_slot_used.add(f"{new_room}|{a['slot']}")
    result[idx]["room"] = new_room
    return result


# ── GA main loop ──────────────────────────────────────────────────────────────

def _crossover(parent_a: list, parent_b: list, faculty_list: list, static_lookup: dict,
                class_sizes: dict, rate: float, rng=None) -> list:
    """
    Uniform crossover between two valid schedules (slot/room only - faculty
    and subject per index are identical across the population by design).
    The result is validated against all hard constraints; if invalid,
    falls back to parent_a unchanged.
    """
    rng = rng or random
    if rng.random() > rate or len(parent_a) != len(parent_b) or not _faculty_unchanged(parent_b, parent_a):
        return copy.deepcopy(parent_a)

    child = copy.deepcopy(parent_a)
    for i in range(len(child)):
        if rng.random() < 0.5:
            child[i]["slot"] = parent_b[i]["slot"]
            child[i]["slot_display"] = parent_b[i]["slot_display"]
            child[i]["room"] = parent_b[i]["room"]

    violations = validate_schedule(child, faculty_list, static_lookup, current_rooms(), class_sizes)
    if violations:
        return copy.deepcopy(parent_a)
    return child


def optimize(
    base_schedule: list,
    faculty_list: list,
    static_lookup: dict,
    soft_constraints: dict,
    generations: int = 50,
    population_size: int = 20,
    mutation_rate: float = 0.15,
    crossover_rate: float = 0.8,
    progress_cb: Optional[Callable] = None,
    time_limit: float = 120.0,
    class_sizes: dict = None,
    rooms=None,
    seed: Optional[int] = None,
    deterministic: Optional[bool] = None,
) -> tuple[list, dict]:
    """
    Run GA preference optimizer over a valid CP-SAT schedule.
    `rooms` is the department's RoomSet (default: the active one).
    `seed` (default: the run's seed, see config.settings) feeds ONE random.Random used by every operator,
    so the same inputs and seed give the same schedule. `deterministic` (default: the run's flag) drops the
    wall-clock cap, because a time cut-off would make the result depend on machine load.
    """
    rs = rooms if rooms is not None else current_rooms()
    import config.settings as _cfg
    rng = random.Random(_cfg.run_seed() if seed is None else seed)
    if _cfg.is_deterministic() if deterministic is None else deterministic:
        time_limit = float("inf")
    with use_rooms(rs):
        return _optimize(base_schedule, faculty_list, static_lookup, soft_constraints,
                         generations, population_size, mutation_rate, crossover_rate,
                         progress_cb, time_limit, class_sizes, rng)


def _optimize(base_schedule, faculty_list, static_lookup, soft_constraints, generations,
              population_size, mutation_rate, crossover_rate, progress_cb, time_limit,
              class_sizes, rng) -> tuple:
    """
    Run GA preference optimizer over a valid CP-SAT schedule.

    Args:
        base_schedule: Valid schedule from CP-SAT solver (never modified)
        faculty_list, static_lookup, soft_constraints: domain data
        generations, population_size, mutation_rate: GA params
        progress_cb: callable(current_gen, total_gens)
        time_limit: wall-clock cap in seconds
        class_sizes: section → {size} mapping for capacity scoring

    Returns:
        (best_schedule, metrics)
    """
    t0 = time.time()

    if not base_schedule:
        return base_schedule, {"ga_time_sec": 0, "generations_run": 0, "improvement": 0.0}

    def fitness(sched):
        return schedule_fitness(sched, soft_constraints, class_sizes)

    base_fit = fitness(base_schedule)

    base_bad = len(validate_schedule(base_schedule, faculty_list, static_lookup, current_rooms(), class_sizes))

    def accept(child, fallback):
        """R8: a child that moves a professor or breaks a hard rule (R1 to R7) is rejected."""
        if not _faculty_unchanged(child, base_schedule):
            return fallback
        bad = len(validate_schedule(child, faculty_list, static_lookup, current_rooms(), class_sizes))
        return child if bad <= base_bad else fallback

    # Seed population from base schedule with perturbations
    population = [copy.deepcopy(base_schedule)]
    for _ in range(population_size - 1):
        ind = copy.deepcopy(base_schedule)
        for _ in range(3):
            op = rng.choice([_mutate_slot_swap, _mutate_slot_shift, _mutate_room])
            prev = ind
            if op == _mutate_room:
                ind = op(ind, soft_constraints, class_sizes, rng)
            else:
                ind = op(ind, faculty_list, soft_constraints, rng)
            ind = accept(ind, prev)
        population.append(ind)

    best = copy.deepcopy(base_schedule)
    best_fit = base_fit

    actual_generations = 0
    for gen in range(generations):
        if time.time() - t0 > time_limit:
            break

        # Evaluate
        scored = [(ind, fitness(ind)) for ind in population]
        scored.sort(key=lambda x: x[1], reverse=True)

        if scored[0][1] > best_fit:
            best = copy.deepcopy(scored[0][0])
            best_fit = scored[0][1]

        if progress_cb:
            progress_cb(gen + 1, generations)

        # Elitism + tournament selection
        elite_count = max(1, population_size // 5)
        new_pop = [copy.deepcopy(scored[i][0]) for i in range(elite_count)]

        while len(new_pop) < population_size:
            t1 = rng.choice(scored[:max(2, population_size // 2)])[0]
            t2 = rng.choice(scored[:max(2, population_size // 2)])[0]
            child = _crossover(t1, t2, faculty_list, static_lookup, class_sizes, crossover_rate, rng)

            if rng.random() < mutation_rate:
                op = rng.choice([
                    lambda s: _mutate_slot_swap(s, faculty_list, soft_constraints, rng),
                    lambda s: _mutate_slot_shift(s, faculty_list, soft_constraints, rng),
                    lambda s: _mutate_room(s, soft_constraints, class_sizes, rng),
                ])
                child = accept(op(child), child)

            new_pop.append(child)

        population = new_pop
        actual_generations = gen + 1

    # Final gate: if the best child is not valid, the CP-SAT schedule is returned unchanged.
    if best is not base_schedule and accept(best, None) is None:
        best, best_fit = copy.deepcopy(base_schedule), base_fit

    ga_time = round(time.time() - t0, 3)
    improvement = round(best_fit - base_fit, 2)
    t_base = fitness_terms(base_schedule, soft_constraints, class_sizes)
    t_final = fitness_terms(best, soft_constraints, class_sizes)
    improvement_terms = {k: round(t_final[k] - t_base[k], 2) for k in t_base}

    return best, {
        "ga_time_sec":      ga_time,
        "generations_run":  actual_generations,
        "base_fitness":     round(base_fit, 2),
        "final_fitness":    round(best_fit, 2),
        "improvement":      improvement,                 # final minus base fitness, GA-changeable terms only
        "improvement_terms": improvement_terms,          # {preference, capacity, affinity}
    }