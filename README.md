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

This is a capstone thesis project, developed by one person between April and July 2026.

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

Uses Google OR-Tools CP-SAT to generate a conflict-free base schedule. If OR-Tools is not installed, the solver falls back to a deterministic greedy backtracking algorithm with the same hard-constraint guarantees.

Hard constraints enforced:
- Faculty qualification based on the specialization map
- Faculty day availability
- Absolute maximum load per faculty (standard 24 units, overload cap 30 units per CHED CMO No. 40, s. 2006)
- No faculty double-booking within a time slot
- No room conflicts within a time slot
- Room type compatibility (LAB subjects go to laboratory rooms only)
- Full section coverage across all year levels and blocks

### Phase 2 - Genetic Algorithm Optimizer (`solver/ga_optimizer.py`)

Takes the valid CP-SAT schedule as input and improves slot and room assignments against faculty soft preferences. It never generates schedules from scratch and never violates hard constraints. Faculty assignments from Phase 1 are authoritative.

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
  cp_sat_solver.py            Phase 1: hard constraint solver (OR-Tools + greedy fallback)
  ga_optimizer.py             Phase 2: preference optimizer (never violates hard constraints)
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
| `CP_SAT_TIME_LIMIT_SECONDS` | 60.0 | OR-Tools solver time limit |
| `GA_WEIGHTS` | See settings.py | Soft preference scoring weights for the GA |

---

## Installation

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` in your browser.

**Requirements:**
- `Flask==3.1.3`
- `flask-cors==6.0.2`
- `ortools>=9.7.2996`
- `Werkzeug==3.1.7`

OR-Tools is strongly recommended. Without it, the built-in greedy backtracking solver runs as a fallback with the same hard-constraint guarantees but slower performance on large inputs.

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