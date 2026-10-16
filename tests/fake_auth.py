"""Fake Supabase for the Playwright tests (Part 16 version).

The real client needs a real project. This stand-in answers the same calls (getSession, profiles, and the tables
that assets/js/data-store.js reads and writes) from two localStorage keys of the test browser:
  __testProfile  the signed-in user ({role, dept, faculty_id, ...})
  __testDb       {table: [rows]}   the "database"; a second browser can be given a copy of it
It applies the same department rules as the RLS policies (a chairperson sees only their department, a faculty
member only their own rows and the approved run), so a test that opens CS must never see IT rows.
Test helpers in the page: window.__testDb.rows(table), .upsert(table, row, keyCols), .seedFaculty(dept, n), .raw().
Setting localStorage.__testFail = '1' makes every write fail like a lost connection."""

FAKE_AUTH = r"""
(() => {
  const prof = () => JSON.parse(localStorage.getItem('__testProfile') || 'null');
  const read = () => JSON.parse(localStorage.getItem('__testDb') || '{}');
  const write = db => localStorage.setItem('__testDb', JSON.stringify(db));
  let n = 0;
  const uid = () => 'row-' + Date.now() + '-' + (++n);
  const UNIQUE = { faculty: ['dept', 'name'], class_sizes: ['dept', 'block_key'], rooms: ['dept', 'name'],
                   dept_settings: ['dept'], faculty_preferences: ['faculty_id'] };

  const deptOf = (db, id) => { const f = (db.faculty || []).find(r => r.id === id); return f && f.dept; };
  function allowed(db, p, table, row, writing) {
    if (p.role === 'chairperson') {
      if (table === 'faculty_preferences' || table === 'faculty_leave') return deptOf(db, row.faculty_id) === p.dept;
      return row.dept === p.dept;
    }
    if (table === 'faculty') return !writing && row.dept === p.dept;
    if (table === 'faculty_preferences' || table === 'faculty_leave') return row.faculty_id === p.faculty_id;
    if (table === 'schedule_runs') return !writing && row.dept === p.dept && row.status === 'approved';
    return false;
  }

  function from(table) {
    const p = prof();
    let op = 'select', filters = [], payload = null, order = null, lim = null, head = false, conflict = null, mode = 'many';
    const b = {
      select(_c, o) { if (o && o.head) head = true; return b; },
      eq(c, v) { filters.push(r => r[c] === v); return b; },
      in(c, vs) { filters.push(r => vs.includes(r[c])); return b; },
      order(c, o) { order = [c, !(o && o.ascending === false)]; return b; },
      limit(k) { lim = k; return b; },
      maybeSingle() { mode = 'maybe'; return b; },
      single() { mode = 'single'; return b; },
      insert(rows) { op = 'insert'; payload = rows; return b; },
      update(v) { op = 'update'; payload = v; return b; },
      upsert(rows, o) { op = 'upsert'; payload = rows; conflict = o && o.onConflict; return b; },
      delete() { op = 'delete'; return b; },
      then(res, rej) { return run().then(res, rej); }
    };
    async function run() {
      if (localStorage.getItem('__testFail') === '1' && op !== 'select') throw new TypeError('Failed to fetch');
      if (!p) return { data: null, error: { message: 'not signed in' } };
      if (table === 'profiles') return { data: p, error: null };
      const db = read();
      db[table] = db[table] || [];
      const rows = db[table];
      const err = (code, message) => ({ data: null, error: { code, message } });
      const pass = r => allowed(db, p, table, r, false) && filters.every(f => f(r));
      if (op === 'select') {
        let out = rows.filter(pass).map(r => Object.assign({}, r));
        if (order) out.sort((x, y) => (x[order[0]] > y[order[0]] ? 1 : -1) * (order[1] ? 1 : -1));
        if (lim) out = out.slice(0, lim);
        if (head) return { data: null, error: null, count: out.length };
        if (mode === 'maybe') return { data: out[0] || null, error: null };
        if (mode === 'single') return out.length === 1 ? { data: out[0], error: null } : err('PGRST116', 'no row');
        return { data: out, error: null };
      }
      if (op === 'insert' || op === 'upsert') {
        const list = Array.isArray(payload) ? payload : [payload];
        const out = [];
        for (const item of list) {
          const row = Object.assign({ id: uid() }, item);
          if (!allowed(db, p, table, row, true)) return err('42501', 'new row violates row-level security policy');
          const key = op === 'upsert' && conflict ? conflict.split(',') : UNIQUE[table];
          const dup = key && rows.find(r => key.every(k => r[k] === row[k]));
          if (dup && op === 'upsert') { Object.assign(dup, item); out.push(Object.assign({}, dup)); continue; }
          if (dup) return err('23505', 'duplicate key value');
          rows.push(row); out.push(Object.assign({}, row));
        }
        write(db);
        return mode === 'single' ? { data: out[0], error: null } : { data: out, error: null };
      }
      const hit = rows.filter(r => allowed(db, p, table, r, true) && filters.every(f => f(r)));
      if (op === 'update') { hit.forEach(r => Object.assign(r, payload)); write(db); return { data: hit.map(r => ({ id: r.id })), error: null }; }
      if (op === 'delete') { db[table] = rows.filter(r => !hit.includes(r)); write(db); return { data: null, error: null }; }
      return err('?', 'unknown op');
    }
    return b;
  }

  window.__testDb = {
    raw: read,
    rows: t => read()[t] || [],
    upsert(t, row, keys) {
      const db = read(); db[t] = db[t] || [];
      const hit = db[t].find(r => keys.every(k => r[k] === row[k]));
      if (hit) Object.assign(hit, row); else db[t].push(Object.assign({ id: uid() }, row));
      write(db);
    },
    seedFaculty(dept, count) {
      const db = read(); db.faculty = db.faculty || [];
      if (db.faculty.some(r => r.dept === dept)) return;
      for (let i = 1; i <= count; i++) db.faculty.push({ id: dept + '-f' + i, dept, name: dept + ' Professor ' + i,
        specializations: [], max_units: 24, overload_buffer: 6, availability: ['Mon', 'Tue', 'Wed', 'Thu'] });
      write(db);
    }
  };
  window.atlasSupabase = {
    auth: {
      getSession: async () => { const p = prof();
        return { data: { session: p ? { access_token: 'test', user: { id: p.id || 'u1', email: p.email } } : null } }; },
      refreshSession: async () => ({ data: { session: null } }),
      signOut: async () => { localStorage.removeItem('__testProfile'); },
      onAuthStateChange() {}
    },
    from
  };
})();
"""


def chair_profile_js(dept_expr):
    """JS statement that makes the fake project return a chairperson of the given department."""
    return ("localStorage.setItem('__testProfile', JSON.stringify({id:'u1', role:'chairperson', dept:%s, "
            "full_name:'Tester', email:'t@psu.palawan.edu.ph'}));" % dept_expr)


# a faculty account linked to the faculty row f1 of IT (the row is created in the fake database too)
FACULTY_PROFILE_JS = (
    "window.__testDb.upsert('faculty', {id:'f1', dept:'IT', name:'Prof. Maria Santos', specializations:[], max_units:24, "
    "overload_buffer:6, availability:['Mon','Tue']}, ['id']);"
    "localStorage.setItem('__testProfile', JSON.stringify({id:'u1', role:'faculty', dept:'IT', faculty_id:'f1', "
    "full_name:'Prof. Maria Santos', email:'t@psu.palawan.edu.ph'}));")


def switch_dept_js(code):
    return ("() => { sessionStorage.setItem('atlasDept','%s'); const p = JSON.parse(localStorage.getItem('__testProfile'));"
            " p.dept = '%s'; localStorage.setItem('__testProfile', JSON.stringify(p)); }" % (code, code))


def seed_js(dept_expr, count=3):
    """JS statement that puts a few faculty rows into the fake database for a department."""
    return "window.__testDb.seedFaculty(%s, %d);" % (dept_expr, count)