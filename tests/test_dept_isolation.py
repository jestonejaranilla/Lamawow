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

BASE = "http://localhost:5000"


@pytest.fixture(scope="module", autouse=True)
def server():
    cfg.CP_SAT_TIME_LIMIT_SECONDS = 10.0
    srv = make_server("127.0.0.1", 5000, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield
    srv.shutdown()
SECTION = re.compile(r"\b(IT|CS|MB|ES|MedB)\d[Bb]\d\b")


def login(page, dept):
    page.goto(f"{BASE}/pages/login.html")
    page.evaluate(
        """d => { sessionStorage.clear();
            sessionStorage.setItem('atlasRole','chairperson'); sessionStorage.setItem('atlasDept', d);
            sessionStorage.setItem('atlasUser','Tester'); sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph'); }""",
        dept)
    page.goto(f"{BASE}/pages/dashboard.html")
    page.wait_for_selector("#facultyTable tbody tr", state="attached")


def run_engine(page, dept):
    page.evaluate(
        """d => { localStorage.setItem('academicMode::'+d, JSON.stringify({year:'2025-2026',semester:'1st Semester'}));
            localStorage.setItem('systemSettings::'+d, JSON.stringify({max_units:24,units_per_assignment:2,cp_sat_time_limit:10,
                population:6,generations:3,mutation:0.15,crossover:0.8})); }""",
        dept)
    page.evaluate("document.getElementById('runGA').click()")
    page.wait_for_selector("#gaScheduleTable tbody tr td:nth-child(3)", state="attached", timeout=120_000)
    page.wait_for_function("!document.getElementById('runGA').disabled", timeout=120_000)


def labels(page):
    return {m.group(1) for m in SECTION.finditer(page.inner_text("body"))}


def test_it_to_cs_to_it():
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.route(re.compile(r"^https?://(?!localhost:5000|127\.0\.0\.1:5000)"), lambda r: r.abort())
        page = ctx.new_page()
        login(page, "IT")
        run_engine(page, "IT")
        assert labels(page) == {"IT"}
        it_saved = page.evaluate("localStorage.getItem('lastGAResult::IT')")

        page.evaluate("atlasLogout()")
        assert page.locator("#gaScheduleTable tbody tr").count() == 0

        login(page, "CS")
        assert "IT" not in labels(page), "IT section label shown in the CS dashboard"
        assert page.evaluate("localStorage.getItem('lastGAResult::CS')") is None
        run_engine(page, "CS")
        assert labels(page) == {"CS"}

        page.evaluate("atlasLogout()")
        login(page, "IT")
        assert page.evaluate("localStorage.getItem('lastGAResult::IT')") == it_saved
        assert labels(page) == {"IT"}, "CS data leaked into the IT dashboard"
        browser.close()