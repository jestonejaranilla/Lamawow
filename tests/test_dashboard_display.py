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

pytestmark = pytest.mark.slow
pw = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server

import config.settings as cfg
from app import app
from fake_auth import FAKE_AUTH, FACULTY_PROFILE_JS, chair_profile_js, switch_dept_js

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
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.add_init_script(FAKE_AUTH)
    page.goto(f"{BASE}/pages/login.html")
    page.evaluate(
        """d => { sessionStorage.clear();
            sessionStorage.setItem('atlasRole','chairperson'); sessionStorage.setItem('atlasDept', d);
            sessionStorage.setItem('atlasUser','Tester'); sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph');
            """ + chair_profile_js('d') + """ }""",
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
            localStorage.setItem('systemSettings::'+d, JSON.stringify({max_units:24,units_per_assignment:2,cp_sat_time_limit:10,
                population:6,generations:3,mutation:0.15,crossover:0.8})); }""",
        dept)
    page.evaluate("document.getElementById('runGA').click()")
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


# ── Part 8: panel layout ──────────────────────────────────────────────────────
@pytest.mark.parametrize("dept", list(DEPTS))
def test_panel_layout_and_preferences_round_trip(browser, dept):
    page, errors = open_dashboard(browser, dept)
    panel = lambda sel: page.evaluate("s => { const e = document.querySelector(s); const p = e && e.closest('.panel');"
                                      " return p ? p.dataset.title : null }", sel)
    # Rooms panel keeps year/semester, rooms, class sizes; nothing else
    for sel in ("#academicModeCard", "#lectureRoomsList", "#labRoomsList", "#classSizesTable"):
        assert panel(sel) == "Rooms", sel
    assert page.locator(".panel[data-title='Rooms'] h2").inner_text().strip() == "Rooms and Blocks"
    assert page.locator(".panel[data-title='Rooms'] #engineSettingsCard").count() == 0
    assert page.locator(".panel[data-title='Rooms'] #scFacultySelect").count() == 0
    assert page.locator(".nav-item[data-panel='4']").inner_text().strip() == "Rooms"
    assert page.locator(".bn-item[data-go='4']").inner_text().strip() == "Rooms"
    # Professor Preferences sits in Faculty and Subjects, between the faculty table and the subjects section
    for sel in ("#scFacultySelect", "#softConstraintForm", "#scSaveBtn", "#scPreferredPeriod"):
        assert panel(sel) == "Faculty and Subjects", sel
    order = page.evaluate("""() => { const q = s => document.querySelector(s);
        const a = q('#facultyTable'), b = q('#scFacultySelect'), c = q('#subjectsTable');
        const f = Node.DOCUMENT_POSITION_FOLLOWING;
        return [!!(a.compareDocumentPosition(b) & f), !!(b.compareDocumentPosition(c) & f)]; }""")
    assert order == [True, True]
    # the button goes to the solver settings
    for i in ("populationSize", "numGenerations", "mutationRate", "crossoverRate", "sysMaxUnits",
              "saveSystemSettings", "engineSettingsCard", "engineSettingsHolder"):
        assert page.locator("#" + i).count() == 0, i                 # moved to the menu settings page
    assert page.inner_text("#solverSummary") == "30 s limit, 50 population, 100 generations"
    btn = page.locator("#goToAdvancedSettings")
    assert btn.inner_text().strip() == "Solver Settings"
    assert "application-settings.html#solver" in btn.get_attribute("onclick")
    # preference save and load still work
    page.wait_for_function("document.querySelector('#scFacultySelect').options.length > 1")
    name = page.evaluate("document.querySelector('#scFacultySelect').options[1].value")
    page.evaluate("""n => { const s = document.getElementById('scFacultySelect'); s.value = n;
        const p = document.getElementById('scPreferredPeriod'); p.selectedIndex = 1;
        document.getElementById('scSaveBtn').click(); }""", name)
    page.wait_for_function("k => localStorage.getItem(k)", arg="softConstraintsData::" + dept)
    saved = page.evaluate("k => JSON.parse(localStorage.getItem(k))", "softConstraintsData::" + dept)
    assert saved[name]["preferred_period"]
    page.reload()
    page.wait_for_function("document.querySelector('#scFacultySelect').options.length > 1")
    page.evaluate("""n => { document.getElementById('scFacultySelect').value = n;
        document.getElementById('scLoadBtn').click(); }""", name)
    assert page.evaluate("document.getElementById('scPreferredPeriod').value") == saved[name]["preferred_period"]
    assert not errors, errors
    page.context.close()


# ── Part 9: solver settings in the menu settings page ─────────────────────────
SETTINGS_URL = BASE + "/app/application-settings.html"
IDS = {"max_units": "sysMaxUnits", "units_per_assignment": "sysUnitsPerAssignment",
       "cp_sat_time_limit": "sysCpSatTimeLimit", "population": "populationSize", "generations": "numGenerations",
       "mutation": "mutationRate", "crossover": "crossoverRate"}


def fill(page, values):
    for k, v in values.items():
        page.fill("#" + IDS[k], str(v))


def stored(page, dept):
    return page.evaluate("d => JSON.parse(localStorage.getItem('systemSettings::' + d) || 'null')", dept)


def test_solver_settings_card_validation_per_department_and_run_request(browser):
    import json
    page, errors = open_dashboard(browser, "IT")
    page.goto(SETTINGS_URL + "#solver")
    assert page.locator("#solver").is_visible()
    assert page.evaluate("document.querySelector('main .app-card').id") == "solver"       # first card
    assert page.input_value("#sysCpSatTimeLimit") == "30"                                 # default is 30, not 60

    # bad values: inline error, nothing saved
    page.evaluate("localStorage.removeItem('systemSettings::IT')")
    fill(page, {"max_units": 41, "units_per_assignment": 11, "cp_sat_time_limit": 41, "population": 3,
                "generations": 201, "mutation": 1.5, "crossover": -0.1})
    page.click("#btnSaveSolver")
    for field in IDS.values():
        assert page.locator("#err-" + field).is_visible(), field
    assert stored(page, "IT") is None
    page.fill("#populationSize", "7.5")
    page.click("#btnSaveSolver")
    assert "whole number" in page.inner_text("#err-populationSize")

    # valid values for IT
    it = {"max_units": 30, "units_per_assignment": 2, "cp_sat_time_limit": 12, "population": 7,
          "generations": 2, "mutation": 0.2, "crossover": 0.5}
    fill(page, it)
    page.click("#btnSaveSolver")
    assert not page.locator("#err-populationSize").is_visible()
    assert stored(page, "IT") == it

    # CS keeps its own values
    page.evaluate(switch_dept_js('CS'))
    page.goto(SETTINGS_URL)
    assert page.input_value("#populationSize") == "50" and stored(page, "CS") is None
    fill(page, {"population": 9})
    page.click("#btnSaveSolver")
    assert stored(page, "CS")["population"] == 9 and stored(page, "IT")["population"] == 7

    # the run request uses the IT values (read at click time, no reload after the change)
    page.evaluate(switch_dept_js('IT'))
    page.goto(BASE + "/pages/dashboard.html")
    page.wait_for_selector("#facultyTable tbody tr", state="attached")
    assert page.inner_text("#solverSummary") == "12 s limit, 7 population, 2 generations"
    bodies = []
    page.on("request", lambda r: bodies.append(r.post_data) if r.url.endswith("/run-ga") else None)
    page.evaluate("document.getElementById('runGA').click()")
    page.wait_for_function("document.getElementById('runGA').disabled")
    body = json.loads(bodies[0])
    print("\n/run-ga body:", {k: body[k] for k in ("dept", "population", "generations", "mutation", "crossover",
                                                    "cp_sat_time_limit", "units_per_assignment", "active_semester")})
    assert (body["population"], body["generations"], body["mutation"], body["crossover"]) == (7, 2, 0.2, 0.5)
    assert body["cp_sat_time_limit"] == 12 and body["dept"] == "IT"
    page.wait_for_function("!document.getElementById('runGA').disabled", timeout=120_000)

    # restore defaults
    page.goto(SETTINGS_URL)
    page.click("#btnRestoreSolver")
    assert stored(page, "IT") == {"max_units": 24, "units_per_assignment": 2, "cp_sat_time_limit": 30,
                                  "population": 50, "generations": 100, "mutation": 0.09, "crossover": 0.95}
    assert not errors, errors
    page.context.close()


def test_old_out_of_range_saved_value_falls_back_to_the_default(browser):
    page, _ = open_dashboard(browser, "MB")
    page.evaluate("localStorage.setItem('systemSettings::MB', JSON.stringify({cp_sat_time_limit: 60, population: 500}))")
    page.reload()
    page.wait_for_selector("#facultyTable tbody tr", state="attached")
    assert page.inner_text("#solverSummary") == "30 s limit, 50 population, 100 generations"
    page.context.close()


def test_faculty_account_does_not_get_the_solver_card(browser):
    ctx = browser.new_context()
    ctx.route(re.compile(r"^https?://(?!localhost:5000|127\.0\.0\.1:5000)"), lambda r: r.abort())
    page = ctx.new_page()
    page.add_init_script(FAKE_AUTH)
    page.goto(f"{BASE}/pages/login.html")
    page.evaluate("""() => { sessionStorage.clear(); sessionStorage.setItem('atlasRole','faculty');
        sessionStorage.setItem('atlasDept','IT'); sessionStorage.setItem('atlasUser','Prof. Maria Santos');
        sessionStorage.setItem('atlasFaculty','Prof. Maria Santos'); sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph');
        """ + FACULTY_PROFILE_JS + """ }""")
    page.goto(SETTINGS_URL + "#solver")
    page.wait_for_selector("main .app-card")
    assert page.locator("#solver").count() == 0
    assert page.locator("#populationSize").count() == 0
    ctx.close()