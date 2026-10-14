"""Shared test data: the 10 default professors from main-script.js (INITIAL_FACULTY)."""

DAYS = ["Mon", "Tue", "Wed", "Thu"]

# (name, specialization). The first seven tags are exactly INITIAL_FACULTY.
_DEFAULT_TAGS = [
    ("Prof A", ["Networks & Security"]), ("Prof B", ["Systems"]),
    ("Prof C", ["Programming"]),         ("Prof D", ["Mathematics"]),
    ("Prof E", ["Networks & Security"]), ("Prof F", ["Web & App Dev"]),
    ("Prof G", ["Systems"]),             ("Prof H", ["Data Management"]),
    ("Prof I", ["Applied Computing"]),   ("Prof J", ["Data Management"]),
]

# INITIAL_FACULTY holds none of "Core Theory", "Research & Capstone" or
# "Industry Practice", which Introduction to Computing, Social and
# Professional Issues, the Capstones, Thesis, Educational Tour and Practicum
# require. Since faculty_qualifies no longer treats a mixed tag list as open,
# the test roster gives three professors those extra tags.
_EXTRA_TAGS = {"Prof A": ["Core Theory"], "Prof B": ["Research & Capstone"],
               "Prof C": ["Industry Practice"]}


def make_faculty(name, spec, max_units=24, absolute_max=30, days=None):
    return {"name": name, "specialization": list(spec), "max_units": max_units,
            "absolute_max_units": absolute_max, "availability": list(days or DAYS)}


def default_faculty(extra_tags=True):
    out = []
    for name, tags in _DEFAULT_TAGS:
        spec = tags + (_EXTRA_TAGS.get(name, []) if extra_tags else [])
        out.append(make_faculty(name, spec))
    return out