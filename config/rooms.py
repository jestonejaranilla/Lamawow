"""
ATLAS PSU - config/rooms.py
Room sets. A RoomSet is the complete room configuration of ONE department
for ONE run: which rooms exist, their capacities, and which rooms host which
kind of class. Solver, GA, validator and analytics read the active RoomSet
from a context variable, so two departments running at the same time in two
threads never see each other's rooms.
"""

import contextlib
import contextvars
from dataclasses import dataclass, field
from typing import Optional

import config.settings as _settings


@dataclass
class RoomSet:
    lecture_rooms: list
    lab_rooms: list
    capacity: dict = field(default_factory=dict)   # room -> {recommended, max, tiers?}
    lab_also_lecture: bool = False                 # lab rooms may host a lecture (soft penalty)
    placeholder: bool = False                      # capacities are sample data

    @property
    def all_rooms(self) -> list:
        return list(self.lecture_rooms) + [r for r in self.lab_rooms if r not in self.lecture_rooms]

    def pool(self, kind: str) -> list:
        """LAB meetings: lab rooms only. LECTURE meetings: lecture rooms (+ lab rooms if allowed)."""
        if kind == "LAB":
            return list(self.lab_rooms)
        return self.all_rooms if self.lab_also_lecture else list(self.lecture_rooms)

    def cap(self, room: str) -> dict:
        return self.capacity.get(room, {"recommended": 9999, "max": 9999})

    def max_of(self, room: str) -> int:
        try:
            return int(self.cap(room).get("max", 9999))
        except (TypeError, ValueError):
            return 9999


def default_roomset() -> RoomSet:
    """IT and CS ("default" rooms): the global lists in config/settings.py."""
    lecture, lab = list(_settings.LECTURE_ROOMS), list(_settings.LABORATORY_ROOMS)
    cap = {r: dict(_settings.ROOM_CAPACITY[r]) for r in lecture + lab if r in _settings.ROOM_CAPACITY}
    return RoomSet(lecture, lab, cap)


_current: contextvars.ContextVar = contextvars.ContextVar("atlas_rooms", default=None)


def current_rooms() -> RoomSet:
    rs = _current.get()
    return rs if rs is not None else default_roomset()


@contextlib.contextmanager
def use_rooms(rooms: Optional[RoomSet]):
    """Make `rooms` the active RoomSet for the current thread/context."""
    token = _current.set(rooms)
    try:
        yield rooms
    finally:
        _current.reset(token)