-- ATLAS PSU - db/schema.sql
-- Supabase (Postgres 15+). Safe to re-run: tables use IF NOT EXISTS, functions use
-- CREATE OR REPLACE, policies and triggers are dropped and recreated.
-- Run the whole file in the Supabase SQL editor, then run db/seed.sql.
--
-- NOTE: current_role is also a reserved SQL keyword. The helper is created as
-- public.current_role() and must ALWAYS be called schema-qualified.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- tables

create table if not exists public.departments (
  code text primary key check (code in ('IT','CS','MB','ES','MedB')),
  name text not null
);

create table if not exists public.faculty (
  id               uuid primary key default gen_random_uuid(),
  dept             text not null references public.departments(code),
  name             text not null,
  specializations  text[] not null default '{}',
  max_units        int  not null default 24 check (max_units > 0),
  overload_buffer  int  not null default 6  check (overload_buffer >= 0),
  availability     text[] not null default '{Mon,Tue,Wed,Thu}'
                   check (availability <@ array['Mon','Tue','Wed','Thu','Fri','Sat']),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (dept, name)
);
create index if not exists faculty_dept_idx on public.faculty(dept);

create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  full_name   text,
  role        text not null check (role in ('chairperson','faculty','admin')),
  dept        text references public.departments(code),
  faculty_id  uuid references public.faculty(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  check (role = 'admin' or dept is not null)
);
create index if not exists profiles_faculty_idx on public.profiles(faculty_id);

create table if not exists public.faculty_preferences (
  faculty_id         uuid primary key references public.faculty(id) on delete cascade,
  preferred_period   text check (preferred_period in ('morning','afternoon','evening')),
  preferred_room     text,
  preferred_building text,
  preferred_floor    text,
  avoid_days         text[] not null default '{}'
                     check (avoid_days <@ array['Mon','Tue','Wed','Thu','Fri','Sat']),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

-- Dates only. No reason column on purpose. One day off = start_date = end_date.
create table if not exists public.faculty_leave (
  id          uuid primary key default gen_random_uuid(),
  faculty_id  uuid not null references public.faculty(id) on delete cascade,
  start_date  date not null,
  end_date    date not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  check (end_date >= start_date)
);
create index if not exists faculty_leave_faculty_idx on public.faculty_leave(faculty_id);

create table if not exists public.class_sizes (
  id          uuid primary key default gen_random_uuid(),
  dept        text not null references public.departments(code),
  block_key   text not null,                       -- e.g. IT1B1
  year        smallint not null check (year between 1 and 4),
  size        int not null check (size > 0),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (dept, block_key)
);

create table if not exists public.rooms (
  id           uuid primary key default gen_random_uuid(),
  dept         text not null references public.departments(code),
  name         text not null,
  kind         text not null check (kind in ('lecture','lab')),
  recommended  int not null check (recommended > 0),
  max          int not null check (max > 0),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (dept, name),
  check (recommended <= max)
);

create table if not exists public.dept_settings (
  dept             text primary key references public.departments(code),
  academic_year    text not null,
  semester         text not null check (semester in ('1st Semester','2nd Semester','Summer')),
  solver           jsonb not null default '{}'::jsonb,
  lab_also_lecture boolean not null default false,  -- lab rooms may host lectures
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table if not exists public.schedule_runs (
  id               uuid primary key default gen_random_uuid(),
  dept             text not null references public.departments(code),
  academic_year    text not null,
  semester         text not null,
  label            text,
  status           text not null default 'draft' check (status in ('draft','saved','approved')),
  created_by       uuid references auth.users(id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  solver_settings  jsonb,
  metrics          jsonb,
  coverage         jsonb,
  duration_ms      int check (duration_ms >= 0),
  result           jsonb,
  analytics        jsonb
);
-- Part 20: the inputs snapshot (faculty, class sizes, rooms, preferences, subjects, settings, seed, hash, versions).
-- Idempotent, so it also upgrades a database created before this column existed.
alter table public.schedule_runs add column if not exists inputs jsonb;
create index if not exists schedule_runs_dept_idx on public.schedule_runs(dept, academic_year, semester);
create unique index if not exists schedule_runs_one_approved
  on public.schedule_runs(dept, academic_year, semester) where status = 'approved';

create table if not exists public.audit_log (
  id         bigint generated always as identity primary key,
  at         timestamptz not null default now(),
  user_id    uuid,
  email      text,
  dept       text,
  action     text not null,
  entity     text,
  entity_id  text,
  meta       jsonb not null default '{}'::jsonb
);
create index if not exists audit_log_dept_at_idx on public.audit_log(dept, at desc);

-- ------------------------------------------------------- helper functions

create or replace function public.current_dept() returns text
language sql stable security definer set search_path = '' as $$
  select p.dept from public.profiles p where p.id = auth.uid()
$$;

create or replace function public.current_role() returns text
language sql stable security definer set search_path = '' as $$
  select p.role from public.profiles p where p.id = auth.uid()
$$;

create or replace function public.current_faculty_id() returns uuid
language sql stable security definer set search_path = '' as $$
  select p.faculty_id from public.profiles p where p.id = auth.uid()
$$;

revoke all on function public.current_dept(), public.current_role(), public.current_faculty_id() from public, anon;
grant execute on function public.current_dept(), public.current_role(), public.current_faculty_id() to authenticated;

-- ---------------------------------------------------------------- triggers

create or replace function public.set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin new.updated_at = now(); return new; end $$;

do $$
declare t text;
begin
  foreach t in array array['profiles','faculty','faculty_preferences','faculty_leave',
                           'class_sizes','rooms','dept_settings','schedule_runs']
  loop
    execute format('drop trigger if exists trg_updated_at on public.%I', t);
    execute format('create trigger trg_updated_at before update on public.%I
                    for each row execute function public.set_updated_at()', t);
  end loop;
end $$;

-- A signed-in non-admin can change only full_name on their own profile.
-- SQL editor and service role (no end-user JWT, auth.uid() is null) are not restricted.
create or replace function public.protect_profile_columns() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is not null and public.current_role() is distinct from 'admin' then
    if new.id         is distinct from old.id
    or new.email      is distinct from old.email
    or new.role       is distinct from old.role
    or new.dept       is distinct from old.dept
    or new.faculty_id is distinct from old.faculty_id then
      raise exception 'only full_name can be changed on your own profile' using errcode = '42501';
    end if;
  end if;
  return new;
end $$;
drop trigger if exists trg_protect_profile on public.profiles;
create trigger trg_protect_profile before update on public.profiles
  for each row execute function public.protect_profile_columns();

-- Audit log is append-only for everyone (service role included). Only DELETE
-- (admin or service role, via purge_audit_log) can remove rows.
create or replace function public.audit_log_no_update() returns trigger
language plpgsql set search_path = '' as $$
begin raise exception 'audit_log rows cannot be edited' using errcode = '42501'; end $$;
drop trigger if exists trg_audit_no_update on public.audit_log;
create trigger trg_audit_no_update before update on public.audit_log
  for each row execute function public.audit_log_no_update();

-- Best-effort guard: meta must be a small flat-ish object with no schedule
-- content or personal data keys. Put counts, ids and status flags only.
create or replace function public.audit_log_check_meta() returns trigger
language plpgsql set search_path = '' as $$
declare bad text[] := array['result','analytics','schedule','assignments','coverage',
  'name','full_name','email','phone','reason','preferences','leave','leave_dates','professor','faculty_name'];
begin
  if jsonb_typeof(new.meta) <> 'object' then
    raise exception 'audit_log.meta must be a JSON object';
  end if;
  if exists (select 1 from jsonb_object_keys(new.meta) k where lower(k) = any(bad)) then
    raise exception 'audit_log.meta must not contain schedule content or personal data';
  end if;
  if pg_column_size(new.meta) > 2048 then
    raise exception 'audit_log.meta is too large (max 2 KB)';
  end if;
  return new;
end $$;
drop trigger if exists trg_audit_meta on public.audit_log;
create trigger trg_audit_meta before insert on public.audit_log
  for each row execute function public.audit_log_check_meta();

-- ------------------------------------------------- schedule_runs guard (approved runs)

-- For a signed-in chairperson or faculty user (auth.uid() is not null) an approved run is frozen:
--   a. it cannot be deleted;
--   b. its result, analytics, metrics, coverage, solver_settings, dept, academic_year, semester and
--      created_by cannot be changed;
--   c. nothing can be inserted or updated INTO status 'approved' except inside
--      approve_run(), which sets atlas.approving = '1' for its own transaction.
-- The service role and the SQL editor have no auth.uid(), so they are not affected, and an admin
-- (public.current_role() = 'admin') may fix an approved run.
-- Chairpersons can still save, load and delete draft and saved runs of their own department.
create or replace function public.schedule_runs_guard() returns trigger
language plpgsql set search_path = '' as $$
declare approving boolean := coalesce(current_setting('atlas.approving', true), '') = '1';
begin
  if auth.uid() is null or public.current_role() = 'admin' then
    if tg_op = 'DELETE' then return old; end if;
    return new;
  end if;

  if tg_op = 'DELETE' then
    if old.status = 'approved' then
      raise exception 'an approved run cannot be deleted' using errcode = '42501';
    end if;
    return old;
  end if;

  if tg_op = 'UPDATE' and old.status = 'approved' then
    if (new.result, new.analytics, new.inputs, new.metrics, new.coverage, new.solver_settings,
        new.dept, new.academic_year, new.semester, new.created_by)
       is distinct from
       (old.result, old.analytics, old.inputs, old.metrics, old.coverage, old.solver_settings,
        old.dept, old.academic_year, old.semester, old.created_by) then
      raise exception 'an approved run cannot be edited' using errcode = '42501';
    end if;
  end if;

  -- S1: an approved run cannot be demoted (then deleted) by a chairperson. Only approve_run() demotes the old one.
  if tg_op = 'UPDATE' and old.status = 'approved' and new.status is distinct from 'approved' and not approving then
    raise exception 'an approved run cannot be demoted' using errcode = '42501';
  end if;

  if new.status = 'approved' and not approving
     and (tg_op = 'INSERT' or old.status is distinct from 'approved') then
    raise exception 'a run can only be approved with approve_run()' using errcode = '42501';
  end if;
  return new;
end $$;
drop trigger if exists trg_runs_guard on public.schedule_runs;
create trigger trg_runs_guard before insert or update or delete on public.schedule_runs
  for each row execute function public.schedule_runs_guard();

-- -------------------------------------------------------------------- RPCs

-- Approve a run: the previous approved run of the same dept/year/semester
-- becomes 'saved' and this one becomes 'approved', in one transaction.
create or replace function public.approve_run(run_id uuid) returns public.schedule_runs
language plpgsql security definer set search_path = '' as $$
declare r public.schedule_runs;
begin
  if public.current_role() is distinct from 'chairperson' then
    raise exception 'only a chairperson can approve a run' using errcode = '42501';
  end if;
  select * into r from public.schedule_runs where id = run_id for update;
  if not found or r.dept is distinct from public.current_dept() then
    raise exception 'run not found or not in your department' using errcode = '42501';
  end if;
  perform pg_advisory_xact_lock(hashtext(r.dept || '|' || r.academic_year || '|' || r.semester));
  perform set_config('atlas.approving', '1', true);          -- lets trg_runs_guard accept the status change below
  update public.schedule_runs set status = 'saved'
   where dept = r.dept and academic_year = r.academic_year and semester = r.semester
     and status = 'approved' and id <> r.id;
  update public.schedule_runs set status = 'approved' where id = r.id returning * into r;
  insert into public.audit_log(user_id, email, dept, action, entity, entity_id)
  select auth.uid(), p.email, p.dept, 'approve_run', 'schedule_run', r.id::text
    from public.profiles p where p.id = auth.uid();
  perform set_config('atlas.approving', '0', true);          -- never leaves the switch on for later statements
  return r;
end $$;

-- Admin only. Returns how many rows were deleted.
create or replace function public.purge_audit_log(older_than interval) returns bigint
language plpgsql security definer set search_path = '' as $$
declare n bigint;
begin
  if public.current_role() is distinct from 'admin' then
    raise exception 'admin only' using errcode = '42501';
  end if;
  if older_than is null or older_than <= interval '0' then
    raise exception 'older_than must be a positive interval';
  end if;
  -- S5: the 12-month retention floor lives here, not only in the purge script. Only the SQL editor (a session
  -- that runs  set atlas.allow_short_purge = 'on')  may purge more recent rows, for example on a development database.
  if older_than < interval '12 months'
     and coalesce(current_setting('atlas.allow_short_purge', true), '') <> 'on' then
    raise exception 'the audit log keeps at least 12 months' using errcode = '42501';
  end if;
  delete from public.audit_log where at < now() - older_than;
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.approve_run(uuid), public.purge_audit_log(interval) from public, anon;
grant execute on function public.approve_run(uuid), public.purge_audit_log(interval) to authenticated;

-- ------------------------------------------------------------------- grants

revoke all on all tables in schema public from anon;
grant select, insert, update, delete on all tables in schema public to authenticated;
-- profiles are created by an admin or the service role, never by the signed-in user
-- (no INSERT/DELETE policy for them below). audit_log: no UPDATE for anyone.
revoke update on public.audit_log from authenticated;

-- --------------------------------------------------------------------- RLS

do $$
declare t text;
begin
  foreach t in array array['departments','profiles','faculty','faculty_preferences','faculty_leave',
    'class_sizes','rooms','dept_settings','schedule_runs','audit_log']
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

-- Drop every policy we own so the file can be re-run.
do $$
declare r record;
begin
  for r in select schemaname, tablename, policyname from pg_policies
           where schemaname = 'public' and policyname like 'atlas\_%'
  loop
    execute format('drop policy %I on %I.%I', r.policyname, r.schemaname, r.tablename);
  end loop;
end $$;

-- departments: any signed-in user reads, admin writes
create policy atlas_departments_read  on public.departments for select to authenticated using (true);
create policy atlas_departments_admin on public.departments for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

-- profiles: read own row only; update own row (trigger limits it to full_name); admin all
create policy atlas_profiles_read_own on public.profiles for select to authenticated
  using (id = auth.uid());
create policy atlas_profiles_update_own on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());
create policy atlas_profiles_admin on public.profiles for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

-- faculty
create policy atlas_faculty_chair on public.faculty for all to authenticated
  using (public.current_role() = 'chairperson' and dept = public.current_dept())
  with check (public.current_role() = 'chairperson' and dept = public.current_dept());
create policy atlas_faculty_read_dept on public.faculty for select to authenticated
  using (public.current_role() = 'faculty' and dept = public.current_dept());
create policy atlas_faculty_admin on public.faculty for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

-- faculty_preferences
create policy atlas_prefs_chair on public.faculty_preferences for all to authenticated
  using (public.current_role() = 'chairperson' and exists
         (select 1 from public.faculty f where f.id = faculty_id and f.dept = public.current_dept()))
  with check (public.current_role() = 'chairperson' and exists
         (select 1 from public.faculty f where f.id = faculty_id and f.dept = public.current_dept()));
create policy atlas_prefs_own on public.faculty_preferences for all to authenticated
  using (public.current_role() = 'faculty' and faculty_id = public.current_faculty_id())
  with check (public.current_role() = 'faculty' and faculty_id = public.current_faculty_id());
create policy atlas_prefs_admin on public.faculty_preferences for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

-- faculty_leave
create policy atlas_leave_chair on public.faculty_leave for all to authenticated
  using (public.current_role() = 'chairperson' and exists
         (select 1 from public.faculty f where f.id = faculty_id and f.dept = public.current_dept()))
  with check (public.current_role() = 'chairperson' and exists
         (select 1 from public.faculty f where f.id = faculty_id and f.dept = public.current_dept()));
create policy atlas_leave_own on public.faculty_leave for all to authenticated
  using (public.current_role() = 'faculty' and faculty_id = public.current_faculty_id())
  with check (public.current_role() = 'faculty' and faculty_id = public.current_faculty_id());
create policy atlas_leave_admin on public.faculty_leave for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

-- class_sizes, rooms, dept_settings: chairperson of the dept, admin
create policy atlas_class_sizes_chair on public.class_sizes for all to authenticated
  using (public.current_role() = 'chairperson' and dept = public.current_dept())
  with check (public.current_role() = 'chairperson' and dept = public.current_dept());
create policy atlas_class_sizes_admin on public.class_sizes for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

create policy atlas_rooms_chair on public.rooms for all to authenticated
  using (public.current_role() = 'chairperson' and dept = public.current_dept())
  with check (public.current_role() = 'chairperson' and dept = public.current_dept());
create policy atlas_rooms_admin on public.rooms for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

create policy atlas_dept_settings_chair on public.dept_settings for all to authenticated
  using (public.current_role() = 'chairperson' and dept = public.current_dept())
  with check (public.current_role() = 'chairperson' and dept = public.current_dept());
create policy atlas_dept_settings_admin on public.dept_settings for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

-- schedule_runs: chairperson full on own dept; faculty read approved runs of own dept
create policy atlas_runs_chair on public.schedule_runs for all to authenticated
  using (public.current_role() = 'chairperson' and dept = public.current_dept())
  with check (public.current_role() = 'chairperson' and dept = public.current_dept());
create policy atlas_runs_faculty_read on public.schedule_runs for select to authenticated
  using (public.current_role() = 'faculty' and dept = public.current_dept() and status = 'approved');
create policy atlas_runs_admin on public.schedule_runs for all to authenticated
  using (public.current_role() = 'admin') with check (public.current_role() = 'admin');

-- audit_log: chairperson reads own dept; users append rows about themselves;
-- admin reads, appends and deletes. Nobody updates (privilege + trigger).
create policy atlas_audit_chair_read on public.audit_log for select to authenticated
  using (public.current_role() = 'chairperson' and dept = public.current_dept());
-- S4: a signed-in user may only append the client-origin actions below, about themselves, in their own department.
-- Every server action (login, runs, rooms, approve...) is written by the server with the service client.
drop policy if exists atlas_audit_insert_self on public.audit_log;
create policy atlas_audit_insert_self on public.audit_log for insert to authenticated
  with check (user_id = auth.uid() and dept is not distinct from public.current_dept()
              and action in ('faculty_added', 'faculty_edited', 'faculty_deleted', 'solver_settings_changed'));
create policy atlas_audit_admin_read on public.audit_log for select to authenticated
  using (public.current_role() = 'admin');
create policy atlas_audit_admin_insert on public.audit_log for insert to authenticated
  with check (public.current_role() = 'admin');
create policy atlas_audit_admin_delete on public.audit_log for delete to authenticated
  using (public.current_role() = 'admin');