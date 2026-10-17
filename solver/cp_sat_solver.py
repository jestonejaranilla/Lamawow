"""
ATLAS PSU - solver/cp_sat_solver.py

Phase 1: CP-SAT constraint solver. Source of truth for schedule generation.

Model (OR-Tools CP-SAT):
  z[g,f]     group g is taught by faculty f  (exactly one f per covered group - R2)
  x[m,f,t]   meeting m is held at slot t by faculty f, and x <= z[group(m), f]
  cover[g]   group g is covered. Coverage is optional inside the model and
             rewarded far above everything else, so an impossible group becomes
             an explicit coverage error instead of making the whole model fail
             or being skipped silently (R3).

Hard rules in the model:
  R1/R3  every group is covered or reported with a reason
  R2     one professor per group (all meetings, all lab sub-groups)
  R4     a block never has two meetings in one slot
  R5     room capacity by `max`: lecture rooms for LECTURE, lab rooms for LAB;
         labs larger than the largest lab room are split into
         k = ceil(size / maxLab) groups (IT1B1-L1, IT1B1-L2) with the same
         professor and different slots
  R6     no room double-booking. Rooms are decided with exact per-slot
         constraints: rooms are eligible by a `max >= students` threshold, so
         eligibility sets are nested and Hall's condition is both necessary and
         sufficient. For every slot and every demand level d the model bounds
         the meetings needing >= d seats by the number of rooms with max >= d.
         The concrete room names are then picked by a matching that is
         guaranteed to succeed.
  R7     load <= absolute_max_units (hard), soft penalty above max_units
  R9     availability is day based
Objective: exact specialization, same professor for the same course across
blocks, balanced load, little overload.

Time limit: never above CP_SAT_MAX_TIME_LIMIT_SECONDS (< 45 s). The best solution found
is returned.

Fallback (OR-Tools missing): a greedy group-level solver that obeys the same
hard rules (same helpers, same room matching). It is not optimal and may leave
groups uncovered; it reports them exactly like the CP-SAT path.
"""

import os
import random
import time
from typing import Callable, Optional

import config.settings as _cfg
from config.settings import TIME_SLOTS
from config.rooms import current_rooms, use_rooms
from solver.constraints import (
    faculty_qualifies, faculty_available_at, is_exact_spec_match,
    is_open_assignment, assignment_units, NON_CLASSROOM,
    get_room_capacity, room_max, max_room_capacity, lab_split_plan,
    validate_schedule,
)

# ── Settings helpers ──────────────────────────────────────────────────────────

def _upa() -> int:
    return _cfg.units_per_assignment()


def _search_workers() -> int:
    """CP-SAT search workers: one per CPU, at most 8 (a small Render instance must not run 8 threads on 1 core)."""
    return max(1, min(8, os.cpu_count() or 1))


def _time_limit() -> float:
    asked = _cfg.cp_sat_time_limit()
    cap = float(getattr(_cfg, "CP_SAT_MAX_TIME_LIMIT_SECONDS", 40.0))
    return max(1.0, min(asked, cap, 44.0))


def _weights() -> dict:
    return dict(getattr(_cfg, "CP_WEIGHTS", {}))


# ── Slot helpers ──────────────────────────────────────────────────────────────

def _slot_str(d: str, h_start: int, h_end: int) -> str:
    return f"{d}: {h_start:02d}:00-{h_end:02d}:00"


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


ALL_SLOT_STRINGS = [_slot_str(t[0], t[1], t[2]) for t in TIME_SLOTS]


# ── Rooms: pools and exact matching ───────────────────────────────────────────

def _pool_rooms(kind: str) -> list:
    """Rooms of the ACTIVE department for a kind of meeting (see config.rooms)."""
    return current_rooms().pool(kind)


def _room_cost(room: str, kind: str, size: int) -> tuple:
    """Preference order for a room: lecture rooms before lab rooms, then the best fit."""
    rs = current_rooms()
    rec = get_room_capacity(room).get("recommended", 9999)
    try:
        rec = int(rec)
    except (TypeError, ValueError):
        rec = 9999
    lab_for_lecture = 1 if (kind != "LAB" and room in rs.lab_rooms) else 0
    over = max(0, size - rec)
    gap = (rec - size) if size <= rec else -rec
    return (lab_for_lecture, over, gap, room)


def _match(demands: list):
    """
    Exact bipartite matching of the meetings held in ONE slot to rooms.
    demands: [(key, kind, size)]. Returns {key: room}, or None when some
    meeting cannot get its own eligible room (a room fits a meeting when it is
    in the pool of the meeting's kind and its `max` >= students).
    """
    rs = current_rooms()
    adj = {}
    for key, kind, size in demands:
        elig = [r for r in rs.pool(kind) if rs.max_of(r) >= size]
        elig.sort(key=lambda r: _room_cost(r, kind, size))
        adj[key] = elig
    owner: dict = {}

    def augment(k, seen):
        for r in adj[k]:
            if r in seen:
                continue
            seen.add(r)
            if r not in owner or augment(owner[r], seen):
                owner[r] = k
                return True
        return False

    for key, _, _ in sorted(demands, key=lambda d: (len(adj[d[0]]), str(d[0]))):
        if not augment(key, set()):
            return None
    return {k: r for r, k in owner.items()}


# ── Preparation: meetings, groups, per-group diagnostics ──────────────────────

def _gid(sec: dict) -> str:
    return sec.get("group_id") or f"{sec.get('section', '')}|{sec.get('name', '')}"


def _build_meetings(classroom_sections: list, max_lab: int) -> list:
    """One entry per slot to schedule. Oversized labs become k sub-meetings."""
    meetings = []
    for sec in classroom_sections:
        size = int(sec.get("student_count", 0) or 0)
        kind = sec.get("class_type", "LECTURE")
        label_base = sec.get("section", "")
        if kind == "LAB" and max_lab > 0 and size > max_lab:
            k, sub = lab_split_plan(size, max_lab)
            parts = [(f"{label_base}-L{i + 1}", sub) for i in range(k)]
        else:
            parts = [("", size)]
        for i, (label, sz) in enumerate(parts):
            meetings.append({
                "idx":   len(meetings),
                "sec":   sec,
                "gid":   _gid(sec),
                "block": sec.get("section", ""),
                "kind":  kind,
                "size":  sz,
                "label": label,
            })
    return meetings


def _group_table(sections: list, meetings: list, faculty_list: list, static_lookup: dict) -> dict:
    """
    {gid: group} with its meetings, units, eligible faculty and, when the group
    can never be covered, a reason (these groups stay out of the model).
    """
    groups: dict = {}
    for m in meetings:
        g = groups.setdefault(m["gid"], {
            "gid": m["gid"], "sec": m["sec"], "title": m["sec"].get("name", ""),
            "code": m["sec"].get("course_code", ""), "block": m["block"],
            "meetings": [], "non": False, "units": 0, "fac": [], "reason": None,
        })
        g["meetings"].append(m["idx"])
    for sec in sections:
        if sec.get("class_type") == NON_CLASSROOM:
            gid = _gid(sec)
            groups[gid] = {
                "gid": gid, "sec": sec, "title": sec.get("name", ""),
                "code": sec.get("course_code", ""), "block": sec.get("section", ""),
                "meetings": [], "non": True, "units": 0, "fac": [], "reason": None,
            }

    slots_by_fac = [sum(1 for s in ALL_SLOT_STRINGS if faculty_available_at(f, s))
                    for f in faculty_list]

    for g in groups.values():
        if g["non"]:
            g["units"] = assignment_units({"class_type": NON_CLASSROOM})
        else:
            g["units"] = len(g["meetings"]) * _upa()
        qualified = [i for i, f in enumerate(faculty_list)
                     if faculty_qualifies(f, g["title"], static_lookup)]
        if not qualified:
            g["reason"] = "no qualified faculty"
            continue
        if not g["non"]:
            # Rooms: every meeting needs some room with enough seats
            for idx in g["meetings"]:
                m = meetings[idx]
                if not any(room_max(r) >= m["size"] for r in _pool_rooms(m["kind"])):
                    g["reason"] = ("no laboratory room available" if m["kind"] == "LAB"
                                   else f"no lecture room fits {m['size']} students")
                    break
            if g["reason"]:
                continue
            need = len(g["meetings"])
            qualified = [i for i in qualified if slots_by_fac[i] >= need]
            if not qualified:
                g["reason"] = "no available day"
                continue
        qualified = [i for i in qualified
                     if g["units"] <= faculty_list[i].get("absolute_max_units", 30)]
        if not qualified:
            g["reason"] = "load cap reached"
            continue
        g["fac"] = qualified
    return groups


def _uncovered_reason(g: dict, faculty_list: list, loads: dict) -> str:
    """Reason for a group the optimizer left out although it looked possible alone."""
    if g["reason"]:
        return g["reason"]
    if all(loads.get(faculty_list[i]["name"], 0) + g["units"]
           > faculty_list[i].get("absolute_max_units", 30) for i in g["fac"]):
        return "load cap reached"
    return "no conflict-free slot and room found"


# ── CP-SAT model ──────────────────────────────────────────────────────────────

def _solve_with_ortools(meetings: list, groups: dict, faculty_list: list,
                        static_lookup: dict, progress_cb: Optional[Callable] = None):
    """Returns (plan, info), or None when OR-Tools is not installed."""
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None

    W = _weights()
    t_limit = _time_limit()
    n_slots = len(ALL_SLOT_STRINGS)
    avail = [[faculty_available_at(f, s) for s in ALL_SLOT_STRINGS] for f in faculty_list]

    model = cp_model.CpModel()
    live = [g for g in groups.values() if not g["reason"]]

    cover, z = {}, {}
    for g in live:
        cover[g["gid"]] = model.NewBoolVar(f"cover_{g['gid']}")
        for f in g["fac"]:
            z[(g["gid"], f)] = model.NewBoolVar(f"z_{g['gid']}_{f}")
        # R2: exactly one professor when covered
        model.Add(sum(z[(g["gid"], f)] for f in g["fac"]) == cover[g["gid"]])

    # x[m,f,t] <= z[group(m), f]; each covered meeting gets exactly one (f, t)
    x = {}
    xs_mt = {}    # (m, t) -> [vars]
    xs_ft = {}    # (f, t) -> [vars]
    for g in live:
        if g["non"]:
            continue
        for mi in g["meetings"]:
            all_vars = []
            for f in g["fac"]:
                for t in range(n_slots):
                    if not avail[f][t]:
                        continue
                    v = model.NewBoolVar(f"x_{mi}_{f}_{t}")
                    x[(mi, f, t)] = v
                    model.AddImplication(v, z[(g["gid"], f)])
                    all_vars.append(v)
                    xs_mt.setdefault((mi, t), []).append(v)
                    xs_ft.setdefault((f, t), []).append(v)
            model.Add(sum(all_vars) == cover[g["gid"]])

    # Faculty: one meeting per slot
    for vs in xs_ft.values():
        if len(vs) > 1:
            model.AddAtMostOne(vs)

    # R4: a block never has two meetings in one slot
    by_block: dict = {}
    for m in meetings:
        if m["block"] and not groups[m["gid"]]["reason"]:
            by_block.setdefault(m["block"], []).append(m["idx"])
    for idxs in by_block.values():
        for t in range(n_slots):
            vs = [v for mi in idxs for v in xs_mt.get((mi, t), [])]
            if len(vs) > 1:
                model.AddAtMostOne(vs)

    # R5/R6: rooms, decided in the model. Rooms with the same kind, hard max and
    # recommended size form a TYPE. For every slot, f[class, type, slot] counts
    # how many meetings of a (kind, students) class sit in rooms of a type:
    #   sum over types f == meetings of the class held in that slot
    #   sum over classes f <= rooms of the type
    # This is an exact transportation model (works when lecture and lab rooms
    # overlap, as in the science departments), so every solution has a real room
    # for every meeting, always with `max` >= students.
    rs = current_rooms()
    types: dict = {}
    for r in rs.all_rooms:
        cap = get_room_capacity(r)
        try:
            rec = int(cap.get("recommended", 9999))
        except (TypeError, ValueError):
            rec = 9999
        key = (r in rs.lab_rooms, r in rs.lecture_rooms, room_max(r), rec)
        types.setdefault(key, {"rooms": [], "lab": key[0], "max": key[2], "rec": rec})["rooms"].append(r)
    live_m = [m for m in meetings if not groups[m["gid"]]["reason"]]
    class_keys = sorted({(m["kind"], m["size"]) for m in live_m})
    class_of = {m["idx"]: class_keys.index((m["kind"], m["size"])) for m in live_m}
    compat = {}
    for ci, (kind, size) in enumerate(class_keys):
        pool = set(rs.pool(kind))
        compat[ci] = [k for k, info in types.items()
                      if info["rooms"][0] in pool and info["max"] >= size]
    rv = {}                      # (class, type, slot) -> room-count variable
    type_terms: dict = {}
    room_cost = []
    for ci, (kind, size) in enumerate(class_keys):
        mids = [m["idx"] for m in live_m if class_of[m["idx"]] == ci]
        for t in range(n_slots):
            xv = [v for mi in mids for v in xs_mt.get((mi, t), [])]
            if not xv:
                continue
            fs = []
            for k in compat[ci]:
                info = types[k]
                fv = model.NewIntVar(0, len(info["rooms"]), f"f_{ci}_{len(rv)}")
                rv[(ci, k, t)] = fv
                fs.append(fv)
                type_terms.setdefault((k, t), []).append(fv)
                pen = 0
                if kind != "LAB" and info["lab"]:
                    pen += W.get("lab_for_lecture", 20)
                pen += W.get("room_over", 1) * max(0, size - info["rec"])
                if pen:
                    room_cost.append(pen * fv)
            model.Add(sum(fs) == sum(xv))
    for (k, t), fvs in type_terms.items():
        model.Add(sum(fvs) <= len(types[k]["rooms"]))

    # R7: load. The hard cap is the variable's domain.
    loads, over = [], []
    load_of = {}                 # faculty index -> load variable
    for fi, fac in enumerate(faculty_list):
        terms = [g["units"] * z[(g["gid"], fi)] for g in live if (g["gid"], fi) in z]
        if not terms:
            continue
        abs_max = int(fac.get("absolute_max_units", 30))
        soft = int(fac.get("max_units", 24))
        load = model.NewIntVar(0, abs_max, f"load_{fi}")
        model.Add(load == sum(terms))
        ov = model.NewIntVar(0, max(0, abs_max - soft), f"over_{fi}")
        model.Add(ov >= load - soft)
        loads.append(load)
        load_of[fi] = load
        over.append(ov)
    top = model.NewIntVar(0, 1000, "top_load")
    for ld in loads:
        model.Add(top >= ld)

    # Objective
    obj = []
    for g in live:
        n = max(1, len(g["meetings"]))
        obj.append(W.get("uncovered_group", 1_000_000) * n * cover[g["gid"]])
        if not is_open_assignment(g["title"], static_lookup):
            for f in g["fac"]:
                if is_exact_spec_match(faculty_list[f], g["title"], static_lookup):
                    obj.append(W.get("exact_spec", 40) * n * z[(g["gid"], f)])
    by_course: dict = {}
    for g in live:
        by_course.setdefault(g["code"] or g["title"], []).append(g)
    for course, gs in by_course.items():
        if len(gs) < 2:
            continue
        for f in {f for g in gs for f in g["fac"]}:
            u = model.NewBoolVar(f"u_{course}_{f}")
            for g in gs:
                if (g["gid"], f) in z:
                    model.AddImplication(z[(g["gid"], f)], u)
            obj.append(-W.get("course_professor", 30) * u)
    for ov in over:
        obj.append(-W.get("over_soft_cap", 25) * ov)
    obj.append(-W.get("load_balance", 3) * top)

    # Fair share: every professor who CAN teach is pulled toward the average load. Without this term
    # only the busiest professor was priced, so adding or removing a professor, or changing days,
    # let the solver leave some professors with little or no teaching load.
    # target = average units per professor, capped by what that professor can actually take
    # (qualified courses, available slots, hard cap), so nobody is pushed beyond what is possible.
    fair_w = W.get("fair_share", 10)
    if fair_w:
        total_units = sum(g["units"] for g in live)
        can_teach = []
        for fi, fac in enumerate(faculty_list):
            pot = sum(g["units"] for g in live if (g["gid"], fi) in z)
            slot_cap = sum(1 for t in range(n_slots) if avail[fi][t]) * _upa()
            cap = min(pot, slot_cap, int(fac.get("absolute_max_units", 30)))
            if cap > 0:
                can_teach.append((fi, cap))
        if can_teach and total_units:
            target = total_units // len(can_teach)
            by_fi = load_of
            for fi, cap in can_teach:
                want = min(target, cap, int(faculty_list[fi].get("max_units", 24)))
                if want <= 0 or fi not in by_fi:
                    continue
                short = model.NewIntVar(0, want, f"short_{fi}")
                model.Add(short >= want - by_fi[fi])
                obj.append(-fair_w * short)
    obj.extend(-c for c in room_cost)
    model.Maximize(sum(obj))

    solver = cp_model.CpSolver()
    if _cfg.is_deterministic():
        # One worker and a deterministic-time limit: the same model and seed give the same answer on any machine load.
        solver.parameters.num_search_workers = 1
        solver.parameters.max_deterministic_time = t_limit
        solver.parameters.max_time_in_seconds = float(getattr(_cfg, "DETERMINISTIC_WALL_CAP_SECONDS", 300.0))
    else:
        solver.parameters.max_time_in_seconds = t_limit
        solver.parameters.num_search_workers = _search_workers()
    solver.parameters.random_seed = _cfg.run_seed()

    t_start = time.time()

    class _Progress(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self):
            if progress_cb:
                progress_cb(min(time.time() - t_start, t_limit), t_limit)

    status = solver.Solve(model, _Progress())
    if progress_cb:
        progress_cb(1, 1)

    names = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
             cp_model.INFEASIBLE: "INFEASIBLE", cp_model.UNKNOWN: "UNKNOWN",
             cp_model.MODEL_INVALID: "MODEL_INVALID"}
    info = {"status": names.get(status, str(status)), "time": round(time.time() - t_start, 3)}

    plan = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        info["objective"] = solver.ObjectiveValue()
        info["bound"] = solver.BestObjectiveBound()
        for g in live:
            if not solver.Value(cover[g["gid"]]):
                continue
            fac = next(f for f in g["fac"] if solver.Value(z[(g["gid"], f)]))
            slots = {}
            for mi in g["meetings"]:
                for t in range(n_slots):
                    v = x.get((mi, fac, t))
                    if v is not None and solver.Value(v):
                        slots[mi] = t
                        break
            plan[g["gid"]] = {"fac": fac, "slots": slots}
        info["rooms"] = _rooms_from_model(solver, plan, rv, types, compat, class_of)
    return plan, info


def _rooms_from_model(solver, plan, rv, types, compat, class_of) -> dict:
    """Concrete room names from the f counts: {meeting_idx: room}."""
    per = {}
    for p in plan.values():
        for mi, t in p["slots"].items():
            per.setdefault((class_of[mi], t), []).append(mi)
    usage: dict = {}
    used_in_slot: dict = {}
    out = {}
    for (ci, t), mis in sorted(per.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        mis.sort()
        pos = 0
        for k in compat[ci]:
            n = solver.Value(rv[(ci, k, t)]) if (ci, k, t) in rv else 0
            for _ in range(n):
                taken = used_in_slot.setdefault(t, set())
                free = [r for r in types[k]["rooms"] if r not in taken]
                free.sort(key=lambda r: (usage.get(r, 0), r))
                room = free[0]
                taken.add(room)
                usage[room] = usage.get(room, 0) + 1
                out[mis[pos]] = room
                pos += 1
    return out


# ── Greedy fallback (same hard rules, no optimality) ──────────────────────────

def _solve_greedy(meetings: list, groups: dict, faculty_list: list, static_lookup: dict,
                  progress_cb: Optional[Callable] = None, randomize: bool = False):
    """
    The greedy group-level solver. randomize=True is the evaluation BASELINE (random-feasible): groups are taken in
    random order, each goes to a random qualified professor and random free slots, and only the hard rules decide
    what is allowed (availability, one meeting per professor, block and room per slot, the absolute load cap).
    """
    deadline = time.time() + (float(getattr(_cfg, "DETERMINISTIC_WALL_CAP_SECONDS", 300.0))
                              if _cfg.is_deterministic() else _time_limit())
    rng = random.Random(_cfg.run_seed())
    n_slots = len(ALL_SLOT_STRINGS)

    fac_slots = {i: set() for i in range(len(faculty_list))}
    block_slots: dict = {}
    slot_demands: dict = {}          # t -> [(key, kind, size)]
    loads = {i: 0 for i in range(len(faculty_list))}
    plan = {}

    live = [g for g in groups.values() if not g["reason"]]
    live.sort(key=lambda g: (len(g["fac"]), -g["units"], g["gid"]))
    if randomize:
        live.sort(key=lambda g: g["gid"])           # a fixed start, so the seed alone decides the shuffle
        rng.shuffle(live)

    for gi, g in enumerate(live):
        if progress_cb:
            progress_cb(gi, len(live))
        if time.time() > deadline:
            break
        open_course = is_open_assignment(g["title"], static_lookup)
        options = sorted(g["fac"], key=lambda f: (
            (not open_course) and not is_exact_spec_match(faculty_list[f], g["title"], static_lookup),
            loads[f] + g["units"] > faculty_list[f].get("max_units", 24),
            loads[f], rng.random()))
        if randomize:
            options = sorted(g["fac"])
            rng.shuffle(options)
        for f in options:
            if loads[f] + g["units"] > faculty_list[f].get("absolute_max_units", 30):
                continue
            if g["non"]:
                plan[g["gid"]] = {"fac": f, "slots": {}}
                loads[f] += g["units"]
                break
            placed, ok = {}, True
            for mi in sorted(g["meetings"], key=lambda i: -meetings[i]["size"]):
                m = meetings[mi]
                day_count: dict = {}
                for t2 in block_slots.get(m["block"], set()) | set(placed.values()):
                    d = ALL_SLOT_STRINGS[t2].split(":")[0]
                    day_count[d] = day_count.get(d, 0) + 1
                cand = []
                for t in range(n_slots):
                    if not faculty_available_at(faculty_list[f], ALL_SLOT_STRINGS[t]):
                        continue
                    if t in fac_slots[f] or t in placed.values():
                        continue
                    if m["block"] and t in block_slots.get(m["block"], set()):
                        continue
                    demands = list(slot_demands.get(t, [])) + [
                        (o, meetings[o]["kind"], meetings[o]["size"])
                        for o, tt in placed.items() if tt == t]
                    if _match(demands + [(mi, m["kind"], m["size"])]) is None:
                        continue
                    cand.append((day_count.get(ALL_SLOT_STRINGS[t].split(":")[0], 0), t))
                if not cand:
                    ok = False
                    break
                placed[mi] = rng.choice(cand)[1] if randomize else min(cand)[1]
            if not ok:
                continue
            for mi, t in placed.items():
                m = meetings[mi]
                fac_slots[f].add(t)
                block_slots.setdefault(m["block"], set()).add(t)
                slot_demands.setdefault(t, []).append((mi, m["kind"], m["size"]))
            loads[f] += g["units"]
            plan[g["gid"]] = {"fac": f, "slots": placed}
            break
    if progress_cb:
        progress_cb(1, 1)
    return plan, {"status": "GREEDY", "time": 0.0}


# ── Output rows ───────────────────────────────────────────────────────────────

def _ids(sec: dict) -> dict:
    return {
        "group_id":    sec.get("group_id", ""),
        "course_code": sec.get("course_code", ""),
        "meeting_id":  sec.get("meeting_id", ""),
    }


def _row(sec: dict, faculty: str, slot: Optional[str], room: str, class_type: str,
         student_count: int, lab_group: str = "") -> dict:
    return {
        "faculty":       faculty,
        "subject":       sec["name"],
        "type":          sec.get("type", "Core Theory"),
        "class_type":    class_type,
        "slot":          slot,
        "slot_display":  _slot_to_12h(slot) if slot else ("N/A" if class_type == NON_CLASSROOM else "Unscheduled"),
        "semester":      sec.get("semester", ""),
        "year":          sec.get("year", ""),
        "section":       sec.get("section", ""),
        "room":          room,
        "student_count": student_count,
        "lab_group":     lab_group,
        **_ids(sec),
    }


def _prefer_lecture_rooms(chosen: dict, plan: dict, meetings: list) -> None:
    """
    Soft rule: a lecture sits in a lecture room (CSLR, GE Bldg) whenever one is
    free in its slot; a lab room (Physics Room) hosts a lecture only when no
    lecture room fits. Applied to the final room names, so it holds even when
    the CP-SAT search stopped at its time limit. Only moves a meeting to a free,
    large-enough room of the same slot, so every hard rule still holds.
    """
    rs = current_rooms()
    if not rs.lab_also_lecture:
        return
    slot_of = {mi: t for p in plan.values() for mi, t in p["slots"].items()}
    used: dict = {}
    for mi, room in chosen.items():
        used.setdefault(slot_of[mi], set()).add(room)
    for mi in sorted(chosen):
        m = meetings[mi]
        if m["kind"] != "LECTURE" or chosen[mi] not in rs.lab_rooms:
            continue
        t = slot_of[mi]
        free = [r for r in rs.lecture_rooms if r not in rs.lab_rooms
                and r not in used[t] and rs.max_of(r) >= m["size"]]
        if free:
            free.sort(key=lambda r: _room_cost(r, "LECTURE", m["size"]))
            used[t].discard(chosen[mi])
            chosen[mi] = free[0]
            used[t].add(free[0])


def _build_rows(plan: dict, groups: dict, meetings: list, faculty_list: list,
                chosen_room: Optional[dict] = None) -> list:
    rows = []

    # Room names: from the CP-SAT model when it decided them, else one exact
    # matching per slot (greedy fallback).
    if chosen_room is None:
        chosen_room = {}
        per_slot: dict = {}
        for p in plan.values():
            for mi, t in p["slots"].items():
                m = meetings[mi]
                per_slot.setdefault(t, []).append((mi, m["kind"], m["size"]))
        for t, here in sorted(per_slot.items()):
            got = _match(here)
            if got is None:
                raise RuntimeError("room matching failed for a slot the solver accepted")
            chosen_room.update(got)
    else:
        chosen_room = dict(chosen_room)
    _prefer_lecture_rooms(chosen_room, plan, meetings)

    for g in groups.values():
        p = plan.get(g["gid"])
        if g["non"]:
            fac = faculty_list[p["fac"]]["name"] if p else ""
            rows.append(_row(g["sec"], fac, None, "N/A", NON_CLASSROOM,
                             int(g["sec"].get("student_count", 0) or 0)))
            continue
        for mi in g["meetings"]:
            m = meetings[mi]
            if p and mi in p["slots"]:
                rows.append(_row(m["sec"], faculty_list[p["fac"]]["name"],
                                 ALL_SLOT_STRINGS[p["slots"][mi]], chosen_room[mi],
                                 m["kind"], m["size"], m["label"]))
            else:
                rows.append(_row(m["sec"], "", None, "Unassigned", m["kind"], m["size"], m["label"]))
    rows.sort(key=lambda r: r["class_type"] == NON_CLASSROOM)   # stable: classroom first
    return rows


# ── Public API ────────────────────────────────────────────────────────────────

def solve(sections: list, faculty_list: list, static_lookup: dict,
          progress_cb: Optional[Callable] = None, strict: bool = False,
          rooms=None, baseline: bool = False) -> tuple:
    """
    `rooms` is the department's RoomSet (default: the active one, see config.rooms).
    `baseline=True` skips CP-SAT and runs the random-feasible greedy (the evaluation baseline, seeded by the run seed).
    """
    rs = rooms if rooms is not None else current_rooms()
    with use_rooms(rs):
        return _solve(sections, faculty_list, static_lookup, progress_cb, strict, baseline)


def _solve(sections: list, faculty_list: list, static_lookup: dict,
           progress_cb: Optional[Callable] = None, strict: bool = False, baseline: bool = False) -> tuple:
    """
    Build the schedule for `sections` (meetings as produced by
    schedule_service.prepare_scheduling_input).

    Returns (assignments, metrics).
      metrics["uncovered_groups"]: {group_id: reason}   (R3, never silent)
      strict=True returns no assignments at all when any group is uncovered.
    Groups that cannot be covered keep placeholder rows (no professor, room
    "Unassigned") so they stay visible; every other group is fully valid.
    """
    t0 = time.time()
    classroom = [s for s in sections if s.get("class_type") != NON_CLASSROOM]
    max_lab = max_room_capacity(current_rooms().lab_rooms)
    meetings = _build_meetings(classroom, max_lab)
    groups = _group_table(sections, meetings, faculty_list, static_lookup)

    result = None if baseline else _solve_with_ortools(meetings, groups, faculty_list, static_lookup, progress_cb)
    solver_used = "cp_sat_ortools"
    if result is None:
        result = _solve_greedy(meetings, groups, faculty_list, static_lookup, progress_cb, randomize=baseline)
        solver_used = "random_feasible" if baseline else "cp_backtracking"   # the service and UI key on cp_backtracking
    plan, info = result
    fell_back = False
    if solver_used == "cp_sat_ortools" and info.get("status") not in ("OPTIMAL", "FEASIBLE"):
        # CP-SAT found no schedule inside the time limit (a slow or busy server can do that), which used to
        # leave every class without a professor. Fall back to the greedy solver so the run still produces
        # a valid schedule, and say so in the metrics.
        plan, info = _solve_greedy(meetings, groups, faculty_list, static_lookup, progress_cb)
        solver_used = "cp_backtracking"
        fell_back = True

    loads = {f["name"]: 0 for f in faculty_list}
    for gid, p in plan.items():
        loads[faculty_list[p["fac"]]["name"]] += groups[gid]["units"]

    uncovered = {gid: _uncovered_reason(g, faculty_list, loads)
                 for gid, g in groups.items() if gid not in plan}

    rows = _build_rows(plan, groups, meetings, faculty_list, info.get("rooms"))
    if strict and uncovered:
        rows = []

    violations = validate_schedule(rows, faculty_list, static_lookup, current_rooms())

    metrics = {
        "solver_used":      solver_used,
        "solver_status":    info.get("status"),
        "solver_fallback":  fell_back,
        "solve_time_sec":   round(time.time() - t0, 3),
        "section_count":    len(sections),
        "group_count":      len(groups),
        "unassigned_count": sum(1 for r in rows if not r["faculty"]),
        "uncovered_groups": uncovered,
        "lab_split_groups": sum(1 for m in meetings if m["label"]),
        "faculty_over_max": sum(1 for f in faculty_list
                                if loads[f["name"]] > f.get("max_units", 24)),
        "violations":       violations,
    }
    if "objective" in info:
        metrics["cp_objective"] = info["objective"]
        metrics["cp_bound"] = info["bound"]
    return rows, metrics