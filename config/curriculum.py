"""
ATLAS PSU - config/curriculum.py
Generic curriculum loader. Each department is one JSON file in
data/curricula/<DEPT>.json (same schema for every department):

  {"dept": "IT", "program": "BSIT",
   "blocks":  {"1": ["B1", "B2"], ...},
   "courses": [{"code", "title", "year", "semester", "lec", "lab",
                "category": "CC|IT|ITE", "scheduled": true,
                "specialization": [...]}]}

Pure functions, no Flask and no dependency on config.settings (settings
imports this module to build SPECIALIZATION_MAP).
"""

import json
import os
from typing import Optional

CURRICULA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "curricula"
)

# Only courses whose prospectus code starts with one of these are scheduled.
IN_SCOPE_PREFIXES = ("CC", "IT")

_REQUIRED_COURSE_KEYS = ("code", "title", "year", "semester", "lec", "lab")
_cache: dict = {}


def _validate(data: dict, path: str) -> dict:
    for key in ("dept", "courses"):
        if key not in data:
            raise ValueError(f"{path}: missing '{key}'")
    seen = set()
    for c in data["courses"]:
        for key in _REQUIRED_COURSE_KEYS:
            if key not in c:
                raise ValueError(f"{path}: course {c.get('code', '?')} missing '{key}'")
        if c["code"] in seen:
            raise ValueError(f"{path}: duplicate course code {c['code']}")
        seen.add(c["code"])
        c.setdefault("category", c["code"].split()[0])
        c.setdefault("scheduled", True)
        c.setdefault("specialization", [])
    data.setdefault("program", data["dept"])
    data.setdefault("blocks", {})
    return data


def load_curriculum(dept: str) -> dict:
    """Load (and cache) data/curricula/<dept>.json."""
    if dept not in _cache:
        path = os.path.join(CURRICULA_DIR, f"{dept}.json")
        with open(path, "r", encoding="utf-8") as fh:
            _cache[dept] = _validate(json.load(fh), path)
    return _cache[dept]


def available_departments() -> list:
    if not os.path.isdir(CURRICULA_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(CURRICULA_DIR) if f.endswith(".json"))


def load_all_curricula() -> dict:
    return {d: load_curriculum(d) for d in available_departments()}


def is_in_scope(course: dict) -> bool:
    """Scope rule: prospectus code starts with CC or IT (IT E1..E4 included)."""
    return str(course.get("code", "")).strip().upper().startswith(IN_SCOPE_PREFIXES)


def in_scope_courses(curriculum: dict, year: Optional[int] = None,
                     semester: Optional[int] = None) -> list:
    out = []
    for c in curriculum["courses"]:
        if not is_in_scope(c):
            continue
        if year is not None and c["year"] != year:
            continue
        if semester is not None and c["semester"] != semester:
            continue
        out.append(c)
    return out


def specialization_map() -> dict:
    """{course title: [specialization tags]} across every loaded department."""
    result = {}
    for cur in load_all_curricula().values():
        for c in cur["courses"]:
            if is_in_scope(c):
                result[c["title"]] = list(c.get("specialization", []))
    return result