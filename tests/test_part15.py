"""
ATLAS PSU - Part 15: the demo login is replaced by Supabase Auth.
Static checks on the pages, plus tests/js/auth_harness.js (Node) which runs app-core.js against a fake Supabase.
Run from the project root:  python -m pytest tests/test_part15.py -q
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


GUARDED = ["pages/dashboard.html", "faculty/dashboard.html", "app/about.html", "app/account.html",
           "app/appearance.html", "app/application-settings.html", "app/menu.html", "app/notifications.html"]


# ── vendored supabase-js, config, client ──────────────────────────────────────

def test_supabase_js_is_vendored_not_loaded_from_a_cdn():
    from app import app
    r = app.test_client().get("/assets/vendor/supabase.js")
    assert r.status_code == 200 and b"createClient" in r.data and b"supabase" in r.data[:400]
    for rel in GUARDED + ["pages/login.html"]:
        html = read(rel)
        assert not re.search(r"<script[^>]+src=[\"']https?://", html), rel
    assert "MIT" in read("assets/vendor/supabase.license.md")


def test_config_has_only_public_values():
    js = read("assets/js/config.js")
    for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "API_BASE", "GOOGLE_ENABLED"):
        assert key in js
    assert "SERVICE_KEY" not in js and "sb_secret_" not in js
    assert "GOOGLE_ENABLED: false" in js
    assert "createClient" in read("assets/js/supabase-client.js")
    assert "SERVICE_KEY" not in read("assets/js/supabase-client.js")


@pytest.mark.parametrize("rel", GUARDED + ["pages/login.html"])
def test_pages_load_config_vendor_client_then_app_core(rel):
    html = read(rel)
    order = [html.index(f"assets/{name}") for name in
             ("js/config.js", "vendor/supabase.js", "js/supabase-client.js", "js/app-core.js")]
    assert order == sorted(order), rel


# ── login page ────────────────────────────────────────────────────────────────

def test_login_page_has_no_demo_chooser_and_no_role_or_department_picker():
    html = read("pages/login.html")
    for gone in ("data-pick-role", "auth-roles", "suDept", "cpDept", "js-dept", "gModal", "js-faculty", "signupForm"):
        assert gone not in html, gone
    assert 'id="siEmail"' in html and 'id="siPassword"' in html and 'type="submit"' in html


def test_google_button_is_hidden_until_enabled():
    html = read("pages/login.html")
    assert re.search(r"data-google hidden", html)
    js = read("assets/js/login-script.js")
    assert "GOOGLE_ENABLED !== true" in js and "signInWithOAuth" in js


def test_login_script_uses_supabase_auth_and_the_profile():
    js = read("assets/js/login-script.js")
    assert "signInWithPassword" in js and "loadUser" in js and "DASH[" in js
    assert not re.search(r"sessionStorage\.setItem\(\s*['\"]atlas(Role|Dept|User)", js)    # cache only via applyCache()
    for msg in ("Wrong email or password", "no ATLAS profile", "no department assigned"):
        assert msg in js


PRIVACY_WORDS = ["We collect", "We never collect", "Who can see it", "student names", "audit log", "IP tracking",
                 "department", "Developers (admin)"]


@pytest.mark.parametrize("rel", ["pages/login.html", "app/about.html"])
def test_privacy_notice_is_present(rel):
    text = read(rel)
    for word in PRIVACY_WORDS:
        assert word.lower() in text.lower(), (rel, word)


# ── session handling in the pages ─────────────────────────────────────────────

def test_app_core_checks_the_session_and_wraps_fetch():
    js = read("assets/js/app-core.js")
    for needle in ("getSession", "maybeSingle", "Authorization", "'Bearer '", "refreshSession", "signOut",
                   "window.atlasFetch", "window.atlasLogout", "visibility = 'hidden'", "onAuthStateChange"):
        assert needle in js, needle


def test_every_api_call_in_the_dashboard_goes_through_the_wrapper():
    js = read("assets/js/main-script.js")
    assert not re.search(r"(?<![\w.])fetch\(`\$\{API_BASE\}", js)
    assert js.count("window.atlasAuth.fetch(`${API_BASE}") == 6


def test_logout_calls_sign_out_and_stays_only_in_account_page():
    js = read("assets/js/app-script.js")
    assert "await window.atlasLogout()" in js
    core = read("assets/js/app-core.js")
    assert "auth.signOut()" in core and "clearLocalAuth()" in core
    assert 'id="btnSignOut"' in read("app/account.html")


def test_account_profile_is_read_only():
    html = read("app/account.html")
    assert "btnSaveProfile" not in html and html.count("readonly") >= 2
    assert "btnSaveProfile" not in read("assets/js/app-script.js")
    assert "fsSaveProfile').hidden = true" in read("assets/js/faculty-script.js")


def test_no_page_script_writes_role_or_dept_to_session_storage_except_the_cache_helper():
    for rel in ("assets/js/main-script.js", "assets/js/app-script.js", "assets/js/faculty-script.js",
                "assets/js/login-script.js"):
        js = read(rel)
        assert not re.search(r"sessionStorage\.setItem\(\s*['\"]atlas(Role|Dept)['\"]", js), rel


def test_env_file_and_service_key_stay_out_of_the_browser():
    assert re.search(r"^\.env\s*$", read(".gitignore"), re.M)
    for rel in ["assets/js/config.js", "assets/js/supabase-client.js", "assets/js/app-core.js",
                "assets/js/login-script.js", "pages/login.html"]:
        text = read(rel)
        assert "SUPABASE_SERVICE_KEY" not in text and "sb_secret_" not in text, rel


# ── the Node harness: app-core.js against a fake Supabase ─────────────────────

@pytest.mark.skipif(NODE is None, reason="Node is not installed")
def test_auth_harness_all_checks_pass():
    out = subprocess.run([NODE, str(ROOT / "tests" / "js" / "auth_harness.js")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    results = json.loads(out.stdout.strip().splitlines()[-1])
    assert len(results) >= 20
    failed = [f"{r['name']}: {r['detail']}" for r in results if not r["ok"]]
    assert not failed, "\n".join(failed)