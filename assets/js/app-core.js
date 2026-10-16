/* ============================================================
   ATLAS PSU - app core (loaded first on every page)
   Device-level preferences: theme, text size, motion, alerts.
   Stored in localStorage under "atlasApp".
   ============================================================ */
(function () {
  'use strict';

  const KEY = 'atlasApp';
  const DEFAULTS = {
    theme: 'light',            // light | dark | auto (device) | schedule (by local time)
    nightStart: '18:00',
    nightEnd: '06:00',
    textSize: 'default',       // small | default | large
    reduceMotion: false,
    startPage: '0',            // index of the dashboard panel opened first
    sound: true,
    vibrate: true,
    system: false,             // system notifications (needs browser permission)
    quiet: false,              // mute sound, vibration and system alerts
    quietStart: '22:00',
    quietEnd: '06:00',
    notifyOptimization: true,
    notifyViolations: true
  };

  const root = document.documentElement;

  function readJSON(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key));
      return value == null ? fallback : value;
    } catch { return fallback; }
  }

  let settings = Object.assign({}, DEFAULTS, readJSON(KEY, {}));

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch { /* storage unavailable */ }
  }

  function toHours(text) {
    const parts = String(text).split(':');
    return Number(parts[0]) + (Number(parts[1]) || 0) / 60;
  }

  function inWindow(start, end) {
    const now = new Date();
    const hour = now.getHours() + now.getMinutes() / 60;
    const s = toHours(start);
    const e = toHours(end);
    return s > e ? (hour >= s || hour < e) : (hour >= s && hour < e);
  }

  function isDark() {
    if (settings.theme === 'dark') return true;
    if (settings.theme === 'auto') return window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (settings.theme === 'schedule') return inWindow(settings.nightStart, settings.nightEnd);
    return false;
  }

  function applyTheme() {
    const dark = isDark();
    root.setAttribute('data-theme', dark ? 'dark' : 'light');
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? '#17120f' : '#9a3608');
  }

  function applyDisplay() {
    root.setAttribute('data-text', settings.textSize);
    root.setAttribute('data-motion', settings.reduceMotion ? 'reduce' : 'full');
  }

  function apply() { applyTheme(); applyDisplay(); }

  /* ---------- Alerts (sound, vibration, system notification) ---------- */
  function isQuiet() {
    return Boolean(settings.quiet) && inWindow(settings.quietStart, settings.quietEnd);
  }

  function beep() {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.7);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.75);
    } catch { /* audio not available */ }
  }

  function alertUser(title, body, tag) {
    if (isQuiet()) return;
    if (settings.sound) beep();
    if (settings.vibrate && navigator.vibrate) navigator.vibrate([200, 100, 200]);
    if (settings.system && 'Notification' in window && Notification.permission === 'granted') {
      try { new Notification(title, { body, tag, icon: '../assets/images/favicon.png' }); } catch { /* blocked */ }
    }
  }

  /* ---------- Session helpers ---------- */
  const session = () => ({
    role: sessionStorage.getItem('atlasRole') || 'chairperson',
    user: sessionStorage.getItem('atlasUser') || '',
    faculty: sessionStorage.getItem('atlasFaculty') || '',
    email: sessionStorage.getItem('atlasEmail') || '',
    dept: sessionStorage.getItem('atlasDept') || ''
  });

  /* ---------- Department scope ----------
     The department comes from the signed-in user's profile and lives in sessionStorage 'atlasDept' (display cache).
     Since Part 16 the department's data lives in Supabase (assets/js/data-store.js). The base names below are the
     OLD browser data keys (<base>::<dept>); nothing writes them any more and the auth module deletes them. */
  const DEPT_CODES = ['IT', 'CS', 'MB', 'ES', 'MedB'];
  const DEPT_BASE_KEYS = [
    'facultyData', 'subjectsData', 'classSizesData', 'academicMode', 'systemSettings',
    'lastGAResult', 'atlasAnalyticsCache', 'softConstraintsData', 'roomsData',
    'atlasCurriculumCache', 'atlasDataVersion', 'coverageData', 'atlasDeptMigrated', 'facultyProfiles'
  ];

  function currentDept() {
    const d = sessionStorage.getItem('atlasDept');
    return DEPT_CODES.includes(d) ? d : 'IT';
  }

  function dk(base, dept) { return base + '::' + (dept || currentDept()); }


  /* Logout: pages listen for 'atlas:logout' and empty everything they hold in memory. */
  function logout() {
    try { window.dispatchEvent(new CustomEvent('atlas:logout')); } catch { /* ignore */ }
    sessionStorage.clear();
  }

  /* Back/forward cache: a page restored for another department is emptied and reloaded. */
  const renderedDept = sessionStorage.getItem('atlasDept') || '';
  window.addEventListener('pageshow', () => {
    const now = sessionStorage.getItem('atlasDept') || '';
    if (now === renderedDept) return;
    try { window.dispatchEvent(new CustomEvent('atlas:logout')); } catch { /* ignore */ }
    window.location.reload();
  });

  window.atlasDept = {
    CODES: DEPT_CODES, BASE_KEYS: DEPT_BASE_KEYS, rendered: renderedDept,
    current: currentDept, dk, logout
  };
  window.atlasLogout = logout;

  window.atlasApp = {
    DEFAULTS,
    get: key => settings[key],
    all: () => Object.assign({}, settings),
    set(key, value) { settings[key] = value; save(); apply(); },
    reset() { settings = Object.assign({}, DEFAULTS); save(); apply(); },
    isDark, isQuiet, beep, alert: alertUser, session,
    startPanel(count) {
      const index = Number(settings.startPage) || 0;
      return index >= 0 && index < count ? index : 0;
    },
    readJSON,
    dashboardUrl(prefix) {
      return (prefix || '') + (session().role === 'faculty' ? 'faculty/dashboard.html' : 'pages/dashboard.html');
    }
  };

  apply();
  document.addEventListener('DOMContentLoaded', applyTheme);
  setInterval(() => { if (settings.theme === 'schedule') applyTheme(); }, 60000);
  if (window.matchMedia) {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => { if (settings.theme === 'auto') applyTheme(); };
    if (query.addEventListener) query.addEventListener('change', onChange);
  }
})();

/* ============================================================
   Supabase Auth: session check, role gate, API calls with a Bearer token, logout.
   sessionStorage atlasRole / atlasDept / atlasUser / atlasEmail / atlasFaculty are only a DISPLAY cache,
   refilled from the profiles table on every page start. They are never trusted: the Flask API decides
   from the verified token, and every protected page re-checks the real Supabase session first.
   ============================================================ */
(function atlasAuthModule() {
  'use strict';
  var CACHE_KEYS = ['atlasRole', 'atlasDept', 'atlasUser', 'atlasEmail', 'atlasFaculty'];
  var scriptSrc = (document.currentScript && document.currentScript.src) || location.href;
  var LOGIN_URL = new URL('../../pages/login.html', scriptSrc).href;
  var DASH = {
    chairperson: new URL('../../pages/dashboard.html', scriptSrc).href,
    faculty: new URL('../../faculty/dashboard.html', scriptSrc).href
  };
  var cfg = window.ATLAS_CONFIG || {};
  var loggingOut = false;

  function sb() { return window.atlasSupabase || null; }

  function pageKind() {
    var p = location.pathname.replace(/\\/g, '/');
    if (/\/pages\/login\.html$/.test(p)) return 'login';
    if (/\/pages\/dashboard\.html$/.test(p)) return 'chairperson';
    if (/\/faculty\/[^/]*$/.test(p)) return 'faculty';
    if (/\/app\/[^/]*$/.test(p)) return 'any';
    return 'public';
  }

  function apiBase() {
    if (cfg.API_BASE) return String(cfg.API_BASE).replace(/\/+$/, '');
    if (window.AtlasDisplay && window.AtlasDisplay.resolveApiBase) return window.AtlasDisplay.resolveApiBase(location);
    return location.origin;
  }

  /* Browser keys that held working data (<base> or <base>::<dept>), the data-store cache, and the Supabase session.
     Device settings (atlasApp: theme, text size) are never touched. */
  var WORKING_BASES = ['facultyData', 'subjectsData', 'classSizesData', 'academicMode', 'systemSettings',
    'lastGAResult', 'atlasAnalyticsCache', 'softConstraintsData', 'roomsData', 'atlasCurriculumCache',
    'atlasDataVersion', 'coverageData', 'atlasDeptMigrated', 'facultyProfiles'];
  var OWNER_KEY = 'atlasCacheOwner';

  function isWorkingKey(k) {
    var base = k.split('::')[0];
    return WORKING_BASES.indexOf(base) >= 0;
  }

  /* what: 'legacy' = the old per-department data keys only; 'cache' = those plus the data-store cache and the owner mark;
     'all' = those plus the Supabase session keys. */
  function purgeLocal(what) {
    try {
      var drop = [];
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (!k) continue;
        if (isWorkingKey(k)) drop.push(k);
        else if (what !== 'legacy' && (k.indexOf('atlasCache:') === 0 || k === OWNER_KEY)) drop.push(k);
        else if (what === 'all' && (k.indexOf('sb-') === 0 || k === 'atlasRememberedEmail')) drop.push(k);
      }
      drop.forEach(function (k) { localStorage.removeItem(k); });
    } catch (e) { /* storage unavailable */ }
  }
  purgeLocal('legacy');                     // old per-department data keys are never used again

  function clearLocalAuth() {
    try { sessionStorage.clear(); } catch (e) { /* storage unavailable */ }
    try { if (window.atlasData && window.atlasData.clear) window.atlasData.clear(); } catch (e) { /* ignore */ }
    purgeLocal('all');
  }

  /* A different person on this computer starts with nothing from the previous one. */
  function claimBrowserFor(userId) {
    try {
      var owner = localStorage.getItem(OWNER_KEY);
      if (owner && owner !== userId) {
        purgeLocal('cache');
        try { window.dispatchEvent(new CustomEvent('atlas:userchanged')); } catch (e) { /* ignore */ }
      }
      localStorage.setItem(OWNER_KEY, userId);
    } catch (e) { /* storage unavailable */ }
  }

  function redirect(reason) {
    location.replace(LOGIN_URL + (reason ? '?reason=' + encodeURIComponent(reason) : ''));
  }

  async function signOutAndRedirect(reason) {
    try { if (sb()) await sb().auth.signOut(); } catch (e) { /* already signed out */ }
    clearLocalAuth();
    redirect(reason);
  }

  /* The real session and profile. Resolves {user} or {error}:
     config, nosession, offline, noprofile, nodept, nofaculty, admin */
  async function loadUser() {
    var client = sb();
    if (!client) return { error: 'config' };
    var s = await client.auth.getSession();
    var session = s && s.data && s.data.session;
    if (!session) return { error: 'nosession' };
    var q = await client.from('profiles').select('id,email,full_name,role,dept,faculty_id')
      .eq('id', session.user.id).maybeSingle();
    if (q.error) return { error: 'offline' };
    var p = q.data;
    if (!p) return { error: 'noprofile' };
    if (p.role === 'admin') return { error: 'admin' };
    if (p.role !== 'chairperson' && p.role !== 'faculty') return { error: 'noprofile' };
    if (!p.dept) return { error: 'nodept' };
    var facultyName = '';
    if (p.role === 'faculty') {
      if (!p.faculty_id) return { error: 'nofaculty' };
      var f = await client.from('faculty').select('name').eq('id', p.faculty_id).maybeSingle();
      if (f.error) return { error: 'offline' };
      if (!f.data) return { error: 'nofaculty' };
      facultyName = f.data.name;
    }
    return {
      user: {
        id: session.user.id, role: p.role, dept: p.dept, facultyName: facultyName, facultyId: p.faculty_id || null,
        email: p.email || session.user.email || '', name: p.full_name || p.email || ''
      }
    };
  }

  /* Fill the display cache from the profile. True when something changed. */
  function applyCache(u) {
    var want = {
      atlasRole: u.role, atlasDept: u.dept, atlasUser: u.name, atlasEmail: u.email,
      atlasFaculty: u.role === 'faculty' ? u.facultyName : ''
    };
    var changed = false;
    CACHE_KEYS.forEach(function (k) {
      var cur = sessionStorage.getItem(k) || '';
      if (cur === want[k]) return;
      changed = true;
      if (want[k]) sessionStorage.setItem(k, want[k]); else sessionStorage.removeItem(k);
    });
    return changed;
  }

  /* ---------- the page-start check ---------- */
  var kind = pageKind();
  var guarded = kind === 'chairperson' || kind === 'faculty' || kind === 'any';
  var auth = { user: null, kind: kind, LOGIN_URL: LOGIN_URL, DASH: DASH };

  function never() { return new Promise(function () { /* the page is navigating away */ }); }

  if (!guarded) {
    auth.ready = Promise.resolve(null);
  } else {
    document.documentElement.style.visibility = 'hidden';        // nothing shows before the check
    auth.ready = (async function () {
      var r;
      try { r = await loadUser(); } catch (e) { r = { error: 'offline' }; }
      if (r.error === 'offline' || r.error === 'config') { redirect(r.error); return never(); }
      if (r.error === 'nosession') { clearLocalAuth(); redirect('expired'); return never(); }
      if (r.error) { await signOutAndRedirect(r.error); return never(); }
      var u = r.user;
      if (kind !== 'any' && kind !== u.role) {                     // wrong page for this role
        applyCache(u);
        location.replace(DASH[u.role]);
        return never();
      }
      var changed = applyCache(u);
      if (changed && !sessionStorage.getItem('atlasAuthReload')) {  // page scripts already ran on a stale cache
        sessionStorage.setItem('atlasAuthReload', '1');
        location.reload();
        return never();
      }
      sessionStorage.removeItem('atlasAuthReload');
      claimBrowserFor(u.id);
      auth.user = u;
      document.documentElement.style.visibility = '';
      return u;
    })();
    if (sb()) {
      sb().auth.onAuthStateChange(function (event) {              // signed out in another tab
        if (event === 'SIGNED_OUT' && !loggingOut) { clearLocalAuth(); redirect('signedout'); }
      });
    }
  }

  /* ---------- API calls ---------- */
  async function accessToken(forceRefresh) {
    var client = sb();
    if (!client) return null;
    if (forceRefresh) {
      var r = await client.auth.refreshSession();
      return r && r.data && r.data.session ? r.data.session.access_token : null;
    }
    var s = await client.auth.getSession();           // supabase-js refreshes an expiring token here
    return s && s.data && s.data.session ? s.data.session.access_token : null;
  }

  /* The one fetch wrapper for the Flask API: waits for the page check, adds the Bearer token,
     retries once with a fresh token on a 401, and signs out + goes to login if it is still 401. */
  async function authFetch(url, opts) {
    await auth.ready;
    opts = opts || {};
    function send(token) {
      var h = new Headers(opts.headers || {});
      if (token) h.set('Authorization', 'Bearer ' + token);
      return fetch(url, Object.assign({}, opts, { headers: h }));
    }
    var res = await send(await accessToken(false));
    if (res.status === 401) {
      var fresh = await accessToken(true);
      if (fresh) res = await send(fresh);
      if (res.status === 401) await signOutAndRedirect('expired');
    }
    return res;
  }

  /* ---------- logout (the only caller is app/account.html) ---------- */
  async function logout() {
    loggingOut = true;
    try { window.dispatchEvent(new CustomEvent('atlas:logout')); } catch (e) { /* ignore */ }
    var client = sb();
    if (client) {
      try {
        var t = await accessToken(false);
        if (t) await fetch(apiBase() + '/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + t } });
      } catch (e) { /* the audit row is best effort */ }
      try { await client.auth.signOut(); } catch (e) { /* ignore */ }
    }
    clearLocalAuth();
  }

  auth.fetch = authFetch;
  auth.accessToken = accessToken;
  auth.loadUser = loadUser;
  auth.applyCache = applyCache;
  auth.clearLocalAuth = clearLocalAuth;
  auth.purgeLocal = purgeLocal;
  auth.apiBase = apiBase;
  auth.logout = logout;
  window.atlasAuth = auth;
  window.atlasFetch = authFetch;
  window.atlasLogout = logout;
  if (window.atlasDept) window.atlasDept.logout = logout;
})();