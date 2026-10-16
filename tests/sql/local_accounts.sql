-- ATLAS PSU - tests/sql/local_accounts.sql   (local test database only, run after db/seed.sql)
-- The four test accounts db/rls_tests.sql expects, with their profiles.
insert into auth.users(email) values
  ('chairit@psu.palawan.edu.ph'), ('chaircs@psu.palawan.edu.ph'),
  ('profmaricar@psu.palawan.edu.ph'), ('adminatlas@psu.palawan.edu.ph')
on conflict (email) do nothing;
insert into public.profiles(id, email, full_name, role, dept, faculty_id)
select u.id, u.email, v.full_name, v.role, v.dept,
       (select f.id from public.faculty f where f.dept = 'IT' and f.name = 'Prof. Maricar Dela Cruz' and v.role = 'faculty')
  from auth.users u join (values
    ('chairit@psu.palawan.edu.ph','IT Chair','chairperson','IT'),
    ('chaircs@psu.palawan.edu.ph','CS Chair','chairperson','CS'),
    ('profmaricar@psu.palawan.edu.ph','Prof Maricar','faculty','IT'),
    ('adminatlas@psu.palawan.edu.ph','Admin','admin',null)) as v(email, full_name, role, dept) on v.email = u.email
on conflict (id) do nothing;