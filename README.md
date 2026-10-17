<div align="center">

<img src="/assets/images/favicon.png" alt="ATLAS PSU" width="72" />



# ATLAS PSU



**A Teaching Load Assignment and Management System for Department Chairpersons of the College of Sciences at Palawan State University**



*A two-phase engine: CP-SAT assigns professors under hard rules and balances load, then a Genetic Algorithm improves times and rooms without changing any professor. Chairpersons review, edit, and finalize every assignment.*



[![Status](https://img.shields.io/badge/status-thesis%20prototype-c9a96e?style=flat-square)](#current-status)

[![Built With](https://img.shields.io/badge/built%20with-Python%20%7C%20Flask%20%7C%20Vanilla%20JS-4a90d9?style=flat-square)](#technologies-used)

[![License](https://img.shields.io/badge/license-Proprietary-gray?style=flat-square)](#license)

[![Location](https://img.shields.io/badge/based%20in-Puerto%20Princesa%2C%20Palawan-0a7ab8?style=flat-square)](#)



</div>



---



## What Is This?



ATLAS PSU is a teaching load assignment and management system built for the Department Chairpersons of the College of Sciences, Palawan State University (PSU), Puerto Princesa City. It covers the Information Technology, Computer Science, Medical Biology, Marine Biology, and Environmental Science departments.



It replaces spreadsheet-based, manual assignment with a two-phase optimization engine. CP-SAT assigns professors under the hard rules and balances load in Phase 1; every professor assignment, and so all workload balance and specialization matching, comes from this phase. A Genetic Algorithm improves times and rooms in Phase 2, for faculty preferences, room capacity fit and building compactness, without changing any professor. An analytics phase then computes workload fairness and specialization match rates.



The existing college tool only plots schedules after the fact: it does no automated assignment, constraint checking, or conflict resolution. ATLAS PSU generates the recommendation, then gives the chairperson decision-support tools (workload charts and a fairness report) and manual editing so the final decision stays with them. Faculty members get their own read-only view of the finished schedule.



This is a capstone thesis project built between April and July 2026.



---



## Current Status



- The proposal prototype defense is complete. The final thesis defense is still ahead.

- The scheduling engine, analytics, chairperson dashboard, and faculty dashboard are built and running on a Flask backend with a vanilla JavaScript frontend.

- Finished runs are saved to Supabase (Postgres) as drafts, and the chairperson can save, approve or delete them. Faculty and scheduling working data still live in the browser and in memory until the next database step.

- Sign in uses Supabase Auth (email and password). Roles and departments come from the `profiles` table and the Flask API checks them on every request. "Sign in with Google" is built but hidden until a Google provider is set up.

- No department chairperson has adopted or piloted the system. Only evaluation against actual chairperson use can show whether it beats the manual process on fairness, efficiency, and assignment quality.



---



## Background and Problem



Faculty teaching loads are assigned by department chairpersons at the start of each semester. Structured interviews with the Department Chairpersons of Information Technology and Computer Science on June 8, 2026 confirmed:



- Matching each faculty member's specialization to the right subjects is the most time-consuming task.

- Soft constraints (time, room, and subject preferences, and dates of unavailability) are not handled by any existing tool.

- Class sizes, schedule splitting, and block-based scheduling across year levels are not addressed by the current system.

- Chairpersons want optimization support, not full automation. They will not accept a system that finalizes assignments on its own.



That last finding is why every recommendation is editable and reviewable before export.



---



## How the Engine Works



### Phase 1 - CP-SAT Solver (`solver/cp_sat_solver.py`)



Uses Google OR-Tools CP-SAT to generate a conflict-free base schedule. The model decides professor, slot and (through exact per-slot capacity constraints) room together, with a time limit under 45 seconds, and returns the best solution found.



Two rules shape every schedule. **One professor per block-course:** a block-course is one course taught to one block (for example IT1B1 and CC 1); all of its lecture meetings, its lab meetings and every lab sub-group are taught by the same professor. **Full coverage is the goal:** every block-course of the active semester is assigned, or it is listed in `coverage_errors` with a reason. Full coverage is not promised for every input: it depends on the faculty pool (tags, days, load caps) and on the rooms and slots available, and a group that cannot be staffed is reported, never dropped.

Hard constraints enforced:

- Every group (block x course) is covered, or reported in `coverage_errors` with a reason ("no qualified faculty", "no available day", "load cap reached", "no lecture room fits N students", ...). Nothing is dropped silently.

- Exactly one professor per group: all lecture meetings, the lab meeting and every lab sub-group share the same professor

- Faculty qualification (a course whose only tag is `Elective`, or that has no tag, is open to any faculty; every other course needs at least one matching specialization tag)

- Faculty day availability and no faculty double-booking

- Load: hard cap at `absolute_max_units` (30), soft penalty above `max_units` (24)

- A block never has two meetings in the same slot

- Room capacity by `max`, no room double-booking; LECTURE meetings use lecture rooms, LAB meetings use laboratory rooms

- Lab splitting: a lab larger than the largest lab room is split into `ceil(size / maxLab)` groups (for example IT1B1-L1, IT1B1-L2) with the same professor and different slots

- Groups with no slot or room (IT 20, IT 22) get one professor and count `NON_CLASSROOM_UNITS` load units



Objective: exact specialization match, the same professor for the same course across blocks, balanced load.



If OR-Tools is not installed, a greedy group-level solver runs instead. It places a group only when the placement passes the same checks (availability, one meeting per professor, block and room per slot, room capacity, load cap, one professor per group), so what it places is valid. It does not promise full coverage and it is not optimal: it can leave groups uncovered that CP-SAT would cover. Those are reported in `coverage_errors` like on the CP-SAT path.



### Phase 2 - Genetic Algorithm Optimizer (`solver/ga_optimizer.py`)



Takes the valid CP-SAT schedule as input and improves slots and rooms. Its fitness has only the terms it can change: faculty preference score, room capacity fit, and building affinity and section clustering. It never generates schedules from scratch and never changes who teaches what: only slots and rooms move, so it cannot improve fairness or specialization match, and the Reports never credit it with either. The professor-assignment terms (specialization bonus, load variance, underload gap) live in `assignment_quality()` and are reported only. `ga_improvement` is the fitness gain on the three GA terms (`ga_improvement_terms` lists them). Every candidate is validated, and if the result has more rule violations than the CP-SAT schedule it started from, the CP-SAT schedule is returned unchanged.



Soft constraints optimized:

- Preferred time periods (for example afternoon over morning)

- Preferred rooms, floors, and buildings

- Restricted days and unavailable dates

- Leave dates and maternity leave flags



### Phase 3 - Analytics (`services/analytics_service.py`)



Computes faculty utilization, Jain's Fairness Index, load standard deviation, and specialization match rates. Results feed the dashboard, the fairness report, and the specialization match report.



### Phase 4 - Chairperson Review and Manual Edit



The chairperson reviews assignments in the timetable grid and analytics panels, edits any assignment, and exports the final schedule. The system informs the final decision; it does not make it.



---



## Features



**Chairperson side**

- Two-phase optimization: CP-SAT assigns professors and balances load under hard rules, GA improves times and rooms for preferences and compactness

- Live phase and percentage progress while the engine runs

- Manual editing of individual assignments after optimization

- Configurable GA parameters: population size, generations, mutation rate, crossover rate

- Per-faculty soft constraints: preferred periods, rooms, floors and buildings, restricted days, unavailable dates, leave dates, maternity leave flags

- Per-faculty load caps with overload detection

- Specialization-aware assignment using a curriculum-to-specialization map

- Timetable grid by day and time slot

- Workload analytics, fairness report, and specialization match report

- Active academic period (year and semester) filter

- Editable rooms, class sizes, and soft constraints, synced to the backend at runtime

- CSV export and a formal A4 portrait PDF report (letterhead, summary, master schedule, signature block, page numbers)



**Faculty side**

- Faculty sign in with their own PSU account, which is linked to one faculty record (`profiles.faculty_id`)

- Personal schedule grouped by day, with Today, In progress, and Done markers

- Personal weekly timetable

- Schedule of all faculty, with a per-faculty filter and a full timetable

- Live clock with current and next class countdown

- Class reminders before and at the start of a class (in-page alert, sound, vibration, and optional system notification)

- Profile and reminder settings per faculty member



**Everywhere**

- Responsive layout: centered sticky top navigation on desktop; on phones a back button, page title and menu button on top with a bottom tab bar

- Application pages: menu, application settings (text size, reduced motion, start page, saved data, install), notification settings (system alerts, sound, vibration, quiet hours, class reminders or optimization alerts), account settings, appearance (light, night, automatic by device, automatic by time) and an About page

- Zoomable schedule viewer and a slim draggable scroll handle on touch devices

- Installable web app (`manifest.json`)



---



## System Architecture



The system is organized around five functional processes derived from the Data Flow Diagram:



**P1 - Authentication:** Supabase Auth signs the user in; the profile (role, department) decides the dashboard, and every API call carries the access token.



**P2 - Configuration:** Accepts faculty profiles, subjects, rooms, class sizes, and soft constraints from the chairperson, stored in the Config Store (D1).



**P3 - Schedule Optimization:** The core engine. Retrieves config data, runs the two-phase solver, and writes results to the Schedule Store (D2). Sub-processes:

- P3.1 validates the faculty list and GA parameters

- P3.2 expands subjects into sections based on class sizes and the semester filter

- P3.3 runs CP-SAT to produce a hard-constraint-valid base schedule

- P3.4 runs the GA against soft preferences (D3 Soft Constraint Store)

- P3.5 computes analytics from the best GA output

- P3.6 reports live progress (phase and percentage) to the chairperson



**P4 - Analytics:** Reads from D2 and generates workload analytics and fairness reports.



**P5 - Export:** Retrieves finalized schedule data from D2 and produces CSV and PDF output.



---



## Technologies Used



**Backend**

- Python 3, Flask 3.1, flask-cors

- Google OR-Tools CP-SAT (ortools 9.15.6755, pinned)

- Custom Genetic Algorithm engine

- Threading-based progress store for non-blocking runs



**Frontend**

- Vanilla HTML, CSS, and JavaScript (no build step)

- Chart.js for load distribution and fairness charts

- `localStorage` for faculty, subjects, class sizes, soft constraints, and the last schedule. The faculty side reads this same data, so it only shows a schedule in a browser where the chairperson ran the optimization.



---



## Project Structure



```

app.py                        Flask bootstrap, runtime-mutable room/class-size stores,

                              and static data endpoints (/rooms, /class-sizes, /subject-types)

manifest.json                 Web app manifest (installable on phones)

index.html                    Landing page (chairperson and faculty entry points)



config/

  settings.py                 Time grid (30 slots), room definitions, subject types,

                              class sizes, GA weights, CP-SAT time limit. The

                              specialization map is built from the curriculum files.

  curriculum.py               Generic loader for data/curricula/<DEPT>.json



data/curricula/

  IT.json                     BSIT prospectus (CC/IT courses only): titles, year, semester,

                              lec/lab units, scheduled flag, specialization tags. Read by the

                              backend and by the dashboard. Other departments = more files.



solver/

  cp_sat_solver.py            Phase 1: CP-SAT model (OR-Tools) + greedy fallback with the same hard rules

  ga_optimizer.py             Phase 2: preference optimizer (moves slots and rooms only; falls back to the CP-SAT schedule if a rule would break)

  constraints.py              Qualification, availability, load, and room compatibility checks

  objective_functions.py      Fitness scoring and satisfaction metrics used by the GA



services/

  schedule_service.py         Orchestrates CP-SAT, GA, and analytics; thread-safe progress store

  analytics_service.py        Phase 3: utilization, Jain's Index, std deviation, match rates



routes/

  schedule_routes.py          /run-ga, /progress, /soft-constraints

  analytics_routes.py         /analytics



models/                       Data classes (faculty, subject, room, schedule). Not yet used

                              by the engine, which works on plain dictionaries.



pages/

  login.html                  Email and password sign in (Supabase Auth), privacy notice

  dashboard.html              Chairperson app: Dashboard, Optimization, Reports,

                              Faculty and Subjects, Settings



faculty/

  dashboard.html              Faculty app: Dashboard (My Schedule, My Week, All Faculty)

                              and Settings



app/                          Application pages shared by both roles

  menu.html                   Mobile menu (desktop opens the first section)

  application-settings.html   Text size, motion, start page, saved data, install

  notifications.html          Alerts, quiet hours, reminders / optimization alerts

  account.html                Profile, data export, log out

  appearance.html             Light, night, automatic themes

  about.html                  About the system



tests/

  test_groups.py              Group expansion, coverage and engine tests (python -m pytest tests -q)



assets/

  js/curriculum.js            Curriculum helpers shared by the dashboard (no DOM)

  css/main-style.css          Design system (rust orange, slate, off-white) and shared components

  css/faculty-style.css       Faculty page components

  css/app-style.css           Application pages

  js/main-script.js           Chairperson logic: optimization, charts, faculty and subject

                              management, export, soft constraints, localStorage sync

  js/faculty-script.js        Faculty logic: schedule from cache, live clock, reminders, settings

  js/login-script.js          Sign in, profile check, routing by role
  js/config.js                Public browser config (Supabase URL, anon key, API base)
  js/supabase-client.js       The shared Supabase client (window.atlasSupabase)
  vendor/supabase.js          supabase-js 2.58.0 (UMD build, no CDN)

  js/app-core.js              Device preferences (theme, text size, alerts), loaded first on every page

  js/app-script.js            Logic for the application pages

  js/shared-ui.js             Top bar title and back button, bottom tab bar, scroll handle,

                              zoomable schedule viewer

  images/favicon.png          Logo and app icon

```



---



## Configuration



Key constants in `config/settings.py`:



| Constant | Default | Description |

|---|---|---|

| `DAYS` | Mon-Sat | Available scheduling days |

| `HOURS` | 5 blocks per day | 07:00 to 09:00 through 17:00 to 19:00 |

| `TIME_SLOTS` | 30 total | Cartesian product of days x hours |

| `UNITS_PER_ASSIGNMENT` | 2 | Teaching units counted per assigned slot |

| `CP_SAT_TIME_LIMIT_SECONDS` | 30.0 | OR-Tools solver time limit requested for a run (the request may override it) |
| `CP_SAT_MAX_TIME_LIMIT_SECONDS` | 40.0 | Hard ceiling for the solver, always under 45 s |
| `CP_WEIGHTS` | See settings.py | CP-SAT objective weights (coverage, exact specialization, same professor per course, load above `max_units`, load balance, room fit) |
| `REQUIRE_FULL_COVERAGE` | False | True returns no assignments when any group cannot be covered |

| `GA_WEIGHTS` | See settings.py | Soft preference scoring weights for the GA |



---



## Installation



**Python 3.10 or newer** (tested on 3.13).

```bash

# 1. create a virtual environment
python -m venv .venv

# activate it: Windows  .venv\Scripts\activate   |   macOS / Linux  source .venv/bin/activate

# 2. install the requirements
pip install -r requirements.txt

# 3. run the server (backend and frontend together)
python app.py

```



Open `http://localhost:5000` in your browser.



> Local development: set `ATLAS_AUTH=off` in `.env` to skip token checks on the Flask side. The pages still sign in through Supabase, so fill `assets/js/config.js` first.

### Authentication (Supabase Auth)

1. Run `db/schema.sql` and `db/seed.sql`, create the test accounts and insert their profiles (see `db/README.md`).
2. In `assets/js/config.js` set `SUPABASE_URL` and `SUPABASE_ANON_KEY`. The anon (publishable) key is public by design. The service key and the JWT secret go only in `.env` and in Render, never in the browser.
3. Open `pages/login.html` and sign in. A chairperson lands on `pages/dashboard.html`, a faculty member on `faculty/dashboard.html`.

How it works:

- Every page except the landing page and the login page checks the real Supabase session first, loads the user's row from `profiles`, and confirms the page matches the role. Otherwise it goes to the login page. A faculty account that opens the chairperson dashboard by URL is sent to the faculty dashboard.
- `sessionStorage` (`atlasRole`, `atlasDept`, `atlasUser`, `atlasEmail`, `atlasFaculty`) is only a display cache, refilled from the profile on every page start. Editing it changes nothing, because the server decides from the verified token.
- `atlasFetch` (in `app-core.js`) sends `Authorization: Bearer <access token>` on every API call, retries once with a refreshed token on a 401, and signs the user out if it is still 401.
- Log out exists only in `app/account.html`. It audits the logout, calls `supabase.auth.signOut()` and clears the session cache and the Supabase keys. Department working data in `localStorage` is kept.
- Accounts are created by an administrator. There is no self sign up, and the browser cannot choose or change a role or department. Administrator accounts have no dashboard here.

### Where the data lives (Part 16)

Faculty, professor preferences, leave dates (date ranges only, no reason), class sizes, rooms, the active academic period and the solver settings are read from and saved to Supabase through `assets/js/data-store.js`. Row Level Security does the filtering: a chairperson gets only their department, a faculty member only their own record, preferences and leave plus the approved run of their department.

- **Saving:** every change shows "Saving...", then "Saved". If a save fails, an error toast appears, what was typed stays on screen and in memory, and a Retry button (and the browser coming back online) saves it again. A newer save replaces an older failed one, so a retry never overwrites newer data.
- **First visit:** a department with no faculty in the database is offered "Load sample faculty" (the pseudonym pool of the curriculum file). It is inserted only after the table is checked to be empty and is never written silently.
- **Browser storage:** only device settings (theme, text size) and a 10-minute cache. The cache is read only when the database cannot be reached, it is shown read-only (saving is off until a reload reaches the database), and it is never written back. Logout clears every working key, the cache and the Supabase session, and so does the first sign-in of a different user on the same computer. The old `<base>::<dept>` keys and their migration code are removed.
- **Run Optimization** sends the faculty, preferences, leave dates (as `leave_dates`, which the engine already scores as unavailable dates), class sizes, rooms and solver settings loaded from the database to `/run-ga` with the Bearer token. It refuses to start while a change is still unsaved.
- **Last result:** the approved run of the department is loaded from `schedule_runs` (see Saved runs below), so the schedule is the same in every browser.
- **Audit:** faculty add, edit and delete and solver or period changes go to `POST /audit` (ids and counts only); rooms and class sizes are audited by their routes.

### Saved runs (Part 17)

On Workload Optimization every finished run is stored as a **Draft** (`schedule_runs`). Two things sit on the page:

- **Save this run:** after a run, a label field (default `<Dept> <Semester> <date time>`) and a "Save this run" button call `POST /runs/<id>/save`; the run becomes **Saved**.
- **Saved runs card:** label, date and time, who ran it, coverage, balance score and a status badge (Draft, Saved, Approved). Per run: **Load**, **Unload**, **Approve** (asks for confirmation, calls `POST /runs/<id>/approve`, and the previous approved run becomes Saved) and **Delete** (asks for confirmation; an approved run cannot be deleted, in the page and in the API and database).
- **Loading a run** fills the optimization table, Reports, Dashboard and the faculty timetable under a banner ("Viewing saved run from 15 Oct 2026 5:30 PM, not the approved schedule") with an **Unload** button that goes back to the approved schedule, or to an empty view when none is approved. A new run or a manual edit only ever changes a draft or saved run; the approved schedule is frozen and cannot be edited from the page.
- **The default view is the approved run** (Dashboard, Reports and the timetable). Faculty can read only the approved run (API and RLS).
- **Size:** the list loads only small columns (`LIST_COLUMNS`), never `result` or `analytics`; a run's result is fetched when it is opened. The list scrolls inside its card and works with 0 or 50+ runs. The balance score (Jain's index of the teaching load, 0 to 100) is stored in `metrics` when the run is saved; older runs show a dash.
- Code: `assets/js/saved-runs.js` (controller and DOM), glue in `main-script.js`; tests in `tests/test_part17.py` and `tests/js/saved_runs_harness.js`.

### Part 18: audit log screen, retention, data documentation

- **Audit log card** (Application Settings, chairperson only): time, user, action and entity of the chairperson's own department, newest first, with an action filter, a date range and paging (25 per page). It reads `GET /audit`, which is read only, forces the department from the profile (an admin may pass `?dept=`), and returns only those four fields: no ids, no `meta`. A chairperson asking for another department gets a 403, faculty get a 403.
- **Purging old rows:** `python scripts/purge_audit_log.py --older-than "12 months" [--dry-run]`. Admin sign in (password prompt), shows the row count, and asks you to type `PURGE`. Production (`ATLAS_ENV=production` or Render) keeps at least 12 months and the script refuses anything shorter. Development may purge freely.
- **Data documentation for the paper:** `docs/DATA.md` (every table and field, why, who reads and writes, retention, what is not collected).
- **Tests:** `tests/test_part18.py`. Set `ATLAS_TEST_PG` to the URL of an empty throwaway PostgreSQL database (with `psql` on PATH) to also run `db/rls_tests.sql` automatically (`tests/sql/` holds the Supabase stand-in). Never use the real project. It also contains the secret scan.
- **Not in the database yet:** the subject table edits (units and types) are kept only on the open page; subjects always start from the curriculum file.

### Privacy notice (also shown on the login page and in About)

- **We collect:** name, email, role, department, faculty scheduling data (specializations, unit limits, availability, preferences, leave dates), saved schedules, and an audit log (ids and counts only).
- **We never collect:** student names, IDs or grades, passwords (Supabase Auth handles sign in), or IP tracking. Hosting providers may keep standard server logs.
- **Who can see it:** a chairperson sees only their own department; faculty see their own preferences and leave and the approved schedule of their department; developers (admin) can see everything for maintenance.



**Requirements:**

- `Flask==3.1.3`

- `flask-cors==6.0.2`

- `ortools==9.15.6755`

- `requests==2.33.1`
- `Werkzeug==3.1.7`
- `gunicorn==23.0.0` (Render)



OR-Tools is strongly recommended. Without it, the built-in greedy solver runs as a fallback: what it places is valid, but it does not guarantee full coverage or an optimal result.

Chart.js is kept in `assets/vendor/`, so the dashboard needs no CDN. On Render the start command is `gunicorn app:app --timeout 120`.



### Tests

```bash
python -m pytest tests -q -m "not slow"   # quick suite, about 20 seconds
python -m pytest tests -q                 # full suite, about 11 minutes
python -m pytest tests/test_part15.py -q  # Supabase sign in: static checks plus a Node run of app-core.js (needs Node)
```

The Playwright tests open the dashboards with a fake Supabase (`tests/fake_auth.py`), so they need no real project.

Tests marked `slow` run the solver for whole departments or open a real browser (Playwright: `pip install playwright pytest && python -m playwright install chromium`). `/run-ga` clamps its inputs (generations 1 to 200, population 4 to 100, mutation and crossover 0 to 1, solver time limit up to `CP_SAT_MAX_TIME_LIMIT_SECONDS`), answers 400 for non-numbers, and applies `units_per_assignment`, `non_classroom_units` and `cp_sat_time_limit` to that run only.

To install the app on a phone, serve the site over HTTPS and use the browser's "Add to Home screen" option.



---



## Roadmap



1. Finish the database layer: faculty data, rooms, class sizes and approved schedules read from Supabase instead of the browser.

2. Respondent data collection, plus usability and AI-output-quality evaluation.

3. Final documentation, submission, and the final thesis defense.



---



## Author



**Arthur V. Baldosano Jr.**

Palawan State University, Computer Studies

PSU-SITE President · Full-Stack Developer · Puerto Princesa, Palawan



---



## License



Proprietary. All rights reserved.



## Departments



Five departments are scheduled separately: IT, CS, MB (Marine Biology), ES (Environmental Science), MedB (Medical Biology). Each is one file in `data/curricula/` with an exact, case-sensitive name: `IT.json`, `CS.json`, `MB.json`, `ES.json`, `MedB.json`.



**File schema.** `dept`, `program`, `name`, `prospectus`, `notes`; `specializations` (allowed tags); `blocks` and `class_sizes` (keys like `IT1B1`, `CS2B3`, `MedB4B2`; 1 to 3 blocks per year, 36 to 48 students, fixed sample data, `class_sizes_placeholder: true`); `rooms` (`"default"` for IT and CS, which use the global room list, or explicit `lecture` and `lab` objects with `recommended` and `max`, plus `lab_rooms_also_lecture` and `capacity_placeholder`); `courses` (`code`, `title`, `year`, `semester`, `lec`, `lab`, `category`, `scheduled`, `specialization`, optional display flags `confirm` and `verify`). A course is in scope when it is present in the file; the files hold only courses taught by College of Sciences faculty. The prospectus images are reference only.



**Role-based behaviour.** Every request carries `dept` (query string for GET, JSON field for POST): `/run-ga`, `/progress`, `/soft-constraints`, `/rooms`, `/class-sizes`, `/analytics*`. A missing or unknown `dept` is a 400. `GET /curricula` lists the departments and `GET /curriculum/<dept>` returns a file (404 when unknown). Once a department is chosen the backend uses only its subjects, blocks, class sizes and rooms. Progress, last result, analytics, warnings, soft constraints, class sizes and room edits are stored per department, each with its own lock, so two departments can run at the same time without touching each other. `/run-ga` returns a `run_id`, echoed by `/progress`.

The browser follows the same rule. The department of the signed-in profile (cached in `atlasDept` for display) decides the curriculum file, tags, rooms, defaults and every saved key: all browser data is stored as `<name>::<dept>` (for example `lastGAResult::CS`), results and reports of one department are never shown in another, and a log out or a different login empties everything held in memory. The faculty login lists only the names saved for the department picked in the same step. **Starting data.** IT starts with a pool of 10 faculty (`default_faculty` in `IT.json`, Mon to Thu, 24 units, hard cap 30); the other four departments start with 8 editable placeholder faculty (Prof A to H). The active period starts as 2026-2027, 1st Semester, until the chairperson sets one. Class sizes and, for MB, ES and MedB, room capacities are sample data (`class_sizes_placeholder`, `capacity_placeholder`): the dashboard says so, and they must be replaced with real figures before the output is used.



**Meetings and rooms.** A course gives `ceil(lec/2)` two-hour lecture meetings plus one lab meeting per lab unit (`LAB_MEETINGS_PER_LAB_UNIT`); unscheduled courses (Practicum, IT 20, IT 22) get one professor and one NON_CLASSROOM row. Labs larger than the department's largest lab room are split (IT and CS: 45; MB, ES, MedB: 60). In MB, ES and MedB the Physics rooms may also host a lecture, with a penalty so lectures prefer lecture rooms. A faculty member qualifies when any tag overlaps the course tags; a course tagged only `Elective` is open to anyone.



**Limits.** Departments are scheduled separately: cross-department room clashes are not checked. The department comes from the signed-in user's profile and is checked by the server on every request; the browser cannot choose it.

**Extract repo zip** git archive -o repository.zip HEAD

### Load unit and fairness metrics

One scheduled meeting counts `units_per_assignment` units (default 2) for its professor, and an unscheduled (non-classroom) group counts `non_classroom_units`. This is a modelling choice, not the teaching load as the prospectus defines it. The `load_model` setting (`LOAD_MODEL` in `config/settings.py`) names the model: `per_meeting` is the only one implemented; `prospectus` (course lecture plus lab hours divided across its meetings) is documented as future work and is not read by any code.

`services/analytics_service.workload_metrics` is the single definition of workload fairness. It covers ALL professors (idle ones included) in units and returns mean, median, min, max, std, cv, Jain, Gini, zero-load count and over-cap counts. Saved runs (`balance_score` = 100 x Jain), the Reports panel and the Home balance card all read it. The Reports colour bands use Jain only (`JAIN_BAND_GOOD` 0.90, `JAIN_BAND_WARNING` 0.80). Underload means `0 < load < target`, target = total assigned units / number of professors. `utilization_pct` is a percent of regular load (`max_units`).

Specialization is counted per course group (year, section, subject), with elective-only groups excluded: `primary_tag_match_pct` (course tag equals the professor's first listed tag), `any_tag_match_pct` ("qualified", 100 by design because the solver refuses unqualified professors) and `elective_group_count`.

### Reproducible runs

`/run-ga` accepts `seed` (random when missing, always returned and stored) and `deterministic` (default off in the UI, `DETERMINISTIC` in `config/settings.py`). The seed drives CP-SAT `random_seed`, one `random.Random(seed)` shared by every GA operator, and the greedy fallback. Deterministic mode runs CP-SAT with one worker and `max_deterministic_time` instead of a wall-clock limit, and removes the GA wall-clock cap, so the same department, semester, inputs and seed give byte-identical assignments on any machine load (a safety stop of `DETERMINISTIC_WALL_CAP_SECONDS` still exists and could break this if it is reached). Each saved run stores an `inputs` snapshot with a SHA-256 hash (see `docs/DATA.md`); `services/run_snapshot.py` builds and verifies it. For chairpersons the run inputs are read from the database, not from the browser.

### Evaluation

`python scripts/evaluate.py` regenerates the results-chapter tables (random-feasible baseline, CP-SAT only, CP-SAT + GA, 10 seeds, 5 departments x 2 semesters, plus the faculty scenarios) into `evaluation/results.csv` and `evaluation/summary.md`; the protocol is in `evaluation/README.md`. `--quick` is a smoke test. The standard faculty pool lives in `tools/faculty_pool.py` and `tests/conftest.py` re-exports it.