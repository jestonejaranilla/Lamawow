"""
ATLAS PSU - Part 25: tests, repo hygiene, deployment (Q1, S6, S7, S8).
Run from the project root:  python -m pytest tests/test_part25.py -q
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".git", "node_modules", "__pycache__", "tests"}


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def site_files(*suffixes):
    return [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in suffixes and not (set(p.relative_to(ROOT).parts) & SKIP)]


# ── S7: fonts are served from this site ──────────────────────────────────────
def test_no_page_or_stylesheet_contacts_google_fonts():
    bad = [str(p.relative_to(ROOT)) for p in site_files(".html", ".css", ".js", ".json")
           if re.search(r"fonts\.(googleapis|gstatic)\.com", p.read_text(encoding="utf-8", errors="ignore"))]
    assert bad == []


def test_every_font_face_points_at_a_file_that_exists_and_keeps_a_system_fallback():
    css = read("assets/css/main-style.css")
    urls = re.findall(r"url\('\.\./fonts/([^']+)'\)", css)
    assert len(urls) >= 10 and all((ROOT / "assets/fonts" / u).is_file() for u in urls)
    assert "font-family: 'DM Sans'" in css and "font-weight: 700" in css and "font-display: swap" in css
    assert re.search(r"--font-sans:\s*'DM Sans', -apple-system", css)             # system-font fallback stays
    assert "--font-display: 'DM Serif Display', Georgia, serif" in css
    assert not re.search(r"@import\s+url\(", css)
    assert any(p.name.startswith("LICENSE") for p in (ROOT / "assets/fonts").iterdir())


def test_the_pages_load_the_shared_stylesheet_that_declares_the_fonts():
    for page in ("index.html", "404.html", "pages/login.html", "pages/dashboard.html", "faculty/dashboard.html", "app/menu.html"):
        assert "assets/css/main-style.css" in read(page), page


def test_data_md_no_longer_says_fonts_come_from_google():
    d = read("docs/DATA.md")
    assert "load fonts from Google" not in d and "assets/fonts" in d


# ── S6: deployment ───────────────────────────────────────────────────────────
def test_search_workers_follow_the_cpu_count_capped_at_8(monkeypatch):
    from solver import cp_sat_solver as cps
    for cpus, want in ((1, 1), (2, 2), (8, 8), (64, 8), (None, 1)):
        monkeypatch.setattr(cps.os, "cpu_count", lambda c=cpus: c)
        assert cps._search_workers() == want
    assert "num_search_workers = 8" not in read("solver/cp_sat_solver.py")


def test_docs_give_the_render_start_command_and_the_in_memory_limits():
    r = read("README.md")
    cmd = "gunicorn app:app --workers 1 --threads 4 --timeout 120"
    assert cmd in r and cmd in read("docs/DEPLOY.md")
    assert "loses a running job" in r and "share one run state" in r


def test_requirements_dev_and_the_playwright_install_step():
    dev = read("requirements-dev.txt").split()
    assert "-r" in dev and "requirements.txt" in dev and "pytest" in dev and "playwright" in dev
    assert "python -m playwright install chromium" in read("README.md")


# ── S8: the deploy checklist holds no secret ─────────────────────────────────
def test_deploy_md_has_the_rotation_checklist_and_no_real_value():
    d = read("docs/DEPLOY.md")
    for needle in ("SUPABASE_SERVICE_KEY", "SUPABASE_JWT_SECRET", "git log --all", "-- .env", "test_part18.py"):
        assert needle in d, needle
    assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}", d) and not re.search(r"sb_secret_|service_role\s*[:=]", d)
    assert not re.search(r"SUPABASE_\w+\s*=\s*\S", d)                              # names only, never NAME=value
    assert "\u2014" not in d and "\u2013" not in d


def test_env_is_git_ignored():
    ig = read(".gitignore").splitlines()
    assert ".env" in ig and ".env.*" in ig


# ── Q1: cleanup and stale tests ──────────────────────────────────────────────
def test_unused_dash_brand_css_is_gone_and_nothing_uses_it():
    assert "dash-brand" not in read("assets/css/main-style.css")
    assert not [p for p in site_files(".html", ".js") if "dash-brand" in p.read_text(encoding="utf-8", errors="ignore")]


@pytest.mark.parametrize("rel,needle", [
    ("tests/test_dashboard_display.py", ".nav-item[data-panel='3']"),
    ("tests/test_dept_isolation.py", ".nav-item[data-panel='3']"),
    ("tests/test_part16.py", ".nav-item[data-panel='3']"),
    ("tests/test_part17.py", ".nav-item[data-panel='1']"),
])
def test_the_formerly_stale_browser_tests_open_their_panel_first(rel, needle):
    assert needle in read(rel)


def test_the_solver_load_check_runs_in_deterministic_mode():
    t = read("tests/test_part6.py")
    assert "deterministic=True" in t and "seed=1" in t