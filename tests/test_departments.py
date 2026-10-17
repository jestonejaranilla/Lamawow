"""
ATLAS PSU - department files, scope, isolation, HTTP endpoints, gunicorn.
Run from the project root:  python -m pytest tests/ -q
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

import config.settings as cfg
from config import curriculum as cur
from config.curriculum import load_curriculum
from config.rooms import current_rooms
from conftest import DEPTS, SEM1, SEM2, dept_faculty
from services import schedule_service as ss

cfg.CP_SAT_TIME_LIMIT_SECONDS = 15.0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCI = ({f"CSLR {i}" for i in range(1, 11)} | {f"GE Bldg {i}" for i in range(1, 11)}
       | {f"Physics Room {i}" for i in range(1, 6)})
ITCS = set(cur.rooms_for("IT").all_rooms)
ALLOWED_GE = {"GE-MMW", "GE-STS", "GE-Elect ES", "GE-Elect MDS", "GE-Elect IT", "GE-Elect PES"}


@pytest.fixture(autouse=True)
def _fresh():
    ss.reset_state()
    yield
    ss.reset_state()


# 1. files
def test_exactly_five_files_with_exact_case():
    files = sorted(os.listdir(cur.CURRICULA_DIR))
    assert files == sorted(["IT.json", "CS.json", "MB.json", "ES.json", "MedB.json"])


@pytest.mark.parametrize("dept", DEPTS)
def test_file_validates(dept):
    with open(os.path.join(cur.CURRICULA_DIR, f"{dept}.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    codes = [c["code"] for c in raw["courses"]]
    assert len(codes) == len(set(codes))
    assert raw["dept"] == dept
    for c in raw["courses"]:
        assert str(c["year"]) in raw["blocks"], c["code"]
        assert set(c["specialization"]) <= set(raw["specializations"]), c["code"]
    for year, blocks in raw["blocks"].items():
        for b in blocks:
            assert f"{dept}{year}{b}" in raw["class_sizes"]
    for key, v in raw["class_sizes"].items():
        assert 36 <= v["size"] <= 48, key
    assert load_curriculum(dept)["dept"] == dept          # the loader's own validation agrees


# 2. scope
def test_no_path_or_nstp_and_only_the_allowed_ge_codes():
    ge = set()
    for d in DEPTS:
        for c in load_curriculum(d)["courses"]:
            assert not c["code"].startswith(("PATH", "NSTP")), (d, c["code"])
            if c["code"].startswith("GE"):
                ge.add(c["code"])
    assert ge == ALLOWED_GE


def test_no_code_prefix_scope_rule_anywhere():
    for sub in ("config", "services", "solver", "routes"):
        for f in os.listdir(os.path.join(ROOT, sub)):
            if f.endswith(".py"):
                src = open(os.path.join(ROOT, sub, f), encoding="utf-8").read()
                assert "IN_SCOPE_PREFIXES" not in src and "is_in_scope" not in src, f


# 7. isolation
@pytest.fixture()
def clients():
    import app as appmod
    return lambda: appmod.app.test_client()


def _post(client, dept, sem, out):
    out[dept] = client.post("/run-ga", json={"dept": dept, "faculty": dept_faculty(dept),
                                             "subjects": [{"name": "x"}], "active_semester": sem,
                                             "generations": 3, "population": 4})


def _wait(client, depts, timeout=150):
    t0 = time.time()
    while time.time() - t0 < timeout:
        ps = {d: client.get(f"/progress?dept={d}").get_json() for d in depts}
        if all(p["phase"] in ("done", "error") for p in ps.values()):
            return ps
        time.sleep(0.3)
    raise AssertionError("runs did not finish")


@pytest.mark.slow
def test_it_and_cs_at_the_same_time_in_two_threads(clients):
    c1, c2, c = clients(), clients(), clients()
    out = {}
    ts = [threading.Thread(target=_post, args=(c1, "IT", SEM2, out)),
          threading.Thread(target=_post, args=(c2, "CS", SEM2, out))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out["IT"].status_code == 200 and out["CS"].status_code == 200
    ps = _wait(c, ("IT", "CS"))
    it, cs = ps["IT"], ps["CS"]
    assert it["phase"] == cs["phase"] == "done" and it["run_id"] == out["IT"].get_json()["run_id"]
    assert cs["run_id"] == out["CS"].get_json()["run_id"] != it["run_id"]
    assert it["dept"] == "IT" and cs["dept"] == "CS"
    assert it["result"] and all(a["section"].startswith("IT") for a in it["result"])
    assert cs["result"] and all(a["section"].startswith("CS") for a in cs["result"])
    rooms = lambda p: {a["room"] for a in p["result"]} - {"N/A", "Unassigned"}
    assert rooms(it) <= ITCS and rooms(cs) <= ITCS and not (rooms(it) | rooms(cs)) & SCI
    assert it["analytics"] and cs["analytics"]
    assert it["coverage"]["total"] == 36 and cs["coverage"]["total"] == 34
    blob = lambda p, other: json.dumps([p["warnings"], p["coverage_errors"]])
    assert '"CS' not in blob(it, "CS") and "CS1B" not in blob(it, "CS") and "CS2B" not in blob(it, "CS")
    assert "IT1B" not in blob(cs, "IT") and "IT2B" not in blob(cs, "IT")
    # a later IT run does not change CS
    before = json.dumps(cs, sort_keys=True)
    _post(c, "IT", SEM1, out)
    _wait(c, ("IT",))
    assert json.dumps(c.get("/progress?dept=CS").get_json(), sort_keys=True) == before
    assert c.get("/analytics?dept=CS").get_json()["data"] == cs["analytics"]


def test_missing_or_unknown_dept_is_400(clients):
    c = clients()
    for url in ("/progress", "/progress?dept=", "/progress?dept=XX", "/progress?dept=it", "/rooms",
                "/analytics", "/class-sizes", "/soft-constraints"):
        assert c.get(url).status_code == 400, url
    assert c.post("/run-ga", json={"faculty": [{}], "subjects": [{}]}).status_code == 400
    assert c.post("/run-ga", json={"dept": "XX", "faculty": [{}], "subjects": [{}]}).status_code == 400


@pytest.mark.slow
def test_cs_then_it_then_mb_in_one_process_leaks_nothing(clients):
    c = clients()
    default_before = (list(cfg.LECTURE_ROOMS), list(cfg.LABORATORY_ROOMS), dict(cfg.ROOM_CAPACITY))
    seen = {}
    for dept, sem in (("CS", SEM2), ("IT", SEM1), ("MB", SEM2)):
        r = c.post("/run-ga", json={"dept": dept, "faculty": dept_faculty(dept), "subjects": [{"name": "x"}],
                                    "active_semester": sem, "generations": 2, "population": 4})
        assert r.status_code == 200
        p = _wait(c, (dept,))[dept]
        assert p["phase"] == "done" and p["result"]
        assert all(a["section"].startswith(dept) for a in p["result"])
        allowed = SCI if dept == "MB" else ITCS
        assert {a["room"] for a in p["result"]} - {"N/A", "Unassigned"} <= allowed
        seen[dept] = json.dumps(p, sort_keys=True)
        for earlier, snap in seen.items():                 # earlier departments are unchanged
            assert json.dumps(c.get(f"/progress?dept={earlier}").get_json(), sort_keys=True) == snap
    assert default_before == (cfg.LECTURE_ROOMS, cfg.LABORATORY_ROOMS, cfg.ROOM_CAPACITY)
    assert set(current_rooms().all_rooms) == ITCS                  # room context reset after the runs
    for other in ("IT", "CS", "ES", "MedB"):                # untouched departments are still blank
        if other not in seen:
            assert c.get(f"/progress?dept={other}").get_json()["result"] == []


# 9. endpoints and gunicorn
def test_curricula_endpoints(clients):
    c = clients()
    r = c.get("/curricula")
    assert r.status_code == 200 and sorted(d["dept"] for d in r.get_json()) == sorted(DEPTS) and len(r.get_json()) == 5
    for d in DEPTS:
        assert c.get(f"/curriculum/{d}").status_code == 200
    assert c.get("/curriculum/XX").status_code == 404


@pytest.mark.skipif(shutil.which("gunicorn") is None or sys.platform == "win32",
                    reason="gunicorn not installed, or Windows (gunicorn needs fcntl; Render runs Linux)")
def test_gunicorn_starts_and_serves_rooms():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(["gunicorn", "app:app", "-b", f"127.0.0.1:{port}"], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        body = None
        for _ in range(60):
            try:
                body = urllib.request.urlopen(f"http://127.0.0.1:{port}/rooms?dept=IT", timeout=2).read()
                break
            except Exception:
                time.sleep(0.5)
        assert body is not None, "gunicorn did not answer"
        assert "lecture_rooms" in json.loads(body)
    finally:
        proc.terminate()
        proc.wait(10)