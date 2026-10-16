/* ============================================================
   ATLAS PSU - shared loading spinner and rubber band (UI only)
   One spinner for every page: it covers the page from the first paint until the page, the sign in check
   and (on the dashboards) the data are ready, and again while a link to another page opens.
   window.atlasLoader.show() / .hide() can be used by any script. Rubber band: on touch screens a pull past
   the top or bottom of the page stretches it and springs back.
   ============================================================ */
(function () {
  'use strict';
  var root = document.documentElement;
  if (!document.head || typeof clearTimeout !== 'function') return;     // not a real page (test harness)
  var css =
    'html.atlas-loading::before{content:"";position:fixed;inset:0;z-index:2147483000;background:var(--bg-page,#faf7f3);opacity:1;transition:opacity .3s ease}' +
    'html.atlas-loading::after{content:"";position:fixed;z-index:2147483001;top:50%;left:50%;width:32px;height:32px;margin:-16px 0 0 -16px;box-sizing:border-box;' +
    'border:3px solid var(--border-default,#e3dbd2);border-top-color:var(--clr-primary-500,#c0440a);border-radius:50%;animation:atlas-spin .8s linear infinite;transition:opacity .3s ease}' +
    'html.atlas-loading.atlas-loading-out::before,html.atlas-loading.atlas-loading-out::after{opacity:0;pointer-events:none}' +
    'html[data-theme="dark"].atlas-loading::before{background:var(--bg-page,#17120f)}' +
    'html.atlas-loading{overflow:hidden}' +
    '@keyframes atlas-spin{to{transform:rotate(360deg)}}';
  try {
    var st = document.createElement('style');
    st.id = 'atlasLoaderCss';
    st.textContent = css;
    (document.head || root).appendChild(st);
  } catch (e) { /* no styling, no loader */ }

  var timer = null, failsafe = null;
  function show(maxMs) {
    clearTimeout(timer);
    root.classList.remove('atlas-loading-out');
    root.classList.add('atlas-loading');
    clearTimeout(failsafe);
    failsafe = setTimeout(hide, maxMs || 8000);
  }
  function hide() {
    clearTimeout(failsafe);
    if (!root.classList.contains('atlas-loading')) return;
    root.classList.add('atlas-loading-out');
    clearTimeout(timer);
    timer = setTimeout(function () { root.classList.remove('atlas-loading', 'atlas-loading-out'); }, 320);
  }
  window.atlasLoader = { show: show, hide: hide };
  show(10000);

  function whenReady() {
    var waits = [];
    var noop = function () {};
    if (window.atlasAuth && window.atlasAuth.ready) waits.push(Promise.resolve(window.atlasAuth.ready).catch(noop));
    if (window.atlasPageReady) waits.push(Promise.resolve(window.atlasPageReady).catch(noop));      // a page can hold the loader until its own data is shown
    if (window.atlasData && window.atlasData.init && /\/(pages|faculty)\/dashboard/.test(location.pathname)) {
      try { waits.push(Promise.resolve(window.atlasData.init()).catch(noop)); } catch (e) { /* not ready */ }
    }
    return Promise.all(waits);
  }
  function onLoaded() { whenReady().then(function () { requestAnimationFrame(hide); }); }
  if (document.readyState === 'complete') onLoaded(); else window.addEventListener('load', onLoaded);
  window.addEventListener('pageshow', function (e) { if (e.persisted) hide(); });

  /* opening another page of the site */
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download')) return;
    var u;
    try { u = new URL(a.href, location.href); } catch (x) { return; }
    if (!/^https?:$/.test(u.protocol) || u.origin !== location.origin) return;
    if (u.pathname === location.pathname && u.search === location.search) return;
    if (!/(\.html|\/)$/.test(u.pathname)) return;
    setTimeout(function () { if (!e.defaultPrevented) show(6000); }, 80);
  });

  /* ---------- rubber band ---------- */
  if (!('ontouchstart' in window)) return;
  var BLOCK = 'input,select,textarea,[contenteditable],[role="dialog"],.modal-overlay,.tt-viewer,.auth-modal,[data-no-rubber]';
  var MAX = 110, g = null;
  function reduce() { return root.getAttribute('data-motion') === 'reduce'; }
  function curve(d) { return MAX * (1 - Math.exp(-d / (MAX * 2.2))); }
  function innerScroller(t, stop) {
    for (; t && t !== stop && t !== document.body && t !== root; t = t.parentElement) {
      var o = getComputedStyle(t).overflowY;
      if ((o === 'auto' || o === 'scroll') && t.scrollHeight > t.clientHeight + 2) return t;
    }
    return null;
  }
  function wrapperEl() { return document.querySelector('.app-shell, .auth-shell, .ld-hero'); }
  function settle(el) {
    if (!el) return;
    el.style.transition = 'transform .6s cubic-bezier(.22,1.25,.36,1)';
    el.style.transform = '';
    setTimeout(function () { el.style.transition = ''; el.style.willChange = ''; }, 650);
  }
  document.addEventListener('touchstart', function (e) {
    g = null;
    var t = e.target;
    if (reduce() || e.touches.length !== 1 || !t.closest || t.closest(BLOCK)) return;
    var panel = t.closest('.panel');
    if (innerScroller(t, panel)) return;
    var el = panel || wrapperEl();
    if (!el) return;
    var sc = panel || document.scrollingElement || root;
    g = { x: e.touches[0].clientX, y: e.touches[0].clientY, panel: panel, sc: sc, el: el, on: false, y0: 0, dir: 0 };
  }, { passive: true });
  document.addEventListener('touchmove', function (e) {
    if (!g) return;
    if (e.defaultPrevented) { g = null; return; }              // the dashboard swipe / pull gesture owns it
    var y = e.touches[0].clientY, dy = y - g.y, dx = e.touches[0].clientX - g.x;
    if (!g.on) {
      if (Math.abs(dy) < 6) return;
      if (Math.abs(dx) > Math.abs(dy)) { g = null; return; }
      var sc = g.sc;
      var atTop = sc.scrollTop <= 0;
      var atBottom = sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 1;
      if (dy > 0 && atTop && !g.panel) g.dir = 1;              // panels pull down to refresh on their own
      else if (dy < 0 && atBottom) g.dir = -1;
      else { g = null; return; }
      g.on = true; g.y0 = y;
      g.el.style.willChange = 'transform';
    }
    var d = (y - g.y0) * g.dir;
    if (d <= 0) { g.el.style.transition = 'none'; g.el.style.transform = ''; var el0 = g.el; g = null; settle(el0); return; }
    if (e.cancelable) e.preventDefault();
    g.el.style.transition = 'none';
    g.el.style.transform = 'translate3d(0,' + (g.dir * curve(d)) + 'px,0)';
  }, { passive: false });
  function release() { if (g && g.on) settle(g.el); g = null; }
  document.addEventListener('touchend', release);
  document.addEventListener('touchcancel', release);
})();

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

/* ============================================================
   ATLAS PSU - site dialogs, offline screen, offline page worker (UI only)
   window.atlasDialog.alert(message, {title, tone}) and .confirm(message, {title, ok, cancel, danger})
   replace the browser's "<site> says" boxes (window.alert is routed here too). The offline screen opens
   whenever the device loses its connection and closes when it is back.
   ============================================================ */
(function () {
  'use strict';
  if (typeof document === 'undefined' || !document.head || typeof window.addEventListener !== 'function' || typeof clearTimeout !== 'function') return;
  var root = document.documentElement;
  var css =
    '.ad-ov{position:fixed;inset:0;z-index:2147483200;display:flex;align-items:center;justify-content:center;padding:20px;background:var(--bg-overlay,rgba(30,20,12,.5));-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);opacity:0;transition:opacity .22s ease}' +
    '.ad-ov.on{opacity:1}' +
    '.ad-card{width:100%;max-width:400px;padding:26px 22px 20px;text-align:center;background:var(--card-bg,#fff);color:var(--text-primary,#2a2119);border:1px solid var(--border-subtle,#eee4da);border-radius:22px;box-shadow:var(--shadow-xl,0 20px 50px rgba(0,0,0,.28));transform:translateY(16px) scale(.95);transition:transform .34s cubic-bezier(.34,1.56,.64,1)}' +
    '.ad-ov.on .ad-card{transform:none}' +
    '.ad-ic{width:54px;height:54px;margin:0 auto 14px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--warn-soft,rgba(217,146,43,.16));color:var(--warn,#b9770e)}' +
    '.ad-ic.info{background:var(--ok-soft,rgba(42,127,134,.14));color:var(--ok,#2a7f86)}' +
    '.ad-ic.danger{background:var(--bad-soft,rgba(180,55,43,.14));color:var(--bad,#b4372b)}' +
    '.ad-ic svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}' +
    '.ad-title{margin:0 0 6px;font-size:1.1rem;font-weight:700;line-height:1.3}' +
    '.ad-msg{margin:0 0 20px;font-size:.92rem;line-height:1.55;color:var(--text-secondary,#6e6358);white-space:pre-line;overflow-wrap:anywhere;max-height:40vh;overflow:auto}' +
    '.ad-btns{display:flex;gap:10px}' +
    '.ad-btn{flex:1;min-height:44px;padding:0 16px;font:inherit;font-weight:600;font-size:.95rem;border-radius:999px;cursor:pointer;color:var(--text-primary,#2a2119);background:transparent;border:1px solid var(--border-default,#d8cdc1);transition:transform .15s ease,background-color .2s ease,border-color .2s ease;touch-action:manipulation}' +
    '.ad-btn:hover{background:var(--bg-surface-3,rgba(0,0,0,.05))}.ad-btn:active{transform:scale(.97)}' +
    '.ad-btn.primary{color:#fff;background:var(--clr-primary-500,#c0440a);border-color:transparent}.ad-btn.primary:hover{background:var(--btn-hover,#9a3608)}' +
    '.ad-btn.danger{color:#fff;background:#c0392b;border-color:transparent}.ad-btn.danger:hover{background:#a53125}' +
    '.ad-btn:focus-visible{outline:2px solid var(--clr-primary-500,#c0440a);outline-offset:2px}' +
    /* offline screen */
    '.ao-ov{position:fixed;inset:0;z-index:2147483300;display:flex;align-items:center;justify-content:center;padding:24px;text-align:center;background:var(--bg-page,#faf7f3);color:var(--text-primary,#2a2119);opacity:0;visibility:hidden;transition:opacity .3s ease,visibility 0s linear .3s}' +
    '.ao-ov.on{opacity:1;visibility:visible;transition:opacity .3s ease}' +
    '.ao-box{max-width:380px;transform:translateY(12px);transition:transform .4s cubic-bezier(.22,.8,.3,1)}.ao-ov.on .ao-box{transform:none}' +
    '.ao-box svg{width:150px;height:auto;margin:0 auto 18px;display:block;color:var(--clr-primary-500,#c0440a)}' +
    '.ao-box h2{margin:0 0 8px;font-size:1.4rem;font-weight:700}' +
    '.ao-box p{margin:0 0 22px;font-size:.95rem;line-height:1.55;color:var(--text-secondary,#6e6358)}' +
    '.ao-box .ad-btn{flex:none;min-width:160px}' +
    '.ao-note{margin:14px 0 0!important;font-size:.82rem!important;color:var(--text-muted,#9a8e82)!important;min-height:1.2em}' +
    '@keyframes ao-pulse{0%,100%{opacity:.35}50%{opacity:1}}.ao-box .ao-dot{animation:ao-pulse 1.6s ease-in-out infinite}' +
    '@media (max-width:480px){.ad-card{padding:22px 18px 18px}}' +
    'html[data-motion="reduce"] .ad-card,html[data-motion="reduce"] .ao-box{transition:none}';
  var st = document.createElement('style');
  st.id = 'atlasDialogCss';
  st.textContent = css;
  document.head.appendChild(st);

  var ICONS = {
    warn: '<path d="M12 3 2.5 20h19L12 3z"/><path d="M12 10v4.5M12 17.6v.1"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.1"/>',
    danger: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.4v.1"/>',
    ask: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1.1.9-1.1 1.7M12 16.6v.1"/>'
  };

  var queue = [], open = false;
  function guess(msg) {
    return /fail|cannot|can't|could not|error|refus/i.test(msg) ? { title: 'Something went wrong', tone: 'danger' }
      : /wait|not saved|first|please|before/i.test(msg) ? { title: 'One moment', tone: 'warn' }
      : { title: 'ATLAS PSU', tone: 'info' };
  }
  function next() {
    if (open || !queue.length) return;
    open = true;
    var job = queue.shift(), o = job.opts;
    var prevFocus = document.activeElement;
    var ov = document.createElement('div');
    ov.className = 'ad-ov';
    ov.innerHTML = '<div class="ad-card" role="alertdialog" aria-modal="true"><div class="ad-ic ' + o.tone + '"><svg viewBox="0 0 24 24" aria-hidden="true">' +
      ICONS[o.confirm ? (o.danger ? 'danger' : 'ask') : o.tone === 'danger' ? 'danger' : o.tone === 'info' ? 'info' : 'warn'] + '</svg></div>' +
      '<h2 class="ad-title"></h2><p class="ad-msg"></p><div class="ad-btns"></div></div>';
    var card = ov.firstChild;
    card.querySelector('.ad-title').textContent = o.title;
    card.querySelector('.ad-msg').textContent = job.msg;
    card.setAttribute('aria-label', o.title);
    var btns = card.querySelector('.ad-btns');
    function mk(label, cls, value) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'ad-btn ' + cls; b.textContent = label;
      b.addEventListener('click', function () { close(value); });
      btns.appendChild(b); return b;
    }
    if (o.confirm) mk(o.cancel, '', false);
    var okBtn = mk(o.ok, o.danger ? 'danger' : 'primary', true);
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); close(o.confirm ? false : true); }
      else if (e.key === 'Tab') {
        var f = card.querySelectorAll('button'); if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    var closed = false;
    function close(value) {
      if (closed) return; closed = true;
      document.removeEventListener('keydown', onKey, true);
      ov.classList.remove('on');
      setTimeout(function () { if (ov.parentNode) ov.parentNode.removeChild(ov); open = false; try { if (prevFocus && prevFocus.focus) prevFocus.focus(); } catch (e) { /* gone */ } job.resolve(value); next(); }, 220);
    }
    ov.addEventListener('mousedown', function (e) { if (e.target === ov && !o.confirm) close(true); });
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(ov);
    requestAnimationFrame(function () { ov.classList.add('on'); okBtn.focus(); });
  }
  function ask(msg, opts, confirm) {
    msg = String(msg == null ? '' : msg);
    var g = guess(msg);
    opts = opts || {};
    var o = {
      confirm: confirm,
      title: opts.title || (confirm ? 'Please confirm' : g.title),
      tone: opts.tone || g.tone,
      ok: opts.ok || (confirm ? 'Confirm' : 'OK'),
      cancel: opts.cancel || 'Cancel',
      danger: !!opts.danger
    };
    return new Promise(function (resolve) {
      var go = function () { queue.push({ msg: msg, opts: o, resolve: resolve }); next(); };
      if (document.body) go(); else document.addEventListener('DOMContentLoaded', go);
    });
  }
  window.atlasDialog = {
    alert: function (m, o) { return ask(m, o, false); },
    confirm: function (m, o) { return ask(m, o, true); }
  };
  window.alert = function (m) { ask(m, null, false); };

  /* ---------- offline screen ---------- */
  var off = null, checking = false;
  var WIFI = '<svg viewBox="0 0 160 120" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="6" y="14" width="148" height="92" rx="16" stroke="var(--border-default,#d8cdc1)" stroke-width="3"/>' +
    '<path d="M44 58c20-17 52-17 72 0" opacity=".45"/><path d="M58 72c13-10 31-10 44 0"/>' +
    '<circle class="ao-dot" cx="80" cy="86" r="4" fill="currentColor" stroke="none"/>' +
    '<path d="M36 28 124 96" stroke="var(--bad,#b4372b)"/></svg>';
  function buildOffline() {
    off = document.createElement('div');
    off.className = 'ao-ov';
    off.setAttribute('role', 'alert');
    off.innerHTML = '<div class="ao-box">' + WIFI + '<h2>No internet connection</h2>' +
      '<p>Check your Wi-Fi or mobile data. ATLAS PSU will carry on as soon as you are back online.</p>' +
      '<button type="button" class="ad-btn primary" id="aoRetry">Try again</button><p class="ao-note" id="aoNote" aria-live="polite"></p></div>';
    document.body.appendChild(off);
    off.querySelector('#aoRetry').addEventListener('click', retry);
  }
  function setOffline(is) {
    if (!document.body) { document.addEventListener('DOMContentLoaded', function () { setOffline(is); }); return; }
    if (is && !off) buildOffline();
    if (!off) return;
    if (is) { requestAnimationFrame(function () { off.classList.add('on'); }); }
    else {
      off.classList.remove('on');
      if (window.__atlasOfflineFallback) { try { location.reload(); } catch (e) { /* ignore */ } }
    }
  }
  function retry() {
    if (checking) return;
    checking = true;
    var note = off.querySelector('#aoNote'), btn = off.querySelector('#aoRetry');
    btn.disabled = true; btn.classList.add('is-busy'); note.textContent = 'Checking...';
    var done = function (ok) {
      checking = false; btn.disabled = false; btn.classList.remove('is-busy');
      if (ok) { note.textContent = ''; setOffline(false); } else note.textContent = 'Still offline. Try again in a moment.';
    };
    if (typeof fetch !== 'function') { done(navigator.onLine); return; }
    fetch(location.pathname + '?_=' + Date.now(), { method: 'HEAD', cache: 'no-store' }).then(function () { done(true); }, function () { done(false); });
  }
  window.addEventListener('offline', function () { setOffline(true); });
  window.addEventListener('online', function () { setOffline(false); });
  if (navigator.onLine === false) setOffline(true);

  /* ---------- page worker: shows the offline / 404 page when a page cannot be fetched ---------- */
  try {
    if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
      var src = document.currentScript && document.currentScript.src;
      var base = src ? src.replace(/assets\/js\/app-core\.js.*$/, '') : '/';
      window.addEventListener('load', function () { navigator.serviceWorker.register(base + 'sw.js').catch(function () { /* optional */ }); });
    }
  } catch (e) { /* optional */ }
})();