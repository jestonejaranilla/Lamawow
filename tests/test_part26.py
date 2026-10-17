"""
ATLAS PSU - Part 26: cleanup before the freeze (N1, N2, N3, N7).
Run from the project root:  python -m pytest tests/test_part26.py -q
"""
import copy
import re
import sys
from pathlib import Path

import pytest

import config.settings as cfg
from config import curriculum as cur
from conftest import make_faculty
from services import schedule_service as ss
from solver import cp_sat_solver as cps
from solver.constraints import is_open_assignment

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ── N1 ────────────────────────────────────────────────────────────────────────
def test_requirements_dev_lives_at_the_repo_root_only():
    assert (ROOT / "requirements-dev.txt").is_file() and not (ROOT / "docs" / "requirements-dev.txt").exists()
    for doc in ("README.md", "docs/DEPLOY.md", "docs/DATA.md"):
        assert "docs/requirements-dev.txt" not in read(doc)


# ── N2 ────────────────────────────────────────────────────────────────────────
def test_smoke_evaluation_outputs_are_gone_and_git_ignored():
    assert not (ROOT / "evaluation" / "results.csv").exists() and not (ROOT / "evaluation" / "summary.md").exists()
    assert (ROOT / "evaluation" / "README.md").is_file()
    ignore = read(".gitignore").split()
    assert "evaluation/results.csv" in ignore and "evaluation/summary.md" in ignore


def test_quick_evaluation_never_writes_into_the_paper_folder(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate as ev
    seen = {}
    monkeypatch.setattr(ev, "run_task", lambda t: [])
    monkeypatch.setattr(ev, "write_summary", lambda path, rows, o: seen.setdefault("summary", path))
    monkeypatch.setattr("tempfile.mkdtemp", lambda prefix="": str(tmp_path))
    ev.main(["--quick", "--skip-scenarios"])
    assert Path(seen["summary"]).parent == tmp_path
    assert Path(seen["summary"]).parent != ROOT / "evaluation"
    assert "--out" in read("scripts/evaluate.py") and "results.csv" in read("scripts/evaluate.py")


# ── N3 (tried and reverted: no gain at weight 2) ──────────────────────────────
def _one_group_case():
    ss.reset_state()
    prep = ss.prepare_scheduling_input("IT", [], "1st Semester", ss.get_class_sizes("IT"))
    lookup = ss.build_static_lookup("IT")
    first = next(s for s in prep["sections"] if s.get("class_type") != "NON_CLASSROOM"
                 and not is_open_assignment(s["name"], lookup))
    secs = [s for s in prep["sections"] if cps._gid(s) == cps._gid(first)]
    return secs, lookup, lookup[first["name"]]


def test_the_reverted_primary_tag_bonus_is_not_in_the_objective():
    assert "primary_tag" not in cfg.CP_WEIGHTS and "W.get(\"primary_tag\"" not in read("solver/cp_sat_solver.py")
    assert cfg.CP_WEIGHTS["fair_share"] > cfg.CP_WEIGHTS["load_balance"]      # fairness still decides


def test_a_professor_who_lists_the_course_tag_second_is_still_qualified_and_covered():
    secs, lookup, tags = _one_group_case()
    fac = [make_faculty("Secondary", ["NoSuchTag", tags[0]]), make_faculty("Primary", [tags[0], "NoSuchTag"])]
    with cfg.run_settings(seed=1, deterministic=True):
        rows, m = cps.solve(secs, fac, lookup, rooms=cur.rooms_for("IT"))
    assert rows and m["uncovered_groups"] == {} and {r["faculty"] for r in rows} <= {"Secondary", "Primary"}


# ── N7 ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    import app as app_module
    return app_module.app.test_client()


def _check_headers(resp):
    h = resp.headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"
    csp = h["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in re.search(r"script-src[^;]*", csp).group(0)


def test_security_headers_on_the_site_root(client):
    r = client.get("/")
    assert r.status_code == 200
    _check_headers(r)


def test_security_headers_on_an_api_response_and_the_service_worker(client):
    _check_headers(client.get("/curriculum/IT"))
    sw = client.get("/sw.js")
    _check_headers(sw)
    assert sw.headers["Cache-Control"] == "no-cache"


def test_csp_connections_use_the_supabase_url_from_the_environment(monkeypatch):
    import app as app_module
    monkeypatch.setenv("SUPABASE_URL", "https://abcd1234.supabase.co/")
    csp = app_module.content_security_policy()
    assert "connect-src 'self' https://abcd1234.supabase.co wss://abcd1234.supabase.co" in csp
    monkeypatch.setenv("SUPABASE_URL", "")
    assert "https://*.supabase.co" in app_module.content_security_policy()


def test_no_page_needs_an_inline_script():
    bad = []
    for rel in ("index.html", "404.html", "pages/login.html", "pages/dashboard.html",
                "app/menu.html", "app/appearance.html", "app/about.html", "app/application-settings.html",
                "app/notifications.html", "app/account.html"):
        html = read(rel)
        if re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) or re.search(r"\son(click|change|input|load|error|submit)=", html):
            bad.append(rel)
    assert bad == []
    assert "/assets/js/offline-page.js" in read("sw.js")