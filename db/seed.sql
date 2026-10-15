-- ATLAS PSU - db/seed.sql
-- Re-runnable (ON CONFLICT DO NOTHING). Run after db/schema.sql.
-- Names are fictional pseudonyms. Specializations, rooms and class sizes come from data/curricula/<dept>.json
-- (IT and CS rooms come from config/settings.py, which the JSON marks as "default").
-- Sample data only: class sizes and room capacities in the JSON are flagged as placeholders.

begin;

insert into public.departments(code,name) values
  ('IT','Information Technology'),
  ('CS','Computer Science'),
  ('MB','Marine Biology'),
  ('ES','Environmental Science'),
  ('MedB','Medical Biology')
on conflict (code) do nothing;

-- IT faculty
insert into public.faculty(dept,name,specializations,max_units,overload_buffer,availability) values
  ('IT','Prof. Maricar Dela Cruz',array['Core Theory','Programming','Systems']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Jericho Manalastas',array['Data Management','Networks & Security','Applied Computing']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Liezl Macaraeg',array['Mathematics','Web & App Dev','Research & Capstone']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Ronaldo Pasion',array['Industry Practice','Core Theory','Programming']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Criselda Bautista',array['Systems','Data Management','Networks & Security']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Emmanuel Tolentino',array['Applied Computing','Mathematics','Web & App Dev']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Glenda Villanueva',array['Research & Capstone','Industry Practice','Core Theory']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Rodel Magsaysay',array['Programming','Systems','Data Management']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Aileen Dimaculangan',array['Networks & Security','Applied Computing','Mathematics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('IT','Prof. Noel Evangelista',array['Web & App Dev','Research & Capstone','Industry Practice']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[])
on conflict (dept,name) do nothing;

-- CS faculty
insert into public.faculty(dept,name,specializations,max_units,overload_buffer,availability) values
  ('CS','Prof. Teresita Alcantara',array['Core Theory','Programming','Systems']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Benedict Salonga',array['Data Management','Networks & Security','Applied Computing']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Marites Dizon',array['Mathematics','Web & App Dev','Research & Capstone']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Arnel Cabansag',array['Industry Practice','Environmental Science','Core Theory']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Rowena Pangilinan',array['Programming','Systems','Data Management']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Lorenzo Maglaya',array['Networks & Security','Applied Computing','Mathematics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Jocelyn Banaag',array['Web & App Dev','Research & Capstone','Industry Practice']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Dennis Hernandez',array['Environmental Science','Core Theory','Programming']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Imelda Ramirez',array['Systems','Data Management','Networks & Security']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('CS','Prof. Cesar Lacsamana',array['Applied Computing','Mathematics','Web & App Dev']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[])
on conflict (dept,name) do nothing;

-- MB faculty
insert into public.faculty(dept,name,specializations,max_units,overload_buffer,availability) values
  ('MB','Prof. Fe Almonte',array['Mathematics','Chemistry','Physics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Rogelio Cadiz',array['Biology','Marine Science','Earth Science']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Analyn Sumagaysay',array['Computing','Research & Capstone','Industry Practice']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Virgilio Catacutan',array['Mathematics','Chemistry','Physics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Josefina Abella',array['Biology','Marine Science','Earth Science']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Nestor Quijano',array['Computing','Research & Capstone','Industry Practice']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Lourdes Peralta',array['Mathematics','Chemistry','Physics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Efren Maniego',array['Biology','Marine Science','Earth Science']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Corazon Dacanay',array['Computing','Research & Capstone','Industry Practice']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MB','Prof. Wilfredo Gatchalian',array['Mathematics','Chemistry','Physics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[])
on conflict (dept,name) do nothing;

-- ES faculty
insert into public.faculty(dept,name,specializations,max_units,overload_buffer,availability) values
  ('ES','Prof. Gemma Ocampo',array['Mathematics','Chemistry','Physics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Alfredo Llamas',array['Biology','Earth Science','Environmental Science']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Rosalinda Tagle',array['Research & Capstone','Industry Practice','Mathematics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Mario Escudero',array['Chemistry','Physics','Biology']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Divina Arguelles',array['Earth Science','Environmental Science','Research & Capstone']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Danilo Sarmiento',array['Industry Practice','Mathematics','Chemistry']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Perla Montemayor',array['Physics','Biology','Earth Science']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Ernesto Balagtas',array['Environmental Science','Research & Capstone','Industry Practice']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Luzviminda Cuevas',array['Mathematics','Chemistry','Physics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('ES','Prof. Honorio Basilio',array['Biology','Earth Science','Environmental Science']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[])
on conflict (dept,name) do nothing;

-- MedB faculty
insert into public.faculty(dept,name,specializations,max_units,overload_buffer,availability) values
  ('MedB','Prof. Salvacion Aquino',array['Mathematics','Chemistry','Physics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Reynaldo Pineda',array['Biology','Environmental Science','Computing']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Natividad Soriano',array['Research & Capstone','Industry Practice','Mathematics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Armando Lazaro',array['Chemistry','Physics','Biology']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Milagros Estrada',array['Environmental Science','Computing','Research & Capstone']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Teodoro Valdez',array['Industry Practice','Mathematics','Chemistry']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Estrella Navarro',array['Physics','Biology','Environmental Science']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Bonifacio Mercado',array['Computing','Research & Capstone','Industry Practice']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Concepcion Ilagan',array['Mathematics','Chemistry','Physics']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[]),
  ('MedB','Prof. Fidel Rosales',array['Biology','Environmental Science','Computing']::text[],24,6,array['Mon','Tue','Wed','Thu']::text[])
on conflict (dept,name) do nothing;

-- IT rooms
insert into public.rooms(dept,name,kind,recommended,max) values
  ('IT','CL1','lecture',35,52),
  ('IT','CL2','lecture',35,52),
  ('IT','CL3','lecture',35,52),
  ('IT','IT Room 1','lecture',45,60),
  ('IT','IT Room 2','lecture',45,60),
  ('IT','IT Room 3','lecture',45,60),
  ('IT','GA Bldg 16','lecture',40,55),
  ('IT','GA Bldg 17','lecture',40,55),
  ('IT','GA Bldg 18','lecture',40,55),
  ('IT','GA Bldg 19','lecture',40,55),
  ('IT','GA Bldg 20','lecture',40,55),
  ('IT','GA Bldg 21','lecture',40,55),
  ('IT','GA Bldg 22','lecture',40,55),
  ('IT','GA Bldg 23','lecture',40,55),
  ('IT','GA Bldg 24','lecture',40,55),
  ('IT','GA Bldg 25','lecture',40,55),
  ('IT','MTC1','lab',32,45),
  ('IT','MTC2','lab',32,45),
  ('IT','IT101','lab',30,40),
  ('IT','NIT1','lab',40,45),
  ('IT','NIT3','lab',40,45)
on conflict (dept,name) do nothing;

-- CS rooms
insert into public.rooms(dept,name,kind,recommended,max) values
  ('CS','CL1','lecture',35,52),
  ('CS','CL2','lecture',35,52),
  ('CS','CL3','lecture',35,52),
  ('CS','IT Room 1','lecture',45,60),
  ('CS','IT Room 2','lecture',45,60),
  ('CS','IT Room 3','lecture',45,60),
  ('CS','GA Bldg 16','lecture',40,55),
  ('CS','GA Bldg 17','lecture',40,55),
  ('CS','GA Bldg 18','lecture',40,55),
  ('CS','GA Bldg 19','lecture',40,55),
  ('CS','GA Bldg 20','lecture',40,55),
  ('CS','GA Bldg 21','lecture',40,55),
  ('CS','GA Bldg 22','lecture',40,55),
  ('CS','GA Bldg 23','lecture',40,55),
  ('CS','GA Bldg 24','lecture',40,55),
  ('CS','GA Bldg 25','lecture',40,55),
  ('CS','MTC1','lab',32,45),
  ('CS','MTC2','lab',32,45),
  ('CS','IT101','lab',30,40),
  ('CS','NIT1','lab',40,45),
  ('CS','NIT3','lab',40,45)
on conflict (dept,name) do nothing;

-- MB rooms
insert into public.rooms(dept,name,kind,recommended,max) values
  ('MB','CSLR 1','lecture',48,60),
  ('MB','CSLR 2','lecture',48,60),
  ('MB','CSLR 3','lecture',48,60),
  ('MB','CSLR 4','lecture',48,60),
  ('MB','CSLR 5','lecture',48,60),
  ('MB','CSLR 6','lecture',48,60),
  ('MB','CSLR 7','lecture',48,60),
  ('MB','CSLR 8','lecture',48,60),
  ('MB','CSLR 9','lecture',48,60),
  ('MB','CSLR 10','lecture',48,60),
  ('MB','GE Bldg 1','lecture',48,60),
  ('MB','GE Bldg 2','lecture',48,60),
  ('MB','GE Bldg 3','lecture',48,60),
  ('MB','GE Bldg 4','lecture',48,60),
  ('MB','GE Bldg 5','lecture',48,60),
  ('MB','GE Bldg 6','lecture',48,60),
  ('MB','GE Bldg 7','lecture',48,60),
  ('MB','GE Bldg 8','lecture',48,60),
  ('MB','GE Bldg 9','lecture',48,60),
  ('MB','GE Bldg 10','lecture',48,60),
  ('MB','Physics Room 1','lab',48,60),
  ('MB','Physics Room 2','lab',48,60),
  ('MB','Physics Room 3','lab',48,60),
  ('MB','Physics Room 4','lab',48,60),
  ('MB','Physics Room 5','lab',48,60)
on conflict (dept,name) do nothing;

-- ES rooms
insert into public.rooms(dept,name,kind,recommended,max) values
  ('ES','CSLR 1','lecture',48,60),
  ('ES','CSLR 2','lecture',48,60),
  ('ES','CSLR 3','lecture',48,60),
  ('ES','CSLR 4','lecture',48,60),
  ('ES','CSLR 5','lecture',48,60),
  ('ES','CSLR 6','lecture',48,60),
  ('ES','CSLR 7','lecture',48,60),
  ('ES','CSLR 8','lecture',48,60),
  ('ES','CSLR 9','lecture',48,60),
  ('ES','CSLR 10','lecture',48,60),
  ('ES','GE Bldg 1','lecture',48,60),
  ('ES','GE Bldg 2','lecture',48,60),
  ('ES','GE Bldg 3','lecture',48,60),
  ('ES','GE Bldg 4','lecture',48,60),
  ('ES','GE Bldg 5','lecture',48,60),
  ('ES','GE Bldg 6','lecture',48,60),
  ('ES','GE Bldg 7','lecture',48,60),
  ('ES','GE Bldg 8','lecture',48,60),
  ('ES','GE Bldg 9','lecture',48,60),
  ('ES','GE Bldg 10','lecture',48,60),
  ('ES','Physics Room 1','lab',48,60),
  ('ES','Physics Room 2','lab',48,60),
  ('ES','Physics Room 3','lab',48,60),
  ('ES','Physics Room 4','lab',48,60),
  ('ES','Physics Room 5','lab',48,60)
on conflict (dept,name) do nothing;

-- MedB rooms
insert into public.rooms(dept,name,kind,recommended,max) values
  ('MedB','CSLR 1','lecture',48,60),
  ('MedB','CSLR 2','lecture',48,60),
  ('MedB','CSLR 3','lecture',48,60),
  ('MedB','CSLR 4','lecture',48,60),
  ('MedB','CSLR 5','lecture',48,60),
  ('MedB','CSLR 6','lecture',48,60),
  ('MedB','CSLR 7','lecture',48,60),
  ('MedB','CSLR 8','lecture',48,60),
  ('MedB','CSLR 9','lecture',48,60),
  ('MedB','CSLR 10','lecture',48,60),
  ('MedB','GE Bldg 1','lecture',48,60),
  ('MedB','GE Bldg 2','lecture',48,60),
  ('MedB','GE Bldg 3','lecture',48,60),
  ('MedB','GE Bldg 4','lecture',48,60),
  ('MedB','GE Bldg 5','lecture',48,60),
  ('MedB','GE Bldg 6','lecture',48,60),
  ('MedB','GE Bldg 7','lecture',48,60),
  ('MedB','GE Bldg 8','lecture',48,60),
  ('MedB','GE Bldg 9','lecture',48,60),
  ('MedB','GE Bldg 10','lecture',48,60),
  ('MedB','Physics Room 1','lab',48,60),
  ('MedB','Physics Room 2','lab',48,60),
  ('MedB','Physics Room 3','lab',48,60),
  ('MedB','Physics Room 4','lab',48,60),
  ('MedB','Physics Room 5','lab',48,60)
on conflict (dept,name) do nothing;

-- IT class sizes
insert into public.class_sizes(dept,block_key,year,size) values
  ('IT','IT1B1',1,38),
  ('IT','IT1B2',1,46),
  ('IT','IT2B1',2,45),
  ('IT','IT2B2',2,43),
  ('IT','IT3B1',3,41),
  ('IT','IT3B2',3,46),
  ('IT','IT4B1',4,44)
on conflict (dept,block_key) do nothing;

-- CS class sizes
insert into public.class_sizes(dept,block_key,year,size) values
  ('CS','CS1B1',1,38),
  ('CS','CS2B1',2,42),
  ('CS','CS2B2',2,48),
  ('CS','CS2B3',2,40),
  ('CS','CS3B1',3,42),
  ('CS','CS3B2',3,40),
  ('CS','CS4B1',4,47)
on conflict (dept,block_key) do nothing;

-- MB class sizes
insert into public.class_sizes(dept,block_key,year,size) values
  ('MB','MB1B1',1,47),
  ('MB','MB1B2',1,41),
  ('MB','MB2B1',2,44),
  ('MB','MB2B2',2,48),
  ('MB','MB2B3',2,46),
  ('MB','MB3B1',3,42),
  ('MB','MB3B2',3,41),
  ('MB','MB4B1',4,48),
  ('MB','MB4B2',4,42)
on conflict (dept,block_key) do nothing;

-- ES class sizes
insert into public.class_sizes(dept,block_key,year,size) values
  ('ES','ES1B1',1,37),
  ('ES','ES1B2',1,47),
  ('ES','ES2B1',2,37),
  ('ES','ES3B1',3,36),
  ('ES','ES4B1',4,36),
  ('ES','ES4B2',4,41)
on conflict (dept,block_key) do nothing;

-- MedB class sizes
insert into public.class_sizes(dept,block_key,year,size) values
  ('MedB','MedB1B1',1,37),
  ('MedB','MedB2B1',2,42),
  ('MedB','MedB2B2',2,37),
  ('MedB','MedB3B1',3,38),
  ('MedB','MedB4B1',4,47),
  ('MedB','MedB4B2',4,48)
on conflict (dept,block_key) do nothing;

-- active period + solver defaults (same defaults as assets/js/solver-settings.js)
insert into public.dept_settings(dept,academic_year,semester,solver,lab_also_lecture) values
  ('IT','2026-2027','1st Semester','{"max_units": 24, "units_per_assignment": 2, "cp_sat_time_limit": 30, "population": 50, "generations": 100, "mutation": 0.09, "crossover": 0.95}'::jsonb,false),
  ('CS','2026-2027','1st Semester','{"max_units": 24, "units_per_assignment": 2, "cp_sat_time_limit": 30, "population": 50, "generations": 100, "mutation": 0.09, "crossover": 0.95}'::jsonb,false),
  ('MB','2026-2027','1st Semester','{"max_units": 24, "units_per_assignment": 2, "cp_sat_time_limit": 30, "population": 50, "generations": 100, "mutation": 0.09, "crossover": 0.95}'::jsonb,true),
  ('ES','2026-2027','1st Semester','{"max_units": 24, "units_per_assignment": 2, "cp_sat_time_limit": 30, "population": 50, "generations": 100, "mutation": 0.09, "crossover": 0.95}'::jsonb,true),
  ('MedB','2026-2027','1st Semester','{"max_units": 24, "units_per_assignment": 2, "cp_sat_time_limit": 30, "population": 50, "generations": 100, "mutation": 0.09, "crossover": 0.95}'::jsonb,true)
on conflict (dept) do nothing;

commit;