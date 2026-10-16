"""
ATLAS PSU - Part 18: audit log screen, retention tool, data documentation, final checks.

- GET /audit (read only, department scoped, four fields, filters, paging) with auth on and a fake Supabase.
- The Audit log card on the chairperson's Application Settings page (static checks).
- scripts/purge_audit_log.py (interval parsing, the 12 month production floor, confirmation).
- db/rls_tests.sql run for real against a throwaway PostgreSQL when ATLAS_TEST_PG is set (see test_rls_sql_on_postgres).
- A secret scan of the repository files that are shipped.
Run from the project root:  python -m pytest tests/test_part18.py -q
"""
import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

import test_part14 as p14
from test_part14 import ADMIN_U, CS_CHAIR, H, IT_CHAIR, PROF, client, db  # noqa: F401  (fixtures)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import purge_audit_log as purge  # noqa: E402


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ── the fake database learns the few extra calls GET /audit uses ──────────────

_orig_execute = p14.Query.execute


def _gte(self, k, v): self.filters.append(lambda r: (r.get(k) or "") >= v); return self
def _lt(self, k, v): self.filters.append(lambda r: (r.get(k) or "") < v); return self
def _range(self, a, b): self._range = (a, b); return self


def _execute(self):
    res = _orig_execute(self)
    rng = getattr(self, "_range", None)
    if rng and self.op == "select":
        res = p14.Res(res.data[rng[0]: rng[1] + 1])
    return res


p14.Query.gte, p14.Query.lt, p14.Query.range, p14.Query.execute = _gte, _lt, _range, _execute


def seed(db, n_it=30, n_cs=3):
    rows = db.tables.setdefault("audit_log", [])
    for i in range(n_it):
        rows.append({"id": i, "at": "2026-10-%02dT08:00:00+00:00" % (i % 28 + 1), "user_id": IT_CHAIR, "email": "chairit@x",
                     "dept": "IT", "action": "run_saved" if i % 2 else "login", "entity": "run", "entity_id": "secret-id-%d" % i,
                     "meta": {"labelled": True}})
    for i in range(n_cs):
        rows.append({"id": 100 + i, "at": "2026-10-05T08:00:00+00:00", "user_id": CS_CHAIR, "email": "chaircs@x",
                     "dept": "CS", "action": "login", "entity": "session", "entity_id": "cs-%d" % i, "meta": {}})


def get(client, uid, qs=""):
    return client.get("/audit" + qs, headers=H(uid))


# ── GET /audit ────────────────────────────────────────────────────────────────

def test_chair_sees_only_own_department_and_only_four_fields(client, db):
    seed(db)
    r = get(client, IT_CHAIR, "?page_size=100")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["dept"] == "IT" and len(data["rows"]) == 30
    assert all(set(x) == {"time", "user", "action", "entity"} for x in data["rows"])
    dump = json.dumps(data)
    assert "secret-id" not in dump and "chaircs" not in dump and "meta" not in dump and "user_id" not in dump
    times = [x["time"] for x in data["rows"]]
    assert times == sorted(times, reverse=True)


def test_chair_cannot_pick_another_department(client, db):
    seed(db)
    assert get(client, IT_CHAIR, "?dept=CS").status_code == 403
    cs = get(client, CS_CHAIR).get_json()["data"]
    assert cs["dept"] == "CS" and len(cs["rows"]) == 3


def test_faculty_and_signed_out_are_refused(client, db):
    seed(db)
    assert get(client, PROF).status_code == 403
    assert client.get("/audit").status_code == 401


def test_admin_may_choose_a_department(client, db):
    seed(db)
    assert len(get(client, ADMIN_U, "?dept=CS").get_json()["data"]["rows"]) == 3
    assert len(get(client, ADMIN_U, "?page_size=100").get_json()["data"]["rows"]) == 33


def test_action_filter(client, db):
    seed(db)
    rows = get(client, IT_CHAIR, "?action=run_saved&page_size=100").get_json()["data"]["rows"]
    assert rows and {x["action"] for x in rows} == {"run_saved"}


def test_date_range_includes_the_last_day(client, db):
    seed(db)
    rows = get(client, IT_CHAIR, "?from=2026-10-05&to=2026-10-05&page_size=100").get_json()["data"]["rows"]
    assert rows and all(x["time"].startswith("2026-10-05") for x in rows)
    none = get(client, IT_CHAIR, "?from=2027-01-01").get_json()["data"]["rows"]
    assert none == []


def test_paging_with_zero_one_page_and_many(client, db):
    assert get(client, IT_CHAIR).get_json()["data"] == {**get(client, IT_CHAIR).get_json()["data"], "rows": [], "has_more": False}
    seed(db, n_it=30)
    p1 = get(client, IT_CHAIR, "?page=1&page_size=25").get_json()["data"]
    p2 = get(client, IT_CHAIR, "?page=2&page_size=25").get_json()["data"]
    assert len(p1["rows"]) == 25 and p1["has_more"] is True
    assert len(p2["rows"]) == 5 and p2["has_more"] is False
    assert p1["rows"][-1]["time"] >= p2["rows"][0]["time"]


@pytest.mark.parametrize("qs", ["?page=0", "?page=abc", "?page_size=101", "?page_size=0", "?from=yesterday",
                                "?from=2026-10-10&to=2026-10-01", "?action=x;drop table", "?page=99999"])
def test_bad_parameters_are_400(client, db, qs):
    assert get(client, IT_CHAIR, qs).status_code == 400


def test_the_screen_is_read_only(client, db):
    seed(db)
    for m in ("put", "patch", "delete"):
        assert getattr(client, m)("/audit", headers=H(IT_CHAIR)).status_code == 405
    assert len(db.tables["audit_log"]) == 33


def test_database_failure_is_a_502_not_a_crash(client, db, monkeypatch):
    seed(db)
    monkeypatch.setattr(p14.Query, "execute", lambda self: (_ for _ in ()).throw(RuntimeError("down")))
    assert get(client, IT_CHAIR).status_code == 502
    monkeypatch.setattr(p14.Query, "execute", _execute)


# ── the card on Application Settings ──────────────────────────────────────────

def test_settings_page_has_a_hidden_audit_card_with_the_filters():
    html = read("app/application-settings.html")
    assert re.search(r'id="auditCard"[^>]*\shidden', html)
    for ident in ("auditAction", "auditFrom", "auditTo", "auditApply", "auditClear", "auditPrev", "auditNext", "auditTable"):
        assert 'id="%s"' % ident in html
    assert html.count("<th") >= 4 and "Time" in html and "Entity" in html


def test_audit_card_script_is_read_only_and_safe():
    js = read("assets/js/app-script.js")
    block = js[js.index("function initAuditLog"): js.index("/* ---------- Solver settings")]
    assert "innerHTML" not in block and "textContent" in block
    assert "method:" not in block and "audit_log" not in block         # only GET /audit through the API, never the table
    assert "role !== 'chairperson'" in block
    assert "initAuditLog();" in js


# ── scripts/purge_audit_log.py ────────────────────────────────────────────────

class FakePurgeClient:
    def __init__(self, count=7):
        self.count, self.rpcs = count, []

    def table(self, name): self.t = name; return self
    def select(self, *a, **k): return self
    def lt(self, *a): return self
    def limit(self, n): return self
    def rpc(self, name, params): self.rpcs.append((name, params)); return self

    def execute(self):
        class R: pass
        r = R()
        r.count, r.data = self.count, self.count
        return r


def run_purge(argv, answers, env=None, client=None):
    client = client or FakePurgeClient()
    said, it = [], iter(answers)
    code = purge.run(argv, client_factory=lambda e, p: client, ask=lambda prompt="": next(it),
                     ask_secret=lambda prompt="": "pw", env=env or {}, out=said.append)
    return code, client, said


def test_interval_parsing():
    assert purge.parse_interval("12 months")[0] == "12 months"
    assert purge.parse_interval("1 Day")[0] == "1 day"
    assert purge.parse_interval("52weeks")[0] == "52 weeks"
    for bad in ("", "12", "soon", "-1 day", "0 days", "1 day; drop table audit_log", "12 minutes"):
        with pytest.raises(ValueError):
            purge.parse_interval(bad)


def test_production_never_purges_under_12_months():
    for text in ("1 day", "11 months", "364 days", "51 weeks"):
        code, client, said = run_purge(["--older-than", text], ["a@x", "PURGE"], env={"ATLAS_ENV": "production"})
        assert code == 2 and client.rpcs == [] and any("12 months" in s for s in said)
    for text in ("12 months", "1 year", "400 days"):
        code, client, _ = run_purge(["--older-than", text], ["a@x", "PURGE"], env={"RENDER": "true"})
        assert code == 0 and client.rpcs == [("purge_audit_log", {"older_than": purge.parse_interval(text)[0]})]


def test_development_may_purge_freely_but_must_confirm():
    code, client, _ = run_purge(["--older-than", "1 day"], ["a@x", "PURGE"])
    assert code == 0 and client.rpcs == [("purge_audit_log", {"older_than": "1 day"})]
    code, client, said = run_purge(["--older-than", "1 day"], ["a@x", "yes"])
    assert code == 1 and client.rpcs == [] and any("Cancelled" in s for s in said)


def test_dry_run_deletes_nothing_and_reports_the_count():
    code, client, said = run_purge(["--older-than", "1 day", "--dry-run"], ["a@x"])
    assert code == 0 and client.rpcs == [] and any("7" in s for s in said)


def test_failed_sign_in_stops_the_purge():
    def boom(e, p): raise RuntimeError("bad login")
    said = []
    code = purge.run(["--older-than", "1 day"], client_factory=boom, ask=lambda prompt="": "a@x",
                     ask_secret=lambda prompt="": "pw", env={}, out=said.append)
    assert code == 1 and any("sign in" in s for s in said)


def test_script_never_takes_a_password_or_key_from_the_command_line():
    src = read("scripts/purge_audit_log.py")
    assert "--password" not in src and "SUPABASE_SERVICE_KEY" not in src.split('"""', 2)[2]


# ── the database rules as automated tests ─────────────────────────────────────

def test_schema_has_the_guards_that_rls_tests_expect():
    sql = read("db/schema.sql")
    for needle in ("drop trigger if exists trg_runs_guard", "create or replace function public.schedule_runs_guard",
                   "atlas.approving", "revoke update on public.audit_log from authenticated", "trg_audit_no_update",
                   "trg_audit_meta", "purge_audit_log", "atlas_audit_chair_read", "atlas_audit_insert_self"):
        assert needle in sql, needle
    tests = read("db/rls_tests.sql")
    assert "ALL RLS TESTS PASSED" in tests and "approved run" in tests and "audit" in tests


PG = os.environ.get("ATLAS_TEST_PG")


@pytest.mark.skipif(not (PG and shutil.which("psql")),
                    reason="set ATLAS_TEST_PG to the URL of an EMPTY throwaway PostgreSQL database (and have psql on PATH)")
def test_rls_sql_on_postgres():
    """Stub of Supabase's auth schema, then schema.sql (twice: it must be re-runnable), seed.sql, the test accounts,
    and db/rls_tests.sql, which must end by printing ALL RLS TESTS PASSED. Never point this at the real project."""
    def psql(rel, twice=False):
        out = ""
        for _ in range(2 if twice else 1):
            p = subprocess.run(["psql", PG, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / rel)],
                               capture_output=True, text=True, timeout=300)
            assert p.returncode == 0, rel + "\n" + p.stderr[-800:]
            out = p.stdout + p.stderr
        return out
    psql("tests/sql/local_setup.sql")
    psql("db/schema.sql", twice=True)
    psql("db/seed.sql")
    psql("tests/sql/local_accounts.sql")
    assert "ALL RLS TESTS PASSED" in psql("db/rls_tests.sql")


# ── secret scan ───────────────────────────────────────────────────────────────

SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache"}
SKIP_FILES = {".env"}                                    # local only, listed in .gitignore
TEXT = {".py", ".js", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml", ".example", ".ini"}


def shipped_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and p.name not in SKIP_FILES \
                and (p.suffix in TEXT or p.name == ".env.example") and "vendor" not in p.parts:
            yield p


def jwt_roles(text):
    for m in re.finditer(r"eyJ[A-Za-z0-9_-]{10,}\.([A-Za-z0-9_-]{10,})\.[A-Za-z0-9_-]{10,}", text):
        try:
            seg = m.group(1); seg += "=" * (-len(seg) % 4)
            yield json.loads(base64.urlsafe_b64decode(seg)).get("role")
        except Exception:                                # noqa: BLE001
            continue


def test_secret_scan_finds_no_private_keys_in_shipped_files():
    bad = []
    for p in shipped_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        rel = str(p.relative_to(ROOT))
        if p.name == "test_part18.py":                   # this file names the patterns it looks for
            continue
        if re.search(r"sb_secret_[A-Za-z0-9_-]{10,}", text) or "-----BEGIN PRIVATE KEY-----" in text:
            bad.append(rel + " (secret key)")
        if any(r == "service_role" for r in jwt_roles(text)):
            bad.append(rel + " (service_role token)")
        for m in re.finditer(r"(SUPABASE_SERVICE_KEY|SUPABASE_JWT_SECRET)\s*=\s*([^\s#]+)", text):
            if len(m.group(2).strip("'\"")) > 8 and p.suffix not in (".py", ".md") and p.name != "test_part18.py":
                bad.append(rel + " (" + m.group(1) + " has a value)")
    assert bad == [], bad


def test_env_files_are_ignored_and_the_example_is_empty():
    ignore = read(".gitignore")
    assert re.search(r"^\.env\s*$", ignore, re.M)
    for line in read(".env.example").splitlines():
        if re.match(r"\s*(SUPABASE_SERVICE_KEY|SUPABASE_JWT_SECRET)\s*=", line):
            assert line.split("=", 1)[1].strip() == "", line


def test_frontend_holds_only_the_public_key():
    cfg = read("assets/js/config.js")
    key = re.search(r"SUPABASE_ANON_KEY:\s*'([^']*)'", cfg).group(1)
    assert key.startswith("sb_publishable_") or set(jwt_roles(key)) == {"anon"}, "config.js must hold the public key only"
    for js in (ROOT / "assets" / "js").glob("*.js"):
        text = js.read_text(encoding="utf-8", errors="ignore")
        assert "sb_secret_" not in text and "service_role" not in set(jwt_roles(text)), js.name


# ── UI pass: no side-accent borders, saved-runs row fix, active period moved ──

def test_no_side_accent_borders_in_the_stylesheets_or_pages():
    for rel in ("assets/css/main-style.css", "assets/css/app-style.css", "assets/css/auth-style.css",
                "assets/css/faculty-style.css", "assets/css/landing-style.css", "pages/dashboard.html",
                "faculty/dashboard.html", "app/application-settings.html", "pages/login.html"):
        text = read(rel)
        for m in re.finditer(r"border-(left|inline-start)\s*:\s*([^;}\n]+)", text):
            assert re.match(r"\s*1px", m.group(2)), (rel, m.group(0))      # only hairlines (scrollbar track), never an accent bar


def test_saved_runs_actions_are_not_a_flex_table_cell():
    css = read("assets/css/main-style.css")
    assert not re.search(r"td\.run-actions|\.run-actions\s*\{[^}]*\}\s*/\*\s*td", css)
    js = read("assets/js/saved-runs.js")
    assert '<td class="run-actions">' not in js and '<td><div class="run-actions">' in js
    assert "Locked" in js                                              # the approved row shows a note, not an empty cell
    assert "#savedRunsTable tbody td { background: transparent; }" in css or "#savedRunsTable tbody tr, #savedRunsTable tbody td { background: transparent; }" in css


def test_active_period_moved_to_settings_and_is_asked_at_sign_in():
    assert "academicModeCard" not in read("pages/dashboard.html")
    html = read("app/application-settings.html")
    assert html.index('id="periodCard"') < html.index('id="solver"')
    js = read("assets/js/app-script.js")
    assert "function initPeriod" in js and "savePeriod" in js
    login = read("pages/login.html")
    assert 'id="periodModal"' in login and 'aria-modal="true"' in login and "periodSave" in login
    ls = read("assets/js/login-script.js")
    assert "role !== 'faculty'" in ls and "atlasPeriodAsked" in ls
    assert ls.index("askPeriod(result.user)") < ls.index("window.location.replace(auth.DASH")


def test_new_ui_only_uses_variables_that_have_a_dark_value():
    css = read("assets/css/main-style.css")
    dark = css[css.index('[data-theme="dark"] {'):]
    dark = dark[: dark.index("\n}")]
    for var in ("--bg-subtle", "--bg-surface-2", "--warn-soft", "--text-muted", "--text-primary"):
        assert var + ":" in dark, var
    new_css = read("assets/css/app-style.css").split("Active academic period card")[1]
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", new_css)               # no hard-coded colours in the new card