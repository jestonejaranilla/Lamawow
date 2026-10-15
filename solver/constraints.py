"""
ATLAS PSU - solver/constraints.py
Hard constraint definitions and validation utilities.
All schedule generation must satisfy every constraint in this module.
"""

import config.settings as _settings
from config.rooms import current_rooms, use_rooms

# Rooms are never global: every function below reads the RoomSet that is active
# for the current run (config.rooms.use_rooms), i.e. the rooms of ONE department.


# ── Qualification ─────────────────────────────────────────────────────────────

def get_required_specs(subject_name: str, static_lookup: dict) -> list:
    """Tags of a course. `static_lookup` is built per run from ONE department's file."""
    return static_lookup.get(subject_name, [])


OPEN_TAG = "Elective"


def is_open_assignment(subject_name: str, static_lookup: dict) -> bool:
    """
    A course is an OPEN assignment - any faculty member may teach it - when its
    only specialization tag is "Elective" (the electives, for example IT E1 to
    IT E4, CS Elective 4, Elective 1) or when it has no tags at all. A course that lists "Elective" next to another
    tag (for example ["Core Theory", "Elective"]) is NOT open: the faculty must
    hold one of the listed tags.
    """
    required = get_required_specs(subject_name, static_lookup)
    return (not required) or all(tag == OPEN_TAG for tag in required)


def faculty_qualifies(faculty: dict, subject_name: str, static_lookup: dict) -> bool:
    """
    Hard qualification rule.
      - Electives (tag list == ["Elective"]) and untagged courses: any faculty.
      - Everything else: the faculty member holds at least one listed tag
        (any overlap with the course tags).
    """
    if is_open_assignment(subject_name, static_lookup):
        return True
    required = get_required_specs(subject_name, static_lookup)
    return any(spec in faculty.get("specialization", []) for spec in required)


def is_exact_spec_match(faculty: dict, subject_name: str, static_lookup: dict) -> bool:
    required = get_required_specs(subject_name, static_lookup)
    if not required:
        return True
    return any(spec in faculty.get("specialization", []) for spec in required)


# ── Availability ──────────────────────────────────────────────────────────────

def slot_day(slot_str: str) -> str:
    try:
        return slot_str.split(":")[0].strip()
    except Exception:
        return ""


def faculty_available_at(faculty: dict, slot_str: str) -> bool:
    return slot_day(slot_str) in faculty.get("availability", [])


# ── Load ──────────────────────────────────────────────────────────────────────

def faculty_load_ok(current_units: int, faculty: dict, units: int = None) -> bool:
    add = _settings.units_per_assignment() if units is None else units
    return current_units + add <= faculty.get("absolute_max_units", 30)


NON_CLASSROOM = "NON_CLASSROOM"


def is_non_classroom(assignment: dict) -> bool:
    """True for groups that need a professor but no slot or room (IT 20, IT 22)."""
    return assignment.get("class_type") == NON_CLASSROOM


def assignment_units(assignment: dict) -> int:
    """Load units one assignment row counts for its professor."""
    if is_non_classroom(assignment):
        return _settings.non_classroom_units()
    return _settings.units_per_assignment()


# ── Room Compatibility ────────────────────────────────────────────────────────

def room_compatible(room_name: str, class_type: str, lab_rooms: list = None) -> bool:
    """
    LAB meetings use laboratory rooms only. LECTURE meetings use the lecture rooms,
    plus the laboratory rooms when the department allows it (lab_rooms_also_lecture).
    """
    rs = current_rooms()
    labs = rs.lab_rooms if lab_rooms is None else lab_rooms
    if class_type == "LAB":
        return room_name in labs
    if class_type == "LECTURE":
        return room_name in rs.pool("LECTURE") if lab_rooms is None else (
            room_name not in labs or rs.lab_also_lecture)
    return True


# ── Room Capacity ─────────────────────────────────────────────────────────────

def get_room_capacity(room_name: str) -> dict:
    """Capacity config of a room in the active department's RoomSet."""
    return current_rooms().cap(room_name)


def room_max(room_name: str) -> int:
    """Hard capacity (`max`) of a room; 9999 when unknown or not numeric."""
    return current_rooms().max_of(room_name)


def max_room_capacity(rooms: list) -> int:
    return max((room_max(r) for r in rooms), default=0)


def lab_split_plan(size: int, max_lab: int):
    """
    R5: a lab larger than the largest allowed lab room is split into
    k = ceil(size / max_lab) groups of ceil(size / k) students.
    Returns (k, students_per_group).
    """
    if size <= 0 or max_lab <= 0 or size <= max_lab:
        return 1, size
    k = -(-size // max_lab)
    return k, -(-size // k)


def room_exceeds_hard_max(room_name: str, student_count: int) -> bool:
    """
    Hard constraint: True if student_count exceeds the room's absolute maximum.
    This prevents assignment entirely.
    """
    if student_count <= 0:
        return False
    return student_count > room_max(room_name)


def room_capacity_penalty(room_name: str, student_count: int) -> float:
    """
    Tiered penalty score for room capacity violations (negative = penalty).
    Returns 0.0 if within recommended capacity.
    Returns negative penalty if over recommended but under hard max.
    Should not be called when room_exceeds_hard_max is True.
    """
    if student_count <= 0:
        return 0.0

    cap = get_room_capacity(room_name)
    recommended = cap.get("recommended", 9999)

    if student_count <= recommended:
        return 0.0  # No penalty - fits comfortably

    tiers = cap.get("tiers")
    if tiers:
        # Tiered penalty: find applicable tier
        penalty = 0.0
        prev_threshold = recommended
        sorted_tiers = sorted(tiers, key=lambda t: t[0])
        for threshold, rate in sorted_tiers:
            if student_count >= threshold:
                # Students in this band
                band_start = max(prev_threshold + 1, threshold)
                band_end = student_count
                # Next tier threshold or student_count
                next_thresholds = [t[0] for t in sorted_tiers if t[0] > threshold]
                if next_thresholds:
                    band_end = min(student_count, next_thresholds[0] - 1)
                students_in_band = max(0, band_end - band_start + 1)
                penalty += students_in_band * rate
                prev_threshold = threshold
        # Remaining students above last tier threshold
        last_threshold, last_rate = sorted_tiers[-1]
        if student_count > last_threshold:
            students_above = student_count - max(prev_threshold, last_threshold)
            if students_above > 0:
                penalty += students_above * last_rate
        return -penalty
    else:
        # Default: flat penalty per student over recommended
        from config.settings import CAPACITY_OVER_PENALTY_PER_STUDENT
        over = student_count - recommended
        return -(over * CAPACITY_OVER_PENALTY_PER_STUDENT)


def room_capacity_score(room_name: str, student_count: int) -> float:
    """
    Combined capacity score for use in fitness/objective functions.
    Positive bonus when at or under recommended; negative penalty when over.
    """
    if student_count <= 0:
        return 0.0

    cap = get_room_capacity(room_name)
    recommended = cap.get("recommended", 9999)

    if student_count <= recommended:
        from config.settings import CAPACITY_FIT_BONUS
        return CAPACITY_FIT_BONUS  # flat fit bonus
    else:
        return room_capacity_penalty(room_name, student_count)


# ── Building helpers ──────────────────────────────────────────────────────────

def get_building(room_name: str) -> str:
    """
    Extract the logical building group from a room name.
    Used for per-day building affinity and section clustering.
    Scalable: any future room name maps to itself as its own building.
    """
    r = room_name.strip()
    if r.startswith("GA Bldg"):  return "GA Bldg"
    if r.startswith("GE Bldg"):  return "GE Bldg"
    if r.startswith("CSLR"):     return "CSLR"
    if r.startswith("Physics"):  return "Physics Room"
    if r.startswith("IT Room"):  return "IT Room"
    if r.startswith("CL"):       return "CL"
    if r.startswith("MTC"):      return "MTC"
    if r.startswith("NIT"):      return "NIT"
    return r  # fallback - handles future rooms gracefully


# ── Schedule Validator ────────────────────────────────────────────────────────

def _group_key(a: dict) -> str:
    return a.get("group_id") or f"{a.get('section', '')}|{a.get('subject', '')}"


def expected_row_counts(sections: list, lab_rooms: list) -> dict:
    """{group_id: rows a fully covered schedule must contain} (lab splits included)."""
    max_lab = max_room_capacity(lab_rooms)
    expected: dict = {}
    for sec in sections:
        key = sec.get("group_id") or f"{sec.get('section', '')}|{sec.get('name', '')}"
        n = 1
        if sec.get("class_type") == "LAB":
            n, _ = lab_split_plan(int(sec.get("student_count", 0) or 0), max_lab)
        expected[key] = expected.get(key, 0) + n
    return expected


def validate_schedule(assignments: list, faculty_list: list, static_lookup: dict,
                       rooms=None, class_sizes: dict = None,
                       sections: list = None) -> list:
    """
    `rooms` is the department's RoomSet (default: the active one).
    See _validate_schedule for the rules.
    """
    rs = rooms if rooms is not None else current_rooms()
    with use_rooms(rs):
        return _validate_schedule(assignments, faculty_list, static_lookup,
                                  list(rs.lab_rooms), class_sizes, sections)


def _validate_schedule(assignments: list, faculty_list: list, static_lookup: dict,
                       lab_rooms: list, class_sizes: dict = None,
                       sections: list = None) -> list:
    """
    Returns list of violation strings. Empty list = fully valid schedule.

    Always checked (rows that have a professor):
      faculty overlap, room conflict, block overlap (R4), availability,
      qualification, room belongs to the department, room type, room capacity
      by `max` (R5), one professor per
      group (R2), lab-group sizes (R5), load cap (R7).
    Checked only when `sections` (the meetings given to the solver) is passed:
      full coverage (R1/R3) - every group has all its rows and a professor.
    Rows without a professor are reported through coverage_errors, so they are
    skipped by the checks that need a professor.
    """
    violations = []
    fac_map = {f["name"]: f for f in faculty_list}
    max_lab = max_room_capacity(lab_rooms)

    fac_slot: dict = {}      # (faculty, slot) → label
    room_slot: dict = {}     # (room, slot) → label
    block_slot: dict = {}    # (block, slot) → label
    fac_load: dict = {f["name"]: 0 for f in faculty_list}
    group_profs: dict = {}   # group → {faculty}
    group_rows: dict = {}    # group → rows with a professor
    lab_rows: dict = {}      # group → [lab rows with a professor]

    for a in assignments:
        if not a.get("faculty"):
            continue

        label = f"{a['subject']}({a['section']})"
        gkey = _group_key(a)
        fac = fac_map.get(a["faculty"])
        if not fac:
            violations.append(f"UNKNOWN_FACULTY: {a['faculty']}")
            continue

        group_profs.setdefault(gkey, set()).add(a["faculty"])
        group_rows[gkey] = group_rows.get(gkey, 0) + 1

        if not faculty_qualifies(fac, a["subject"], static_lookup):
            violations.append(f"UNQUALIFIED: {a['faculty']} → {a['subject']}")

        fac_load[a["faculty"]] = fac_load.get(a["faculty"], 0) + assignment_units(a)

        # NON_CLASSROOM groups hold no slot or room - only load and qualification
        if is_non_classroom(a):
            continue

        slot, room = a.get("slot"), a.get("room")
        if not slot:
            violations.append(f"NO_SLOT: {label} has a professor but no slot")
            continue

        key = f"{a['faculty']}|{slot}"
        if key in fac_slot:
            violations.append(f"FACULTY_OVERLAP: {a['faculty']} at {slot}: {fac_slot[key]} vs {label}")
        else:
            fac_slot[key] = label

        bkey = f"{a.get('section', '')}|{slot}"
        if a.get("section"):
            if bkey in block_slot:
                violations.append(f"BLOCK_OVERLAP: {a['section']} at {slot}: {block_slot[bkey]} vs {label}")
            else:
                block_slot[bkey] = label

        if not room or room in ("Unassigned", "N/A"):
            violations.append(f"NO_ROOM: {label} at {slot}")
        else:
            room_key = f"{room}|{slot}"
            if room_key in room_slot:
                violations.append(f"ROOM_CONFLICT: {room} at {slot}: {room_slot[room_key]} vs {label}")
            else:
                room_slot[room_key] = label

            if room not in current_rooms().all_rooms:
                violations.append(f"ROOM_NOT_IN_DEPARTMENT: {room} for {label}")
            elif not room_compatible(room, a["class_type"]):
                violations.append(f"ROOM_INCOMPATIBLE: {room} for {a['class_type']} class {label}")

            # Room capacity (hard max). The row's own student_count is used: it is
            # the lab-group size for split labs.
            student_count = int(a.get("student_count", 0) or 0)
            if student_count <= 0 and class_sizes:
                entry = class_sizes.get(a.get("section", ""))
                student_count = entry.get("size", 0) if isinstance(entry, dict) else 0
            if student_count > 0 and room_exceeds_hard_max(room, student_count):
                violations.append(
                    f"CAPACITY_EXCEEDED: {room} (max {room_max(room)}) cannot fit "
                    f"{student_count} students for {label}"
                )

        if not faculty_available_at(fac, slot):
            violations.append(f"UNAVAILABLE: {a['faculty']} not available {slot}")

        if a["class_type"] == "LAB":
            # one entry per LAB meeting: a split meeting has k rows (one per lab group)
            lab_rows.setdefault(a.get("meeting_id") or gkey, []).append(a)

    # One professor per group (R2)
    for gkey, profs in group_profs.items():
        if len(profs) > 1:
            violations.append(f"GROUP_MULTIPLE_PROFESSORS: {gkey}: {', '.join(sorted(profs))}")

    # Lab-group sizes (R5)
    if class_sizes:
        for gkey, rows in lab_rows.items():
            entry = class_sizes.get(rows[0].get("section", ""))
            size = entry.get("size", 0) if isinstance(entry, dict) else 0
            if size <= 0:
                continue
            k, sub = lab_split_plan(size, max_lab)
            if len(rows) != k:
                violations.append(f"LAB_SPLIT_COUNT: {gkey}: {len(rows)} lab group(s), expected {k}")
            for r in rows:
                if int(r.get("student_count", 0) or 0) != sub:
                    violations.append(
                        f"LAB_GROUP_SIZE: {gkey} {r.get('lab_group') or ''}: "
                        f"{r.get('student_count')} students, expected {sub}"
                    )

    # Full coverage (R1/R3)
    if sections is not None:
        for gkey, want in expected_row_counts(sections, lab_rooms).items():
            have = group_rows.get(gkey, 0)
            if have < want:
                violations.append(f"UNCOVERED: {gkey}: {have}/{want} meeting(s) have a professor")

    # Load caps (R7, hard)
    for f in faculty_list:
        load = fac_load.get(f["name"], 0)
        if load > f.get("absolute_max_units", 30):
            violations.append(f"OVERLOAD: {f['name']} assigned {load} > {f['absolute_max_units']}")

    return violations