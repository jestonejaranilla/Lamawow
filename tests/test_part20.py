"""
ATLAS PSU - Part 20: reproducibility and run snapshots.
Run from the project root:  python -m pytest tests/test_part20.py -q
"""
import hashlib
import json
import random
from pathlib import Path

import pytest

import config.settings as cfg
from conftest import dept_faculty
from services import run_snapshot, run_store
from services import schedule_service as ss
from test_part14 import IT_CHAIR, PROF, H, client, db, seed_runs   # noqa: F401  (fixtures: db, client)

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def run_it(seed, deterministic=True):
    ss.reset_state("IT")
    subj = [{"group_id": g["group_id"]} for g in ss.build_groups("IT", "1st Semester", ss.get_class_sizes("IT"))[0]]
    out = ss.start_scheduling("IT", dept_faculty("IT"), subj, "1st Semester", {"generations": 4, "population": 6}, {}, None,
                              run_settings={"cp_sat_time_limit": 10}, seed=seed, deterministic=deterministic, wait=True)
    assert "run_id" in out, out
    p = ss.get_progress("IT")
    assert p["result"] and p["phase"] == "done"
    return p


_CACHE = {}


def run_cached(seed):
    """Runs are deterministic, so the tests that only need a finished run share one."""
    if seed not in _CACHE:
        _CACHE[seed] = run_it(seed)
    return _CACHE[seed]


def dump(p):
    return json.dumps(p["result"], sort_keys=True)


# ── seed and deterministic mode ───────────────────────────────────────────────
def test_same_seed_in_deterministic_mode_gives_byte_identical_schedules():
    random.seed(1)
    a = run_it(7)
    random.seed(999)                                   # the global generator must not matter
    b = run_it(7)
    assert dump(a) == dump(b)
    assert hashlib.sha256(dump(a).encode()).hexdigest() == hashlib.sha256(dump(b).encode()).hexdigest()
    assert a["inputs_raw"]["seed"] == 7 and a["inputs_raw"]["deterministic"] is True


def test_a_different_seed_still_finishes_with_the_same_rows():
    a, c = run_cached(7), run_cached(8)
    assert len(c["result"]) == len(a["result"]) and c["phase"] == "done"      # results may differ, the set of meetings does not


def test_ga_uses_only_its_own_generator():
    from solver import ga_optimizer
    base = run_cached(7)["result"]
    fac, sc = dept_faculty("IT"), {}
    ss.reset_state("IT")
    lookup = ss.build_static_lookup("IT")
    outs = []
    for global_seed in (1, 2):
        random.seed(global_seed)
        best, _ = ga_optimizer.optimize(base, fac, lookup, sc, generations=5, population_size=6, seed=11,
                                        deterministic=True, class_sizes=ss.get_class_sizes("IT"))
        outs.append(json.dumps(best, sort_keys=True))
    assert outs[0] == outs[1]
    assert "random.random(" not in read("solver/ga_optimizer.py").split("def optimize(")[0]


def test_seed_and_deterministic_settings_are_per_run():
    assert cfg.run_seed() == 1 and cfg.is_deterministic() is False
    with cfg.run_settings(seed=42, deterministic=True):
        assert cfg.run_seed() == 42 and cfg.is_deterministic() is True
    assert cfg.run_seed() == 1 and cfg.is_deterministic() is False


# ── the snapshot ──────────────────────────────────────────────────────────────
def test_a_saved_run_contains_inputs_with_a_matching_hash(db):
    p = run_cached(7)
    run_store.save_draft("IT", "11111111-1111-1111-1111-111111111111", p,
                         {"seed": 7, "deterministic": True}, 5, "2026-2027", "1st Semester")
    row = db.tables["schedule_runs"][-1]
    inp = row["inputs"]
    assert inp["schema"] == 1 and run_snapshot.verify(inp)
    data = inp["data"]
    assert hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() == inp["sha256"]
    assert data["seed"] == 7 and data["deterministic"] is True
    assert data["academic_year"] == "2026-2027" and data["semester"] == "1st Semester"
    f0 = data["faculty"][0]
    assert set(f0) == {"name", "specialization", "max_units", "overload_buffer", "absolute_max_units", "availability"}
    assert data["class_sizes"] and data["rooms"]["lecture_rooms"] and data["rooms"]["capacity"]
    assert inp["code_version"] and inp["libraries"]["python"] and "ortools" in inp["libraries"]
    tampered = json.loads(json.dumps(inp))
    tampered["data"]["seed"] = 8
    assert not run_snapshot.verify(tampered)


def test_the_hash_ignores_code_version_and_depends_on_the_inputs():
    d = {"dept": "IT", "faculty": [], "seed": 1}
    a, b = run_snapshot.finalize(d, "2026-2027", "1st Semester"), run_snapshot.finalize(d, "2026-2027", "1st Semester")
    assert a["sha256"] == b["sha256"]
    assert run_snapshot.finalize(d, "2026-2027", "2nd Semester")["sha256"] != a["sha256"]
    assert run_snapshot.finalize({**d, "seed": 2}, "2026-2027", "1st Semester")["sha256"] != a["sha256"]


def test_preferences_in_the_snapshot_keep_only_ids_and_dates():
    sc = {"Prof A": {"preferred_period": "morning", "restricted_days": ["Sat"], "reason": "private note",
                     "leave_dates": [{"start": "2026-11-01", "end": "2026-11-03", "why": "x"}], "maternity_leave": True}}
    out = run_snapshot._preferences(sc)
    assert out == {"Prof A": {"preferred_period": "morning", "restricted_days": ["Sat"],
                              "leave_dates": [{"start": "2026-11-01", "end": "2026-11-03"}]}}


def test_schema_adds_inputs_idempotently_and_the_guard_freezes_it():
    sql = read("db/schema.sql")
    assert "add column if not exists inputs jsonb" in sql
    guard = sql[sql.index("function public.schedule_runs_guard"):sql.index("create trigger trg_runs_guard")]
    assert guard.count("inputs") >= 2 and "new.inputs" in guard and "old.inputs" in guard


def test_faculty_never_receive_the_inputs_snapshot(client, db):
    runs = seed_runs(db)
    appr = runs["it_appr"]
    appr["inputs"] = {"data": {"preferences": {"Prof A": {"leave_dates": []}}}}
    staff = client.get("/runs/" + appr["id"], headers=H(IT_CHAIR)).get_json()["data"]["run"]
    assert "inputs" in staff
    seen = client.get("/runs/" + appr["id"], headers=H(PROF)).get_json()["data"]["run"]
    assert "inputs" not in seen


# ── /run-ga does not trust the browser ────────────────────────────────────────
@pytest.fixture
def started(monkeypatch):
    import routes.schedule_routes as rt
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"run_id": "t"}
    monkeypatch.setattr(rt, "start_scheduling", fake)
    return seen


def db_faculty(db):
    db.tables["faculty"] = [
        {"id": "f2", "dept": "IT", "name": "Prof Beta", "specializations": ["Programming", "Systems"], "max_units": 24,
         "overload_buffer": 6, "availability": ["Mon", "Tue"]},
        {"id": "f1", "dept": "IT", "name": "Prof Alpha", "specializations": ["Mathematics"], "max_units": 18,
         "overload_buffer": 4, "availability": ["Wed"]},
        {"id": "f9", "dept": "CS", "name": "Other Dept", "specializations": ["Programming"], "max_units": 24,
         "overload_buffer": 6, "availability": ["Mon"]},
    ]
    db.tables["faculty_preferences"] = [{"faculty_id": "f1", "preferred_period": "morning", "avoid_days": ["Sat"]}]
    db.tables["faculty_leave"] = [{"faculty_id": "f2", "start_date": "2026-11-02", "end_date": "2026-11-04"}]


FORGED = [{"name": "Forged Genius", "specialization": ["Programming", "Systems", "Mathematics"], "max_units": 99,
           "overload_buffer": 0, "absolute_max_units": 99, "availability": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]}]


def test_a_forged_client_faculty_list_does_not_change_the_run(client, db, started):
    db_faculty(db)
    body = {"dept": "IT", "faculty": FORGED, "subjects": [{"group_id": "x"}], "soft_constraints": {"Forged Genius": {"preferred_period": "evening"}},
            "class_sizes": {"IT1B1": 999}}
    r = client.post("/run-ga", json=body, headers=H(IT_CHAIR))
    assert r.status_code == 200
    assert [f["name"] for f in started["faculty_raw"]] == ["Prof Alpha", "Prof Beta"]     # database list, sorted by name
    assert started["faculty_raw"][0] == {"name": "Prof Alpha", "specialization": ["Mathematics"], "max_units": 18,
                                         "overload_buffer": 4, "absolute_max_units": 22, "availability": ["Wed"]}
    assert started["soft_constraints_incoming"] == {
        "Prof Alpha": {"preferred_period": "morning", "restricted_days": ["Sat"]},
        "Prof Beta": {"leave_dates": [{"start": "2026-11-02", "end": "2026-11-04"}]}}
    assert started["replace_preferences"] is True                                           # cleared preferences stay cleared
    assert started["class_sizes"] == {}                                                     # the browser's sizes are ignored
    assert any("differs" in w for w in r.get_json()["warnings"])


def test_a_matching_client_list_gives_no_warning(client, db, started):
    db_faculty(db)
    same = [{"name": "Prof Alpha", "specialization": ["Mathematics"], "max_units": 18, "absolute_max_units": 22, "availability": ["Wed"]},
            {"name": "Prof Beta", "specialization": ["Programming", "Systems"], "max_units": 24, "absolute_max_units": 30,
             "availability": ["Tue", "Mon"]}]
    r = client.post("/run-ga", json={"dept": "IT", "faculty": same, "subjects": [{"group_id": "x"}]}, headers=H(IT_CHAIR))
    assert r.status_code == 200 and r.get_json()["warnings"] == []


def test_a_chair_with_no_saved_faculty_gets_an_error_not_the_browsers_list(client, db, started):
    db.tables["faculty"] = []
    r = client.post("/run-ga", json={"dept": "IT", "faculty": FORGED, "subjects": [{"group_id": "x"}]}, headers=H(IT_CHAIR))
    assert r.status_code == 400 and started == {}


def test_database_unavailable_never_falls_back_to_the_browser(client, db, started, monkeypatch):
    def boom(dept):
        raise RuntimeError("db down")
    monkeypatch.setattr(run_store, "load_dept_inputs", boom)
    r = client.post("/run-ga", json={"dept": "IT", "faculty": FORGED, "subjects": [{"group_id": "x"}]}, headers=H(IT_CHAIR))
    assert r.status_code == 503 and started == {}


def test_size_caps(client, db, started):
    db_faculty(db)
    many_f = [{"name": "p%d" % i} for i in range(201)]
    many_s = [{"group_id": str(i)} for i in range(2001)]
    assert client.post("/run-ga", json={"dept": "IT", "faculty": many_f, "subjects": [{"group_id": "x"}]}, headers=H(IT_CHAIR)).status_code == 400
    assert client.post("/run-ga", json={"dept": "IT", "faculty": FORGED, "subjects": many_s}, headers=H(IT_CHAIR)).status_code == 400
    assert client.post("/run-ga", json={"dept": "IT", "faculty": [{"name": "p%d" % i} for i in range(200)],
                                        "subjects": [{"group_id": str(i)} for i in range(2000)]}, headers=H(IT_CHAIR)).status_code == 200


def test_seed_is_random_when_missing_given_when_sent_and_always_returned(client, db, started):
    db_faculty(db)
    h = H(IT_CHAIR)
    b = {"dept": "IT", "subjects": [{"group_id": "x"}]}
    r1 = client.post("/run-ga", json=b, headers=h).get_json()
    assert isinstance(r1["seed"], int) and started["seed"] == r1["seed"] and r1["deterministic"] is False
    r2 = client.post("/run-ga", json={**b, "seed": 123, "deterministic": True}, headers=h).get_json()
    assert r2["seed"] == 123 and r2["deterministic"] is True and started["seed"] == 123 and started["deterministic"] is True
    assert client.post("/run-ga", json={**b, "seed": "x"}, headers=h).status_code == 400
    assert client.post("/run-ga", json={**b, "deterministic": "yes"}, headers=h).status_code == 400


def test_docs_explain_the_snapshot_and_the_privacy_rule():
    text = read("docs/DATA.md").lower()
    assert "inputs" in text and "pseudonymous" in text and "privacy review" in text and "reproducib" in text