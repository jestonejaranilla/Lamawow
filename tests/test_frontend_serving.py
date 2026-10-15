"""
ATLAS PSU - Part 5: Flask serves the frontend; API_BASE resolution; dashboards load for all departments.
Run from the project root:  python -m pytest tests/test_frontend_serving.py -q
"""
import json
import os
import shutil
import subprocess

import pytest

from app import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPTS = ["IT", "CS", "MB", "ES", "MedB"]
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def client():
    return app.test_client()


@pytest.mark.parametrize("path", [
    "/", "/index.html", "/pages/login.html", "/pages/dashboard.html", "/faculty/dashboard.html",
    "/assets/css/main-style.css", "/assets/js/display.js", "/app/menu.html", "/manifest.json",
    "/data/curricula/IT.json",
])
def test_public_files_are_served(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", [
    "/app.py", "/.env", "/README.md", "/solver/cp_sat_solver.py", "/tests/conftest.py",
    "/pages/../app.py", "/data/../app.py", "/assets/%2e%2e/app.py", "/config/settings.py",
])
def test_private_files_are_not_served(client, path):
    assert client.get(path).status_code == 404


def test_html_pages_are_html_and_api_routes_still_work(client):
    r = client.get("/")
    assert r.status_code == 200 and b"ATLAS" in r.data
    assert client.get("/curricula").get_json()
    assert client.get("/rooms?dept=IT").status_code == 200
    assert client.get("/rooms").status_code == 400


@pytest.mark.parametrize("dept", DEPTS)
def test_department_files_reachable_for_the_dashboard(client, dept):
    r = client.get(f"/data/curricula/{dept}.json")       # same relative path the dashboard fetches
    assert r.status_code == 200 and r.get_json()["dept"] == dept
    assert client.get(f"/curriculum/{dept}").status_code == 200
    assert client.get(f"/rooms?dept={dept}").status_code == 200


def test_dashboard_pages_load_scripts_in_order(client):
    html = client.get("/pages/dashboard.html").get_data(as_text=True)
    tag = lambda name: html.index('src="../assets/js/%s"' % name)
    assert tag("display.js") < tag("curriculum.js") < tag("main-script.js")
    fac = client.get("/faculty/dashboard.html").get_data(as_text=True)
    assert fac.index("display.js") < fac.index("faculty-script.js")
    for rel in ("assets/js/display.js", "assets/js/curriculum.js", "assets/js/main-script.js",
                "assets/js/faculty-script.js", "assets/js/app-core.js"):
        assert client.get("/" + rel).status_code == 200


def _node(js):
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_api_base_three_cases():
    got = _node("""
      const D = require('./assets/js/display.js');
      const loc = (h, p, proto='http:') => ({hostname: h, port: p, protocol: proto,
        host: p ? h + ':' + p : h, origin: proto + '//' + (p ? h + ':' + p : h)});
      console.log(JSON.stringify([
        D.resolveApiBase(loc('localhost', '5000')),
        D.resolveApiBase(loc('127.0.0.1', '5000')),
        D.resolveApiBase(loc('localhost', '8000')),
        D.resolveApiBase(loc('127.0.0.1', '5500')),
        D.resolveApiBase(loc('localhost', '')),
        D.resolveApiBase(loc('atlas-psu.onrender.com', '', 'https:')),
        D.resolveApiBase(loc('atlas.example.edu.ph', '', 'https:')),
      ]));""")
    assert got == ["http://localhost:5000", "http://127.0.0.1:5000", "http://localhost:5000",
                   "http://localhost:5000", "http://localhost:5000",
                   "https://atlas-drsg.onrender.com", "https://atlas-drsg.onrender.com"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_labels_coverage_and_no_classroom_text():
    got = _node("""
      const D = require('./assets/js/display.js');
      console.log(JSON.stringify({
        plain: D.rowLabel({section: 'CS2B3'}),
        lab:   D.rowLabel({section: 'IT1B1', lab_group: 'IT1B1-L2'}),
        med:   D.rowLabel({section: 'MedB4B2', lab_group: ''}),
        none:  D.isNoClassroom({class_type: 'NON_CLASSROOM'}),
        txt:   D.NO_CLASSROOM_TEXT,
        cov:   D.coverageText({assigned: 30, total: 30}),
        err:   D.coverageErrorText({block: 'IT2B1', course: 'IT 4', title: 'Networking', reason: 'no conflict-free slot and room found'}),
      }));""")
    assert got["plain"] == "CS2B3" and got["lab"] == "IT1B1-L2" and got["med"] == "MedB4B2"
    assert got["none"] is True and got["txt"] == "No classroom (professor assigned)"
    assert got["cov"] == "30 of 30 block-courses assigned"
    assert got["err"].startswith("IT2B1 · IT 4 Networking: no conflict")


@pytest.mark.slow
def test_lab_group_labels_come_from_the_engine():
    """The rows the frontend shows carry section and -L1/-L2 lab labels for every department."""
    import config.settings as cfg
    from conftest import dept_faculty
    from services import schedule_service as ss
    cfg.CP_SAT_TIME_LIMIT_SECONDS = 10.0
    seen = {}
    for dept in ("CS", "IT", "MedB"):
        ss.reset_state(dept)
        fac = dept_faculty(dept)
        subj = [{"group_id": g["group_id"]} for g in
                ss.build_groups(dept, "1st Semester", ss.get_class_sizes(dept))[0]]
        ss.start_scheduling(dept, fac, subj, "1st Semester", {"generations": 2, "population": 4},
                            {}, None, wait=True)
        p = ss.get_progress(dept)
        rows = p["result"]
        assert rows and all(r["section"].startswith(dept) for r in rows)
        labs = [r for r in rows if r["class_type"] == "LAB"]
        assert labs
        if dept in ("CS", "IT"):            # oversized labs are split: IT1B2-L1, IT1B2-L2
            assert any(r["lab_group"].startswith(r["section"] + "-L") for r in labs)
        assert p["coverage"]["total"] > 0 and "coverage_errors" in p
        seen[dept] = p["coverage"]
    assert seen