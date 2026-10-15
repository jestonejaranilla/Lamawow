"""
ATLAS PSU - department files, groups, meeting expansion, coverage, endpoints, isolation.
Run from the project root:  python -m pytest tests/ -q
"""
import threading
import time

import pytest

import config.settings as cfg
from config import curriculum as cur
from config.curriculum import load_curriculum, courses_of, UnknownDepartment
from conftest import DEPTS, SEMS, SEM1, SEM2, dept_faculty, legacy_subjects, make_faculty
from services import schedule_service as ss
from solver.cp_sat_solver import _build_meetings
from solver.constraints import faculty_qualifies, is_open_assignment, max_room_capacity
from config.rooms import use_rooms

# (block-courses, lecture meetings, lab meetings, lab groups after splitting)
EXPECTED = {
    ("IT", 1): (30, 31, 26, 34),   ("IT", 2): (36, 45, 24, 30),
    ("CS", 1): (38, 49, 26, 32),   ("CS", 2): (34, 40, 24, 27),
    ("MB", 1): (42, 61, 47, 47),   ("MB", 2): (32, 47, 28, 28),
    ("ES", 1): (27, 44, 26, 26),   ("ES", 2): (23, 32, 19, 19),
    ("MedB", 1): (29, 45, 31, 31), ("MedB", 2): (20, 31, 24, 24),
}


@pytest.fixture(autouse=True)
def _fresh_state():
    ss.reset_state()
    yield
    ss.reset_state()


def prep_for(dept, sem):
    return ss.prepare_scheduling_input(dept, [], sem, ss.get_class_sizes(dept))


# ── Department files ──────────────────────────────────────────────────────────

def test_five_department_files_exact_names():
    assert cur.available_departments() == sorted(["IT", "CS", "MB", "ES", "MedB"])


@pytest.mark.parametrize("dept", DEPTS)
def test_file_loads_and_validates(dept):
    c = load_curriculum(dept)
    assert c["dept"] == dept and c["name"] and c["prospectus"]
    assert all(str(y) in c["blocks"] for y in {x["year"] for x in c["courses"]})
    assert c["class_sizes_placeholder"] is True


def test_department_names_are_case_sensitive_and_unknown_is_rejected():
    for bad in ("it", "Cs", "XX", "", None, "../IT", "IT.json"):
        with pytest.raises(UnknownDepartment):
            load_curriculum(bad)
        with pytest.raises(UnknownDepartment):
            ss.check_dept(bad)


def test_scope_is_presence_in_the_file_not_a_code_prefix():
    assert not hasattr(cur, "IN_SCOPE_PREFIXES")
    assert not hasattr(cur, "is_in_scope")
    assert not hasattr(cfg, "SPECIALIZATION_MAP") and not hasattr(cfg, "DEFAULT_CLASS_SIZES")
    for d in DEPTS:
        assert len(courses_of(d)) == len(load_curriculum(d)["courses"])


def test_same_title_different_tags_per_department():
    it, mb = cur.specialization_lookup("IT"), cur.specialization_lookup("MB")
    t = "Science, Technology and Society"
    assert it[t] != mb[t]


def test_list_departments():
    out = cur.list_departments()
    assert sorted(d["dept"] for d in out) == sorted(DEPTS)
    assert all(d["name"] and d["program"] for d in out)


# ── Counts (before / after lab splitting) ─────────────────────────────────────

@pytest.mark.parametrize("dept", DEPTS)
@pytest.mark.parametrize("sem", [1, 2])
def test_counts_match_the_expected_table(dept, sem):
    prep = prep_for(dept, SEMS[sem - 1])
    kinds = [s["class_type"] for s in prep["sections"]]
    rooms = cur.rooms_for(dept)
    with use_rooms(rooms):
        classroom = [s for s in prep["sections"] if s["class_type"] != "NON_CLASSROOM"]
        meetings = _build_meetings(classroom, max_room_capacity(rooms.lab_rooms))
    got = (len(prep["groups"]), kinds.count("LECTURE"), kinds.count("LAB"),
           sum(1 for m in meetings if m["kind"] == "LAB"))
    assert got == EXPECTED[(dept, sem)]
    assert prep["errors"] == []


def test_lab_split_uses_the_departments_own_largest_lab_room():
    def largest(d):
        rs = cur.rooms_for(d)
        with use_rooms(rs):
            return max_room_capacity(rs.lab_rooms)
    assert largest("IT") == largest("CS") == 45
    assert [largest(d) for d in ("MB", "ES", "MedB")] == [50, 50, 50]


@pytest.mark.parametrize("dept", DEPTS)
def test_section_labels_and_student_counts(dept):
    sizes = ss.get_class_sizes(dept)
    for sem in SEMS:
        for r in prep_for(dept, sem)["sections"]:
            assert r["section"].startswith(dept) and r["section"] in sizes
            assert r["section"] == f"{dept}{r['year'][0]}{sizes[r['section']]['block']}"
            assert r["student_count"] == sizes[r["section"]]["size"] > 0


def test_meetings_are_ceil_lec_over_two_plus_one_lab_per_lab_unit():
    # IT 1st sem 2nd year block 1: IT 3 (2/1), CC 4 (2/1), IT E1 (2/1), IT E2 (2/1)
    rows = [r for r in prep_for("IT", SEM1)["sections"] if r["section"] == "IT2B1"]
    assert sorted((r["class_type"]) for r in rows) == ["LAB"] * 4 + ["LECTURE"] * 4
    # Fundamentals of Electronics (1/2) in IT 2nd sem: 1 lecture + 2 labs per block
    el = [r for r in prep_for("IT", SEM2)["sections"] if r["name"] == "Fundamentals of Electronics"
          and r["section"] == "IT2B1"]
    assert sorted(r["class_type"] for r in el) == ["LAB", "LAB", "LECTURE"]
    assert len({r["meeting_id"] for r in el}) == 3


@pytest.mark.parametrize("dept,code", [("IT", "IT 20"), ("IT", "IT 22"), ("CS", "Practicum"),
                                       ("MB", None), ("ES", "Practicum"), ("MedB", "Practicum")])
def test_unscheduled_courses_give_one_non_classroom_row_per_block(dept, code):
    c = load_curriculum(dept)
    unsched = [x for x in c["courses"] if not x["scheduled"]]
    if code is None:
        assert unsched == []          # MB has no unscheduled course (summer practicum is excluded)
        return
    course = next(x for x in unsched if x["code"] == code)
    prep = prep_for(dept, f"{course['semester']}{'st' if course['semester'] == 1 else 'nd'} Semester")
    rows = [r for r in prep["sections"] if r["course_code"] == code]
    blocks = c["blocks"][str(course["year"])]
    assert len(rows) == len(blocks) and {r["class_type"] for r in rows} == {"NON_CLASSROOM"}


def test_blocks_come_from_class_sizes_and_a_missing_size_is_a_coverage_error():
    sizes = ss.get_class_sizes("IT")
    prep = ss.prepare_scheduling_input("IT", [], SEM1, {k: v for k, v in sizes.items() if k != "IT2B2"})
    assert not any(r["section"] == "IT2B2" for r in prep["sections"])
    sizes = {k: v for k, v in sizes.items() if not k.startswith("IT4")}
    prep = ss.prepare_scheduling_input("IT", [], SEM1, sizes)
    assert any("no blocks defined" in e["reason"] for e in prep["errors"])


def test_legacy_request_and_unknown_groups_are_reported_not_silent():
    p = ss.prepare_scheduling_input("IT", legacy_subjects(), SEM1, ss.get_class_sizes("IT"))
    assert any("no group ids" in w for w in p["warnings"])
    rows = [{"group_id": "IT1B1|CC 1", "class_type": "LECTURE"}, {"group_id": "IT1B1|NOPE"}]
    p = ss.prepare_scheduling_input("IT", rows, SEM1, ss.get_class_sizes("IT"))
    assert any("out of scope" in w and "IT1B1|NOPE" in w for w in p["warnings"])
    assert any("missing from the request" in w for w in p["warnings"])


# ── Qualification (P5) ────────────────────────────────────────────────────────

def test_electives_open_to_any_faculty_and_mixed_tags_are_not():
    lk = cur.specialization_lookup("IT")
    nobody = make_faculty("N", ["Networks & Security"])
    assert is_open_assignment("IT Elective 1", lk) and faculty_qualifies(nobody, "IT Elective 1", lk)
    assert not is_open_assignment("Introduction to Computing", lk)        # ["Core Theory","Elective"]
    assert not faculty_qualifies(nobody, "Introduction to Computing", lk)
    assert faculty_qualifies(make_faculty("C", ["Core Theory"]), "Introduction to Computing", lk)
    cs = cur.specialization_lookup("CS")
    assert is_open_assignment("CS Elective 4", cs) and faculty_qualifies(nobody, "CS Elective 5", cs)


# ── Service: one department per run ───────────────────────────────────────────

def run_job(dept, sem, fac, **kw):
    r = ss.start_scheduling(dept, fac, legacy_subjects(), sem,
                            {"generations": 5, "population": 4}, {}, None, wait=True, **kw)
    assert "error" not in r, r
    return ss.get_progress(dept), r


def test_engine_run_returns_run_id_and_department_progress():
    p, r = run_job("CS", SEM1, dept_faculty("CS"))
    assert p["phase"] == "done" and p["dept"] == "CS" and p["run_id"] == r["run_id"]
    assert p["coverage"] == {"assigned": 38, "total": 38} and p["coverage_errors"] == []
    assert p["result"] and all(a["section"].startswith("CS") for a in p["result"])
    assert ss.get_progress("IT")["result"] == [] and ss.get_progress("IT")["run_id"] is None


def test_unknown_or_missing_department_is_rejected_by_the_service():
    for bad in (None, "", "XX", "it"):
        with pytest.raises(UnknownDepartment):
            ss.start_scheduling(bad, [{}], legacy_subjects(), SEM1, {}, {}, None)
        with pytest.raises(UnknownDepartment):
            ss.get_progress(bad)


def test_uncoverable_group_is_reported_with_a_reason():
    fac = dept_faculty("IT")
    for f in fac:
        f["specialization"] = [t for t in f["specialization"] if t not in ("Core Theory", "Elective")]
        f["specialization"] = f["specialization"] or ["Systems"]
    p, _ = run_job("IT", SEM1, fac)
    assert p["coverage"] == {"assigned": 26, "total": 30}
    assert {e["group_id"] for e in p["coverage_errors"]} == {
        f"IT1B{b}|{c}" for b in (1, 2) for c in ("CC 1", "GE-STS")}
    assert {e["reason"] for e in p["coverage_errors"]} == {"no qualified faculty"}


def test_science_department_warns_that_capacities_are_placeholders():
    p, _ = run_job("ES", SEM2, dept_faculty("ES"))
    assert "Room capacities for this department are placeholders." in p["warnings"]
    p, _ = run_job("IT", SEM2, dept_faculty("IT"))
    assert "Room capacities for this department are placeholders." not in p["warnings"]


# ── Rooms of each department ──────────────────────────────────────────────────

SCIENCE_ROOMS = ({f"CSLR {i}" for i in range(1, 11)} | {f"GE Bldg {i}" for i in range(1, 11)}
                 | {f"Physics Room {i}" for i in range(1, 6)})


def test_room_sets_are_per_department():
    it, mb = cur.rooms_for("IT"), cur.rooms_for("MB")
    assert set(mb.all_rooms) == SCIENCE_ROOMS and mb.lab_also_lecture and mb.placeholder
    assert set(mb.lab_rooms) == {f"Physics Room {i}" for i in range(1, 6)}
    assert set(it.all_rooms).isdisjoint(SCIENCE_ROOMS) and not it.lab_also_lecture
    assert set(cur.rooms_for("CS").all_rooms) == set(it.all_rooms)


def test_runtime_room_edits_stay_in_their_department():
    ss.update_rooms("IT", room_capacity={"CL1": {"recommended": 10, "max": 11}})
    assert cur.rooms_for("IT").cap("CL1")["max"] == 52                      # file value untouched
    assert ss.get_rooms("IT").cap("CL1")["max"] == 11
    assert ss.get_rooms("CS").cap("CL1")["max"] == 52
    ss.update_rooms("MB", lecture_rooms=["X1"])
    assert "X1" in ss.get_rooms("MB").lecture_rooms and "X1" not in ss.get_rooms("ES").lecture_rooms


def test_class_size_edits_accept_only_the_departments_blocks():
    ss.update_class_sizes("IT", {"IT1B1": 40})
    assert ss.get_class_sizes("IT")["IT1B1"]["size"] == 40
    assert ss.get_class_sizes("CS")["CS1B1"]["size"] == 38
    with pytest.raises(ValueError):
        ss.update_class_sizes("IT", {"CS1B1": 40})


# ── Isolation: two departments at the same time ───────────────────────────────

def wait_done(depts, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if all(ss.get_progress(d)["phase"] in ("done", "error") for d in depts):
            return
        time.sleep(0.3)
    raise AssertionError("runs did not finish")


def test_two_departments_run_at_the_same_time_without_mixing():
    for d in ("IT", "CS"):
        r = ss.start_scheduling(d, dept_faculty(d), legacy_subjects(), SEM2,
                                {"generations": 5, "population": 4}, {}, None)
        assert "error" not in r
    assert ss.is_running("IT") and ss.is_running("CS")          # both in flight together
    wait_done(("IT", "CS"))
    it, cs = ss.get_progress("IT"), ss.get_progress("CS")
    assert it["phase"] == cs["phase"] == "done" and it["run_id"] != cs["run_id"]
    it_rooms, cs_rooms = set(cur.rooms_for("IT").all_rooms), set(cur.rooms_for("CS").all_rooms)
    assert it["result"] and all(a["section"].startswith("IT") for a in it["result"])
    assert cs["result"] and all(a["section"].startswith("CS") for a in cs["result"])
    assert {a["room"] for a in it["result"]} - {"N/A", "Unassigned"} <= it_rooms
    assert {a["room"] for a in cs["result"]} - {"N/A", "Unassigned"} <= cs_rooms
    assert it["coverage"]["total"] == 36 and cs["coverage"]["total"] == 34
    assert it["analytics"] and cs["analytics"]
    for p, pre in ((it, "IT"), (cs, "CS")):
        assert all(pre in str(w) or not any(x in str(w) for x in ("IT", "CS") if x != pre)
                   for w in p["warnings"] if "group" in str(w))


def test_a_later_run_of_one_department_leaves_the_other_untouched():
    run_job("CS", SEM2, dept_faculty("CS"))
    before = ss.get_progress("CS")
    run_job("IT", SEM2, dept_faculty("IT"))
    after = ss.get_progress("CS")
    assert after["result"] == before["result"] and after["run_id"] == before["run_id"]
    assert after["analytics"] == before["analytics"] and after["warnings"] == before["warnings"]


def test_a_second_start_for_a_running_department_is_refused_but_not_for_another():
    st = ss._state("IT")
    with st.lock:
        st.progress["running"] = True
    r = ss.start_scheduling("IT", dept_faculty("IT"), legacy_subjects(), SEM2, {}, {}, None)
    assert "already running" in r["error"]
    r = ss.start_scheduling("CS", dept_faculty("CS"), legacy_subjects(), SEM2,
                            {"generations": 2, "population": 4}, {}, None)
    assert "error" not in r
    wait_done(("CS",))


# ── HTTP endpoints ────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    import app as appmod
    return appmod.app.test_client()


def test_curricula_and_curriculum_endpoints(client):
    r = client.get("/curricula")
    assert r.status_code == 200 and sorted(d["dept"] for d in r.get_json()) == sorted(DEPTS)
    for d in DEPTS:
        assert client.get(f"/curriculum/{d}").status_code == 200
    assert client.get("/curriculum/XX").status_code == 404
    assert client.get("/curriculum/it").status_code == 404


def test_every_endpoint_needs_a_known_department(client):
    for url in ("/progress", "/progress?dept=XX", "/progress?dept=it", "/soft-constraints",
                "/rooms", "/class-sizes", "/analytics", "/analytics/workload"):
        assert client.get(url).status_code == 400, url
    for url, body in (("/run-ga", {"faculty": [{}]}), ("/run-ga", {"dept": "XX", "faculty": [{}]}),
                      ("/soft-constraints", {"faculty": "A"}), ("/rooms", {"lecture_rooms": []}),
                      ("/class-sizes", {"IT1B1": 40})):
        assert client.post(url, json=body).status_code == 400, (url, body)


def test_department_scoped_reads(client):
    sizes = client.get("/class-sizes?dept=CS").get_json()
    assert sizes and all(k.startswith("CS") for k in sizes)
    rooms = client.get("/rooms?dept=MB").get_json()
    assert set(rooms["all_rooms"]) == SCIENCE_ROOMS and rooms["capacity_placeholder"] is True
    assert client.post("/class-sizes", json={"dept": "IT", "CS1B1": 40}).status_code == 400
    assert client.post("/soft-constraints?dept=IT", json={"faculty": "A", "constraints": {"k": 1}}).status_code == 200
    assert client.get("/soft-constraints?dept=CS").get_json() == {}
    assert client.get("/soft-constraints?dept=IT").get_json() == {"A": {"k": 1}}
    t = client.get("/subject-types?dept=MB").get_json()["data"]["subject_types"]
    assert "Marine Science" in t


def test_run_ga_progress_and_analytics_are_per_department(client):
    body = {"dept": "CS", "faculty": dept_faculty("CS"), "subjects": legacy_subjects(),
            "active_semester": SEM2, "generations": 3, "population": 4}
    r = client.post("/run-ga", json=body)
    assert r.status_code == 200 and r.get_json()["dept"] == "CS" and r.get_json()["run_id"]
    wait_done(("CS",))
    p = client.get("/progress?dept=CS").get_json()
    assert p["run_id"] == r.get_json()["run_id"] and p["phase"] == "done" and p["result"]
    assert client.get("/progress?dept=IT").get_json()["result"] == []
    assert client.get("/analytics?dept=CS").get_json()["data"]
    assert client.get("/analytics?dept=IT").get_json()["data"] == {"status": "no_schedule"}