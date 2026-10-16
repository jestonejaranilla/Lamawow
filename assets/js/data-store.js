/* ============================================================
   ATLAS PSU - assets/js/data-store.js  (Part 16)
   The data layer: faculty, preferences, leave dates, class sizes, rooms, the active academic period and the
   solver settings are read from and saved to Supabase (supabase-js). Row Level Security does the filtering,
   so a chairperson only ever gets their own department and a faculty member only their own record.

   Rules this file keeps:
   - The database is the source of truth. Pages read from the in-memory copy that init() filled from the database.
   - localStorage is only a short-lived cache (10 minutes). It is read ONLY when the database cannot be reached,
     it is never written back to the database, and while an offline copy is shown, saving is switched off, so a
     stale copy can never overwrite newer data.
   - A failed save keeps what the user typed on screen and in memory, shows "Not saved" with a Retry button and an
     error toast, and is retried when the connection returns. A newer save of the same thing replaces an older failed one.
   - Rows are only deleted by an explicit delete (never because they are missing from a list on screen),
     except for the explicit "Save rooms" and "Save class sizes" buttons, which save the whole list.
   - Faculty add, edit and delete and solver setting changes are reported to POST /audit (ids and counts only).
   ============================================================ */
(function () {
  'use strict';

  var DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var PERIODS = ['morning', 'afternoon', 'evening'];
  var SEMESTERS = ['1st Semester', '2nd Semester', 'Summer'];
  var DEFAULT_PERIOD = { academic_year: '2026-2027', semester: '1st Semester' };
  var CACHE_PREFIX = 'atlasCache:';
  var CACHE_TTL_MS = 10 * 60 * 1000;
  var ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

  var ctx = null;                 // { user, client, dept, role }
  var initPromise = null;
  var fromCache = false;          // true while the data on screen is an offline copy
  var mem = emptyMemory();
  var snap = { faculty: {} };     // last saved JSON of each faculty row, by id
  var chains = {};                // entity -> promise (saves of one entity never overlap)
  var failed = {};                // entity -> { work } of the latest failed save
  var versions = {};              // entity -> counter, so an older failed save is never replayed over a newer one
  var pending = 0;

  function emptyMemory() {
    return { faculty: [], prefs: {}, leave: {}, classSizes: null, rooms: null, settings: null, run: null, names: [] };
  }

  function client() { return ctx && ctx.client; }
  function clone(v) { return v === undefined ? v : JSON.parse(JSON.stringify(v)); }

  /* ---------------------------------------------------------- status pill + toast */
  var statusEl = null, hideTimer = null;

  function ensureStatusEl() {
    if (statusEl || !document.body) return statusEl;
    statusEl = document.createElement('div');
    statusEl.id = 'atlasSaveStatus';
    statusEl.setAttribute('role', 'status');
    statusEl.setAttribute('aria-live', 'polite');
    statusEl.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:9999;display:none;align-items:center;gap:10px;' +
      'padding:8px 14px;border-radius:999px;font:600 13px/1.2 system-ui,sans-serif;color:#fff;' +
      'background:rgba(30,41,59,.94);box-shadow:0 4px 14px rgba(0,0,0,.25);max-width:calc(100vw - 32px)';
    document.body.appendChild(statusEl);
    return statusEl;
  }

  function setStatus(kind, text) {
    var el = ensureStatusEl();
    if (!el) return;
    clearTimeout(hideTimer);
    el.dataset.state = kind;
    el.style.display = 'inline-flex';
    el.style.background = kind === 'error' ? 'rgba(185,28,28,.96)' : kind === 'saved' ? 'rgba(21,128,61,.96)' : 'rgba(30,41,59,.94)';
    el.textContent = text;
    if (kind === 'error') {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = 'Retry';
      b.style.cssText = 'border:0;border-radius:999px;padding:3px 10px;font:inherit;cursor:pointer;background:#fff;color:#7f1d1d';
      b.addEventListener('click', function () { retryFailed(); });
      el.appendChild(b);
    }
    if (kind === 'saved') hideTimer = setTimeout(function () { el.style.display = 'none'; }, 2500);
  }

  function toastError(message) {
    if (typeof window.showToast === 'function') { window.showToast(message, 'error'); return; }
    var t = document.createElement('div');
    t.setAttribute('role', 'alert');
    t.textContent = message;
    t.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:10000;max-width:min(360px,calc(100vw - 32px));' +
      'padding:10px 14px;border-radius:10px;font:600 13px/1.35 system-ui,sans-serif;color:#fff;background:#b91c1c;' +
      'box-shadow:0 4px 14px rgba(0,0,0,.3)';
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 6000);
  }

  function friendly(err) {
    var code = err && err.code, msg = String((err && err.message) || err || '');
    if (code === '23505') return 'That name is already used in this department.';
    if (code === '42501' || /row-level security|permission denied/i.test(msg)) return 'You are not allowed to save this.';
    if (code === '23514' || code === '22P02' || code === '22007') return 'One of the values is not allowed. Check the numbers and dates.';
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return 'You are offline.';
    if (/failed to fetch|networkerror|load failed|network request/i.test(msg)) return 'Cannot reach the database. Check your connection.';
    return msg || 'Could not save.';
  }

  /* ---------------------------------------------------------- short-lived cache (offline fallback only) */
  function cacheKey(entity) {
    return CACHE_PREFIX + (ctx ? ctx.user.id : '?') + ':' + (ctx ? ctx.dept : '?') + ':' + entity;
  }
  function cacheSet(entity, value) {
    try { localStorage.setItem(cacheKey(entity), JSON.stringify({ t: Date.now(), v: value })); } catch (e) { /* storage unavailable */ }
  }
  function cacheGet(entity) {
    try {
      var raw = JSON.parse(localStorage.getItem(cacheKey(entity)) || 'null');
      if (!raw || Date.now() - raw.t > CACHE_TTL_MS) return undefined;
      return raw.v;
    } catch (e) { return undefined; }
  }
  function purgeCache() {
    try {
      var drop = [];
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && k.indexOf(CACHE_PREFIX) === 0) drop.push(k);
      }
      drop.forEach(function (k) { localStorage.removeItem(k); });
    } catch (e) { /* storage unavailable */ }
  }

  /* ---------------------------------------------------------- save queue */
  function retryFailed() {
    var entries = Object.keys(failed).map(function (k) { return [k, failed[k].work]; });
    failed = {};
    entries.forEach(function (e) { persist(e[0], e[1]); });
  }

  function persist(entity, work) {
    var ver = (versions[entity] = (versions[entity] || 0) + 1);
    pending++;
    setStatus('saving', 'Saving\u2026');
    var prev = chains[entity] || Promise.resolve();
    var run = prev.then(async function () {
      try {
        if (!ctx) throw new Error('Not signed in.');
        if (fromCache) throw new Error('Showing an offline copy. Reconnect and reload the page before saving.');
        if (typeof navigator !== 'undefined' && navigator.onLine === false) throw new Error('You are offline.');
        await work();
        delete failed[entity];                                   // this save includes everything an older failed save held
        return { ok: true };
      } catch (e) {
        if (versions[entity] === ver) failed[entity] = { work: work };
        var text = friendly(e);
        toastError('Not saved: ' + text);
        return { ok: false, error: text };
      } finally {
        pending--;
        if (pending === 0) {
          if (Object.keys(failed).length) setStatus('error', 'Not saved \u2014 your changes are kept on screen.');
          else setStatus('saved', 'Saved');
        }
      }
    });
    chains[entity] = run;
    return run;
  }

  window.addEventListener('online', function () { if (Object.keys(failed).length) retryFailed(); });

  /* ---------------------------------------------------------- audit (POST /audit: ids and counts only) */
  function report(action, entityId, meta) {
    try {
      if (!window.atlasAuth || !window.atlasAuth.fetch || !ctx || ctx.role === 'faculty') return;
      var base = window.atlasAuth.apiBase();
      window.atlasAuth.fetch(base + '/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action, entity_id: entityId ? String(entityId) : null, dept: ctx.dept, meta: meta || {} })
      }).catch(function () { /* the audit row is best effort */ });
    } catch (e) { /* never block a save */ }
  }

  /* ---------------------------------------------------------- row mapping */
  function yearNumber(label) { var n = parseInt(String(label || ''), 10); return n >= 1 && n <= 4 ? n : 1; }
  function yearLabel(n) { return ({ 1: '1st Year', 2: '2nd Year', 3: '3rd Year', 4: '4th Year' })[n] || '1st Year'; }

  function facFromDb(r) {
    return {
      id: r.id, name: r.name, specialization: (r.specializations || []).slice(),
      max_units: r.max_units, overload_buffer: r.overload_buffer, availability: (r.availability || []).slice()
    };
  }

  function facToDb(f) {
    return {
      dept: ctx.dept, name: String(f.name || '').trim(), specializations: (f.specialization || []).slice(),
      max_units: parseInt(f.max_units, 10), overload_buffer: parseInt(f.overload_buffer, 10),
      availability: (f.availability || []).filter(function (d) { return DAYS.indexOf(d) >= 0; })
    };
  }

  function checkFaculty(row) {
    if (!row.name || row.name.length > 80) return 'A professor needs a name of 1 to 80 characters.';
    if (!(row.max_units > 0 && row.max_units <= 50)) return 'Max units must be a number from 1 to 50.';
    if (!(row.overload_buffer >= 0 && row.overload_buffer <= 20)) return 'The overload buffer must be a number from 0 to 20.';
    return '';
  }

  function sameJson(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

  /* ---------------------------------------------------------- loading */
  async function selectOrThrow(q) {
    var r = await q;
    if (r.error) throw r.error;
    return r.data;
  }

  async function fetchChair() {
    var c = client(), d = ctx.dept;
    var out = await Promise.all([
      selectOrThrow(c.from('faculty').select('*').eq('dept', d).order('name')),
      selectOrThrow(c.from('faculty_preferences').select('*')),
      selectOrThrow(c.from('faculty_leave').select('id,faculty_id,start_date,end_date')),
      selectOrThrow(c.from('class_sizes').select('*').eq('dept', d)),
      selectOrThrow(c.from('rooms').select('*').eq('dept', d).order('name')),
      selectOrThrow(c.from('dept_settings').select('*').eq('dept', d).maybeSingle())
    ]);
    return { faculty: out[0] || [], prefs: out[1] || [], leave: out[2] || [], classSizes: out[3] || [], rooms: out[4] || [], settings: out[5] || null };
  }

  async function fetchFacultySelf() {
    var c = client(), id = ctx.user.facultyId;
    if (!id) throw new Error('This account is not linked to a faculty record.');
    var out = await Promise.all([
      selectOrThrow(c.from('faculty').select('*').eq('id', id).maybeSingle()),
      selectOrThrow(c.from('faculty').select('id,name').eq('dept', ctx.dept).order('name')),
      selectOrThrow(c.from('faculty_preferences').select('*').eq('faculty_id', id).maybeSingle()),
      selectOrThrow(c.from('faculty_leave').select('id,faculty_id,start_date,end_date').eq('faculty_id', id)),
      selectOrThrow(c.from('schedule_runs').select('id,academic_year,semester,label,status,updated_at,solver_settings,result')
        .eq('dept', ctx.dept).eq('status', 'approved').order('updated_at', { ascending: false }).limit(1))
    ]);
    return {
      self: out[0], names: out[1] || [], prefs: out[2] ? [out[2]] : [], leave: out[3] || [], run: (out[4] || [])[0] || null
    };
  }

  function applyChair(raw) {
    mem = emptyMemory();
    mem.faculty = raw.faculty.map(facFromDb);
    snap.faculty = {};
    raw.faculty.forEach(function (r) { snap.faculty[r.id] = JSON.stringify(facComparable(facFromDb(r))); });
    raw.prefs.forEach(function (p) { mem.prefs[p.faculty_id] = p; });
    raw.leave.forEach(function (l) { (mem.leave[l.faculty_id] = mem.leave[l.faculty_id] || []).push(l); });
    if (raw.classSizes.length) {
      mem.classSizes = {};
      raw.classSizes.forEach(function (r) {
        var rest = r.block_key.indexOf(ctx.dept) === 0 ? r.block_key.slice(ctx.dept.length + 1) : '';
        mem.classSizes[r.block_key] = { year: yearLabel(r.year), block: rest, size: r.size };
      });
    }
    if (raw.rooms.length) {
      mem.rooms = { lecture: [], lab: [], capacity: {} };
      raw.rooms.forEach(function (r) {
        (r.kind === 'lab' ? mem.rooms.lab : mem.rooms.lecture).push(r.name);
        mem.rooms.capacity[r.name] = { recommended: r.recommended, max: r.max };
      });
    }
    mem.settings = raw.settings ? {
      academic_year: raw.settings.academic_year, semester: raw.settings.semester,
      solver: clone(raw.settings.solver || {}), lab_also_lecture: !!raw.settings.lab_also_lecture, exists: true
    } : { academic_year: DEFAULT_PERIOD.academic_year, semester: DEFAULT_PERIOD.semester, solver: {}, lab_also_lecture: false, exists: false };
  }

  function applyFacultySelf(raw) {
    mem = emptyMemory();
    mem.names = raw.names.map(function (r) { return r.name; });
    if (raw.self) {
      mem.faculty = [facFromDb(raw.self)];
      if (mem.names.indexOf(raw.self.name) < 0) mem.names.push(raw.self.name);
    }
    raw.prefs.forEach(function (p) { mem.prefs[p.faculty_id] = p; });
    raw.leave.forEach(function (l) { (mem.leave[l.faculty_id] = mem.leave[l.faculty_id] || []).push(l); });
    mem.run = raw.run;
  }

  function facComparable(f) {
    return { name: f.name, specialization: f.specialization, max_units: f.max_units, overload_buffer: f.overload_buffer, availability: f.availability };
  }

  async function init() {
    if (initPromise) return initPromise;
    initPromise = (async function () {
      var user = window.atlasAuth ? await window.atlasAuth.ready : null;
      if (!user || !window.atlasSupabase) throw new Error('Not signed in.');
      ctx = { user: user, client: window.atlasSupabase, dept: user.dept, role: user.role };
      var isChair = user.role === 'chairperson';
      var key = isChair ? 'chair' : 'self';
      try {
        var raw = isChair ? await fetchChair() : await fetchFacultySelf();
        (isChair ? applyChair : applyFacultySelf)(raw);
        fromCache = false;
        cacheSet(key, raw);                                   // overwritten on every successful load: always the newest database copy
      } catch (e) {
        var cached = cacheGet(key);
        if (cached === undefined) { setStatus('error', 'Cannot load data: ' + friendly(e)); throw e; }
        (isChair ? applyChair : applyFacultySelf)(cached);
        fromCache = true;                                     // read-only until a reload reaches the database
        toastError('Cannot reach the database. Showing an offline copy; saving is off until you reload.');
      }
      return ctx;
    })();
    initPromise.catch(function () { /* callers handle the rejection */ });
    return initPromise;
  }

  /* ---------------------------------------------------------- faculty (chairperson) */
  var faculty = {
    list: function () { return clone(mem.faculty); },
    isEmpty: function () { return !fromCache && mem.faculty.length === 0; },

    /* rows: [{name, specialization, max_units, overload_buffer, availability, getId(), setId(id)}].
       Inserts the new ones, updates the changed ones. Never deletes. */
    save: function (rows) {
      mem.faculty = rows.filter(function (r) { return r.name; }).map(function (r) {
        return { id: r.getId() || null, name: r.name, specialization: r.specialization, max_units: r.max_units,
                 overload_buffer: r.overload_buffer, availability: r.availability };
      });
      return persist('faculty', async function () {
        var errors = [];
        for (var i = 0; i < rows.length; i++) {
          var r = rows[i];
          if (!r.name) continue;
          var db = facToDb(r), bad = checkFaculty(db);
          if (bad) { errors.push(bad); continue; }
          var id = r.getId();
          if (id) {
            var now = JSON.stringify(facComparable(facFromDb(Object.assign({ id: id }, { name: db.name, specializations: db.specializations,
              max_units: db.max_units, overload_buffer: db.overload_buffer, availability: db.availability }))));
            if (snap.faculty[id] === now) continue;               // nothing changed
            var upd = await client().from('faculty').update({ name: db.name, specializations: db.specializations, max_units: db.max_units,
              overload_buffer: db.overload_buffer, availability: db.availability }).eq('id', id).select('id');
            if (upd.error) throw upd.error;
            if (!upd.data || !upd.data.length) throw new Error('This professor no longer exists. Reload the page.');
            snap.faculty[id] = now;
            report('faculty_edited', id, { fields: 5 });
          } else {
            var ins = await client().from('faculty').insert(db).select('id').single();
            if (ins.error) throw ins.error;
            r.setId(ins.data.id);
            snap.faculty[ins.data.id] = JSON.stringify(facComparable(facFromDb(Object.assign({ id: ins.data.id }, { name: db.name,
              specializations: db.specializations, max_units: db.max_units, overload_buffer: db.overload_buffer, availability: db.availability }))));
            report('faculty_added', ins.data.id, {});
          }
        }
        if (errors.length) throw new Error(errors[0]);
      });
    },

    remove: function (id) {
      if (!id) return Promise.resolve({ ok: true });
      mem.faculty = mem.faculty.filter(function (f) { return f.id !== id; });
      delete mem.prefs[id]; delete mem.leave[id]; delete snap.faculty[id];
      return persist('facultyDel:' + id, async function () {
        var r = await client().from('faculty').delete().eq('id', id);
        if (r.error) throw r.error;
        report('faculty_deleted', id, {});
      });
    },

    /* Insert the sample pool only when the department has no faculty in the database (checked again right now). */
    loadSample: async function (list) {
      if (fromCache) return { ok: false, error: 'Showing an offline copy. Reload first.' };
      setStatus('saving', 'Saving\u2026');
      try {
        var cnt = await client().from('faculty').select('id', { count: 'exact', head: true }).eq('dept', ctx.dept);
        if (cnt.error) throw cnt.error;
        if (cnt.count > 0) {
          setStatus('saved', 'Saved');
          return { ok: false, error: 'This department already has faculty. Nothing was changed.' };
        }
        var rows = list.map(function (f) { return facToDb(f); }).filter(function (r) { return !checkFaculty(r); });
        var ins = await client().from('faculty').insert(rows).select('*');
        if (ins.error) throw ins.error;
        mem.faculty = ins.data.map(facFromDb);
        ins.data.forEach(function (r) { snap.faculty[r.id] = JSON.stringify(facComparable(facFromDb(r))); });
        report('faculty_added', null, { count: ins.data.length });
        setStatus('saved', 'Saved');
        return { ok: true, rows: clone(mem.faculty) };
      } catch (e) {
        var text = friendly(e);
        toastError('Not saved: ' + text);
        setStatus('error', 'Not saved');
        return { ok: false, error: text };
      }
    }
  };

  /* ---------------------------------------------------------- preferences + leave */
  var prefs = {
    get: function (facultyId) { return clone(mem.prefs[facultyId] || null); },
    save: function (facultyId, p) {
      var row = {
        faculty_id: facultyId,
        preferred_period: PERIODS.indexOf(p.preferred_period) >= 0 ? p.preferred_period : null,
        preferred_room: p.preferred_room || null, preferred_building: p.preferred_building || null,
        preferred_floor: p.preferred_floor || null,
        avoid_days: (p.avoid_days || []).filter(function (d) { return DAYS.indexOf(d) >= 0; })
      };
      mem.prefs[facultyId] = row;
      return persist('prefs:' + facultyId, async function () {
        var r = await client().from('faculty_preferences').upsert(row, { onConflict: 'faculty_id' });
        if (r.error) throw r.error;
      });
    },
    clear: function (facultyId) {
      delete mem.prefs[facultyId];
      return persist('prefs:' + facultyId, async function () {
        var r = await client().from('faculty_preferences').delete().eq('faculty_id', facultyId);
        if (r.error) throw r.error;
      });
    }
  };

  var leave = {
    get: function (facultyId) {
      return (mem.leave[facultyId] || []).map(function (l) { return { start: l.start_date, end: l.end_date }; });
    },
    /* ranges: [{start, end}] (ISO dates). Dates only, no reason. Inserts the new ranges first, then removes the old
       ones, so a failure in the middle never loses a leave date. */
    replace: function (facultyId, ranges) {
      var clean = [], seen = {};
      for (var i = 0; i < ranges.length; i++) {
        var s = ranges[i].start, e = ranges[i].end || ranges[i].start;
        if (!s && !ranges[i].end) continue;
        if (!ISO_DATE.test(s || '') || !ISO_DATE.test(e || '') || e < s) return Promise.resolve({ ok: false, error: 'Each leave needs a start date and an end date that is not before it.' });
        if (!seen[s + '|' + e]) { seen[s + '|' + e] = 1; clean.push({ start: s, end: e }); }
      }
      mem.leave[facultyId] = clean.map(function (c) { return { id: null, faculty_id: facultyId, start_date: c.start, end_date: c.end }; });
      return persist('leave:' + facultyId, async function () {
        var q = await client().from('faculty_leave').select('id,start_date,end_date').eq('faculty_id', facultyId);
        if (q.error) throw q.error;
        var have = {}, keep = {};
        (q.data || []).forEach(function (l) { have[l.start_date + '|' + l.end_date] = l.id; });
        var toAdd = clean.filter(function (c) { return !have[c.start + '|' + c.end]; });
        clean.forEach(function (c) { keep[c.start + '|' + c.end] = 1; });
        var toDel = (q.data || []).filter(function (l) { return !keep[l.start_date + '|' + l.end_date]; }).map(function (l) { return l.id; });
        if (toAdd.length) {
          var ins = await client().from('faculty_leave').insert(toAdd.map(function (c) { return { faculty_id: facultyId, start_date: c.start, end_date: c.end }; }));
          if (ins.error) throw ins.error;
        }
        if (toDel.length) {
          var del = await client().from('faculty_leave').delete().in('id', toDel);
          if (del.error) throw del.error;
        }
      });
    }
  };

  /* Preferences + leave of every faculty member, in the engine's soft-constraint format (no names are sent to /audit). */
  function softConstraints() {
    var out = {};
    mem.faculty.forEach(function (f) {
      var p = mem.prefs[f.id], l = mem.leave[f.id] || [], sc = {};
      if (p) {
        if (p.preferred_period) sc.preferred_period = p.preferred_period;
        if (p.preferred_room) sc.preferred_room = p.preferred_room;
        if (p.preferred_building) sc.preferred_building = p.preferred_building;
        if (p.preferred_floor) sc.preferred_floor = p.preferred_floor;
        if ((p.avoid_days || []).length) sc.restricted_days = p.avoid_days.slice();
      }
      if (l.length) sc.leave_dates = l.map(function (x) { return { start: x.start_date, end: x.end_date }; });
      if (Object.keys(sc).length) out[f.name] = sc;
    });
    return out;
  }

  /* ---------------------------------------------------------- class sizes */
  var classSizes = {
    has: function () { return !!mem.classSizes; },
    get: function () { return clone(mem.classSizes); },
    /* map: { key: {year: '1st Year', block, size} }: saves the whole list (explicit Save button) */
    save: function (map) {
      mem.classSizes = clone(map);
      return persist('classSizes', async function () {
        var rows = Object.keys(map).map(function (k) {
          return { dept: ctx.dept, block_key: k, year: yearNumber(map[k].year), size: parseInt(map[k].size, 10) };
        });
        for (var i = 0; i < rows.length; i++) {
          if (!(rows[i].size > 0 && rows[i].size <= 200)) throw new Error('Class size of ' + rows[i].block_key + ' must be a number from 1 to 200.');
        }
        if (rows.length) {
          var up = await client().from('class_sizes').upsert(rows, { onConflict: 'dept,block_key' });
          if (up.error) throw up.error;
        }
        var cur = await client().from('class_sizes').select('id,block_key').eq('dept', ctx.dept);
        if (cur.error) throw cur.error;
        var keep = {};
        rows.forEach(function (r) { keep[r.block_key] = 1; });
        var gone = (cur.data || []).filter(function (r) { return !keep[r.block_key]; }).map(function (r) { return r.id; });
        if (gone.length) {
          var del = await client().from('class_sizes').delete().in('id', gone);
          if (del.error) throw del.error;
        }
      });
    }
  };

  /* ---------------------------------------------------------- rooms */
  var rooms = {
    has: function () { return !!mem.rooms; },
    get: function () { return clone(mem.rooms); },
    /* value: {lecture: [names], lab: [names], capacity: {name: {recommended, max}}}: saves the whole list */
    save: function (value) {
      mem.rooms = clone(value);
      return persist('rooms', async function () {
        var rows = [], names = {};
        [['lecture', value.lecture], ['lab', value.lab]].forEach(function (pair) {
          (pair[1] || []).forEach(function (name) {
            var cap = (value.capacity || {})[name] || {};
            var rec = parseInt(cap.recommended, 10), max = parseInt(cap.max, 10);
            if (!(rec > 0 && max > 0)) throw new Error('Room "' + name + '" needs a recommended and a maximum capacity.');
            if (rec > max) throw new Error('Room "' + name + '": the recommended capacity cannot be above the maximum.');
            if (names[name]) throw new Error('Room "' + name + '" is listed twice.');
            names[name] = 1;
            rows.push({ dept: ctx.dept, name: name, kind: pair[0], recommended: rec, max: max });
          });
        });
        if (rows.length) {
          var up = await client().from('rooms').upsert(rows, { onConflict: 'dept,name' });
          if (up.error) throw up.error;
        }
        var cur = await client().from('rooms').select('id,name').eq('dept', ctx.dept);
        if (cur.error) throw cur.error;
        var gone = (cur.data || []).filter(function (r) { return !names[r.name]; }).map(function (r) { return r.id; });
        if (gone.length) {
          var del = await client().from('rooms').delete().in('id', gone);
          if (del.error) throw del.error;
        }
      });
    }
  };

  /* ---------------------------------------------------------- period + solver settings (dept_settings) */
  function saveSettingsRow(changedKeys) {
    var s = mem.settings;
    return persist('settings', async function () {
      var r = await client().from('dept_settings').upsert({
        dept: ctx.dept, academic_year: s.academic_year, semester: s.semester,
        solver: s.solver, lab_also_lecture: !!s.lab_also_lecture
      }, { onConflict: 'dept' });
      if (r.error) throw r.error;
      s.exists = true;
      report('solver_settings_changed', null, { keys: changedKeys });
    });
  }

  var settings = {
    get: function () { return clone(mem.settings) || { academic_year: DEFAULT_PERIOD.academic_year, semester: DEFAULT_PERIOD.semester, solver: {}, lab_also_lecture: false, exists: false }; },
    period: function () {
      var s = mem.settings || DEFAULT_PERIOD;
      return { year: s.academic_year, semester: s.semester };
    },
    solver: function () { return clone((mem.settings && mem.settings.solver) || {}); },
    savePeriod: function (year, semester) {
      if (!mem.settings) mem.settings = { academic_year: DEFAULT_PERIOD.academic_year, semester: DEFAULT_PERIOD.semester, solver: {}, lab_also_lecture: false, exists: false };
      if (SEMESTERS.indexOf(semester) < 0) return Promise.resolve({ ok: false, error: 'Unknown semester.' });
      mem.settings.academic_year = String(year).trim();
      mem.settings.semester = semester;
      return saveSettingsRow(2);
    },
    saveSolver: function (values) {
      if (!mem.settings) mem.settings = { academic_year: DEFAULT_PERIOD.academic_year, semester: DEFAULT_PERIOD.semester, solver: {}, lab_also_lecture: false, exists: false };
      mem.settings.solver = Object.assign({}, mem.settings.solver, values);
      return saveSettingsRow(Object.keys(values).length);
    }
  };

  /* ---------------------------------------------------------- faculty side (read-only data + own preferences/leave) */
  var self = {
    facultyId: function () { return ctx && ctx.user.facultyId; },
    record: function () { return clone(mem.faculty[0] || null); },
    names: function () { return mem.names.slice(); },
    run: function () { return clone(mem.run); },
    prefs: function () { return prefs.get(self.facultyId()); },
    leave: function () { return leave.get(self.facultyId()); },
    savePrefs: function (p) { return prefs.save(self.facultyId(), p); },
    saveLeave: function (ranges) { return leave.replace(self.facultyId(), ranges); },
    reload: async function () {
      var raw = await fetchFacultySelf();
      applyFacultySelf(raw);
      fromCache = false;
      cacheSet('self', raw);
    }
  };

  /* ---------------------------------------------------------- saved runs (chairperson): the last result on screen */
  var runs = {
    /* The newest run of the department (draft, saved or approved), so the schedule is the same in every browser. */
    latest: async function () {
      var r = await client().from('schedule_runs').select('id,status,academic_year,semester,result,analytics,coverage,created_at')
        .eq('dept', ctx.dept).order('created_at', { ascending: false }).limit(1);
      if (r.error) throw r.error;
      return (r.data && r.data[0]) || null;
    },
    /* A manual edit of a draft or saved run. An approved run is frozen by the database and answers with an error. */
    saveResult: function (runId, result) {
      if (!runId) return Promise.resolve({ ok: false, error: 'This result is not saved as a run yet.' });
      return persist('run:' + runId, async function () {
        var r = await client().from('schedule_runs').update({ result: result }).eq('id', runId).select('id');
        if (r.error) throw r.error;
        if (!r.data || !r.data.length) throw new Error('The saved run could not be found.');
      });
    }
  };

  /* ---------------------------------------------------------- logout / user change */
  function clearAll() {
    mem = emptyMemory();
    snap = { faculty: {} };
    chains = {}; failed = {}; versions = {}; pending = 0;
    ctx = null; initPromise = null; fromCache = false;
    purgeCache();
    if (statusEl) statusEl.style.display = 'none';
  }
  window.addEventListener('atlas:logout', clearAll);

  window.atlasData = {
    DAYS: DAYS, init: init, ready: function () { return init(); },
    isOffline: function () { return fromCache; },
    dept: function () { return ctx && ctx.dept; },
    faculty: faculty, prefs: prefs, leave: leave, softConstraints: softConstraints,
    classSizes: classSizes, rooms: rooms, settings: settings, self: self, runs: runs,
    retry: retryFailed, clear: clearAll, purgeCache: purgeCache,
    pendingSaves: function () { return pending + Object.keys(failed).length; }
  };
})();