"""
Part 24: what a leave range means for a run.

The timetable repeats every week, so leave cannot block single dates. It is judged against the active period
(period_start .. period_end of the department's settings):
  - a range that does not overlap the period is ignored;
  - ranges that together cover the whole period make the professor unavailable (hard exclusion, with a warning);
  - a partial overlap keeps the soft penalty, scaled by the fraction of the period covered (union of ranges,
    so overlapping ranges are never counted twice).
Limitation: a professor on leave for half the period is not scheduled around the weeks they are away.
Without any period dates (no saved dates and no academic year) the old flat penalty applies.
"""
import copy
from datetime import date, timedelta
from typing import Optional


def parse_date(v) -> Optional[date]:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def default_period(academic_year, semester) -> Optional[tuple]:
    """Typical Philippine calendar, used only when the chairperson saved no dates:
    1st Semester Aug 1 - Dec 20, 2nd Semester Jan 12 - May 31, Summer Jun 8 - Jul 31."""
    try:
        y1 = int(str(academic_year).strip()[:4])
    except (TypeError, ValueError):
        return None
    s = str(semester or "")
    if s.startswith("1"):
        return date(y1, 8, 1), date(y1, 12, 20)
    if s.startswith("2"):
        return date(y1 + 1, 1, 12), date(y1 + 1, 5, 31)
    if s.lower().startswith("sum"):
        return date(y1 + 1, 6, 8), date(y1 + 1, 7, 31)
    return None


def resolve_period(period_start, period_end, academic_year=None, semester=None) -> Optional[tuple]:
    """(start, end) dates: the saved dates first, then the default for the academic year and semester, else None."""
    s, e = parse_date(period_start), parse_date(period_end)
    if s and e and e >= s:
        return s, e
    return default_period(academic_year, semester)


def _ranges(sc: dict) -> list:
    out = []
    for key in ("leave_dates", "unavailable_dates"):
        for r in sc.get(key) or []:
            if isinstance(r, dict):
                a, b = parse_date(r.get("start")), parse_date(r.get("end"))
                if a and b and b >= a:
                    out.append((a, b))
    return out


def leave_fraction(ranges: list, period: tuple) -> float:
    """Share of the period (0..1) covered by the union of the ranges."""
    ps, pe = period
    clipped = sorted((max(a, ps), min(b, pe)) for a, b in ranges if a <= pe and b >= ps)
    covered, cur_end = 0, None
    cur_start = None
    for a, b in clipped:
        if cur_end is None or a > cur_end + timedelta(days=1):
            if cur_end is not None:
                covered += (cur_end - cur_start).days + 1
            cur_start, cur_end = a, b
        elif b > cur_end:
            cur_end = b
    if cur_end is not None:
        covered += (cur_end - cur_start).days + 1
    return min(1.0, covered / ((pe - ps).days + 1))


def apply_leave(faculty: list, soft: dict, period: Optional[tuple]):
    """
    -> (active_faculty, soft_for_run, warnings). `soft` is not modified.
    With a period: professors fully on leave leave `active_faculty`; others get `leave_fraction` (partial leave)
    and lose the raw ranges, so the objective scales the penalty. Without a period nothing changes.
    """
    soft_out = copy.deepcopy(soft or {})
    if not period:
        return list(faculty), soft_out, []
    warnings, active = [], []
    for name in list(soft_out):
        sc = soft_out[name]
        rngs = _ranges(sc)
        sc.pop("leave_dates", None)
        sc.pop("unavailable_dates", None)
        frac = leave_fraction(rngs, period) if rngs else 0.0
        if frac > 0:
            sc["leave_fraction"] = round(frac, 4)
        if not sc:
            del soft_out[name]
    for f in faculty:
        frac = (soft_out.get(f["name"]) or {}).get("leave_fraction", 0.0)
        if frac >= 1.0:
            warnings.append(f"{f['name']} is on leave for the whole period ({period[0]} to {period[1]}), "
                            "so no classes were assigned to them.")
            soft_out.pop(f["name"], None)           # excluded, so their preferences no longer matter
            continue
        if frac > 0:
            warnings.append(f"{f['name']} is on leave for {round(frac * 100)}% of the period; "
                            "their classes carry a proportional preference penalty (the weekly timetable "
                            "does not skip the weeks they are away).")
        active.append(f)
    return active, soft_out, warnings