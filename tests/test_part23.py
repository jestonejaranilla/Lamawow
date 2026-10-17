"""
ATLAS PSU - Part 23: data integrity and security fixes (S1 to S5, S9, S10).
The SQL side (S1, S4, S5) is proved by db/rls_tests.sql, which test_part18 runs when ATLAS_TEST_PG is set.
Run from the project root:  python -m pytest tests/test_part23.py -q
"""
import logging
from pathlib import Path

import pytest

import config.settings as cfg
from services import auth_service as auth
from services import schedule_service as ss
from test_part14 import IT_CHAIR, H, client, db   # noqa: F401  (fixtures: db, client)

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ── S2: preferences and leave are exactly what the request sent ──────────────
def test_load_soft_constraints_replaces_and_a_cleared_preference_is_gone_after_the_next_run():
    ss.reset_state("IT")
    ss.load_soft_constraints("IT", {"Prof A": {"preferred_period": "morning"}, "Prof B": {"restricted_days": ["Sat"]}})
    assert set(ss.get_soft_constraints("IT")) == {"Prof A", "Prof B"}
    ss.load_soft_constraints("IT", {"Prof A": {"preferred_room": "R1"}})
    assert ss.get_soft_constraints("IT") == {"Prof A": {"preferred_room": "R1"}}       # the old key and Prof B are gone


def _run_with(prefs):
    ss.reset_state("IT")
    from conftest import dept_faculty
    subj = [{"group_id": g["group_id"]} for g in ss.build_groups("IT", "1st Semester", ss.get_class_sizes("IT"))[0]]
    out = ss.start_scheduling("IT", dept_faculty("IT"), subj, "1st Semester", {"generations": 1, "population": 4}, prefs, None,
                              run_settings={"cp_sat_time_limit": 1}, wait=True)
    assert "run_id" in out, out


def test_set_a_preference_run_clear_it_run_again_the_server_no_longer_holds_it():
    pref = {"Prof A": {"preferred_period": "morning", "leave_dates": [{"start": "2026-11-01", "end": "2026-11-02"}]}}
    _run_with(pref)
    assert ss.get_soft_constraints("IT") == pref
    _run_with({})                                       # the chair cleared it in the UI, so the request carries nothing
    assert ss.get_soft_constraints("IT") == {}
    _run_with({"Prof B": {"preferred_period": "evening"}})
    assert set(ss.get_soft_constraints("IT")) == {"Prof B"}


# ── S3: the audit read failure is logged and has a stable code ───────────────
def test_audit_read_failure_is_logged_without_row_data_and_returns_a_code(client, db, monkeypatch, caplog):
    import routes.session_routes as sr

    class Boom:
        def table(self, name):
            raise RuntimeError("relation exploded: secret-row-value")
    monkeypatch.setattr(sr.supabase_client, "get_user_client", lambda token: Boom())
    with caplog.at_level(logging.ERROR, logger="atlas.audit"):
        r = client.get("/audit?dept=IT", headers=H(IT_CHAIR))
    assert r.status_code == 502
    body = r.get_json()
    assert body["code"] == "audit_read_failed" and body["success"] is False and "administrator" in body["error"].lower()
    assert any(rec.name == "atlas.audit" and "RuntimeError" in rec.getMessage() for rec in caplog.records)
    assert "audit_read_failed" in read("assets/js/app-script.js")


# ── S9: unknown keys and size caps on /run-ga ────────────────────────────────
@pytest.fixture
def started(monkeypatch):
    import routes.schedule_routes as rt
    seen = {}
    monkeypatch.setattr(rt, "start_scheduling", lambda **kw: seen.update(kw) or {"run_id": "t"})
    return seen


def test_run_ga_rejects_unknown_keys_and_still_accepts_every_key_the_page_sends(client, db, started):
    db.tables["faculty"] = [{"id": "f1", "dept": "IT", "name": "Prof A", "specializations": ["Programming"], "max_units": 24,
                             "overload_buffer": 6, "availability": ["Mon"]}]
    h = H(IT_CHAIR)
    r = client.post("/run-ga", json={"dept": "IT", "subjects": [{"group_id": "x"}], "is_admin": True, "evil": 1}, headers=h)
    assert r.status_code == 400 and "Unknown field" in r.get_json()["error"] and started == {}
    page = {"dept": "IT", "academic_year": "2026-2027", "faculty": [], "subjects": [{"group_id": "x"}], "population": 20,
            "generations": 50, "mutation": 0.15, "crossover": 0.8, "soft_constraints": {}, "active_semester": "1st Semester",
            "class_sizes": {}, "room_capacity": {}, "units_per_assignment": 2, "cp_sat_time_limit": 30}
    assert client.post("/run-ga", json=page, headers=h).status_code == 200


# ── S10: short profile cache ─────────────────────────────────────────────────
def test_profile_cache_is_short_and_expires(monkeypatch):
    assert auth.PROFILE_TTL_SECONDS <= 15
    calls = {"n": 0}
    monkeypatch.setattr(auth, "_load_profile", lambda uid: calls.update(n=calls["n"] + 1) or {"id": uid, "role": "faculty", "dept": "IT"})
    auth.clear_profile_cache()
    now = {"t": 1000.0}
    monkeypatch.setattr(auth.time, "monotonic", lambda: now["t"])
    auth.get_profile("u1")
    auth.get_profile("u1")
    assert calls["n"] == 1                               # cached
    now["t"] += auth.PROFILE_TTL_SECONDS + 1
    auth.get_profile("u1")
    assert calls["n"] == 2                               # expired: a removed or demoted user is seen again
    auth.clear_profile_cache()


# ── SQL side: the schema and the SQL tests carry the S1, S4 and S5 rules ─────
def test_schema_and_sql_tests_cover_s1_s4_s5():
    sql, tests = read("db/schema.sql"), read("db/rls_tests.sql")
    guard = sql[sql.index("function public.schedule_runs_guard"):sql.index("create trigger trg_runs_guard")]
    assert "approved run cannot be demoted" in guard and "old.status = 'approved' and new.status is distinct from 'approved'" in guard
    pol = sql[sql.index("create policy atlas_audit_insert_self"):sql.index("create policy atlas_audit_admin_read")]
    for action in ("faculty_added", "faculty_edited", "faculty_deleted", "solver_settings_changed"):
        assert f"'{action}'" in pol
    assert "drop policy if exists atlas_audit_insert_self" in sql
    purge = sql[sql.index("function public.purge_audit_log"):sql.index("revoke all on function public.approve_run")]
    assert "interval '12 months'" in purge and "atlas.allow_short_purge" in purge
    for needle in ("S1", "S4", "S5", "cannot be demoted", "ALL RLS TESTS PASSED"):
        assert needle in tests


def test_docs_say_exactly_what_the_audit_trail_guarantees():
    text = read("docs/DATA.md")
    assert "audit trail guarantees" in text.lower() and "faculty_added" in text and "12 months" in text