<div align="center">

<img src="/assets/images/favicon.png" alt="ATLAS PSU" width="72" />



# ATLAS PSU



**A Teaching Load Assignment and Management System for Department Chairpersons of the College of Sciences at Palawan State University**



*A hybrid CP-SAT and Genetic Algorithm engine that recommends faculty teaching loads. Chairpersons review, edit, and finalize every assignment.*



[![Status](https://img.shields.io/badge/status-thesis%20prototype-c9a96e?style=flat-square)](#current-status)

[![Built With](https://img.shields.io/badge/built%20with-Python%20%7C%20Flask%20%7C%20Vanilla%20JS-4a90d9?style=flat-square)](#technologies-used)

[![License](https://img.shields.io/badge/license-Proprietary-gray?style=flat-square)](#license)

[![Location](https://img.shields.io/badge/based%20in-Puerto%20Princesa%2C%20Palawan-0a7ab8?style=flat-square)](#)



</div>



---



## What Is This?



ATLAS PSU is a teaching load assignment and management system built for the Department Chairpersons of the College of Sciences, Palawan State University (PSU), Puerto Princesa City. It covers the Information Technology, Computer Science, Medical Biology, Marine Biology, and Environmental Science departments.



It replaces spreadsheet-based, manual assignment with a two-phase optimization engine. A CP-SAT constraint solver produces a hard-constraint-valid base schedule in Phase 1. A Genetic Algorithm tunes that schedule against faculty preferences in Phase 2. An analytics phase then computes workload fairness and specialization match rates.



The existing college tool only plots schedules after the fact: it does no automated assignment, constraint checking, or conflict resolution. ATLAS PSU generates the recommendation, then gives the chairperson decision-support tools (workload charts and a fairness report) and manual editing so the final decision stays with them. Faculty members get their own read-only view of the finished schedule.



This is a capstone thesis project built between April and July 2026.



---



## Current Status



- The proposal prototype defense is complete. The final thesis defense is still ahead.

- The scheduling engine, analytics, chairperson dashboard, and faculty dashboard are built and running on a Flask backend with a vanilla JavaScript frontend.

- Data is held in memory and in files. There is no persistent database yet. A Postgres backend is planned once the scheduling logic is fully validated.

- Login does not perform real authentication yet. It starts a browser session and routes the user by role.

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



Takes the valid CP-SAT schedule as input and improves slot and room assignments against faculty soft preferences. It never generates schedules from scratch and never changes who teaches what: only slots and rooms move. Every candidate is validated, and if the result has more rule violations than the CP-SAT schedule it started from, the CP-SAT schedule is returned unchanged.



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

- Two-phase optimization: CP-SAT for correctness, GA for preference satisfaction

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

- Faculty sign in by choosing their name from the faculty list saved in the browser

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



**P1 - Authentication:** Establishes a session and routes the user by role (chairperson or faculty).



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

- Google OR-Tools CP-SAT (ortools >= 9.7)

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

  login.html                  Role (chairperson or faculty), sign in / sign up

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

  js/login-script.js          Login and sign up for both roles

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



> Demo build: runs locally, data stays in the browser.



**Requirements:**

- `Flask==3.1.3`

- `flask-cors==6.0.2`

- `ortools>=9.7.2996`

- `requests==2.33.1`
- `Werkzeug==3.1.7`
- `gunicorn==23.0.0` (Render)



OR-Tools is strongly recommended. Without it, the built-in greedy solver runs as a fallback: what it places is valid, but it does not guarantee full coverage or an optimal result.

Chart.js is kept in `assets/vendor/`, so the dashboard needs no CDN. On Render the start command is `gunicorn app:app --timeout 120`.



To install the app on a phone, serve the site over HTTPS and use the browser's "Add to Home screen" option.



---



## Roadmap



1. Finish the database layer (Postgres).

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

The browser follows the same rule. The department chosen at login (`atlasDept`) decides the curriculum file, tags, rooms, defaults and every saved key: all browser data is stored as `<name>::<dept>` (for example `lastGAResult::CS`), results and reports of one department are never shown in another, and a log out or a different login empties everything held in memory. The faculty login lists only the names saved for the department picked in the same step. **Starting data.** IT starts with a pool of 10 faculty (`default_faculty` in `IT.json`, Mon to Thu, 24 units, hard cap 30); the other four departments start with 8 editable placeholder faculty (Prof A to H). The active period starts as 2026-2027, 1st Semester, until the chairperson sets one. Class sizes and, for MB, ES and MedB, room capacities are sample data (`class_sizes_placeholder`, `capacity_placeholder`): the dashboard says so, and they must be replaced with real figures before the output is used.



**Meetings and rooms.** A course gives `ceil(lec/2)` two-hour lecture meetings plus one lab meeting per lab unit (`LAB_MEETINGS_PER_LAB_UNIT`); unscheduled courses (Practicum, IT 20, IT 22) get one professor and one NON_CLASSROOM row. Labs larger than the department's largest lab room are split (IT and CS: 45; MB, ES, MedB: 50). In MB, ES and MedB the Physics rooms may also host a lecture, with a penalty so lectures prefer lecture rooms. A faculty member qualifies when any tag overlaps the course tags; a course tagged only `Elective` is open to anyone.



**Limits.** Departments are scheduled separately: cross-department room clashes are not checked. Department selection at login is not authentication.