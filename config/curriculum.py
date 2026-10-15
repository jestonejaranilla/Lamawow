"""
ATLAS PSU - config/curriculum.py
Department curriculum loader. Each department is one JSON file in
data/curricula/<DEPT>.json (exact, case-sensitive file names: Render runs
Linux). Departments: IT, CS, MB, ES, MedB.

Schema (see README, Departments):
  dept, program, name, prospectus, notes
  blocks:      {"1": ["B1", "B2"], ...}
  class_sizes: {"IT1B1": {"year", "block", "size"}, ...}
  specializations: allowed tags
  default_faculty (optional, IT only): [{name, specialization, max_units,
               absolute_max_units, availability}] the dashboard starts with
  rooms: {"lecture": "default" | {room: {recommended, max}},
          "lab":     "default" | {room: {recommended, max}},
          "lab_rooms_also_lecture": bool, "capacity_placeholder": bool}
  courses: [{code, title, year, semester, lec, lab, category, scheduled,
             specialization, confirm?, verify?}]

SCOPE: a course is in scope when it is present in the file. The files hold
only courses taught by College of Sciences faculty.

Pure functions, no Flask.
"""

import copy
import json
import os
from typing import Optional

from config.rooms import RoomSet, default_roomset
import config.settings as _settings

CURRICULA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "curricula"
)

_REQUIRED_COURSE_KEYS = ("code", "title", "year", "semester", "lec", "lab")
_cache: dict = {}


class UnknownDepartment(ValueError):
    pass


def available_departments() -> list:
    if not os.path.isdir(CURRICULA_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(CURRICULA_DIR) if f.endswith(".json"))


def _validate(data: dict, path: str) -> dict:
    for key in ("dept", "courses", "blocks", "class_sizes"):
        if key not in data:
            raise ValueError(f"{path}: missing '{key}'")
    dept = data["dept"]
    allowed = set(data.get("specializations") or [])
    seen = set()
    for c in data["courses"]:
        for key in _REQUIRED_COURSE_KEYS:
            if key not in c:
                raise ValueError(f"{path}: course {c.get('code', '?')} missing '{key}'")
        if c["code"] in seen:
            raise ValueError(f"{path}: duplicate course code {c['code']}")
        seen.add(c["code"])
        if str(c["year"]) not in data["blocks"]:
            raise ValueError(f"{path}: course {c['code']} is in year {c['year']} which has no blocks")
        c.setdefault("category", c["code"].split()[0])
        c.setdefault("scheduled", True)
        c.setdefault("specialization", [])
        if allowed:
            bad = [t for t in c["specialization"] if t not in allowed]
            if bad:
                raise ValueError(f"{path}: course {c['code']} has tags not in 'specializations': {bad}")
    for f in data.get("default_faculty", []):
        bad = [t for t in f.get("specialization", []) if allowed and t not in allowed]
        if bad:
            raise ValueError(f"{path}: default_faculty {f.get('name')} has tags not in 'specializations': {bad}")
    for year, blocks in data["blocks"].items():
        for b in blocks:
            if f"{dept}{year}{b}" not in data["class_sizes"]:
                raise ValueError(f"{path}: class_sizes has no entry for {dept}{year}{b}")
    data.setdefault("program", dept)
    data.setdefault("name", dept)
    data.setdefault("rooms", {"lecture": "default", "lab": "default"})
    return data


def load_curriculum(dept: str) -> dict:
    """Load (and cache) data/curricula/<dept>.json. Case-sensitive; unknown -> UnknownDepartment."""
    if not isinstance(dept, str) or dept not in available_departments():
        raise UnknownDepartment(f"Unknown department: {dept!r}")
    if dept not in _cache:
        path = os.path.join(CURRICULA_DIR, f"{dept}.json")
        with open(path, "r", encoding="utf-8") as fh:
            _cache[dept] = _validate(json.load(fh), path)
    return _cache[dept]


def list_departments() -> list:
    out = []
    for d in available_departments():
        c = load_curriculum(d)
        out.append({"dept": d, "name": c["name"], "program": c["program"]})
    return out


def courses_of(dept: str, semester: Optional[int] = None, year: Optional[int] = None) -> list:
    return [c for c in load_curriculum(dept)["courses"]
            if (semester is None or c["semester"] == semester)
            and (year is None or c["year"] == year)]


def specialization_lookup(dept: str) -> dict:
    """{course title: [tags]} for ONE department (titles repeat across departments)."""
    return {c["title"]: list(c.get("specialization", [])) for c in load_curriculum(dept)["courses"]}


def class_sizes_for(dept: str) -> dict:
    return copy.deepcopy(load_curriculum(dept)["class_sizes"])


def rooms_for(dept: str, override: Optional[dict] = None) -> RoomSet:
    """
    The RoomSet of one department, from its own file only. `override` is the
    runtime edit stored for that department: lecture_rooms, laboratory_rooms,
    room_capacity.
    """
    spec = load_curriculum(dept).get("rooms", {})
    dflt = default_roomset()

    def part(key, dflt_rooms):
        v = spec.get(key, "default")
        if v == "default":
            return list(dflt_rooms), {r: dict(dflt.capacity[r]) for r in dflt_rooms if r in dflt.capacity}
        return list(v.keys()), {r: dict(c) for r, c in v.items()}

    lecture, cap_l = part("lecture", dflt.lecture_rooms)
    lab, cap_b = part("lab", dflt.lab_rooms)
    cap = {**cap_l, **cap_b}
    override = override or {}
    if override.get("lecture_rooms") is not None:
        lecture = [str(r).strip() for r in override["lecture_rooms"] if str(r).strip()]
    if override.get("laboratory_rooms") is not None:
        lab = [str(r).strip() for r in override["laboratory_rooms"] if str(r).strip()]
    for r, c in (override.get("room_capacity") or {}).items():
        if isinstance(c, dict):
            cap[r] = dict(c)
    return RoomSet(lecture, lab, cap,
                   lab_also_lecture=bool(spec.get("lab_rooms_also_lecture", False)),
                   placeholder=bool(spec.get("capacity_placeholder", False)))