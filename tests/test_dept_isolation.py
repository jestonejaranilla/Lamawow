"""
ATLAS PSU - browser check: department isolation (IT -> CS -> IT).
Needs: pip install playwright && python -m playwright install chromium
Run from the project root (port 5000 must be free: the test starts the app there):
    python -m pytest tests/test_dept_isolation.py -q
"""
import re
import threading

import pytest

pytestmark = pytest.mark.slow
pw = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server

import config.settings as cfg
from app import app
from fake_auth import FAKE_AUTH, FACULTY_PROFILE_JS, chair_profile_js, switch_dept_js

BASE = "http://localhost:5000"


@pytest.fixture(scope="module", autouse=True)
def server():
    cfg.CP_SAT_TIME_LIMIT_SECONDS = 10.0
    srv = make_server("127.0.0.1", 5000, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield
    srv.shutdown()
SECTION = re.compile(r"\b(IT|CS|MB|ES|MedB)\d[Bb]\d\b")


def ensure_faculty(page):
    """A department with no faculty in the database offers "Load sample faculty"; take the offer (the real feature)."""
    page.click(".nav-item[data-panel='3']")                  # Part 25: the dashboard opens on Home; the faculty table and notice live in panel 3
    page.wait_for_function("document.querySelector('#facultyTable tbody tr') || "
                           "(document.getElementById('facultyEmptyNotice') && !document.getElementById('facultyEmptyNotice').hidden)")
    if page.locator("#facultyEmptyNotice").is_visible():
        page.click("#loadSampleFaculty")
    page.wait_for_selector("#facultyTable tbody tr", state="attached")
    page.wait_for_function("window.atlasData.pendingSaves() === 0")


def login(page, dept):
    page.add_init_script(FAKE_AUTH)
    page.goto(f"{BASE}/pages/login.html")
    page.evaluate(
        """d => { sessionStorage.clear();
            sessionStorage.setItem('atlasRole','chairperson'); sessionStorage.setItem('atlasDept', d);
            sessionStorage.setItem('atlasUser','Tester'); sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph');
            """ + chair_profile_js('d') + """ }""",
        dept)
    page.goto(f"{BASE}/pages/dashboard.html")
    ensure_faculty(page)


def run_engine(page, dept):
    page.evaluate(
        """d => window.__testDb.upsert('dept_settings', {dept: d, academic_year: '2025-2026', semester: '1st Semester',
            solver: {max_units:24,units_per_assignment:2,cp_sat_time_limit:10,population:6,generations:3,mutation:0.15,crossover:0.8},
            lab_also_lecture: false}, ['dept'])""",
        dept)
    page.reload()                       # the period and solver settings are read from the (fake) database at page start
    ensure_faculty(page)
    page.evaluate("document.getElementById('runGA').click()")
    page.wait_for_selector("#gaScheduleTable tbody tr td:nth-child(3)", state="attached", timeout=120_000)
    page.wait_for_function("!document.getElementById('runGA').disabled", timeout=120_000)


def labels(page):
    page.click(".nav-item[data-panel='1']")        # Part 25: the timetable sits in the Optimization panel; hidden text is not read
    return {m.group(1) for m in SECTION.finditer(page.inner_text("body"))}


def local_data_keys(page):
    """Old per-department browser keys and the data cache: after Part 16 nothing of a department stays here."""
    return page.evaluate("Object.keys(localStorage).filter(k => k.includes('::') || k.startsWith('atlasCache:'))")


def test_it_to_cs_to_it():
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(bypass_csp=True)
        ctx.route(re.compile(r"^https?://(?!localhost:5000|127\.0\.0\.1:5000)"), lambda r: r.abort())
        page = ctx.new_page()
        login(page, "IT")
        run_engine(page, "IT")
        assert labels(page) == {"IT"}
        assert local_data_keys(page) == [] or all(k.startswith("atlasCache:") for k in local_data_keys(page))
        # a professor edited in IT is saved in the database
        page.click(".nav-item[data-panel='3']")
        page.fill("#facultyTable tbody tr:first-child input[type=text]", "ZZ IT Sentinel")
        page.press("#facultyTable tbody tr:first-child input[type=text]", "Enter")     # Part 24: the name saves on Enter or blur
        page.wait_for_function("window.atlasData.pendingSaves() === 0 && window.__testDb.rows('faculty').some(f => f.name === 'ZZ IT Sentinel')")

        page.evaluate("atlasLogout()")
        assert page.locator("#gaScheduleTable tbody tr").count() == 0
        assert local_data_keys(page) == [], "logout must clear every per-department working key"

        login(page, "CS")
        assert "IT" not in labels(page), "IT section label shown in the CS dashboard"
        assert "ZZ IT Sentinel" not in page.inner_text("body"), "IT professor shown in the CS dashboard"
        assert page.evaluate("window.__testDb.rows('faculty').filter(f => f.name === 'ZZ IT Sentinel').map(f => f.dept)") == ["IT"]
        run_engine(page, "CS")
        assert labels(page) == {"CS"}

        page.evaluate("atlasLogout()")
        assert local_data_keys(page) == []
        login(page, "IT")
        assert page.evaluate("atlasData.faculty.list().some(f => f.name === 'ZZ IT Sentinel')"), "the IT edit is not in the database"
        assert page.evaluate("atlasData.faculty.list().every(f => window.__testDb.rows('faculty').find(r => r.id === f.id).dept === 'IT')"), "CS data leaked into the IT dashboard"
        browser.close()