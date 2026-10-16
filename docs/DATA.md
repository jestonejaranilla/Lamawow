# ATLAS PSU: data inventory

This file describes every piece of data the ATLAS prototype stores, why, who can read and write it, how long it is
kept, and what it deliberately does not collect. It matches `db/schema.sql` and the Row Level Security (RLS)
rules in that file. If the two ever disagree, `db/schema.sql` is the source of truth and this file must be fixed.

## Scope and status

- **All faculty data in the prototype is pseudonymous test data.** Faculty names are invented pseudonyms
  (see `db/seed.sql`). They are not real PSU staff. Email addresses used for the test accounts are test accounts.
- **The survey and interview data of the study are stored outside this system.** ATLAS does not hold, link to or
  export any survey answer, interview recording, transcript or participant identity.
- Data lives in one Supabase (PostgreSQL) project. The Flask server holds some working state in memory while it
  runs (see "Server memory"). Nothing else is stored server side.
- Departments: IT, CS, MB, ES, MedB. Roles: `chairperson`, `faculty`, `admin`.

## How access works (applies to every table)

- A signed-out visitor (`anon`) has no access to any table.
- A **chairperson** reads and writes only rows of their own department.
- **Faculty** read their own department's faculty list and its approved schedule, and read and write only their
  own preferences and leave.
- **Admin** can read and write everything.
- The department and role of a user come from the `profiles` row. A user cannot change their own `role`, `dept`
  or `faculty_id` (a trigger blocks it).
- The Flask server writes some rows with the service key, which bypasses RLS. The routes check role and
  department before doing so. The service key is never sent to the browser.

## Tables and fields

### `departments`
| Field | Why |
|---|---|
| `code`, `name` | The five departments. Used to keep each department's data separate. |

Read: all signed-in users. Write: admin. Kept: permanently (reference data).

### `profiles` (one row per account)
| Field | Why |
|---|---|
| `id` | Links to the Supabase Auth account. |
| `email` | Identifies the account and is shown as "user" in the audit log. |
| `full_name` | Display name in the app. |
| `role`, `dept` | Decide what the user may do and which department they see. |
| `faculty_id` | Links a faculty account to its faculty record. |
| `created_at`, `updated_at` | Housekeeping. |

Read: the user reads their own row; admin reads all. Write: the user may edit their own `full_name`; admin,
the SQL editor or the service role set the rest. Kept: while the account exists. The row is deleted with the
Supabase Auth account.

### `faculty`
| Field | Why |
|---|---|
| `id`, `dept` | Identity and department. |
| `name` | Shown in schedules. Pseudonym in the prototype. |
| `specializations` | The engine matches subjects to specializations. |
| `max_units`, `overload_buffer` | Teaching load limits used by the engine. |
| `availability` | Days the person can teach (Mon to Sat). |
| `created_at`, `updated_at` | Housekeeping. |

Read: own department (chairperson and faculty). Write: chairperson of that department, admin. Kept: until a
chairperson deletes the record.

### `faculty_preferences` (one row per faculty member)
| Field | Why |
|---|---|
| `faculty_id` | Whose preference it is. |
| `preferred_period`, `preferred_room`, `preferred_building`, `preferred_floor`, `avoid_days` | Soft constraints the engine scores. |

Read: the faculty member and the chairperson of the department. A colleague cannot read it. Write: the faculty
member (own row), the chairperson, admin. Kept: until changed or deleted. Deleted with the faculty record.

### `faculty_leave`
| Field | Why |
|---|---|
| `faculty_id`, `start_date`, `end_date` | Dates the person is unavailable. A one day leave has equal start and end. |

There is **no reason field, on purpose**. Read and write: same as preferences. Kept: until deleted. Deleted
with the faculty record.

### `class_sizes`
| Field | Why |
|---|---|
| `dept`, `block_key` (for example `IT1B1`), `year`, `size` | Number of students in a class block, used to choose rooms. |

Only a head count per block. No student is identified. Read and write: chairperson of the department, admin.
Kept: until changed or deleted.

### `rooms`
| Field | Why |
|---|---|
| `dept`, `name`, `kind` (lecture or lab), `recommended`, `max` | Room capacity for the engine. |

Read and write: chairperson of the department, admin. Kept: until changed or deleted.

### `dept_settings` (one row per department)
| Field | Why |
|---|---|
| `academic_year`, `semester` | The active academic period. |
| `solver` | Solver settings (limits and time limit). |
| `lab_also_lecture` | Whether lab rooms may host lectures. |

Read and write: chairperson of the department, admin. Faculty cannot read it. Kept: until changed.

### `schedule_runs` (saved optimization results)
| Field | Why |
|---|---|
| `dept`, `academic_year`, `semester` | Which period the run belongs to. |
| `label` | A name the chairperson gives the run. Do not put personal data in it. |
| `status` | `draft`, `saved` or `approved`. At most one approved run per department, year and semester. |
| `created_by` | The account that ran it ("who ran it" in the list). |
| `solver_settings`, `metrics`, `coverage`, `duration_ms` | How the run was made and how good it was. |
| `result`, `analytics` | The schedule and its charts. Contains faculty names (pseudonyms), subjects, rooms and times. |
| `created_at`, `updated_at` | Housekeeping. |

Read: chairperson of the department (all statuses), faculty of the department (**approved only**), admin.
Write: chairperson of the department and admin for draft and saved runs. A signed-in chairperson cannot delete
an approved run, edit its result, or set a run to approved except through `approve_run()` (trigger
`trg_runs_guard`). Kept: until a chairperson or admin deletes it. Approved runs are kept.

### `audit_log` (append-only)
| Field | Why |
|---|---|
| `at` | When it happened. |
| `user_id`, `email` | Who did it. |
| `dept` | Which department it concerns. Used to filter the chairperson's view. |
| `action`, `entity`, `entity_id` | What was done and to what kind of thing, for example `run_saved` on a `run`. |
| `meta` | Small flags and counts only (for example how many rooms). Never schedule content or personal data. |

Read: chairperson reads their own department. Admin reads all. Faculty have no access. The audit screen shows
only time, user (email), action and entity. Write: signed-in users may add rows about themselves in their own
department. The server adds rows with the service key. Nobody can edit a row, including the service role.
Only admin or the service role can delete rows, through `purge_audit_log()`.

`meta` is checked twice: in `services/audit_service.py` and by the trigger `trg_audit_meta` (JSON object, at most
2 KB, forbidden keys such as `name`, `email`, `result`, `leave`, `reason`). These checks are a guard against
mistakes, not a full scanner.

**Retention:** production keeps at least 12 months of audit rows (team decision). Rows are not removed
automatically. An admin purges old rows with `scripts/purge_audit_log.py`, which refuses to delete anything
newer than 12 months when running in production. Development databases may be purged freely.

## Server memory (not a database)

While the Flask server runs it keeps engine state in memory: the department's loaded faculty, rooms, class sizes
and settings for a run in progress, and a 60 second cache of the signed-in user's profile. This is lost on
restart. Finished runs and audit events are the only things the server writes to the database.

## Data in the browser

- **Device settings** (theme, text size, notification preferences) stay in the browser's local storage.
- **Working data** (faculty, rooms and so on) is read from the database. A short-lived local copy is used only if
  the database cannot be reached, and it is never written back over newer database data.
- **Logout, or a different user signing in on the same computer, clears all working keys.** Only device settings remain.
- The Supabase session token is held by the browser while signed in and removed on logout.

## What is deliberately not collected

- **Student names, student IDs and grades.** Class sizes are head counts only.
- **Passwords.** ATLAS tables hold no password. Sign in is handled by Supabase Auth, which stores a salted hash
  on its side. ATLAS never sees or logs a password.
- **IP addresses and device identifiers.** No ATLAS table or log field records them.
- **Tracking.** No analytics, advertising, cookies for tracking, fingerprinting or third party tracking scripts.
  The chart and Supabase libraries are served from `assets/vendor/`, not from a CDN.
- **Reasons for leave.** Dates only.
- **Survey and interview data of the study.** Stored outside the system.

### Limits of these statements

- The pages load fonts from Google Fonts (`fonts.googleapis.com`, `fonts.gstatic.com`). A browser that loads
  them sends its IP address to Google. ATLAS itself does not record it. The fonts can be hosted locally if this must be avoided.
- The hosting provider and Supabase may keep their own infrastructure request logs. ATLAS does not read or control them.
- `profiles.email` and `audit_log.email` are personal data of the people who use the system.