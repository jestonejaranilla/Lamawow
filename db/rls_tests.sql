-- ATLAS PSU - db/rls_tests.sql
-- Proves the RLS rules. Run in the Supabase SQL editor (as postgres) AFTER schema.sql, seed.sql,
-- creating the test accounts and inserting their profiles (see db/README.md).
-- Everything runs in one transaction that ends with ROLLBACK, so no data is kept.
-- Any failed check raises an exception and stops the script. Success prints "PASS ..." notices
-- and ends with "ALL RLS TESTS PASSED". Optional admin tests run only if adminatlas@... exists.
-- Part 15b: also proves that approved runs are frozen for chairpersons (trg_runs_guard) and open to admin.

begin;

-- ---------------------------------------------------------------- setup (as postgres)
select set_config('t.it_chair', (select id::text from public.profiles where email = 'chairit@psu.palawan.edu.ph'), true);
select set_config('t.cs_chair', (select id::text from public.profiles where email = 'chaircs@psu.palawan.edu.ph'), true);
select set_config('t.prof',     (select id::text from public.profiles where email = 'profmaricar@psu.palawan.edu.ph'), true);
select set_config('t.admin',    coalesce((select id::text from public.profiles where email = 'adminatlas@psu.palawan.edu.ph'), ''), true);
select set_config('t.maricar',  (select id::text from public.faculty where dept = 'IT' and name = 'Prof. Maricar Dela Cruz'), true);
select set_config('t.jericho',  (select id::text from public.faculty where dept = 'IT' and name = 'Prof. Jericho Manalastas'), true);
select set_config('t.cs_fac',   (select id::text from public.faculty where dept = 'CS' and name = 'Prof. Teresita Alcantara'), true);

do $$ begin
  if current_setting('t.it_chair') = '' or current_setting('t.cs_chair') = '' or current_setting('t.prof') = ''
     or current_setting('t.maricar') = '' then
    raise exception 'SETUP: create the test accounts and profiles from db/README.md first, and run seed.sql';
  end if;
  if (select faculty_id from public.profiles where id = current_setting('t.prof')::uuid)
       is distinct from current_setting('t.maricar')::uuid then
    raise exception 'SETUP: profmaricar profile must be linked to Prof. Maricar Dela Cruz (IT)';
  end if;
end $$;

-- test rows use academic year 2099-2100 and label 'rls-test ...' so they never clash with real data
insert into public.schedule_runs(dept, academic_year, semester, label, status) values
  ('IT','2099-2100','1st Semester','rls-test IT approved','approved'),
  ('IT','2099-2100','1st Semester','rls-test IT draft','draft'),
  ('CS','2099-2100','1st Semester','rls-test CS approved','approved'),
  ('CS','2099-2100','1st Semester','rls-test CS draft','draft');
insert into public.faculty_preferences(faculty_id, preferred_period) values
  (current_setting('t.maricar')::uuid, 'morning'),
  (current_setting('t.jericho')::uuid, 'afternoon'),
  (current_setting('t.cs_fac')::uuid,  'evening');
insert into public.faculty_leave(faculty_id, start_date, end_date) values
  (current_setting('t.jericho')::uuid, '2099-01-05', '2099-01-05'),
  (current_setting('t.cs_fac')::uuid,  '2099-01-06', '2099-01-06');
insert into public.audit_log(dept, action, entity) values
  ('IT','rls_test','test'), ('CS','rls_test','test');

-- helper: become a signed-in user (JWT claims + authenticated role) until RESET ROLE
create or replace function pg_temp.act_as(uid text) returns void language plpgsql as $$
begin
  perform set_config('request.jwt.claims',
    json_build_object('sub', uid, 'role', 'authenticated')::text, true);
  execute 'set local role authenticated';
end $$;

-- =============================================================== IT chairperson
do $$
declare n int;
begin
  perform pg_temp.act_as(current_setting('t.it_chair'));

  -- READ: only IT rows
  select count(*) into n from public.faculty where dept <> 'IT';
  if n <> 0 then raise exception 'FAIL: IT chair can read % non-IT faculty rows', n; end if;
  select count(*) into n from public.faculty where dept = 'IT';
  if n < 10 then raise exception 'FAIL: IT chair should see the 10 IT faculty, sees %', n; end if;
  select count(*) into n from public.faculty_preferences where faculty_id = current_setting('t.cs_fac')::uuid;
  if n <> 0 then raise exception 'FAIL: IT chair can read CS preferences'; end if;
  select count(*) into n from public.faculty_leave where faculty_id = current_setting('t.cs_fac')::uuid;
  if n <> 0 then raise exception 'FAIL: IT chair can read CS leave'; end if;
  select count(*) into n from public.class_sizes where dept <> 'IT';
  if n <> 0 then raise exception 'FAIL: IT chair can read other dept class_sizes'; end if;
  select count(*) into n from public.rooms where dept <> 'IT';
  if n <> 0 then raise exception 'FAIL: IT chair can read other dept rooms'; end if;
  select count(*) into n from public.dept_settings where dept <> 'IT';
  if n <> 0 then raise exception 'FAIL: IT chair can read other dept settings'; end if;
  select count(*) into n from public.schedule_runs where dept = 'CS' and label like 'rls-test%';
  if n <> 0 then raise exception 'FAIL: IT chair can read CS runs'; end if;
  select count(*) into n from public.schedule_runs where dept = 'IT' and label like 'rls-test%';
  if n <> 2 then raise exception 'FAIL: IT chair should see both IT runs (approved + draft), sees %', n; end if;
  select count(*) into n from public.audit_log where dept = 'CS';
  if n <> 0 then raise exception 'FAIL: IT chair can read CS audit log'; end if;
  select count(*) into n from public.audit_log where dept = 'IT' and action = 'rls_test';
  if n <> 1 then raise exception 'FAIL: IT chair should read the IT audit row'; end if;
  select count(*) into n from public.profiles;
  if n <> 1 then raise exception 'FAIL: a user must see only their own profile, sees %', n; end if;
  raise notice 'PASS IT chair reads only IT rows';

  -- WRITE: nothing in CS
  update public.faculty set max_units = 99 where dept = 'CS';
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: IT chair updated % CS faculty rows', n; end if;
  delete from public.rooms where dept = 'CS';
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: IT chair deleted % CS rooms', n; end if;
  update public.schedule_runs set label = 'hacked' where dept = 'CS';
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: IT chair updated CS runs'; end if;
  update public.faculty_preferences set preferred_period = 'morning'
    where faculty_id = current_setting('t.cs_fac')::uuid;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: IT chair updated CS preferences'; end if;

  begin
    insert into public.rooms(dept, name, kind, recommended, max) values ('CS','HACK 1','lecture',10,20);
    raise exception 'FAIL: IT chair inserted a CS room';
  exception when insufficient_privilege then null; end;
  begin
    insert into public.schedule_runs(dept, academic_year, semester) values ('CS','2099-2100','1st Semester');
    raise exception 'FAIL: IT chair inserted a CS run';
  exception when insufficient_privilege then null; end;
  begin
    update public.faculty set dept = 'CS' where dept = 'IT' and name = 'Prof. Noel Evangelista';
    raise exception 'FAIL: IT chair moved an IT professor into CS';
  exception when insufficient_privilege then null; end;
  begin
    insert into public.audit_log(user_id, dept, action) values (current_setting('t.it_chair')::uuid, 'CS', 'forged');
    raise exception 'FAIL: IT chair wrote an audit row for CS';
  exception when insufficient_privilege then null; end;

  -- WRITE: own dept works
  update public.faculty set max_units = 24 where dept = 'IT';
  get diagnostics n = row_count;
  if n < 10 then raise exception 'FAIL: IT chair should be able to update IT faculty'; end if;
  insert into public.rooms(dept, name, kind, recommended, max) values ('IT','RLS TEST ROOM','lecture',30,40);
  raise notice 'PASS IT chair cannot read or write CS rows, can write IT rows';

  -- profile columns are locked
  begin
    update public.profiles set role = 'admin' where id = auth.uid();
    raise exception 'FAIL: chair changed own role';
  exception when insufficient_privilege then null; end;
  begin
    update public.profiles set dept = 'CS' where id = auth.uid();
    raise exception 'FAIL: chair changed own dept';
  exception when insufficient_privilege then null; end;
  update public.profiles set full_name = full_name where id = auth.uid();
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: chair should still be able to update own full_name'; end if;
  raise notice 'PASS profile role/dept are locked';

  -- audit log is read-only for the chair
  begin
    update public.audit_log set action = 'edited' where dept = 'IT';
    raise exception 'FAIL: chair edited the audit log';
  exception when insufficient_privilege then null; end;
  delete from public.audit_log where dept = 'IT';
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: chair deleted % audit rows', n; end if;
  insert into public.audit_log(user_id, dept, action) values (current_setting('t.it_chair')::uuid, 'IT', 'own_row');
  begin
    insert into public.audit_log(user_id, dept, action, meta)
      values (current_setting('t.it_chair')::uuid, 'IT', 'x', '{"email":"a@b.c"}');
    raise exception 'FAIL: audit meta with personal data was accepted';
  exception when raise_exception then
    if sqlerrm like 'FAIL%' then raise; end if;
  end;
  raise notice 'PASS chair appends own audit rows, cannot edit or delete them, meta is guarded';

  reset role;
end $$;

-- ============================================================ faculty (Maricar, IT)
do $$
declare n int;
begin
  perform pg_temp.act_as(current_setting('t.prof'));

  select count(*) into n from public.faculty where dept = 'IT';
  if n < 10 then raise exception 'FAIL: faculty should read IT faculty, sees %', n; end if;
  select count(*) into n from public.faculty where dept <> 'IT';
  if n <> 0 then raise exception 'FAIL: faculty can read other dept faculty'; end if;

  -- schedule runs: only the approved run of own dept
  select count(*) into n from public.schedule_runs where label = 'rls-test IT approved';
  if n <> 1 then raise exception 'FAIL: faculty should see the approved IT run'; end if;
  select count(*) into n from public.schedule_runs where label in ('rls-test IT draft','rls-test CS approved','rls-test CS draft');
  if n <> 0 then raise exception 'FAIL: faculty can see draft or other-dept runs'; end if;

  -- nothing else readable
  select count(*) into n from public.rooms;
  if n <> 0 then raise exception 'FAIL: faculty can read rooms'; end if;
  select count(*) into n from public.class_sizes;
  if n <> 0 then raise exception 'FAIL: faculty can read class_sizes'; end if;
  select count(*) into n from public.audit_log;
  if n <> 0 then raise exception 'FAIL: faculty can read the audit log'; end if;
  raise notice 'PASS faculty reads IT faculty and the approved IT run only';

  -- own preferences: allowed
  update public.faculty_preferences set preferred_period = 'afternoon'
    where faculty_id = current_setting('t.maricar')::uuid;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: faculty cannot edit own preferences'; end if;

  -- another professor (same dept): not readable, not writable
  select count(*) into n from public.faculty_preferences where faculty_id = current_setting('t.jericho')::uuid;
  if n <> 0 then raise exception 'FAIL: faculty can read a colleague''s preferences'; end if;
  update public.faculty_preferences set preferred_period = 'evening'
    where faculty_id = current_setting('t.jericho')::uuid;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: faculty edited another professor''s preferences'; end if;
  begin
    insert into public.faculty_preferences(faculty_id) values (current_setting('t.cs_fac')::uuid);
    raise exception 'FAIL: faculty inserted preferences for someone else';
  exception when insufficient_privilege then null; end;

  -- leave: own works, others do not
  insert into public.faculty_leave(faculty_id, start_date, end_date)
    values (current_setting('t.maricar')::uuid, '2099-02-02', '2099-02-02');
  begin
    insert into public.faculty_leave(faculty_id, start_date, end_date)
      values (current_setting('t.jericho')::uuid, '2099-02-03', '2099-02-03');
    raise exception 'FAIL: faculty inserted leave for another professor';
  exception when insufficient_privilege then null; end;
  update public.faculty_leave set end_date = '2099-01-09' where faculty_id = current_setting('t.jericho')::uuid;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: faculty edited another professor''s leave'; end if;
  delete from public.faculty_leave where faculty_id = current_setting('t.jericho')::uuid;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: faculty deleted another professor''s leave'; end if;
  raise notice 'PASS faculty edits only own preferences and leave';

  -- faculty table and runs are read-only for faculty
  update public.faculty set max_units = 99 where id = current_setting('t.maricar')::uuid;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: faculty updated the faculty table'; end if;
  update public.schedule_runs set label = 'hacked' where dept = 'IT';
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'FAIL: faculty updated schedule runs'; end if;
  begin
    update public.profiles set role = 'admin' where id = auth.uid();
    raise exception 'FAIL: faculty changed own role';
  exception when insufficient_privilege then null; end;
  begin
    perform public.approve_run((select id from public.schedule_runs where label = 'rls-test IT approved'));
    raise exception 'FAIL: faculty called approve_run';
  exception when insufficient_privilege then null; end;
  begin
    perform public.purge_audit_log(interval '1 day');
    raise exception 'FAIL: faculty called purge_audit_log';
  exception when insufficient_privilege then null; end;
  raise notice 'PASS faculty is read-only elsewhere, cannot approve or purge';

  reset role;
end $$;

-- ===================================================== approve_run (IT chairperson)
do $$
declare n int; draft_id uuid; cs_id uuid;
begin
  select id into draft_id from public.schedule_runs where label = 'rls-test IT draft';
  select id into cs_id    from public.schedule_runs where label = 'rls-test CS draft';
  perform pg_temp.act_as(current_setting('t.it_chair'));

  begin
    perform public.approve_run(cs_id);
    raise exception 'FAIL: IT chair approved a CS run';
  exception when insufficient_privilege then null; end;

  perform public.approve_run(draft_id);
  reset role;

  select count(*) into n from public.schedule_runs
   where dept = 'IT' and academic_year = '2099-2100' and status = 'approved';
  if n <> 1 then raise exception 'FAIL: expected exactly one approved IT run, found %', n; end if;
  if (select status from public.schedule_runs where id = draft_id) <> 'approved' then
    raise exception 'FAIL: new run was not approved'; end if;
  if (select status from public.schedule_runs where label = 'rls-test IT approved') <> 'saved' then
    raise exception 'FAIL: previous approved run was not moved to saved'; end if;
  if (select status from public.schedule_runs where id = cs_id) <> 'draft' then
    raise exception 'FAIL: CS run changed'; end if;
  raise notice 'PASS approve_run swaps the approved run in one step, own dept only';
end $$;

-- ===================================================== Part 15b: approved runs are frozen (IT chairperson)
-- State here: 'rls-test IT draft' is approved, 'rls-test IT approved' was moved to saved by approve_run above.
do $$
declare
  n int; ap_id uuid; old_id uuid; new_id uuid; col text;
begin
  reset role;
  perform set_config('request.jwt.claims', '', true);
  select id into ap_id  from public.schedule_runs where label = 'rls-test IT draft'    and status = 'approved';
  select id into old_id from public.schedule_runs where label = 'rls-test IT approved' and status = 'saved';
  if ap_id is null or old_id is null then raise exception 'FAIL: setup for the approved-run tests is missing'; end if;

  perform pg_temp.act_as(current_setting('t.it_chair'));

  -- a. an approved run cannot be deleted
  begin
    delete from public.schedule_runs where id = ap_id;
    raise exception 'FAIL: chair deleted an approved run';
  exception when insufficient_privilege then
    if sqlerrm not like '%approved run cannot be deleted%' then
      raise exception 'FAIL: delete was refused for the wrong reason: %', sqlerrm; end if;
  end;

  -- b. its content columns cannot be edited
  foreach col in array array['result','analytics','metrics','coverage','solver_settings'] loop
    begin
      execute format('update public.schedule_runs set %I = %L::jsonb where id = %L', col, '{"hacked":true}', ap_id);
      raise exception 'FAIL: chair edited % of an approved run', col;
    exception when insufficient_privilege then
      if sqlerrm not like '%approved run cannot be edited%' then
        raise exception 'FAIL: edit of % was refused for the wrong reason: %', col, sqlerrm; end if;
    end;
  end loop;
  foreach col in array array['dept','academic_year','semester'] loop
    begin
      execute format('update public.schedule_runs set %I = %L where id = %L', col,
                     case col when 'dept' then 'CS' when 'academic_year' then '2100-2101' else '2nd Semester' end, ap_id);
      raise exception 'FAIL: chair edited % of an approved run', col;
    exception when insufficient_privilege then
      if sqlerrm not like '%approved run cannot be edited%' then
        raise exception 'FAIL: edit of % was refused for the wrong reason: %', col, sqlerrm; end if;
    end;
  end loop;
  begin
    update public.schedule_runs set created_by = current_setting('t.cs_chair')::uuid where id = ap_id;
    raise exception 'FAIL: chair edited created_by of an approved run';
  exception when insufficient_privilege then
    if sqlerrm not like '%approved run cannot be edited%' then
      raise exception 'FAIL: created_by edit was refused for the wrong reason: %', sqlerrm; end if;
  end;
  raise notice 'PASS an approved run cannot be deleted or edited by its chairperson';

  -- c. status approved only through approve_run()
  begin
    update public.schedule_runs set status = 'approved' where id = old_id;
    raise exception 'FAIL: chair set status approved with a direct update';
  exception when insufficient_privilege then
    if sqlerrm not like '%approve_run()%' then
      raise exception 'FAIL: direct approve was refused for the wrong reason: %', sqlerrm; end if;
  end;
  begin
    insert into public.schedule_runs(dept, academic_year, semester, status)
      values ('IT', '2099-2100', '2nd Semester', 'approved');
    raise exception 'FAIL: chair inserted an approved run';
  exception when insufficient_privilege then
    if sqlerrm not like '%approve_run()%' then
      raise exception 'FAIL: insert as approved was refused for the wrong reason: %', sqlerrm; end if;
  end;
  raise notice 'PASS status approved can only be set by approve_run()';

  -- the chairperson can still save, load, edit and delete draft and saved runs of the own department
  insert into public.schedule_runs(dept, academic_year, semester, label)
    values ('IT', '2099-2100', '1st Semester', 'rls-test chair draft') returning id into new_id;
  update public.schedule_runs set status = 'saved', label = 'rls-test chair saved' where id = new_id;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: chair could not save a draft'; end if;
  update public.schedule_runs set result = '[]'::jsonb where id = new_id;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: chair could not edit a saved run'; end if;
  select count(*) into n from public.schedule_runs where id = new_id and status = 'saved';
  if n <> 1 then raise exception 'FAIL: chair could not load the saved run'; end if;
  delete from public.schedule_runs where id = new_id;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: chair could not delete a saved run'; end if;
  raise notice 'PASS chair still saves, loads, edits and deletes draft and saved runs';

  -- approve_run still works: approve the earlier run again, the current approved one becomes saved
  perform public.approve_run(old_id);
  reset role;
  perform set_config('request.jwt.claims', '', true);
  select count(*) into n from public.schedule_runs
   where dept = 'IT' and academic_year = '2099-2100' and semester = '1st Semester' and status = 'approved';
  if n <> 1 then raise exception 'FAIL: expected exactly one approved IT run, found %', n; end if;
  if (select status from public.schedule_runs where id = old_id) <> 'approved' then
    raise exception 'FAIL: approve_run did not approve the run'; end if;
  if (select status from public.schedule_runs where id = ap_id) <> 'saved' then
    raise exception 'FAIL: the previous approved run did not become saved'; end if;
  select count(*) into n from public.audit_log where action = 'approve_run' and entity_id = old_id::text;
  if n <> 1 then raise exception 'FAIL: approve_run wrote % audit rows, expected 1', n; end if;
  raise notice 'PASS approve_run still works and the previous approved run becomes saved';

  -- the approving switch is off again after approve_run, so a direct update is still refused
  perform pg_temp.act_as(current_setting('t.it_chair'));
  begin
    update public.schedule_runs set status = 'approved' where id = ap_id;
    raise exception 'FAIL: the approving switch stayed on after approve_run';
  exception when insufficient_privilege then null; end;
  reset role;
  perform set_config('request.jwt.claims', '', true);
  raise notice 'PASS the approving switch does not leak out of approve_run';

  -- no signed-in user (service role, SQL editor): the guard does not apply
  update public.schedule_runs set result = '[]'::jsonb where id = old_id;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: the service role could not edit an approved run'; end if;
  delete from public.schedule_runs where label = 'rls-test CS approved';
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: the service role could not delete an approved run'; end if;
  raise notice 'PASS the guard does not apply to the service role';
end $$;

-- ===================================================== Part 15b: admin may fix approved runs
do $$
declare n int; run_id uuid; tmp_id uuid;
begin
  reset role;
  perform set_config('request.jwt.claims', '', true);
  if current_setting('t.admin') = '' then
    raise notice 'SKIP admin approved-run tests (no adminatlas@psu.palawan.edu.ph profile)';
    return;
  end if;
  select id into run_id from public.schedule_runs
   where dept = 'IT' and academic_year = '2099-2100' and semester = '1st Semester' and status = 'approved';
  if run_id is null then raise exception 'FAIL: setup for the admin approved-run tests is missing'; end if;

  perform pg_temp.act_as(current_setting('t.admin'));
  update public.schedule_runs set result = '[]'::jsonb, metrics = '{"fixed":true}'::jsonb where id = run_id;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: admin could not edit an approved run'; end if;
  update public.schedule_runs set status = 'saved' where id = run_id;
  update public.schedule_runs set status = 'approved' where id = run_id;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: admin could not change the status of an approved run'; end if;
  insert into public.schedule_runs(dept, academic_year, semester, label, status)
    values ('CS', '2099-2100', '1st Semester', 'rls-test admin approved', 'approved') returning id into tmp_id;
  delete from public.schedule_runs where id = tmp_id;
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'FAIL: admin could not delete an approved run'; end if;
  reset role;
  perform set_config('request.jwt.claims', '', true);
  raise notice 'PASS admin can edit, re-approve and delete approved runs';
end $$;

-- ===================================================== purge_audit_log + anon
do $$
declare n bigint; admin_id text := current_setting('t.admin');
begin
  perform pg_temp.act_as(current_setting('t.it_chair'));
  begin
    perform public.purge_audit_log(interval '1 day');
    raise exception 'FAIL: chair called purge_audit_log';
  exception when insufficient_privilege then null; end;
  reset role;

  if admin_id = '' then
    raise notice 'SKIP admin tests (no adminatlas@psu.palawan.edu.ph profile)';
  else
    insert into public.audit_log(at, dept, action) values (now() - interval '400 days', 'IT', 'rls_test_old');
    perform pg_temp.act_as(admin_id);
    select count(*) into n from public.audit_log where dept = 'CS';
    if n < 1 then raise exception 'FAIL: admin should read every dept audit log'; end if;
    n := public.purge_audit_log(interval '365 days');
    if n < 1 then raise exception 'FAIL: admin purge deleted nothing'; end if;
    if exists (select 1 from public.audit_log where action = 'rls_test_old') then
      raise exception 'FAIL: old audit row survived the purge'; end if;
    if not exists (select 1 from public.audit_log where action = 'rls_test') then
      raise exception 'FAIL: recent audit rows were purged'; end if;
    reset role;
    raise notice 'PASS admin purges old audit rows only';
  end if;

  -- signed-out (anon) role gets nothing
  execute 'set local role anon';
  begin
    perform 1 from public.faculty limit 1;
    raise exception 'FAIL: anon can read faculty';
  exception when insufficient_privilege then null; end;
  reset role;
  raise notice 'PASS anon has no access';
end $$;

do $$ begin raise notice 'ALL RLS TESTS PASSED'; end $$;

rollback;

-- Only reached when every check above passed (a failed check stops the script with an error).
-- The SQL editor shows only the last result grid, so this row is the visible proof.
select 'ALL RLS TESTS PASSED' as result;