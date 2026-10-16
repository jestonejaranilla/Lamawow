# ATLAS PSU database (Supabase / Postgres)

SQL and docs only. No app code uses this yet.

## Files

| File | What it does |
|---|---|
| `schema.sql` | Tables, helper functions, triggers, RPCs, grants and RLS policies. Safe to re-run. |
| `seed.sql` | 5 departments, 10 pseudonym faculty each, rooms, class sizes, active period and solver defaults. Re-runnable (`on conflict do nothing`). |
| `rls_tests.sql` | Proves the access rules. Runs in one transaction and rolls back. |

## Setup order

1. Supabase dashboard, SQL editor: run `schema.sql`, then `seed.sql`.
2. Authentication, Users: create the test accounts below (tick "Auto confirm user").
3. Run the profiles snippet below.
4. Run `rls_tests.sql`. Expected last line: `ALL RLS TESTS PASSED`.

The seed tags come from `data/curricula/<dept>.json`. `Elective` is not given to anyone, because the engine treats electives as open to every faculty. Each professor gets 3 tags and every other tag of the department is covered at least twice. IT and CS rooms come from `config/settings.py` (the JSON marks them as `default`). Room capacities and class sizes are the placeholder values from the JSON.

## Test accounts

Create these in Auth. Pick any password you will remember; do not reuse a real one.

| Email | Role | Dept |
|---|---|---|
| `chairit@psu.palawan.edu.ph` | chairperson | IT |
| `chaircs@psu.palawan.edu.ph` | chairperson | CS |
| `chairmb@psu.palawan.edu.ph` | chairperson | MB |
| `chaires@psu.palawan.edu.ph` | chairperson | ES |
| `chairmedb@psu.palawan.edu.ph` | chairperson | MedB |
| `profmaricar@psu.palawan.edu.ph` | faculty, linked to Prof. Maricar Dela Cruz | IT |
| `adminatlas@psu.palawan.edu.ph` (optional, developers) | admin | none |

### Insert the profiles (after the users exist in Auth)

```sql
insert into public.profiles (id, email, full_name, role, dept, faculty_id)
select u.id, u.email, v.full_name, v.role, v.dept,
       (select f.id from public.faculty f where f.dept = v.dept and f.name = v.faculty_name)
from auth.users u
join (values
  ('chairit@psu.palawan.edu.ph',    'IT Chairperson',   'chairperson', 'IT',   null),
  ('chaircs@psu.palawan.edu.ph',    'CS Chairperson',   'chairperson', 'CS',   null),
  ('chairmb@psu.palawan.edu.ph',    'MB Chairperson',   'chairperson', 'MB',   null),
  ('chaires@psu.palawan.edu.ph',    'ES Chairperson',   'chairperson', 'ES',   null),
  ('chairmedb@psu.palawan.edu.ph',  'MedB Chairperson', 'chairperson', 'MedB', null),
  ('profmaricar@psu.palawan.edu.ph','Prof. Maricar Dela Cruz','faculty','IT',  'Prof. Maricar Dela Cruz'),
  ('adminatlas@psu.palawan.edu.ph', 'ATLAS Admin',      'admin',       null,   null)
) as v(email, full_name, role, dept, faculty_name) on v.email = u.email
on conflict (id) do nothing;
```

Roles and departments are never set by the signed-in user. Only an admin, the SQL editor or the service role can create or change a profile's `role`, `dept` or `faculty_id`.

## Faculty names (pseudonyms, all different across departments)

- **IT:** Maricar Dela Cruz, Jericho Manalastas, Liezl Macaraeg, Ronaldo Pasion, Criselda Bautista, Emmanuel Tolentino, Glenda Villanueva, Rodel Magsaysay, Aileen Dimaculangan, Noel Evangelista
- **CS, MB, ES, MedB:** see `seed.sql`

## Who can do what

| Table | Chairperson (own dept only) | Faculty | Admin |
|---|---|---|---|
| `departments` | read | read | all |
| `profiles` | read own row, edit own `full_name` | same | all |
| `faculty` | read, write | read own dept | all |
| `faculty_preferences` | read, write own dept | read and write only their own row | all |
| `faculty_leave` | read, write own dept | read and write only their own rows | all |
| `class_sizes`, `rooms`, `dept_settings` | read, write | no access | all |
| `schedule_runs` | read, write | read `approved` runs of own dept only | all |
| `audit_log` | read own dept, no edit, no delete | no access (can only add rows about themselves) | read, add, delete |

- `anon` (signed out) has no access to anything.
- Faculty cannot read a colleague's preferences or leave, even in the same department.
- `faculty_leave` has no reason column. One day off is `start_date = end_date`.
- Helper functions `public.current_dept()` and `public.current_role()` read the caller's `profiles` row (security definer). `current_role` is also an SQL keyword, so always call it as `public.current_role()`.
- `profiles.role` and `dept` are protected by a trigger, not just by policy: a signed-in non-admin can change only `full_name`.

### RPCs

- `approve_run(run_id uuid)`: chairperson of the run's department only. In one transaction it moves the previous `approved` run of the same dept, year and semester to `saved`, then approves the new one. The partial unique index `schedule_runs_one_approved` also guarantees at most one approved run per (dept, academic_year, semester). It writes an `approve_run` row to `audit_log`.
- **Approved runs are frozen for chairpersons** (trigger `trg_runs_guard` on `schedule_runs`, Part 15b). A signed-in chairperson or faculty user cannot:
  - delete an `approved` run;
  - change its `result`, `analytics`, `metrics`, `coverage`, `solver_settings`, `dept`, `academic_year`, `semester` or `created_by`;
  - insert or update a run into `approved`, except through `approve_run`, which sets `atlas.approving` for its own transaction only.
  Draft and saved runs of the own department can still be saved, loaded, edited and deleted. Admin, the service role and the SQL editor are not restricted by the guard.
- `purge_audit_log(older_than interval)`: admin only. Returns the number of rows deleted. Example: `select public.purge_audit_log(interval '12 months');`

## Audit log

`audit_log.meta` must never contain schedule content or personal data. Store counts, ids, status flags and settings keys only. A trigger rejects non-object `meta`, anything over 2 KB, and top-level keys such as `result`, `analytics`, `schedule`, `assignments`, `name`, `email`, `reason`, `leave`. This is a guard against mistakes, not a full scanner, so the app code must still keep meta clean.

Audit rows cannot be edited by anyone, including the service role (a trigger blocks UPDATE). The `email` column holds the actor's email on purpose; it is not part of `meta`.

### Retention (team decision)

- Production: keep at least 12 months of audit rows. Run `purge_audit_log` no more often than monthly, and never with an interval shorter than 12 months.
- Use `python scripts/purge_audit_log.py --older-than "12 months"` (admin sign in, asks you to type PURGE). With `ATLAS_ENV=production` (or on Render) it refuses anything shorter than 12 months. That floor is enforced by the script and by this rule, not by the database function, which only needs an admin and a positive interval.
- Every table and field is described in `docs/DATA.md`.
- Development: purge freely, for example `select public.purge_audit_log(interval '1 day');`.

## Notes

- `dept_settings` has one extra column, `lab_also_lecture boolean`. The curriculum JSON uses it for MB, ES and MedB (lab rooms may host lectures), and there was no other place to keep it.
- `class_sizes.year` is a number 1 to 4 (the JSON stores "1st Year"). `block_key` is the JSON key, for example `IT1B1`.
- `dept_settings.semester` accepts the same strings as the dashboard: `1st Semester`, `2nd Semester`, `Summer`. The seed sets `2026-2027`, `1st Semester`.
- `schedule_runs.result` and `analytics` hold full schedules (large jsonb). Faculty can read them for approved runs, so do not put private notes in there.
- Not modeled yet: `maternity_leave` and `unavailable_dates` from the current UI. Unavailable dates map to `faculty_leave` rows with `start_date = end_date`.