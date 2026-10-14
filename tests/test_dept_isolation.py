"""
ATLAS PSU - browser check: department isolation (IT -> CS -> IT).
Needs: pip install playwright && python -m playwright install chromium
Run from the project root with the backend and a static server up:
    python app.py                       # http://localhost:5000
    python -m http.server 8000          # serves the repo root
    python -m pytest tests/e2e -q
"""
import re
import pytest

pw = pytest.importorskip("playwright.sync_api")
BASE = "http://localhost:8000"
SECTION = re.compile(r"\b(IT|CS|MB|ES|MedB)\d[Bb]\d\b")


def login(page, dept):
    page.goto(f"{BASE}/pages/login.html")
    page.evaluate(
        """d => { sessionStorage.clear();
            sessionStorage.setItem('atlasRole','chairperson'); sessionStorage.setItem('atlasDept', d);
            sessionStorage.setItem('atlasUser','Tester'); sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph'); }""",
        dept)
    page.goto(f"{BASE}/pages/dashboard.html")
    page.wait_for_selector("#facultyTable tbody tr")


def run_engine(page, dept):
    page.evaluate(
        """d => { localStorage.setItem('academicMode::'+d, JSON.stringify({year:'2025-2026',semester:'1st Semester'}));
            localStorage.setItem('systemSettings::'+d, JSON.stringify({max_units:24,units_per_assignment:2,cp_sat_time_limit:10})); }""",
        dept)
    page.fill("#populationSize", "10")
    page.fill("#numGenerations", "5")
    page.click("#runGA")
    page.wait_for_selector("#gaScheduleTable tbody tr td:nth-child(3)", timeout=120_000)
    page.wait_for_function("!document.getElementById('runGA').disabled", timeout=120_000)


def labels(page):
    return {m.group(1) for m in SECTION.finditer(page.inner_text("body"))}


def test_it_to_cs_to_it():
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
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