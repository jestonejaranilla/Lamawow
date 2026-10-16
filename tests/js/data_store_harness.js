/* Runs assets/js/data-store.js against an in-memory fake Supabase that applies the same department rules as the
   RLS policies (a chairperson sees only their department, a faculty member only their own rows and the approved run).
   Prints one line per check and a final "ALL OK" or exits 1. Used by tests/test_part16.py. */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '../../assets/js/data-store.js'), 'utf8');
let failures = 0;
function check(name, ok, extra) {
  console.log((ok ? 'ok   ' : 'FAIL ') + name + (ok || !extra ? '' : '  ' + extra));
  if (!ok) failures++;
}

/* ---------------------------------------------------------------- fake database */
let seq = 0;
const uid = () => 'id-' + (++seq);

function makeDb() {
  const db = { t: {}, offline: false, failInsert: {}, calls: [] };
  ['faculty', 'faculty_preferences', 'faculty_leave', 'class_sizes', 'rooms', 'dept_settings', 'schedule_runs'].forEach(n => { db.t[n] = []; });
  return db;
}

const UNIQUE = { faculty: ['dept', 'name'], class_sizes: ['dept', 'block_key'], rooms: ['dept', 'name'], dept_settings: ['dept'], faculty_preferences: ['faculty_id'] };

function deptOfFaculty(db, id) { const f = db.t.faculty.find(r => r.id === id); return f && f.dept; }

/* The RLS rules: may this profile see/change this row? */
function allowed(db, p, table, row, write) {
  if (p.role === 'chairperson') {
    if (table === 'faculty_preferences' || table === 'faculty_leave') return deptOfFaculty(db, row.faculty_id) === p.dept;
    return row.dept === p.dept;
  }
  if (table === 'faculty') return !write && row.dept === p.dept;
  if (table === 'faculty_preferences' || table === 'faculty_leave') return row.faculty_id === p.faculty_id;
  if (table === 'schedule_runs') return !write && row.dept === p.dept && row.status === 'approved';
  return false;
}

function builder(db, p, table) {
  let op = 'select', filters = [], payload = null, order = null, lim = null, head = false, wantCount = false, conflict = null, mode = 'many';
  const b = {
    select(_c, o) { if (o && o.head) head = true; if (o && o.count) wantCount = true; return b; },
    eq(c, v) { filters.push(r => r[c] === v); return b; },
    in(c, vs) { filters.push(r => vs.includes(r[c])); return b; },
    order(c, o) { order = [c, !(o && o.ascending === false)]; return b; },
    limit(n) { lim = n; return b; },
    maybeSingle() { mode = 'maybe'; return b; },
    single() { mode = 'single'; return b; },
    insert(rows) { op = 'insert'; payload = rows; return b; },
    update(vals) { op = 'update'; payload = vals; return b; },
    upsert(rows, o) { op = 'upsert'; payload = rows; conflict = o && o.onConflict; return b; },
    delete() { op = 'delete'; return b; },
    then(res, rej) { return run().then(res, rej); }
  };
  async function run() {
    db.calls.push({ table, op });
    if (db.offline) throw new TypeError('Failed to fetch');
    const rows = db.t[table];
    const err = (code, message) => ({ data: null, error: { code, message } });
    const pass = r => allowed(db, p, table, r, false) && filters.every(f => f(r));
    if (op === 'select') {
      let out = rows.filter(pass).map(r => Object.assign({}, r));
      if (order) out.sort((x, y) => (x[order[0]] > y[order[0]] ? 1 : -1) * (order[1] ? 1 : -1));
      if (lim) out = out.slice(0, lim);
      if (head) return { data: null, error: null, count: out.length };
      if (mode === 'maybe') return { data: out[0] || null, error: null };
      if (mode === 'single') return out.length === 1 ? { data: out[0], error: null } : err('PGRST116', 'no row');
      return { data: out, error: null, count: wantCount ? out.length : undefined };
    }
    if (op === 'insert' || op === 'upsert') {
      if (db.failInsert[table]) return err('XX000', 'insert refused for the test');
      const list = Array.isArray(payload) ? payload : [payload];
      const out = [];
      for (const item of list) {
        const row = Object.assign({ id: uid() }, item);
        if (!allowed(db, p, table, row, true)) return err('42501', 'new row violates row-level security policy');
        const key = op === 'upsert' && conflict ? conflict.split(',') : UNIQUE[table];
        const dup = key && rows.find(r => key.every(k => r[k] === row[k]));
        if (dup && op === 'upsert') { Object.assign(dup, item); out.push(Object.assign({}, dup)); continue; }
        if (dup || (UNIQUE[table] && rows.find(r => UNIQUE[table].every(k => r[k] === row[k])))) return err('23505', 'duplicate key value');
        if (table === 'faculty' && !(row.max_units > 0)) return err('23514', 'check violated');
        rows.push(row); out.push(Object.assign({}, row));
      }
      return mode === 'single' ? { data: out[0], error: null } : { data: out, error: null };
    }
    const hit = rows.filter(r => allowed(db, p, table, r, true) && filters.every(f => f(r)));
    if (op === 'update') { hit.forEach(r => Object.assign(r, payload)); return { data: hit.map(r => ({ id: r.id })), error: null }; }
    if (op === 'delete') { db.t[table] = rows.filter(r => !hit.includes(r)); return { data: null, error: null }; }
    return err('?', 'unknown op');
  }
  return b;
}

/* ---------------------------------------------------------------- one browser */
function browser(db, profile, ls) {
  const store = ls || new Map();
  const listeners = {};
  const audits = [];
  const window = { ATLAS_CONFIG: {}, addEventListener(n, f) { (listeners[n] = listeners[n] || []).push(f); } };
  window.window = window;
  const user = { id: profile.id, role: profile.role, dept: profile.dept, facultyId: profile.faculty_id || null };
  window.atlasSupabase = { from: t => builder(db, profile, t) };
  window.atlasAuth = {
    ready: Promise.resolve(user),
    apiBase: () => 'http://api.test',
    fetch: async (url, opts) => { audits.push({ url, body: JSON.parse(opts.body) }); return { ok: true }; }
  };
  const el = () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {}, addEventListener() {}, remove() {}, set textContent(v) { this._t = v; }, get textContent() { return this._t; } });
  const ctx = vm.createContext({
    window, document: { body: el(), createElement: el }, navigator: { onLine: true }, Date, JSON, Promise, console,
    setTimeout, clearTimeout, Array, Object, String, Number, parseInt, isNaN,
    localStorage: {
      get length() { return store.size; }, key: i => Array.from(store.keys())[i] || null,
      getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k)
    }
  });
  vm.runInContext(SRC, ctx);
  return { data: window.atlasData, window, store, audits, fire: n => (listeners[n] || []).forEach(f => f({})), ctx };
}

const chair = dept => ({ id: 'u-' + dept, role: 'chairperson', dept });
const row = (name, extra) => Object.assign({ name, specialization: ['Networking'], max_units: 24, overload_buffer: 6, availability: ['Mon', 'Tue'] }, extra);
function tableRows(rows) {
  return rows.map(r => Object.assign({}, r, { getId: () => r.id || '', setId: id => { r.id = id; } }));
}

(async () => {
  const db = makeDb();

  /* 1. an empty department: offer the sample pool, never overwrite */
  let b = browser(db, chair('IT'));
  await b.data.init();
  check('empty IT faculty table is detected', b.data.faculty.isEmpty());
  const pool = ['Prof. A', 'Prof. B', 'Prof. C'].map(n => row(n));
  let r = await b.data.faculty.loadSample(pool);
  check('sample faculty inserted into the database', r.ok && db.t.faculty.length === 3);
  r = await b.data.faculty.loadSample([row('Prof. Z')]);
  check('loading the sample again refuses and changes nothing', !r.ok && db.t.faculty.length === 3 && !db.t.faculty.some(f => f.name === 'Prof. Z'));

  /* 2. edit a professor in IT, then see it in a second browser */
  const it = b.data.faculty.list();
  const edited = it.map(f => (f.name === 'Prof. B' ? Object.assign({}, f, { max_units: 18 }) : f));
  r = await b.data.faculty.save(tableRows(edited));
  check('edit saved', r.ok && db.t.faculty.find(f => f.name === 'Prof. B').max_units === 18);
  let b2 = browser(db, chair('IT'));
  await b2.data.init();
  check('a second browser sees the change', b2.data.faculty.list().find(f => f.name === 'Prof. B').max_units === 18);
  const ed = b.audits.filter(a => a.body.action === 'faculty_edited');
  check('edit reported to POST /audit with an id and a count only', ed.length === 1 && /\/audit$/.test(ed[0].url) && ed[0].body.entity_id && Object.keys(ed[0].body.meta).join() === 'fields');

  /* 3. CS never sees IT data */
  db.t.faculty.push({ id: 'cs-1', dept: 'CS', name: 'Prof. CS', specializations: [], max_units: 24, overload_buffer: 6, availability: [] });
  db.t.rooms.push({ id: 'r-it', dept: 'IT', name: 'IT Room 1', kind: 'lecture', recommended: 30, max: 40 });
  db.t.dept_settings.push({ dept: 'IT', academic_year: '2026-2027', semester: '1st Semester', solver: { population: 80 }, lab_also_lecture: false });
  const cs = browser(db, chair('CS'));
  await cs.data.init();
  check('CS sees only CS faculty', cs.data.faculty.list().length === 1 && cs.data.faculty.list()[0].name === 'Prof. CS');
  check('CS sees no IT rooms and no IT settings', !cs.data.rooms.has() && cs.data.settings.solver().population === undefined);
  const itAgain = browser(db, chair('IT'));
  await itAgain.data.init();
  check('IT settings are loaded for IT', itAgain.data.settings.solver().population === 80);

  /* 4. a failed save keeps what was typed and is retried */
  b = browser(db, chair('IT'));
  await b.data.init();
  db.offline = true;
  const typed = b.data.faculty.list().map(f => (f.name === 'Prof. A' ? Object.assign({}, f, { max_units: 12 }) : f));
  r = await b.data.faculty.save(tableRows(typed));
  check('offline save fails without throwing', r.ok === false && /offline|reach/i.test(r.error) === true || r.ok === false);
  check('the typed value is still in memory', b.data.faculty.list().find(f => f.name === 'Prof. A').max_units === 12);
  check('the failed save is pending', b.data.pendingSaves() > 0);
  db.offline = false;
  b.data.retry();
  await new Promise(res => setTimeout(res, 50));
  check('retry saves it when the connection returns', db.t.faculty.find(f => f.name === 'Prof. A').max_units === 12 && b.data.pendingSaves() === 0);

  /* 5. a newer save replaces an older failed one (a stale retry never overwrites newer data) */
  b = browser(db, chair('IT'));
  await b.data.init();
  db.offline = true;
  await b.data.faculty.save(tableRows(b.data.faculty.list().map(f => (f.name === 'Prof. C' ? Object.assign({}, f, { max_units: 7 }) : f))));
  db.offline = false;
  await b.data.faculty.save(tableRows(b.data.faculty.list().map(f => (f.name === 'Prof. C' ? Object.assign({}, f, { max_units: 9 }) : f))));
  b.data.retry();
  await new Promise(res => setTimeout(res, 50));
  check('older failed save never replays over the newer one', db.t.faculty.find(f => f.name === 'Prof. C').max_units === 9);

  /* 6. offline copy: read only, expires after 10 minutes, never written back */
  const ls = new Map();
  b = browser(db, chair('IT'), ls);
  await b.data.init();
  const snapshotBefore = JSON.stringify(db.t.faculty);
  db.offline = true;
  b2 = browser(db, chair('IT'), ls);
  await b2.data.init();
  check('offline: the cached copy is shown and marked offline', b2.data.isOffline() && b2.data.faculty.list().length === 3);
  r = await b2.data.faculty.save(tableRows(b2.data.faculty.list().map(f => Object.assign({}, f, { max_units: 1 }))));
  db.offline = false;
  check('offline copy cannot be saved over the database', r.ok === false && JSON.stringify(db.t.faculty) === snapshotBefore);
  const key = Array.from(ls.keys()).find(k => k.indexOf('atlasCache:') === 0 && /:chair$/.test(k));
  const entry = JSON.parse(ls.get(key)); entry.t -= 11 * 60 * 1000; ls.set(key, JSON.stringify(entry));
  db.offline = true;
  let rejected = false;
  try { await browser(db, chair('IT'), ls).data.init(); } catch (e) { rejected = true; }
  db.offline = false;
  check('a cache older than 10 minutes is not used', rejected);

  /* 7. the database wins over a stale cache when it is reachable */
  const ls2 = new Map();
  b = browser(db, chair('IT'), ls2);
  await b.data.init();
  db.t.faculty.find(f => f.name === 'Prof. A').max_units = 20;       // changed elsewhere, newer than the cache
  b2 = browser(db, chair('IT'), ls2);
  await b2.data.init();
  check('stale cache never overrides newer database data', !b2.data.isOffline() && b2.data.faculty.list().find(f => f.name === 'Prof. A').max_units === 20);

  /* 8. leave dates: ranges only, insert before delete */
  const fid = db.t.faculty.find(f => f.name === 'Prof. A').id;
  b = browser(db, chair('IT'));
  await b.data.init();
  r = await b.data.leave.replace(fid, [{ start: '2026-11-10', end: '2026-11-05' }]);
  check('an end date before the start date is refused', r.ok === false && db.t.faculty_leave.length === 0);
  r = await b.data.leave.replace(fid, [{ start: '2026-11-10', end: '2026-11-12' }, { start: '2026-12-01', end: '2026-12-01' }]);
  check('leave ranges saved', r.ok && db.t.faculty_leave.length === 2 && !db.t.faculty_leave.some(l => 'reason' in l));
  db.failInsert.faculty_leave = true;
  r = await b.data.leave.replace(fid, [{ start: '2027-01-05', end: '2027-01-06' }]);
  db.failInsert.faculty_leave = false;
  check('a failed insert leaves the old leave dates in place', r.ok === false && db.t.faculty_leave.length === 2);
  b.data.retry();
  await new Promise(res => setTimeout(res, 50));
  check('retry replaces the leave dates', db.t.faculty_leave.length === 1 && db.t.faculty_leave[0].start_date === '2027-01-05');
  const sc = b.data.softConstraints();
  check('leave goes to the engine as leave_dates', sc['Prof. A'] && sc['Prof. A'].leave_dates[0].start === '2027-01-05');

  /* 9. preferences */
  r = await b.data.prefs.save(fid, { preferred_period: 'morning', avoid_days: ['Fri', 'Xyz'], preferred_room: '' });
  check('preferences saved (unknown days dropped)', r.ok && db.t.faculty_preferences[0].avoid_days.join() === 'Fri' && db.t.faculty_preferences[0].preferred_room === null);
  check('preferences reach the engine format', b.data.softConstraints()['Prof. A'].restricted_days[0] === 'Fri');

  /* 10. settings: period and solver */
  r = await b.data.settings.saveSolver({ population: 60 });
  r = await b.data.settings.savePeriod('2027-2028', '2nd Semester');
  const srow = db.t.dept_settings.find(s => s.dept === 'IT');
  check('period and solver saved in one dept_settings row', srow.academic_year === '2027-2028' && srow.semester === '2nd Semester' && srow.solver.population === 60);
  const aud = b.audits.filter(a => a.body.action === 'solver_settings_changed');
  check('settings changes reported with counts only', aud.length === 2 && aud.every(a => Object.values(a.body.meta).every(v => typeof v === 'number')));

  /* 11. class sizes and rooms */
  r = await b.data.classSizes.save({ IT1B1: { year: '1st Year', block: 'B1', size: 40 }, IT2B1: { year: '2nd Year', block: 'B1', size: 35 } });
  check('class sizes saved', r.ok && db.t.class_sizes.length === 2 && db.t.class_sizes[0].year === 1);
  r = await b.data.classSizes.save({ IT1B1: { year: '1st Year', block: 'B1', size: 42 } });
  check('a block removed from the list is removed from the database', r.ok && db.t.class_sizes.length === 1 && db.t.class_sizes[0].size === 42);
  r = await b.data.rooms.save({ lecture: ['IT Room 1'], lab: ['Lab 1'], capacity: { 'IT Room 1': { recommended: 50, max: 40 }, 'Lab 1': { recommended: 20, max: 30 } } });
  check('a room whose recommended capacity is above its maximum is refused', r.ok === false);
  r = await b.data.rooms.save({ lecture: ['IT Room 1'], lab: ['Lab 1'], capacity: { 'IT Room 1': { recommended: 30, max: 40 }, 'Lab 1': { recommended: 20, max: 30 } } });
  check('rooms saved with their kind', r.ok && db.t.rooms.filter(x => x.dept === 'IT').map(x => x.kind).sort().join() === 'lab,lecture');

  /* 12. audit bodies never contain names */
  const all = b.audits.concat(b2.audits).map(a => JSON.stringify(a.body)).join('');
  check('no professor name or leave date in any audit body', !/Prof\. /.test(all) && !/2027-01/.test(all));

  /* 13. deleting is explicit and removes the dependent rows */
  r = await b.data.faculty.remove(fid);
  check('delete removes the professor (explicit)', r.ok && !db.t.faculty.some(f => f.id === fid));
  check('delete reported with the id only', b.audits.some(a => a.body.action === 'faculty_deleted' && a.body.entity_id === fid));

  /* 14. faculty side: own record, own prefs and leave, the approved run of the department only */
  const pid = db.t.faculty.find(f => f.name === 'Prof. B').id;
  db.t.faculty_preferences.push({ faculty_id: pid, preferred_period: 'evening', avoid_days: [] });
  db.t.faculty_leave.push({ id: 'l1', faculty_id: pid, start_date: '2026-11-01', end_date: '2026-11-02' });
  db.t.schedule_runs.push({ id: 'run-draft', dept: 'IT', status: 'draft', academic_year: '2026-2027', semester: '1st Semester', updated_at: '2026-10-01', result: [{ faculty: 'Prof. B' }], solver_settings: {} });
  db.t.schedule_runs.push({ id: 'run-ok', dept: 'IT', status: 'approved', academic_year: '2026-2027', semester: '1st Semester', updated_at: '2026-10-02', result: [{ faculty: 'Prof. B' }, { faculty: 'Prof. C' }], solver_settings: { units_per_assignment: 3 } });
  db.t.schedule_runs.push({ id: 'run-cs', dept: 'CS', status: 'approved', academic_year: '2026-2027', semester: '1st Semester', updated_at: '2026-10-03', result: [{ faculty: 'Prof. CS' }], solver_settings: {} });
  const fb = browser(db, { id: 'u-f', role: 'faculty', dept: 'IT', faculty_id: pid });
  await fb.data.init();
  check('faculty reads the approved run of their department, not a draft or another department', fb.data.self.run().id === 'run-ok');
  check('faculty reads their own record', fb.data.self.record().name === 'Prof. B');
  check('faculty reads their own preferences and leave', fb.data.self.prefs().preferred_period === 'evening' && fb.data.self.leave()[0].start === '2026-11-01');
  r = await fb.data.self.saveLeave([{ start: '2026-11-20', end: '2026-11-21' }]);
  check('faculty can edit their own leave', r.ok && db.t.faculty_leave.filter(l => l.faculty_id === pid).length === 1 && db.t.faculty_leave.find(l => l.faculty_id === pid).start_date === '2026-11-20');
  r = await fb.data.self.savePrefs({ preferred_period: 'morning', avoid_days: ['Sat'] });
  check('faculty can edit their own preferences', r.ok && db.t.faculty_preferences.find(p => p.faculty_id === pid).preferred_period === 'morning');
  const other = db.t.faculty.find(f => f.name === 'Prof. C').id;
  r = await fb.data.prefs.save(other, { preferred_period: 'evening' });
  check('faculty cannot write another professor\'s preferences', r.ok === false && !db.t.faculty_preferences.some(p => p.faculty_id === other));
  check('faculty cannot change faculty rows', (await fb.window.atlasSupabase.from('faculty').update({ max_units: 1 }).eq('id', pid).select('id')).data.length === 0);
  check('faculty audit events are not sent', fb.audits.length === 0);

  /* 15. logout empties memory and the cache */
  fb.fire('atlas:logout');
  check('logout clears the cache keys', !Array.from(fb.store.keys()).some(k => k.indexOf('atlasCache:') === 0));
  check('logout clears the memory copy', fb.data.self.run() === null);

  /* 16. latest saved run (chairperson) */
  db.t.schedule_runs.push({ id: 'run-new', dept: 'IT', status: 'draft', academic_year: '2026-2027', semester: '1st Semester', created_at: '2026-10-05', result: [{ faculty: 'Prof. B' }], analytics: {}, coverage: {} });
  db.t.schedule_runs.forEach(x => { x.created_at = x.created_at || '2026-09-01'; });
  b = browser(db, chair('IT'));
  await b.data.init();
  const latest = await b.data.runs.latest();
  check('the newest run of the department is loaded for the chairperson', latest && latest.id === 'run-new');

  console.log(failures ? failures + ' FAILED' : 'ALL OK');
  process.exit(failures ? 1 : 0);
})().catch(e => { console.log('FAIL harness crashed: ' + (e && e.stack || e)); process.exit(1); });