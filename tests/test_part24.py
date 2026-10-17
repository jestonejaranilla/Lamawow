"""
ATLAS PSU - Part 24: leave and availability semantics, and the faculty form (P8, Q2, Q3).
Run from the project root:  python -m pytest tests/test_part24.py -q
"""
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

import config.settings as cfg
from services import leave_service as ls
from services import schedule_service as ss
from solver.objective_functions import preference_term

ROOT = Path(__file__).resolve().parent.parent
PERIOD = (date(2026, 8, 1), date(2026, 12, 20))          # 142 days


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def fac(name):
    return {"name": name, "specialization": ["Programming"], "max_units": 24, "overload_buffer": 6,
            "absolute_max_units": 30, "availability": ["Mon", "Tue", "Wed", "Thu"]}


def leave(a, b):
    return {"start": a, "end": b}


def test_leave_outside_the_period_has_no_effect():
    soft = {"A": {"preferred_period": "morning", "leave_dates": [leave("2025-01-01", "2025-02-01")]}}
    active, out, warns = ls.apply_leave([fac("A")], soft, PERIOD)
    assert [f["name"] for f in active] == ["A"] and warns == []
    assert out == {"A": {"preferred_period": "morning"}}            # the range is dropped, nothing else changes
    assert soft["A"]["leave_dates"]                                  # the input is never modified


def test_full_period_leave_excludes_the_professor_with_a_warning():
    soft = {"A": {"leave_dates": [leave("2026-07-01", "2026-12-31")]}}
    active, out, warns = ls.apply_leave([fac("A"), fac("B")], soft, PERIOD)
    assert [f["name"] for f in active] == ["B"]
    assert len(warns) == 1 and "A is on leave for the whole period" in warns[0]
    assert "A" not in out


def test_ranges_that_together_cover_the_period_also_exclude():
    soft = {"A": {"leave_dates": [leave("2026-08-01", "2026-10-15"), leave("2026-10-16", "2026-12-20")]}}
    active, _, _ = ls.apply_leave([fac("A"), fac("B")], soft, PERIOD)
    assert [f["name"] for f in active] == ["B"]


def test_partial_leave_gives_a_proportional_penalty_and_overlaps_count_once():
    # 71 of 142 days, given as two overlapping ranges
    soft = {"A": {"leave_dates": [leave("2026-08-01", "2026-09-20"), leave("2026-09-01", "2026-10-10")]}}
    assert ls.leave_fraction(ls._ranges(soft["A"]), PERIOD) == pytest.approx(71 / 142)
    active, out, warns = ls.apply_leave([fac("A")], soft, PERIOD)
    assert len(active) == 1 and out["A"]["leave_fraction"] == pytest.approx(0.5, abs=0.001)
    assert "50%" in warns[0]
    w = cfg.GA_WEIGHTS
    a = {"faculty": "A", "slot": "Mon: 7:00-9:00", "room": "R1"}
    base = preference_term(a, {"A": {}})
    half = preference_term(a, {"A": {"leave_fraction": 0.5}})
    full = preference_term(a, {"A": {"leave_fraction": 1.0}})
    assert half - base == pytest.approx(0.5 * (full - base)) and full < half < base
    assert full - base == pytest.approx(w.get("leave_penalty", -10.0))


def test_without_a_period_the_old_flat_penalty_stays():
    soft = {"A": {"leave_dates": [leave("2026-11-01", "2026-11-02")]}}
    active, out, warns = ls.apply_leave([fac("A")], soft, None)
    assert out == soft and warns == [] and len(active) == 1


def test_period_resolution_prefers_saved_dates_then_the_default_calendar():
    assert ls.resolve_period("2026-09-01", "2026-12-01") == (date(2026, 9, 1), date(2026, 12, 1))
    assert ls.resolve_period(None, None, "2026-2027", "1st Semester") == (date(2026, 8, 1), date(2026, 12, 20))
    assert ls.resolve_period(None, None, "2026-2027", "2nd Semester")[0] == date(2027, 1, 12)
    assert ls.resolve_period("2026-12-01", "2026-09-01", "2026-2027", "1st Semester")[0] == date(2026, 8, 1)  # bad order
    assert ls.resolve_period(None, None, None, "1st Semester") is None


def _run(prefs, faculty, **kw):
    ss.reset_state("IT")
    subj = [{"group_id": g["group_id"]} for g in ss.build_groups("IT", "1st Semester", ss.get_class_sizes("IT"))[0]]
    return ss.start_scheduling("IT", faculty, subj, "1st Semester", {"generations": 1, "population": 4}, prefs, None,
                               run_settings={"cp_sat_time_limit": 1}, wait=True, **kw)


def test_a_run_excludes_a_professor_on_leave_for_the_whole_period_and_says_why():
    from conftest import dept_faculty
    faculty = dept_faculty("IT")
    gone = faculty[0]["name"]
    out = _run({gone: {"leave_dates": [leave("2026-07-01", "2027-01-31")]}}, faculty,
               period_start="2026-08-01", period_end="2026-12-20")
    assert "run_id" in out, out
    p = ss.get_progress("IT")
    assert p["phase"] == "done"
    assert all(a.get("faculty") != gone for a in p["result"])
    assert any(gone in w and "on leave for the whole period" in w for w in p["warnings"])
    assert gone in [f["name"] for f in p["inputs_raw"]["faculty"]]         # the snapshot keeps the full list
    assert p["inputs_raw"]["period"] == {"start": "2026-08-01", "end": "2026-12-20"}


def test_a_run_with_everyone_on_leave_is_refused():
    from conftest import dept_faculty
    faculty = dept_faculty("IT")
    prefs = {f["name"]: {"leave_dates": [leave("2026-01-01", "2027-12-31")]} for f in faculty}
    out = _run(prefs, faculty, period_start="2026-08-01", period_end="2026-12-20")
    assert "error" in out and "on leave" in out["error"]


def test_a_run_ignores_leave_outside_the_period():
    from conftest import dept_faculty
    faculty = dept_faculty("IT")
    name = faculty[0]["name"]
    out = _run({name: {"leave_dates": [leave("2020-01-01", "2020-02-01")]}}, faculty,
               period_start="2026-08-01", period_end="2026-12-20")
    assert "run_id" in out
    assert not any("on leave" in w for w in ss.get_progress("IT")["warnings"])


# ── faculty form: defaults, hint, name saving ────────────────────────────────
def test_new_professor_defaults_to_mon_to_thu_in_the_form_the_database_and_the_pool():
    js = read("assets/js/main-script.js")
    assert "const DEFAULT_AVAILABILITY = ['Mon', 'Tue', 'Wed', 'Thu'];" in js
    assert js.count("DEFAULT_AVAILABILITY") == 3                    # declaration + the two places that used the old list
    assert "|| ['Mon','Tue','Wed','Thu','Fri','Sat']" not in js
    assert "availability     text[] not null default '{Mon,Tue,Wed,Thu}'" in read("db/schema.sql")
    from tools.faculty_pool import DAYS
    assert DAYS == ["Mon", "Tue", "Wed", "Thu"]


def test_form_hints_a_professor_without_a_specialization_and_never_blocks_saving():
    js = read("assets/js/main-script.js")
    assert "Only electives can be assigned" in js and "function updateSpecHint(tr)" in js
    assert "updateSpecHint(tr);" in js and "if (row) updateSpecHint(row);" in js      # on creation and on every tag change
    assert "tr.classList.toggle('no-specialization', none)" in js
    assert "tr.no-specialization" in read("assets/css/main-style.css")
    body = js[js.index("function updateSpecHint(tr)"):][:400]
    assert "saveFaculty" not in body and "return false" not in body


def test_the_name_saves_on_change_or_enter_not_on_every_keystroke():
    js = read("assets/js/main-script.js")
    assert "nameInput.addEventListener('change', saveFaculty);" in js
    assert "e.key === 'Enter'" in js and "nameInput.blur()" in js
    assert not re.search(r"input\[type=\"text\"\], input\[type=\"number\"\]'\)\.forEach", js)
    assert "querySelectorAll('input[type=\"number\"]').forEach(input => {\n    input.addEventListener('input', debounce(saveFaculty, 500));" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_name_typed_slowly_writes_one_audit_row_not_many(tmp_path):
    """Replays the row's name wiring against the real data layer harness: 12 keystrokes, then blur."""
    js = read("assets/js/main-script.js")
    wiring = js[js.index("// Numbers save shortly after typing stops."):js.index("updateSpecHint(tr);\n", js.index("// Numbers save shortly"))]
    script = """
      let saves = 0; const saveFaculty = () => { saves++; };
      const debounce = (fn, d) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), d); }; };
      const L = {}; const mk = () => ({ addEventListener: (n, f) => { (L[n] = L[n] || []).push(f); }, blur() { (L.change || []).forEach(f => f()); } });
      const nm = mk(); const tr = { querySelectorAll: () => [], querySelector: () => nm };
      %s
      (async () => {
        for (const ch of 'Prof. Maria Santos') { (L.input || []).forEach(f => f()); await new Promise(r => setTimeout(r, 700)); }
        if (saves !== 0) { console.log('FAIL typing saved ' + saves); process.exit(1); }
        L.keydown[0]({ key: 'Enter', preventDefault() {} });
        console.log(saves === 1 ? 'OK' : 'FAIL ' + saves);
      })();
    """ % wiring.replace("updateSpecHint(tr);", "")
    f = tmp_path / "t.js"
    f.write_text(script)
    r = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "OK", r.stdout + r.stderr


def test_the_period_dates_migration_is_idempotent_and_the_data_layer_saves_them():
    sql = read("db/schema.sql")
    assert "add column if not exists period_start date" in sql and "add column if not exists period_end   date" in sql
    assert "if not exists (select 1 from pg_constraint where conname = 'dept_settings_period_order')" in sql
    ds = read("assets/js/data-store.js")
    assert "period_start: s.period_start || null" in ds and "savePeriodDates" in ds