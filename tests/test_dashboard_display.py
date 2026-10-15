"""
ATLAS PSU - Part 5 browser check, pages served by Flask itself (http://localhost:5000):
every department dashboard loads, results show section / lab group labels, and the
coverage summary appears. Needs: pip install playwright && python -m playwright install chromium
Run from the project root:  python -m pytest tests/test_dashboard_display.py -q
(port 5000 must be free: the test starts the app there)
"""
import re
import threading

import pytest

pw = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server

import config.settings as cfg
from app import app

DEPTS = {"IT": "Information Technology", "CS": "Computer Science", "MB": "Marine Biology",
         "ES": "Environmental Science", "MedB": "Medical Biology"}
BASE = "http://localhost:5000"


@pytest.fixture(scope="module")
def server():
    cfg.CP_SAT_TIME_LIMIT_SECONDS = 10.0
    srv = make_server("127.0.0.1", 5000, app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield
    srv.shutdown()


@pytest.fixture(scope="module")
def browser(server):
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_dashboard(browser, dept):
    ctx = browser.new_context()
    ctx.route(re.compile(r"^https?://(?!localhost:5000|127\.0\.0\.1:5000)"), lambda r: r.abort())   # nothing may load from the internet
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{BASE}/pages/login.html")
    page.evaluate(
        """d => { sessionStorage.clear();
            sessionStorage.setItem('atlasRole','chairperson'); sessionStorage.setItem('atlasDept', d);
            sessionStorage.setItem('atlasUser','Tester'); sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph'); }""",
        dept)
    page.goto(f"{BASE}/pages/dashboard.html")
    page.wait_for_selector("#facultyTable tbody tr", state="attached")
    return page, errors


@pytest.mark.parametrize("dept", list(DEPTS))
def test_dashboard_loads_for_every_department(browser, dept):
    page, errors = open_dashboard(browser, dept)
    assert page.evaluate("API_BASE") == BASE                  # served by Flask on :5000 -> same origin
    assert DEPTS[dept] in page.inner_text("#deptBannerName")
    assert page.locator("#subjectsTable tbody tr").count() > 0
    assert page.locator("#classSizesTable tbody tr").count() > 0
    assert page.evaluate("typeof Chart") == "function"        # Chart.js comes from assets/vendor, not a CDN
    mode = page.evaluate("JSON.parse(localStorage.getItem('academicMode::%s'))" % dept)
    assert mode == {"year": "2026-2027", "semester": "1st Semester"}   # default active period
    assert not errors, errors
    page.context.close()


@pytest.mark.parametrize("dept", ["IT", "CS"])
def test_results_show_labels_and_coverage(browser, dept):
    page, errors = open_dashboard(browser, dept)
    page.evaluate(
        """d => { localStorage.setItem('academicMode::'+d, JSON.stringify({year:'2025-2026',semester:'1st Semester'}));
            localStorage.setItem('systemSettings::'+d, JSON.stringify({max_units:24,units_per_assignment:2,cp_sat_time_limit:10})); }""",
        dept)
    page.evaluate("""() => { document.getElementById('populationSize').value = 6;
        document.getElementById('numGenerations').value = 3; document.getElementById('runGA').click(); }""")
    page.wait_for_selector("#gaScheduleTable tbody tr td:nth-child(3)", state="attached", timeout=120_000)
    page.wait_for_function("!document.getElementById('runGA').disabled", timeout=120_000)

    badges = page.locator("#gaScheduleTable td.section-cell .section-badge").all_inner_texts()
    assert badges and all(re.fullmatch(rf"{dept}\dB\d(-L\d)?", b.strip()) for b in badges), badges[:5]
    assert any("-L" in b for b in badges), "split lab groups (-L1, -L2) are shown"

    summary = page.inner_text("#coverageSummary")
    assert re.search(r"\d+ of \d+ block-courses assigned", summary), summary
    assert page.evaluate("localStorage.getItem('coverageData::%s')" % dept)
    assert re.search(rf"{dept}\dB\d", page.inner_text("#facultyTimetableContainer"))
    assert not errors, errors

    page.evaluate("atlasLogout()")                           # nothing of this department stays on screen
    assert page.inner_text("#coverageSummary").strip() == ""
    page.context.close()