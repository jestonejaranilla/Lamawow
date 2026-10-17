"""
ATLAS PSU - Part 17: saved runs.

- tests/js/saved_runs_harness.js (Node): the controller of assets/js/saved-runs.js against a fake API that follows run_routes.py
  (save, load, unload, approve twice, delete of an approved run refused, 0 and 50 runs, the large fields stay out of the list).
- The real Flask routes against the fake Supabase of test_part14 (approve twice, delete approved is 409, faculty see no drafts).
- Static checks on the page and the glue code, and one Playwright check (skipped without Playwright).
"""
import json
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

import pytest

from test_part14 import IT_CHAIR, PROF, H, client, db, seed_runs  # noqa: F401  (fixtures: db, client)
from services import run_store

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def statuses(db):
    return {r["id"]: r["status"] for r in db.tables["schedule_runs"]}


# ── the controller (Node) ─────────────────────────────────────────────────────
@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_saved_runs_harness_all_checks_pass():
    out = subprocess.run([NODE, str(ROOT / "tests" / "js" / "saved_runs_harness.js")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip().endswith("ALL OK"), out.stdout[-2500:] + out.stderr[-500:]


# ── the API the page uses ─────────────────────────────────────────────────────
def test_save_with_label_then_the_list_shows_it_without_the_large_fields(client, db):
    runs = seed_runs(db)
    rid = runs["it_draft"]["id"]
    assert client.post(f"/runs/{rid}/save", json={"label": "IT 1st Semester 15 Oct 2026 5:30 PM"}, headers=H(IT_CHAIR)).status_code == 200
    rows = client.get("/runs?dept=IT", headers=H(IT_CHAIR)).get_json()["data"]["runs"]
    row = next(r for r in rows if r["id"] == rid)
    assert row["status"] == "saved" and row["label"].startswith("IT 1st Semester")
    assert "result" not in row and "analytics" not in row


def test_approve_twice_the_old_approved_run_becomes_saved(client, db):
    runs = seed_runs(db)
    a, b, old = runs["it_draft"]["id"], runs["it_saved"]["id"], runs["it_appr"]["id"]
    h = H(IT_CHAIR)
    assert client.post(f"/runs/{a}/approve", headers=h).status_code == 200
    assert statuses(db)[a] == "approved" and statuses(db)[old] == "saved"
    assert client.post(f"/runs/{b}/approve", headers=h).status_code == 200
    st = statuses(db)
    assert st[b] == "approved" and st[a] == "saved" and st[old] == "saved"
    assert [r for r in db.tables["schedule_runs"] if r["dept"] == "IT" and r["status"] == "approved"] == [
        next(r for r in db.tables["schedule_runs"] if r["id"] == b)]
    assert statuses(db)[runs["cs_appr"]["id"]] == "approved"                       # another department is untouched


def test_deleting_the_approved_run_is_refused_and_it_stays(client, db):
    runs = seed_runs(db)
    appr = runs["it_appr"]["id"]
    r = client.delete(f"/runs/{appr}", headers=H(IT_CHAIR))
    assert r.status_code == 409 and "approved" in r.get_json()["error"].lower()
    assert appr in statuses(db) and statuses(db)[appr] == "approved"


def test_faculty_cannot_see_drafts_or_saved_runs(client, db):
    runs = seed_runs(db)
    listed = client.get("/runs", headers=H(PROF)).get_json()["data"]["runs"]
    assert [r["id"] for r in listed] == [runs["it_appr"]["id"]]
    for key in ("it_draft", "it_saved"):
        assert client.get("/runs/" + runs[key]["id"], headers=H(PROF)).status_code == 404


def test_zero_runs_and_fifty_runs(client, db):
    db.tables["schedule_runs"] = []
    r = client.get("/runs?dept=IT", headers=H(IT_CHAIR))
    assert r.status_code == 200 and r.get_json()["data"]["runs"] == []
    big = [{"x": "y" * 200}] * 400                                                  # a large result per run
    db.tables["schedule_runs"] = [
        {"id": str(uuid.uuid4()), "dept": "IT", "status": ("approved" if i == 0 else "saved" if i % 2 else "draft"), "label": f"run {i}",
         "academic_year": "2026-2027", "semester": "1st Semester", "created_at": str(i), "created_by": "u",
         "metrics": {"balance_score": 90}, "coverage": {"summary": {"assigned": 1, "total": 1}, "errors": []},
         "result": big, "analytics": {"k": big}} for i in range(50)]
    r = client.get("/runs?dept=IT", headers=H(IT_CHAIR))
    rows = r.get_json()["data"]["runs"]
    assert len(rows) == 50 and all("result" not in x and "analytics" not in x for x in rows)
    assert len(r.data) < 60_000, "the list of 50 runs must stay small (%d bytes)" % len(r.data)
    one = client.get("/runs/" + rows[3]["id"], headers=H(IT_CHAIR)).get_json()["data"]["run"]
    assert len(one["result"]) == 400                                                # opened on request


def test_a_finished_run_is_stored_with_its_balance_score(db):
    assert run_store.balance_score([]) is None
    assert run_store.balance_score([{"faculty": "A"}, {"faculty": "B"}]) == 100.0
    assert run_store.balance_score([{"faculty": "A"}] * 3 + [{"faculty": "B"}]) == 80.0
    run_store.save_draft("IT", str(uuid.uuid4()), {"result": [{"faculty": "A"}, {"faculty": "A"}, {"faculty": "B"}], "metrics": {"solve_time_sec": 1}},
                         {}, 5, "2026-2027", "1st Semester")
    row = db.tables["schedule_runs"][-1]
    assert row["metrics"]["balance_score"] == 90.0 and row["metrics"]["solve_time_sec"] == 1
    assert "result" not in run_store.LIST_COLUMNS and "analytics" not in run_store.LIST_COLUMNS


# ── the page ──────────────────────────────────────────────────────────────────
def test_optimization_panel_has_the_save_bar_the_list_and_the_banner_hooks():
    html = read("pages/dashboard.html")
    for i in ("saveRunBar", "saveRunLabel", "saveRunBtn", "savedRunsCard", "savedRunsCount", "savedRunsEmpty", "savedRunsTable", "savedRunsBody"):
        assert 'id="%s"' % i in html, i
    for head in ("Label", "Date and time", "Ran by", "Coverage", "Balance score", "Status", "Actions"):
        assert "<th>%s</th>" % head in html, head
    assert html.index('<script src="../assets/js/saved-runs.js"') < html.index('<script src="../assets/js/main-script.js"')
    assert html.index('id="saveRunBar"') < html.index('id="coverageSummary"') < html.index('id="savedRunsCard"')


def test_the_controller_uses_the_run_endpoints_and_confirms_before_approving_and_deleting():
    js = read("assets/js/saved-runs.js")
    for call in ("'/runs?dept='", "'/runs/' + v.id + '/save'", "'/runs/' + id + '/approve'", "{ method: 'DELETE' }"):
        assert call in js, call
    assert js.count("ui.confirm(") == 2                                              # approve and delete
    assert "Viewing saved run from" in js and "not the approved schedule" in js
    assert "'Draft'" in js and "'Saved'" in js and "'Approved'" in js
    assert "data-act=\"remove\"" in js and "canDelete: r.status !== 'approved'" in js


def test_reports_and_timetable_default_to_the_approved_run_and_edits_never_touch_it():
    main = read("assets/js/main-script.js")
    assert "restoreLatestRun" not in main                                            # the newest run is no longer the default view
    assert "await initSavedRuns();" in main and "savedRunsCtl.init()" in main
    assert "showApproved" in read("assets/js/saved-runs.js")
    assert "savedRunsCtl.editsBlocked()" in main and "The approved schedule cannot be edited." in main
    assert "if (currentRunStatus === 'approved') return;" in main                   # nothing is written into an approved run
    assert "screenSemester" in main                                                  # another semester's run is not filtered away
    assert "noteFreshRun(currentRunDbId)" in main                                    # a finished run shows the banner and the save bar


def test_faculty_page_still_reads_only_the_approved_run():
    js = read("assets/js/faculty-script.js")
    assert ".eq('status', 'approved')" in read("assets/js/data-store.js") and "self.run()" in js


# ── browser check ─────────────────────────────────────────────────────────────
try:
    import playwright.sync_api as pw
except ImportError:
    pw = None


@pytest.mark.slow
@pytest.mark.skipif(pw is None, reason="Playwright is not installed")
def test_page_works_with_zero_saved_runs():
    from werkzeug.serving import make_server
    import config.settings as cfg
    from app import app
    from fake_auth import FAKE_AUTH, chair_profile_js

    cfg.CP_SAT_TIME_LIMIT_SECONDS = 6.0
    srv = make_server("127.0.0.1", 5000, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(bypass_csp=True)
            ctx.route(re.compile(r"^https?://(?!localhost:5000|127\.0\.0\.1:5000)"), lambda r: r.abort())
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(FAKE_AUTH)
            page.goto("http://localhost:5000/pages/login.html")
            page.evaluate("""d => { sessionStorage.clear(); sessionStorage.setItem('atlasRole','chairperson'); sessionStorage.setItem('atlasDept', d);
                sessionStorage.setItem('atlasUser','T'); sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph'); """
                          + chair_profile_js("d") + " window.__testDb.seedFaculty(d, 3); }", "IT")
            page.goto("http://localhost:5000/pages/dashboard.html")
            page.click(".nav-item[data-panel='1']")                   # Part 25: open the panel that holds the saved runs list
            page.wait_for_selector("#savedRunsCard", state="attached")
            page.wait_for_function("document.getElementById('savedRunsCount').textContent.length > 0")
            assert page.locator("#savedRunsCard").count() == 1
            assert page.locator("#savedRunsBody tr").count() == 0
            assert page.locator("#saveRunBar").is_hidden() and page.locator(".run-banner:visible").count() == 0
            assert page.locator("#savedRunsEmpty").is_visible()
            assert not errors, errors
            b.close()
    finally:
        srv.shutdown()