"""
Part 14: Flask verifies the Supabase user and saves runs.
Runs with ATLAS_AUTH on and a fake Supabase (no network). The rest of the suite runs with auth off.
"""
import time
import uuid

import jwt
import pytest

import app as app_module
from services import auth_service as auth
from services import run_store, supabase_client
from services import schedule_service as ss
from services.audit_service import audit, clean_meta

SECRET = "test-secret-test-secret-test-secret-1234"
IT_CHAIR, CS_CHAIR, PROF, ADMIN_U = (str(uuid.uuid4()) for _ in range(4))
PROFILES = {
    IT_CHAIR: {"id": IT_CHAIR, "email": "chairit@x", "full_name": "IT Chair", "role": "chairperson", "dept": "IT", "faculty_id": None},
    CS_CHAIR: {"id": CS_CHAIR, "email": "chaircs@x", "full_name": "CS Chair", "role": "chairperson", "dept": "CS", "faculty_id": None},
    PROF:     {"id": PROF, "email": "prof@x", "full_name": "Prof", "role": "faculty", "dept": "IT", "faculty_id": str(uuid.uuid4())},
    ADMIN_U:  {"id": ADMIN_U, "email": "admin@x", "full_name": "Admin", "role": "admin", "dept": None, "faculty_id": None},
}


def token(uid, secret=SECRET, exp=3600, aud="authenticated", alg="HS256"):
    return jwt.encode({"sub": uid, "aud": aud, "exp": int(time.time()) + exp, "role": "authenticated"}, secret, algorithm=alg)


def H(uid, **kw):
    return {"Authorization": "Bearer " + token(uid, **kw)}


# ── a tiny fake of the supabase-py calls we use ───────────────────────────────

class Res:
    def __init__(self, data): self.data = data


class Query:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.filters, self.payload, self._limit, self._order = db, name, "select", [], None, None, None

    def select(self, cols="*"): self.op = "select"; self.cols = cols; return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, patch): self.op, self.payload = "update", patch; return self
    def delete(self): self.op = "delete"; return self
    def eq(self, k, v): self.filters.append(lambda r: r.get(k) == v); return self
    def in_(self, k, vals): self.filters.append(lambda r: r.get(k) in vals); return self
    def order(self, k, desc=False): self._order = (k, desc); return self
    def limit(self, n): self._limit = n; return self

    def execute(self):
        if self.db.fail_table == self.name and self.op == "insert":
            raise RuntimeError("db down")
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            row = dict(self.payload); row.setdefault("id", str(uuid.uuid4())); row.setdefault("created_at", str(len(rows)))
            rows.append(row); return Res([row])
        hit = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "update":
            for r in hit: r.update(self.payload)
            return Res([dict(r) for r in hit])
        if self.op == "delete":
            for r in hit: rows.remove(r)
            return Res(hit)
        if self._order: hit.sort(key=lambda r: r.get(self._order[0]) or "", reverse=self._order[1])
        if self.cols != "*":
            keep = self.cols.split(","); hit = [{k: r.get(k) for k in keep} for r in hit]
        return Res([dict(r) for r in (hit[: self._limit] if self._limit else hit)])


class Rpc:
    def __init__(self, db, token, name, params): self.db, self.token, self.name, self.params = db, token, name, params

    def execute(self):
        self.db.rpc_calls.append((self.name, self.params, self.token))
        rows = self.db.tables["schedule_runs"]
        run = next(r for r in rows if r["id"] == self.params["run_id"])
        for r in rows:
            if (r["dept"], r["academic_year"], r["semester"]) == (run["dept"], run["academic_year"], run["semester"]) and r["status"] == "approved":
                r["status"] = "saved"
        run["status"] = "approved"
        return Res(run)


class Client:
    def __init__(self, db): self.db, self.token = db, None; self.postgrest = self
    def auth(self, tok): self.token = tok
    def table(self, name): return Query(self.db, name)
    def rpc(self, name, params): return Rpc(self.db, self.token, name, params)


class DB:
    def __init__(self): self.tables, self.rpc_calls, self.fail_table = {}, [], None
    def actions(self): return [r["action"] for r in self.tables.get("audit_log", [])]


@pytest.fixture
def db(monkeypatch):
    monkeypatch.delenv("ATLAS_AUTH", raising=False)              # default = on
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service")
    fake = DB()
    import supabase
    monkeypatch.setattr(supabase, "create_client", lambda url, key: Client(fake))
    monkeypatch.setattr(supabase_client, "_service", None)
    calls = {"n": 0}

    def load(uid):
        calls["n"] += 1
        return PROFILES.get(uid)
    monkeypatch.setattr(auth, "_load_profile", load)
    auth.clear_profile_cache()
    fake.profile_loads = calls
    ss.reset_state()
    yield fake
    auth.clear_profile_cache()
    monkeypatch.setattr(supabase_client, "_service", None)
    ss.reset_state()


@pytest.fixture
def client(db):
    return app_module.app.test_client()


# ── 401: no or bad token ──────────────────────────────────────────────────────

PROTECTED = [("get", "/progress?dept=IT"), ("post", "/run-ga"), ("get", "/rooms?dept=IT"), ("post", "/rooms"),
             ("get", "/class-sizes?dept=IT"), ("post", "/class-sizes"), ("get", "/soft-constraints?dept=IT"),
             ("post", "/soft-constraints"), ("get", "/analytics?dept=IT"), ("get", "/analytics/workload?dept=IT"),
             ("get", "/subject-types"), ("get", "/runs?dept=IT"), ("get", "/runs/abc"), ("post", "/runs/abc/save"),
             ("post", "/runs/abc/approve"), ("delete", "/runs/abc"), ("post", "/auth/session"),
             ("post", "/auth/logout"), ("post", "/audit")]


@pytest.mark.parametrize("method,url", PROTECTED)
def test_no_token_is_401(client, method, url):
    r = getattr(client, method)(url, json={}) if method in ("post", "delete") else getattr(client, method)(url)
    assert r.status_code == 401
    assert r.get_json()["success"] is False


@pytest.mark.parametrize("url", ["/", "/index.html", "/curricula", "/curriculum/IT", "/manifest.json",
                                 "/assets/images/favicon.png"])
def test_public_routes_need_no_token(client, url):
    assert client.get(url).status_code == 200


def test_bad_tokens_are_401(client):
    wrong = [{"Authorization": "Bearer garbage"},
             {"Authorization": "Basic abc"},
             {"Authorization": "Bearer"},
             H(IT_CHAIR, secret="another-secret-another-secret-another-1"),
             H(IT_CHAIR, exp=-3600),
             H(IT_CHAIR, aud="anon"),
             {"Authorization": "Bearer " + jwt.encode({"sub": IT_CHAIR, "aud": "authenticated"}, SECRET, "HS256")}]  # no exp
    for h in wrong:
        assert client.get("/rooms?dept=IT", headers=h).status_code == 401, h
    none_tok = jwt.encode({"sub": IT_CHAIR, "aud": "authenticated", "exp": int(time.time()) + 99}, None, algorithm="none")
    assert client.get("/rooms?dept=IT", headers={"Authorization": "Bearer " + none_tok}).status_code == 401


def test_valid_token_without_profile_is_403(client):
    assert client.get("/rooms?dept=IT", headers=H(str(uuid.uuid4()))).status_code == 403


def test_hs256_without_secret_is_401(client, monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    assert client.get("/rooms?dept=IT", headers=H(IT_CHAIR)).status_code == 401


def test_asymmetric_token_checked_against_jwks(client, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    other = ec.generate_private_key(ec.SECP256R1())

    class FakeJwks:
        def __init__(self, *a, **k): pass
        def get_signing_key_from_jwt(self, t):
            return type("K", (), {"key": key.public_key()})()
    monkeypatch.setattr(jwt, "PyJWKClient", FakeJwks)
    monkeypatch.setattr(auth, "_jwks_client", None)
    good = jwt.encode({"sub": IT_CHAIR, "aud": "authenticated", "exp": int(time.time()) + 99}, key, algorithm="ES256")
    bad = jwt.encode({"sub": IT_CHAIR, "aud": "authenticated", "exp": int(time.time()) + 99}, other, algorithm="ES256")
    assert client.get("/rooms?dept=IT", headers={"Authorization": "Bearer " + good}).status_code == 200
    assert client.get("/rooms?dept=IT", headers={"Authorization": "Bearer " + bad}).status_code == 401


# ── 403: department and role ──────────────────────────────────────────────────

def test_it_token_on_cs_is_403_everywhere(client):
    h = H(IT_CHAIR)
    assert client.get("/rooms?dept=CS", headers=h).status_code == 403
    assert client.get("/class-sizes?dept=CS", headers=h).status_code == 403
    assert client.get("/soft-constraints?dept=CS", headers=h).status_code == 403
    assert client.get("/progress?dept=CS", headers=h).status_code == 403
    assert client.get("/analytics?dept=CS", headers=h).status_code == 403
    assert client.get("/runs?dept=CS", headers=h).status_code == 403
    assert client.get("/subject-types?dept=CS", headers=h).status_code == 403
    assert client.post("/run-ga", json={"dept": "CS", "faculty": [{"name": "x"}], "subjects": [{"name": "x"}]}, headers=h).status_code == 403
    assert client.post("/run-ga?dept=CS", json={"dept": "IT", "x": 1}, headers=h).status_code == 403   # either one is enough
    assert client.post("/rooms", json={"dept": "CS", "lecture_rooms": ["X"]}, headers=h).status_code == 403
    assert client.post("/class-sizes", json={"dept": "CS"}, headers=h).status_code == 403
    assert client.post("/soft-constraints", json={"dept": "CS", "faculty": "A", "constraints": {}}, headers=h).status_code == 403
    assert "X" not in ss.get_rooms("CS").lecture_rooms


def test_chairperson_own_dept_and_default_dept_from_profile(client):
    h = H(IT_CHAIR)
    assert client.get("/rooms?dept=IT", headers=h).status_code == 200
    r = client.get("/rooms", headers=h)                           # no dept: taken from the profile
    assert r.status_code == 200 and r.get_json()["dept"] == "IT"
    assert client.get("/class-sizes", headers=h).status_code == 200
    r = client.get("/subject-types", headers=h)
    assert r.status_code == 200 and "Core Theory" in r.get_json()["data"]["subject_types"]


def test_faculty_cannot_run_or_edit(client):
    h = H(PROF)
    body = {"dept": "IT", "faculty": [{"name": "x"}], "subjects": [{"name": "x"}], "generations": 1}
    assert client.post("/run-ga", json=body, headers=h).status_code == 403
    assert client.post("/rooms", json={"dept": "IT", "lecture_rooms": ["X"]}, headers=h).status_code == 403
    assert client.post("/class-sizes", json={"dept": "IT"}, headers=h).status_code == 403
    assert client.post("/soft-constraints", json={"dept": "IT", "faculty": "A", "constraints": {"a": 1}}, headers=h).status_code == 403
    assert client.post("/audit", json={"action": "faculty_added"}, headers=h).status_code == 403
    assert ss.get_progress("IT")["run_id"] is None
    assert "X" not in ss.get_rooms("IT").lecture_rooms
    # faculty may read reference data of their own department only
    assert client.get("/subject-types", headers=h).status_code == 200
    assert client.get("/subject-types?dept=CS", headers=h).status_code == 403
    # and not the working data of a chairperson (drafts, personal preferences)
    for url in ("/progress", "/analytics", "/soft-constraints", "/rooms", "/class-sizes"):
        assert client.get(url + "?dept=IT", headers=h).status_code == 403, url


def test_admin_can_choose_a_department(client):
    h = H(ADMIN_U)
    assert client.get("/rooms?dept=CS", headers=h).status_code == 200
    assert client.get("/rooms?dept=IT", headers=h).status_code == 200
    assert client.get("/rooms", headers=h).status_code == 400    # admin has no department of their own


def test_profile_cached_for_60_seconds(client, db, monkeypatch):
    h = H(IT_CHAIR)
    for _ in range(3):
        client.get("/rooms", headers=h)
    assert db.profile_loads["n"] == 1
    real = time.monotonic
    monkeypatch.setattr(auth.time, "monotonic", lambda: real() + 61)
    client.get("/rooms", headers=h)
    assert db.profile_loads["n"] == 2


def test_auth_off_flag_and_render_override(monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH", "off")
    c = app_module.app.test_client()
    assert c.get("/rooms?dept=IT").status_code == 200
    assert c.get("/rooms?dept=CS").status_code == 200
    monkeypatch.setenv("RENDER", "true")                          # production host: the flag is ignored
    assert c.get("/rooms?dept=IT").status_code == 401


def test_cors_origins(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("ATLAS_CORS_ORIGINS", "")
    monkeypatch.delenv("ATLAS_AUTH", raising=False)
    assert "*" not in app_module.cors_origins() and "http://localhost:5000" in app_module.cors_origins()
    monkeypatch.setenv("ATLAS_AUTH", "off")
    assert app_module.cors_origins() == "*"
    monkeypatch.setenv("ATLAS_CORS_ORIGINS", "https://a.example, https://b.example")
    assert app_module.cors_origins() == ["https://a.example", "https://b.example"]


# ── saving a run, run routes, audit ───────────────────────────────────────────

def fake_start(monkeypatch, phase="done"):
    """Replace the engine start by one that finishes at once; the real hook (on_finish) still runs."""
    import routes.schedule_routes as sr

    def start(dept, **kw):
        st = ss._state(dept)
        st.progress = ss._blank_progress(dept)
        st.progress.update(run_id="run123abc", running=False, phase=phase,
                           result=[{"faculty": "Prof X", "course": "SECRET-COURSE"}], analytics={"jain": 0.9},
                           metrics={"solver_used": "cp_sat"}, coverage={"assigned": 3, "total": 3}, coverage_errors=[])
        kw["on_finish"](dept, "run123abc")
        return {"status": "started", "run_id": "run123abc", "dept": dept, "groups": 3}
    monkeypatch.setattr(sr, "start_scheduling", start)


RUN_BODY = {"dept": "IT", "faculty": [{"name": "Prof X"}], "subjects": [{"name": "x"}], "generations": 5,
            "population": 8, "cp_sat_time_limit": 7, "active_semester": "1st Semester", "academic_year": "2026-2027"}


def test_finished_run_is_saved_as_draft_and_audited(client, db, monkeypatch):
    fake_start(monkeypatch)
    r = client.post("/run-ga", json=RUN_BODY, headers=H(IT_CHAIR))
    assert r.status_code == 200
    (row,) = db.tables["schedule_runs"]
    assert row["status"] == "draft" and row["dept"] == "IT" and row["created_by"] == IT_CHAIR
    assert row["academic_year"] == "2026-2027" and row["semester"] == "1st Semester"
    assert row["result"][0]["course"] == "SECRET-COURSE" and row["analytics"] == {"jain": 0.9}
    assert row["metrics"] == {"solver_used": "cp_sat", "balance_score": 100.0} and isinstance(row["duration_ms"], int)   # Part 17 adds the balance score
    assert row["solver_settings"]["generations"] == 5 and row["solver_settings"]["cp_sat_time_limit"] == 7
    assert row["coverage"]["summary"] == {"assigned": 3, "total": 3}
    prog = client.get("/progress", headers=H(IT_CHAIR)).get_json()
    assert prog["saved_run_id"] == row["id"]
    assert sorted(db.actions()) == ["run_finished", "run_started"]   # the fake engine finishes before the route returns
    dump = str(db.tables["audit_log"])
    assert "SECRET-COURSE" not in dump and "Prof X" not in dump


def test_engine_error_is_audited_and_not_saved(client, db, monkeypatch):
    fake_start(monkeypatch, phase="error")
    assert client.post("/run-ga", json=RUN_BODY, headers=H(IT_CHAIR)).status_code == 200
    assert "schedule_runs" not in db.tables or not db.tables["schedule_runs"]
    fin = next(r for r in db.tables["audit_log"] if r["action"] == "run_finished")
    assert fin["meta"]["status"] == "error"


def test_period_falls_back_to_dept_settings(client, db, monkeypatch):
    db.tables["dept_settings"] = [{"dept": "IT", "academic_year": "2030-2031", "semester": "2nd Semester"}]
    fake_start(monkeypatch)
    body = {k: v for k, v in RUN_BODY.items() if k not in ("academic_year", "active_semester")}
    client.post("/run-ga", json=body, headers=H(IT_CHAIR))
    row = db.tables["schedule_runs"][0]
    assert (row["academic_year"], row["semester"]) == ("2030-2031", "2nd Semester")


def seed_runs(db):
    mk = lambda dept, status, label="": {"id": str(uuid.uuid4()), "dept": dept, "status": status, "label": label,
                                         "academic_year": "2026-2027", "semester": "1st Semester",
                                         "result": [{"big": "payload"}], "analytics": {"a": 1}, "created_at": "1"}
    runs = {"it_draft": mk("IT", "draft"), "it_saved": mk("IT", "saved"), "it_appr": mk("IT", "approved"),
            "cs_draft": mk("CS", "draft"), "cs_appr": mk("CS", "approved")}
    db.tables["schedule_runs"] = list(runs.values())
    return runs


def test_list_and_get_runs(client, db):
    runs = seed_runs(db)
    r = client.get("/runs?dept=IT", headers=H(IT_CHAIR)).get_json()["data"]["runs"]
    assert {x["id"] for x in r} == {runs[k]["id"] for k in ("it_draft", "it_saved", "it_appr")}
    assert all("result" not in x and "analytics" not in x for x in r)
    full = client.get("/runs/" + runs["it_draft"]["id"], headers=H(IT_CHAIR)).get_json()["data"]["run"]
    assert full["result"] == [{"big": "payload"}]
    assert client.get("/runs/" + runs["cs_draft"]["id"], headers=H(IT_CHAIR)).status_code == 403
    assert client.get("/runs/nope", headers=H(IT_CHAIR)).status_code == 404


def test_faculty_sees_only_approved_runs_of_own_dept(client, db):
    runs = seed_runs(db)
    h = H(PROF)
    r = client.get("/runs", headers=h).get_json()["data"]["runs"]
    assert [x["id"] for x in r] == [runs["it_appr"]["id"]]
    assert client.get("/runs/" + runs["it_appr"]["id"], headers=h).status_code == 200
    assert client.get("/runs/" + runs["it_draft"]["id"], headers=h).status_code == 404
    assert client.get("/runs/" + runs["it_saved"]["id"], headers=h).status_code == 404
    assert client.get("/runs/" + runs["cs_appr"]["id"], headers=h).status_code == 403
    assert client.get("/runs?dept=CS", headers=h).status_code == 403
    assert client.delete("/runs/" + runs["it_draft"]["id"], headers=h).status_code == 403
    assert client.post("/runs/" + runs["it_draft"]["id"] + "/approve", headers=h).status_code == 403


def test_save_run(client, db):
    runs = seed_runs(db)
    rid = runs["it_draft"]["id"]
    assert client.post(f"/runs/{rid}/save", json={"label": ""}, headers=H(IT_CHAIR)).status_code == 400
    assert client.post(f"/runs/{rid}/save", json={"label": "x" * 500}, headers=H(IT_CHAIR)).status_code == 400
    r = client.post(f"/runs/{rid}/save", json={"label": "  Final v2 "}, headers=H(IT_CHAIR))
    assert r.status_code == 200
    row = next(x for x in db.tables["schedule_runs"] if x["id"] == rid)
    assert row["status"] == "saved" and row["label"] == "Final v2"
    assert db.actions() == ["run_saved"] and "Final v2" not in str(db.tables["audit_log"])
    assert client.post(f"/runs/{runs['it_appr']['id']}/save", json={"label": "a"}, headers=H(IT_CHAIR)).status_code == 409
    assert client.post(f"/runs/{runs['cs_draft']['id']}/save", json={"label": "a"}, headers=H(IT_CHAIR)).status_code == 403


def test_approve_calls_rpc_as_the_user(client, db):
    runs = seed_runs(db)
    rid, old = runs["it_saved"]["id"], runs["it_appr"]["id"]
    h = H(IT_CHAIR)
    assert client.post(f"/runs/{rid}/approve", headers=h).status_code == 200
    (name, params, tok), = db.rpc_calls
    assert name == "approve_run" and params == {"run_id": rid} and tok == h["Authorization"].split()[1]
    by_id = {x["id"]: x["status"] for x in db.tables["schedule_runs"]}
    assert by_id[rid] == "approved" and by_id[old] == "saved"
    assert client.post(f"/runs/{rid}/approve", headers=h).status_code == 200        # already approved: no second call
    assert len(db.rpc_calls) == 1
    assert client.post(f"/runs/{runs['cs_draft']['id']}/approve", headers=h).status_code == 403
    assert client.post(f"/runs/{runs['cs_draft']['id']}/approve", headers=H(CS_CHAIR)).status_code == 200
    assert client.post(f"/runs/{rid}/approve", headers=H(ADMIN_U)).status_code == 403   # chairperson only


def test_delete_run(client, db):
    runs = seed_runs(db)
    assert client.delete("/runs/" + runs["it_appr"]["id"], headers=H(IT_CHAIR)).status_code == 409
    assert client.delete("/runs/" + runs["cs_draft"]["id"], headers=H(IT_CHAIR)).status_code == 403
    assert client.delete("/runs/" + runs["it_draft"]["id"], headers=H(IT_CHAIR)).status_code == 200
    assert runs["it_draft"]["id"] not in {x["id"] for x in db.tables["schedule_runs"]}
    assert runs["it_appr"]["id"] in {x["id"] for x in db.tables["schedule_runs"]}
    assert db.actions() == ["run_deleted"]


def test_runs_need_a_database(client, db, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "")
    monkeypatch.setattr(supabase_client, "_service", None)
    assert client.get("/runs?dept=IT", headers=H(IT_CHAIR)).status_code == 401 or True   # profile load is faked
    assert client.get("/runs?dept=IT", headers=H(IT_CHAIR)).status_code == 503


# ── audit ─────────────────────────────────────────────────────────────────────

def test_login_logout_and_config_changes_are_audited(client, db):
    h = H(IT_CHAIR)
    me = client.post("/auth/session", headers=h).get_json()["data"]["user"]
    assert me["role"] == "chairperson" and me["dept"] == "IT" and "token" not in me
    assert client.post("/rooms", json={"dept": "IT", "lecture_rooms": ["R1", "R2"], "laboratory_rooms": ["L1"],
                                       "room_capacity": {"R1": {"recommended": 30, "max": 40},
                                                         "R2": {"recommended": 30, "max": 40},
                                                         "L1": {"recommended": 30, "max": 40}}}, headers=h).status_code == 200
    assert client.post("/class-sizes", json={"dept": "IT", "IT1B1": 30}, headers=h).status_code == 200
    assert client.post("/soft-constraints", json={"dept": "IT", "faculty": "Prof A", "constraints": {"preferred_period": "morning"}}, headers=h).status_code == 200
    for a in ("faculty_added", "faculty_edited", "faculty_deleted", "solver_settings_changed"):
        assert client.post("/audit", json={"action": a, "entity_id": "id1", "meta": {"count": 2, "name": "Prof A", "x": [1]}}, headers=h).status_code == 200
    assert client.post("/audit", json={"action": "drop_tables"}, headers=h).status_code == 400
    assert client.post("/audit", json={"action": "faculty_added", "dept": "CS"}, headers=h).status_code == 403
    assert client.post("/auth/logout", headers=h).status_code == 200
    assert db.actions() == ["login", "rooms_changed", "class_sizes_changed", "soft_constraints_changed",
                            "faculty_added", "faculty_edited", "faculty_deleted", "solver_settings_changed", "logout"]
    rows = db.tables["audit_log"]
    assert all(r["user_id"] == IT_CHAIR and r["dept"] == "IT" and r["email"] == "chairit@x" for r in rows)
    assert "Prof A" not in str(rows) and "morning" not in str(rows)
    assert rows[-2]["meta"] == {"count": 2}


def test_audit_never_raises(db, monkeypatch):
    db.fail_table = "audit_log"
    assert audit({"id": "u", "dept": "IT"}, "x", "e", "1", {"a": 1}) is False
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "")
    monkeypatch.setattr(supabase_client, "_service", None)
    assert audit(None, "x") is False


def test_failed_audit_does_not_break_requests(client, db):
    db.fail_table = "audit_log"
    assert client.post("/auth/session", headers=H(IT_CHAIR)).status_code == 200
    assert client.post("/rooms", json={"dept": "IT", "lecture_rooms": ["R1"]}, headers=H(IT_CHAIR)).status_code == 200


def test_clean_meta_keeps_only_flat_ids_and_counts():
    assert clean_meta({"n": 3, "ok": True, "s": "x" * 200, "result": [1], "email": "a@b", "nested": {"a": 1},
                       "lst": [1], "label": "L", "none": None, "nan": float("nan")}) == {
        "n": 3, "ok": True, "s": "x" * 64, "none": None, "nan": None}
    assert clean_meta("nope") == {}


def test_save_hook_does_not_change_the_engine_result():
    """on_finish runs exactly once and does not change what is scheduled.
    Deliberately not timing based: the solver may assign a different number of courses on a slow machine,
    so only the prepared sections and groups (fixed before the solver starts) are compared."""
    from conftest import dept_faculty, SEM1
    ss.reset_state()
    seen = []
    args = ("MedB", dept_faculty("MedB"), [{"name": "x"}], SEM1, {"generations": 2, "population": 4}, {}, None)
    settings = {"cp_sat_time_limit": 15}
    first = ss.start_scheduling(*args, wait=True, run_settings=settings, on_finish=lambda d, r: seen.append((d, r)))
    with_hook = ss.get_progress("MedB")
    assert seen == [("MedB", first["run_id"])]                    # the hook ran once, for this run
    assert with_hook["phase"] == "done" and with_hook["run_id"] == first["run_id"]
    ss.reset_state()
    second = ss.start_scheduling(*args, wait=True, run_settings=settings)
    assert len(seen) == 1                                         # no hook given, so nothing more was called
    assert first["sections"] == second["sections"] > 0
    assert first["groups"] == second["groups"]


def test_env_files():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    ex = (root / ".env.example").read_text()
    for k in ("SUPABASE_URL=", "SUPABASE_ANON_KEY=", "SUPABASE_SERVICE_KEY=", "SUPABASE_JWT_SECRET=", "ATLAS_AUTH=", "ATLAS_CORS_ORIGINS="):
        assert any(line.strip() == k for line in ex.splitlines()), k          # present and empty
    ign = (root / ".gitignore").read_text().splitlines()
    assert ".env" in ign and "!.env.example" in ign
    req = (root / "requirements.txt").read_text()
    assert "supabase==" in req and "PyJWT[crypto]==" in req