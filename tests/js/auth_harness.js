/* Runs assets/js/app-core.js in a fake browser with a fake Supabase and prints one JSON line per check.
   Used by tests/test_part15.py. Needs only Node, no packages. */
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, '..', '..', 'assets', 'js', 'app-core.js'), 'utf8');
const BASE = 'http://localhost:5000';
const results = [];

function store(initial) {
  const m = new Map(Object.entries(initial || {}));
  return {
    getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k), clear: () => m.clear(),
    key: i => Array.from(m.keys())[i], get length() { return m.size; }, _m: m
  };
}

/* opts: path, session (bool), profile (row|null), faculty ({name}|null), cache, token, statuses (api replies) */
function world(opts) {
  const w = { calls: [], redirects: [], reloads: 0, signedOut: 0, hidden: null, listeners: {} };
  const session = opts.session === false ? null : { access_token: opts.token || 'tok1', user: { id: 'u1', email: 'u@psu.palawan.edu.ph' } };
  const statuses = (opts.statuses || [200]).slice();
  const table = name => {
    const chain = { select() { return chain; }, eq() { return chain; },
      maybeSingle: async () => ({ data: name === 'profiles' ? opts.profile : opts.faculty, error: opts.dbError ? { message: 'x' } : null }) };
    return chain;
  };
  const supa = {
    auth: {
      getSession: async () => ({ data: { session } }),
      refreshSession: async () => ({ data: { session: session ? { ...session, access_token: 'tok2' } : null } }),
      signOut: async () => { w.signedOut++; },
      onAuthStateChange: cb => { w.authCb = cb; }
    },
    from: table
  };
  const ls = store(opts.local); const ss = store(opts.cache);
  const root = { style: {}, classList: { toggle() {}, add() {}, remove() {} }, setAttribute() {}, dataset: {} };
  const win = {
    atlasSupabase: opts.noClient ? null : supa, ATLAS_CONFIG: { API_BASE: BASE },
    addEventListener(n, f) { (w.listeners[n] = w.listeners[n] || []).push(f); },
    dispatchEvent(e) { (w.listeners[e.type] || []).forEach(f => f(e)); return true; },
    matchMedia: () => ({ matches: false, addEventListener() {} }), navigator: {}, Notification: undefined
  };
  const location = {
    pathname: opts.path, href: BASE + opts.path, origin: BASE, hostname: 'localhost', port: '5000',
    replace: u => w.redirects.push(u), reload: () => { w.reloads++; }
  };
  const ctx = {
    window: win, document: { documentElement: root, currentScript: { src: BASE + '/assets/js/app-core.js' },
      querySelector: () => null, addEventListener() {}, getElementById: () => null, querySelectorAll: () => [] },
    sessionStorage: ss, localStorage: ls, location, URL, URLSearchParams, Headers, CustomEvent: class { constructor(t) { this.type = t; } },
    setInterval: () => 0, setTimeout, console, Promise,
    fetch: async (url, o) => {
      w.calls.push({ url, auth: new Headers(o && o.headers).get('Authorization'), method: (o && o.method) || 'GET' });
      return { status: statuses.length > 1 ? statuses.shift() : statuses[0] };
    }
  };
  win.document = ctx.document; win.location = location; win.sessionStorage = ss; win.localStorage = ls;
  Object.assign(win, { URL, Headers, CustomEvent: ctx.CustomEvent });
  ctx.self = win; ctx.globalThis = win;
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  w.win = win; w.ss = ss; w.ls = ls; w.root = root;
  return w;
}

const tick = () => new Promise(r => setTimeout(r, 15));
const chair = (dept, extra) => ({ id: 'u1', email: 'chair@psu.palawan.edu.ph', full_name: dept + ' Chairperson', role: 'chairperson', dept, faculty_id: null, ...extra });
const prof = { id: 'u1', email: 'profmaricar@psu.palawan.edu.ph', full_name: 'Prof. Maricar Dela Cruz', role: 'faculty', dept: 'IT', faculty_id: 'f1' };
const DASH = BASE + '/pages/dashboard.html', FAC = BASE + '/faculty/dashboard.html', LOGIN = BASE + '/pages/login.html';
const check = (name, ok, detail) => results.push({ name, ok: Boolean(ok), detail: ok ? '' : JSON.stringify(detail) });

(async () => {
  let w = world({ path: '/pages/dashboard.html', session: false, cache: { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'x' } });
  await tick();
  check('no session -> login (expired), page stays hidden, cache cleared',
    w.redirects[0] === LOGIN + '?reason=expired' && w.root.style.visibility === 'hidden' && w.ss.length === 0, w.redirects);

  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), cache: { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'IT Chairperson', atlasEmail: 'chair@psu.palawan.edu.ph' } });
  const u = await w.win.atlasAuth.ready;
  check('chairperson on dashboard: ready, page shown, no redirect',
    u && u.dept === 'IT' && w.root.style.visibility === '' && !w.redirects.length && !w.reloads, [u, w.redirects, w.reloads]);

  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), cache: { atlasRole: 'chairperson', atlasDept: 'CS', atlasUser: 'x' } });
  await tick();
  check('forged atlasDept=CS is rewritten from the profile, then the page reloads once',
    w.ss.getItem('atlasDept') === 'IT' && w.reloads === 1, [w.ss._m, w.reloads]);

  w = world({ path: '/pages/dashboard.html', profile: prof, faculty: { name: prof.full_name }, cache: { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'x' } });
  await tick();
  check('faculty opening the chairperson dashboard by URL goes to the faculty dashboard',
    w.redirects[0] === FAC && w.ss.getItem('atlasRole') === 'faculty', [w.redirects, w.ss._m]);

  w = world({ path: '/faculty/dashboard.html', profile: chair('CS') });
  await tick();
  check('chairperson opening the faculty dashboard goes to the chairperson dashboard', w.redirects[0] === DASH, w.redirects);

  w = world({ path: '/faculty/dashboard.html', profile: prof, faculty: { name: prof.full_name }, cache: { atlasRole: 'faculty', atlasDept: 'IT', atlasUser: prof.full_name, atlasEmail: prof.email, atlasFaculty: prof.full_name } });
  const fu = await w.win.atlasAuth.ready;
  check('faculty on the faculty dashboard: ready with the linked faculty name', fu && fu.facultyName === prof.full_name && !w.redirects.length, [fu, w.redirects]);

  w = world({ path: '/app/menu.html', profile: chair('MB'), cache: { atlasRole: 'chairperson', atlasDept: 'MB', atlasUser: 'MB Chairperson', atlasEmail: 'chair@psu.palawan.edu.ph' } });
  check('app pages accept any signed-in role', Boolean(await w.win.atlasAuth.ready) && !w.redirects.length, w.redirects);

  for (const [label, p, f, reason] of [
    ['admin account', { ...chair('IT'), role: 'admin', dept: null }, null, 'admin'],
    ['account without a profile', null, null, 'noprofile'],
    ['chairperson without a department', chair(null), null, 'nodept'],
    ['faculty without a faculty record', { ...prof, faculty_id: null }, null, 'nofaculty']]) {
    w = world({ path: '/pages/dashboard.html', profile: p, faculty: f });
    await tick();
    check(label + ' -> signed out and sent to login (' + reason + ')',
      w.redirects[0] === LOGIN + '?reason=' + reason && w.signedOut === 1, [w.redirects, w.signedOut]);
  }

  w = world({ path: '/pages/dashboard.html', dbError: true, profile: chair('IT') });
  await tick();
  check('a database/network error does not sign the user out', w.redirects[0] === LOGIN + '?reason=offline' && w.signedOut === 0, [w.redirects, w.signedOut]);

  w = world({ path: '/pages/dashboard.html', noClient: true });
  await tick();
  check('missing Supabase config -> login says config', w.redirects[0] === LOGIN + '?reason=config', w.redirects);

  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), cache: { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'IT Chairperson', atlasEmail: 'chair@psu.palawan.edu.ph' } });
  let r = await w.win.atlasFetch(BASE + '/rooms?dept=IT');
  check('atlasFetch sends Authorization: Bearer <access token>', r.status === 200 && w.calls[0].auth === 'Bearer tok1', w.calls);

  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), statuses: [401, 200], cache: { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'IT Chairperson', atlasEmail: 'chair@psu.palawan.edu.ph' } });
  r = await w.win.atlasFetch(BASE + '/rooms?dept=IT');
  check('a 401 refreshes the token once and retries', r.status === 200 && w.calls.length === 2 && w.calls[1].auth === 'Bearer tok2' && w.signedOut === 0, [w.calls, w.signedOut]);

  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), statuses: [401], cache: { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'IT Chairperson', atlasEmail: 'chair@psu.palawan.edu.ph' } });
  await w.win.atlasFetch(BASE + '/rooms?dept=IT');
  check('a 401 that survives the refresh signs out and goes to login', w.signedOut === 1 && w.redirects.pop() === LOGIN + '?reason=expired' && w.ss.length === 0, [w.signedOut, w.redirects]);

  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), statuses: [403], cache: { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'IT Chairperson', atlasEmail: 'chair@psu.palawan.edu.ph' } });
  r = await w.win.atlasFetch(BASE + '/rooms?dept=CS');
  check('a 403 (wrong department) is returned to the page and does not sign out', r.status === 403 && w.signedOut === 0, w.signedOut);

  const chairCache = { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'IT Chairperson', atlasEmail: 'chair@psu.palawan.edu.ph' };
  w = world({ path: '/app/account.html', profile: chair('IT'), cache: chairCache,
    local: { 'sb-abc-auth-token': '{}', atlasRememberedEmail: 'a', atlasApp: '{"theme":"dark","textSize":"large"}',
             'facultyData::IT': '[]', 'lastGAResult::CS': '[]', atlasDeptMigrated: '1', facultyProfiles: '{}' } });
  await w.win.atlasAuth.ready;
  check('page start deletes the old per-department data keys and the migration flag',
    ['facultyData::IT', 'lastGAResult::CS', 'atlasDeptMigrated', 'facultyProfiles'].every(k => w.ls.getItem(k) === null), w.ls._m);
  check('page start keeps the device settings', w.ls.getItem('atlasApp') !== null);
  w.ls.setItem('lastGAResult::IT', '[]'); w.ls.setItem('coverageData::IT', '{}'); w.ls.setItem('atlasAnalyticsCache::IT', '{}');
  w.ls.setItem('systemSettings::IT', '{}'); w.ls.setItem('roomsData::IT', '{}'); w.ls.setItem('softConstraintsData::IT', '{}');
  w.ls.setItem('atlasCache:u1:IT:chair', '{}');
  let loggedOut = false; w.win.addEventListener('atlas:logout', () => { loggedOut = true; });
  await w.win.atlasLogout();
  const post = w.calls.find(c => c.url.endsWith('/auth/logout'));
  check('logout: audit call, signOut, session cache and sb- keys cleared, event fired',
    post && post.method === 'POST' && post.auth === 'Bearer tok1' && w.signedOut === 1 && w.ss.length === 0 &&
    w.ls.getItem('sb-abc-auth-token') === null && w.ls.getItem('atlasRememberedEmail') === null && loggedOut, [w.calls, w.ls._m]);
  check('logout clears every per-department working key and the data cache',
    ['lastGAResult::IT', 'coverageData::IT', 'atlasAnalyticsCache::IT', 'systemSettings::IT', 'roomsData::IT', 'softConstraintsData::IT',
     'atlasCache:u1:IT:chair', 'atlasCacheOwner'].every(k => w.ls.getItem(k) === null), w.ls._m);
  check('logout keeps only the device settings (theme, text size)', w.ls.getItem('atlasApp') !== null);

  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), cache: chairCache,
    local: { atlasCacheOwner: 'someone-else', 'atlasCache:someone-else:IT:chair': '{}', atlasApp: '{}' } });
  await w.win.atlasAuth.ready;
  check('a different user on the same computer starts with an empty data cache',
    w.ls.getItem('atlasCache:someone-else:IT:chair') === null && w.ls.getItem('atlasCacheOwner') === 'u1' && w.ls.getItem('atlasApp') !== null, w.ls._m);
  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), cache: chairCache,
    local: { atlasCacheOwner: 'u1', 'atlasCache:u1:IT:chair': '{}' } });
  await w.win.atlasAuth.ready;
  check('the same user keeps their short-lived cache', w.ls.getItem('atlasCache:u1:IT:chair') !== null, w.ls._m);

  w = world({ path: '/pages/dashboard.html', profile: chair('IT'), cache: { atlasRole: 'chairperson', atlasDept: 'IT', atlasUser: 'IT Chairperson', atlasEmail: 'chair@psu.palawan.edu.ph' } });
  await w.win.atlasAuth.ready; w.authCb('SIGNED_OUT'); 
  check('signing out in another tab sends this tab to login', w.redirects.pop() === LOGIN + '?reason=signedout', w.redirects);

  w = world({ path: '/pages/login.html', session: false });
  check('the login page is not guarded', (await w.win.atlasAuth.ready) === null && w.root.style.visibility !== 'hidden' && !w.redirects.length, w.redirects);

  console.log(JSON.stringify(results));
})().catch(e => { console.log(JSON.stringify([{ name: 'harness crashed', ok: false, detail: String(e && e.stack || e) }])); });