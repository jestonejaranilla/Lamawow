"""
ATLAS PSU - Part 16: faculty and settings data come from the database, not the browser.

Static checks on the pages and scripts, tests/js/data_store_harness.js (Node) which runs assets/js/data-store.js against a
fake Supabase that applies the same department rules as the RLS policies, and a few Playwright checks (skipped when
Playwright is not installed). Nothing here talks to the real Supabase project.
"""
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


OLD_KEYS = ["facultyData", "subjectsData", "classSizesData", "academicMode", "systemSettings", "lastGAResult",
            "atlasAnalyticsCache", "softConstraintsData", "roomsData", "coverageData", "atlasCurriculumCache",
            "atlasDataVersion", "atlasDeptMigrated"]


# ── the data layer itself (Node) ──────────────────────────────────────────────
@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_data_store_harness_all_checks_pass():
    out = subprocess.run([NODE, str(ROOT / "tests" / "js" / "data_store_harness.js")], capture_output=True, text=True, timeout=90)
    assert out.returncode == 0 and out.stdout.strip().endswith("ALL OK"), out.stdout[-2500:] + out.stderr[-500:]


# ── the browser keeps no department data ──────────────────────────────────────
@pytest.mark.parametrize("rel", ["assets/js/main-script.js", "assets/js/faculty-script.js", "assets/js/app-script.js",
                                 "assets/js/solver-settings.js", "assets/js/data-store.js"])
def test_no_script_reads_or_writes_an_old_data_key(rel):
    js = read(rel)
    for line in js.splitlines():
        if "localStorage" in line:
            assert not any(k in line for k in OLD_KEYS), "%s still uses browser storage for data: %s" % (rel, line.strip())
    assert "dk(" not in js, rel + " still builds a <base>::<dept> key"


def test_migration_code_is_gone_and_logout_clears_every_working_key():
    core = read("assets/js/app-core.js")
    assert "migrateLegacyKeys" not in core
    assert "localStorage.setItem('atlasDeptMigrated'" not in core and "localStorage.getItem('atlasDeptMigrated')" not in core
    for key in ["facultyData", "subjectsData", "classSizesData", "systemSettings", "softConstraintsData", "roomsData",
                "lastGAResult", "atlasAnalyticsCache", "coverageData", "academicMode"]:
        assert "'%s'" % key in core, key + " is not in the purge list"
    assert "atlasCache:" in core and "atlasCacheOwner" in core          # the data cache and the owner mark are purged too
    assert "purgeLocal('all')" in core                                  # logout
    assert "claimBrowserFor(u.id)" in core                              # a different user starts clean


def test_data_store_is_cache_only_when_offline_and_never_trusts_it():
    js = read("assets/js/data-store.js")
    assert "10 * 60 * 1000" in js                                       # short-lived
    assert "cacheGet(key)" in js and js.count("cacheGet(") == 2         # definition + the single use in the catch branch
    assert "fromCache = true" in js and "Showing an offline copy" in js  # saving is off for an offline copy
    assert "Not saved" in js and "Retry" in js                          # visible failure state
    assert "navigator.onLine" in js and "'online'" in js                # retried when the connection returns


# ── scripts are wired in the right order ──────────────────────────────────────
@pytest.mark.parametrize("rel,later", [
    ("pages/dashboard.html", ["solver-settings.js", "main-script.js"]),
    ("faculty/dashboard.html", ["faculty-script.js"]),
    ("app/application-settings.html", ["solver-settings.js", "app-script.js"]),
    ("app/account.html", ["app-script.js"]),
])
def test_data_store_loads_after_app_core_and_before_its_users(rel, later):
    html = read(rel)
    pos = lambda name: html.index('<script src="../assets/%s' % ('vendor/' if name.startswith('supabase.js') else 'js/') + name)   # the script tag, not a preload hint
    assert pos("supabase-client.js") < pos("app-core.js") < pos("data-store.js")
    for name in later:
        assert pos("data-store.js") < pos(name), (rel, name)


# ── pages ─────────────────────────────────────────────────────────────────────
def test_dashboard_offers_sample_faculty_and_date_ranges_only():
    html = read("pages/dashboard.html")
    assert 'id="loadSampleFaculty"' in html and 'id="facultyEmptyNotice"' in html
    assert "scMaternityLeave" not in html and "unavailDatesContainer" not in html     # no reason, no single dates
    assert 'id="leaveDatesContainer"' in html and 'id="addLeaveDate"' in html
    assert not re.search(r"reason", html, re.I) or "no reason" in html.lower()


def test_faculty_dashboard_edits_only_preferences_and_leave():
    html = read("faculty/dashboard.html")
    for i in ("fsPrefsCard", "fsPrefPeriod", "fsAvoidDays", "fsLeaveList", "fsAddLeave", "fsSavePrefs"):
        assert 'id="%s"' % i in html, i
    js = read("assets/js/faculty-script.js")
    assert "self.run()" in js and "self.names()" in js and "self.record()" in js        # approved run + own record from the database
    assert "savePrefs" in js and "saveLeave" in js
    assert not re.search(r"atlasData\.(faculty|classSizes|rooms|settings)\.save", js)   # nothing else is writable from this page


def test_sample_faculty_is_never_written_silently():
    main = read("assets/js/main-script.js")
    assert "loadSample(pool)" in main and "initSampleFaculty()" in main
    assert "defaultFaculty().forEach(f => addFacultyRow(f))" not in main               # the old silent fallback is gone
    store = read("assets/js/data-store.js")
    assert "This department already has faculty. Nothing was changed." in store         # re-checked right before inserting


# ── Run Optimization uses the database copy and the bearer token ──────────────
def test_run_payload_comes_from_the_database_and_carries_the_token():
    main = read("assets/js/main-script.js")
    i = main.index("async function triggerGARunAPI()")
    run = main[i:main.index("function initRunGA()", i)]
    assert "window.atlasData.faculty.list()" in run and "faculty:          dbFaculty" in run
    assert "getFacultyFromTable()" not in run
    assert "loadSoftConstraintsFromStorage()" in run and "window.atlasData.softConstraints()" in main
    assert "pendingSaves() > 0" in run                                                  # unsaved edits are never silently dropped
    assert "window.atlasAuth.fetch(`${API_BASE}/run-ga`" in run                         # Bearer token wrapper


def test_leave_dates_reach_the_engine_through_the_existing_support():
    """The engine already scores leave_dates / unavailable_dates (solver/objective_functions.py); the solver is not changed."""
    assert "leave_dates" in read("solver/objective_functions.py")
    store = read("assets/js/data-store.js")
    assert "sc.leave_dates = " in store


# ── audit: ids and counts only, only events the server accepts ────────────────
def test_audit_events_are_accepted_by_the_server_and_carry_no_personal_data():
    from routes.session_routes import CLIENT_EVENTS
    from services.audit_service import clean_meta

    store = read("assets/js/data-store.js")
    calls = re.findall(r"report\('([a-z_]+)',\s*[^,]+,\s*(\{[^}]*\})\)", store)
    assert calls, "no audit reports found"
    actions = {a for a, _ in calls}
    assert {"faculty_added", "faculty_edited", "faculty_deleted", "solver_settings_changed"} <= actions
    assert actions <= set(CLIENT_EVENTS), actions - set(CLIENT_EVENTS)
    for _, meta in calls:
        keys = re.findall(r"([a-z_]+):", meta)
        sample = {k: 3 for k in keys}
        assert clean_meta(sample) == sample, "clean_meta would drop %s" % keys           # nothing forbidden in the meta
        assert not re.search(r"name|email|leave|reason|faculty", meta, re.I)


def test_rooms_and_class_sizes_changes_are_audited_by_their_routes():
    routes = read("routes/schedule_routes.py")
    assert '"rooms_changed"' in routes and '"class_sizes_changed"' in routes
    main = read("assets/js/main-script.js")
    assert "await syncRoomsToBackend();" in main and "/class-sizes" in main             # the save buttons still call them


# ── sessions ──────────────────────────────────────────────────────────────────
def test_database_rules_are_unchanged_by_part_16():
    schema = read("db/schema.sql")
    assert "create table if not exists public.faculty_leave" in schema and "reason" not in schema.split("faculty_leave")[1].split(");")[0]


# ── browser checks (Playwright) ───────────────────────────────────────────────
try:
    import playwright.sync_api as pw
except ImportError:                       # the static and Node checks above still run
    pw = None
from werkzeug.serving import make_server  # noqa: E402

import config.settings as cfg  # noqa: E402
from app import app  # noqa: E402
from fake_auth import FAKE_AUTH, FACULTY_PROFILE_JS, chair_profile_js  # noqa: E402

BASE = "http://localhost:5000"


needs_browser = pytest.mark.skipif(pw is None, reason="Playwright is not installed")


@pytest.fixture(scope="module")
def server():
    cfg.CP_SAT_TIME_LIMIT_SECONDS = 10.0
    srv = make_server("127.0.0.1", 5000, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield
    srv.shutdown()


@pytest.fixture(scope="module")
def browser(server):
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def new_page(browser):
    ctx = browser.new_context()
    ctx.route(re.compile(r"^https?://(?!localhost:5000|127\.0\.0\.1:5000)"), lambda r: r.abort())
    page = ctx.new_page()
    page.add_init_script(FAKE_AUTH)
    page.goto(f"{BASE}/pages/login.html")
    return page


def chair_dashboard(page, dept, pre=""):
    page.evaluate("""d => { sessionStorage.clear(); sessionStorage.setItem('atlasRole','chairperson'); sessionStorage.setItem('atlasDept', d);
        sessionStorage.setItem('atlasUser','Tester'); sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph'); """
                  + pre + chair_profile_js("d") + " }", dept)
    page.goto(f"{BASE}/pages/dashboard.html")


@pytest.mark.slow
@needs_browser
def test_empty_department_offers_sample_faculty_and_existing_data_is_never_overwritten(browser):
    page = new_page(browser)
    chair_dashboard(page, "IT")
    page.click(".nav-item[data-panel='3']")                  # Part 25: the dashboard opens on Home; the faculty table and notice live in panel 3
    page.wait_for_selector("#facultyEmptyNotice:not([hidden])")
    assert page.locator("#facultyTable tbody tr").count() == 0
    page.click("#loadSampleFaculty")
    page.wait_for_selector("#facultyTable tbody tr", state="attached")
    n = page.locator("#facultyTable tbody tr").count()
    assert n > 0 and len(page.evaluate("window.__testDb.rows('faculty')")) == n
    page.reload()
    page.click(".nav-item[data-panel='3']")                  # Part 25: the dashboard opens on Home; the faculty table and notice live in panel 3
    page.wait_for_selector("#facultyTable tbody tr", state="attached")
    assert page.locator("#facultyEmptyNotice").is_hidden() and page.locator("#facultyTable tbody tr").count() == n

    # a department that already has faculty is not offered the sample and keeps exactly what it has
    page.evaluate("() => window.__testDb.upsert('faculty', {id:'cs-1', dept:'CS', name:'Existing CS Prof', specializations:[], "
                  "max_units:24, overload_buffer:6, availability:['Mon']}, ['id'])")
    page.evaluate("() => { atlasLogout(); }")
    page.goto(f"{BASE}/pages/login.html")
    chair_dashboard(page, "CS")
    page.click(".nav-item[data-panel='3']")                  # Part 25: the dashboard opens on Home; the faculty table and notice live in panel 3
    page.wait_for_selector("#facultyTable tbody tr", state="attached")
    assert page.locator("#facultyEmptyNotice").is_hidden()
    assert page.locator("#facultyTable tbody tr").count() == 1
    assert page.input_value("#facultyTable tbody tr:first-child input[type=text]") == "Existing CS Prof"   # a name is an input value, not text
    page.context.close()


@pytest.mark.slow
@needs_browser
def test_a_failed_save_keeps_what_was_typed_and_retry_saves_it(browser):
    page = new_page(browser)
    chair_dashboard(page, "IT")
    page.click(".nav-item[data-panel='3']")                  # Part 25: the dashboard opens on Home; the faculty table and notice live in panel 3
    page.wait_for_selector("#facultyEmptyNotice:not([hidden])")
    page.click("#loadSampleFaculty")
    page.wait_for_selector("#facultyTable tbody tr", state="attached")
    page.wait_for_function("window.atlasData.pendingSaves() === 0")
    page.evaluate("localStorage.setItem('__testFail', '1')")             # the connection is lost
    box = page.locator("#facultyTable tbody tr:first-child input[type=text]")
    box.fill("Typed While Offline")
    box.press("Enter")                                                  # Part 24: the name saves on Enter or blur
    page.wait_for_function("document.getElementById('atlasSaveStatus') && document.getElementById('atlasSaveStatus').dataset.state === 'error'")
    assert box.input_value() == "Typed While Offline"                   # nothing was lost on screen
    assert not any(f["name"] == "Typed While Offline" for f in page.evaluate("window.__testDb.rows('faculty')"))
    page.evaluate("localStorage.removeItem('__testFail')")
    page.click("#atlasSaveStatus button")                                # Retry
    page.wait_for_function("window.atlasData.pendingSaves() === 0")
    assert any(f["name"] == "Typed While Offline" for f in page.evaluate("window.__testDb.rows('faculty')"))
    assert box.input_value() == "Typed While Offline"
    page.context.close()


@pytest.mark.slow
@needs_browser
def test_faculty_dashboard_reads_the_approved_run_and_edits_only_preferences_and_leave(browser):
    page = new_page(browser)
    page.evaluate("""() => { sessionStorage.clear(); sessionStorage.setItem('atlasRole','faculty'); sessionStorage.setItem('atlasDept','IT');
        sessionStorage.setItem('atlasUser','Prof. Maria Santos'); sessionStorage.setItem('atlasFaculty','Prof. Maria Santos');
        sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph'); """ + FACULTY_PROFILE_JS + """
        window.__testDb.upsert('schedule_runs', {id:'run-ok', dept:'IT', status:'approved', academic_year:'2026-2027',
            semester:'1st Semester', updated_at:'2026-10-02', result:[], solver_settings:{units_per_assignment:3}}, ['id']);
        window.__testDb.upsert('schedule_runs', {id:'run-draft', dept:'IT', status:'draft', academic_year:'2026-2027',
            semester:'1st Semester', updated_at:'2026-10-09', result:[], solver_settings:{}}, ['id']); }""")
    page.goto(f"{BASE}/faculty/dashboard.html")
    page.wait_for_selector("#fsPrefsCard", state="attached")
    assert page.evaluate("atlasData.self.run().id") == "run-ok"            # approved, not the newer draft
    assert page.evaluate("atlasData.self.record().name") == "Prof. Maria Santos"
    assert "your limit 24 units" in page.inner_text("#fsDataInfo")
    page.click(".nav-item[data-panel='1']")
    page.select_option("#fsPrefPeriod", "morning")
    page.check("#fsAvoidDays input[value=Fri]")
    page.click("#fsAddLeave")
    page.fill("#fsLeaveList input >> nth=0", "2026-11-10")
    page.fill("#fsLeaveList input >> nth=1", "2026-11-12")
    page.click("#fsSavePrefs")
    page.wait_for_function("window.atlasData.pendingSaves() === 0")
    prefs = page.evaluate("window.__testDb.rows('faculty_preferences')")
    leave = page.evaluate("window.__testDb.rows('faculty_leave')")
    assert prefs[0]["preferred_period"] == "morning" and prefs[0]["avoid_days"] == ["Fri"]
    assert [(l["start_date"], l["end_date"]) for l in leave] == [("2026-11-10", "2026-11-12")]
    assert not any("reason" in l for l in leave)
    page.context.close()