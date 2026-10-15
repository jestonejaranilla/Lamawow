"""
ATLAS PSU - config/settings.py
Central configuration for scheduling engine and system parameters.
"""

# ── Time Grid ─────────────────────────────────────────────────────────────────
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
HOURS = [(7, 9), (9, 11), (13, 15), (15, 17), (17, 19)]
TIME_SLOTS = [(d, h[0], h[1]) for d in DAYS for h in HOURS]  # 30 slots

# ── Room Definitions ──────────────────────────────────────────────────────────
LECTURE_ROOMS = [
    "CL1", "CL2", "CL3",
    "IT Room 1", "IT Room 2", "IT Room 3",
    "GA Bldg 16", "GA Bldg 17", "GA Bldg 18", "GA Bldg 19", "GA Bldg 20",
    "GA Bldg 21", "GA Bldg 22", "GA Bldg 23", "GA Bldg 24", "GA Bldg 25",
]
LABORATORY_ROOMS = ["MTC1", "MTC2", "IT101", "NIT1", "NIT3"]
ALL_ROOMS = LECTURE_ROOMS + LABORATORY_ROOMS

# ── Room Capacity Configuration ───────────────────────────────────────────────
# Each room entry: {recommended, max, penalties: [(threshold, penalty_per_student), ...]}
# Tiered Penalty Constraint: soft penalty when over recommended but under max;
# Hard rejection when student_count > max.
ROOM_CAPACITY = {
    # CL1-CL3: Recommended 35, reject >52 (50% over as realistic hard max)
    "CL1":      {"recommended": 35, "max": 52},
    "CL2":      {"recommended": 35, "max": 52},
    "CL3":      {"recommended": 35, "max": 52},

    # IT Rooms: Recommended 45, reject >60
    "IT Room 1": {"recommended": 45, "max": 60},
    "IT Room 2": {"recommended": 45, "max": 60},
    "IT Room 3": {"recommended": 45, "max": 60},

    # GA Building Rooms: Recommended 40, reject >55
    "GA Bldg 16": {"recommended": 40, "max": 55},
    "GA Bldg 17": {"recommended": 40, "max": 55},
    "GA Bldg 18": {"recommended": 40, "max": 55},
    "GA Bldg 19": {"recommended": 40, "max": 55},
    "GA Bldg 20": {"recommended": 40, "max": 55},
    "GA Bldg 21": {"recommended": 40, "max": 55},
    "GA Bldg 22": {"recommended": 40, "max": 55},
    "GA Bldg 23": {"recommended": 40, "max": 55},
    "GA Bldg 24": {"recommended": 40, "max": 55},
    "GA Bldg 25": {"recommended": 40, "max": 55},

    # MTC1-MTC2: Computer cubicle lab - hard max 45, reject >45
    # Tiers: <=32 comfortable, 33-40 moderate penalty, 41-45 higher penalty
    "MTC1": {"recommended": 32, "max": 45,
              "tiers": [(33, 2.0), (41, 5.0)]},  # per-student penalty per tier start
    "MTC2": {"recommended": 32, "max": 45,
              "tiers": [(33, 2.0), (41, 5.0)]},

    # IT101: Recommended 30, hard max 40
    # Tiers: <=30 ok, 31-35 moderate, 36-40 higher penalty
    "IT101": {"recommended": 30, "max": 40,
               "tiers": [(31, 2.0), (36, 5.0)]},

    # NIT1-NIT3: Recommended 40, hard max 45
    "NIT1": {"recommended": 40, "max": 45},
    "NIT3": {"recommended": 40, "max": 45},
}

# Penalty per student over recommended capacity (default for rooms without tiers)
CAPACITY_OVER_PENALTY_PER_STUDENT = 3.0
# Bonus per student under or at recommended capacity (reward good fit)
CAPACITY_FIT_BONUS = 2.0

# ── Subject Types ─────────────────────────────────────────────────────────────
SUBJECT_TYPES = [
    "Core Theory", "Programming", "Systems", "Data Management",
    "Networks & Security", "Applied Computing", "Mathematics",
    "Web & App Dev", "Research & Capstone", "Industry Practice", "Elective",
]

# Specialization tags and class sizes live in data/curricula/<DEPT>.json (one file
# per department). There is no global specialization map: course titles repeat
# across departments with different tags.

# ── Meetings per course ───────────────────────────────────────────────────────
# ceil(lec / 2) two-hour LECTURE meetings, plus this many LAB meetings per lab unit.
LAB_MEETINGS_PER_LAB_UNIT = 1

# ── GA Optimizer Weights (configurable) ──────────────────────────────────────
GA_WEIGHTS = {
    "preferred_period_match":   5.0,
    "preferred_period_miss":   -2.0,
    "preferred_room_match":     5.0,
    "preferred_room_miss":     -1.0,
    "preferred_building_match": 3.0,
    "preferred_building_miss": -0.5,
    "preferred_floor_match":    2.0,
    "restricted_day_penalty": -12.0,
    "maternity_leave_penalty": -20.0,
    "leave_penalty": -10.0,
    "exact_spec_match":         8.0,
    "load_variance_weight":     1.5,
    "underload_gap_weight":     3.0,
    # Room capacity weights (integrated into fitness)
    "capacity_fit_bonus":       2.0,   # per student under/at recommended
    "capacity_over_penalty":    3.0,   # per student over recommended (default)
    # Building affinity weights
    "building_affinity_bonus":  4.0,   # reward faculty staying in same building per day
    "building_affinity_penalty":-3.0,  # penalise each extra building a faculty uses per day
    "section_cluster_bonus":    3.0,   # reward section staying in same building per day
    "section_cluster_penalty": -2.5,   # penalise each extra building a section uses per day
}

# ── Solver Config ─────────────────────────────────────────────────────────────
CP_SAT_TIME_LIMIT_SECONDS = 30.0      # default; the solver never runs past the max below
CP_SAT_MAX_TIME_LIMIT_SECONDS = 40.0  # hard ceiling (always under 45 s), best solution is returned
# False: schedule every group that can be staffed and list the rest in coverage_errors.
# True: if any group cannot be covered, return no assignments, only coverage_errors.
REQUIRE_FULL_COVERAGE = False

# CP-SAT objective weights (integers)
# The solver reads exactly these names (see cp_sat_solver._weights).
CP_WEIGHTS = {
    "uncovered_group":   1_000_000,  # reward per meeting of a covered group; coverage dominates everything else
    "exact_spec":        40,         # per meeting, exact specialization match
    "course_professor":  30,         # per distinct professor teaching the same course
    "over_soft_cap":     25,         # per load unit above max_units (24)
    "load_balance":      3,          # per load unit of the busiest professor
    "lab_for_lecture":   20,         # per lecture placed in a laboratory room
    "room_over":         1,          # per student above a room's recommended size
}
UNITS_PER_ASSIGNMENT = 2
# Load units counted for one NON_CLASSROOM group (unscheduled courses such as IT 20, IT 22, Practicum).
NON_CLASSROOM_UNITS = 2