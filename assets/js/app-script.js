/* ============================================================
   ATLAS PSU - application pages (app/*.html)
   Menu, application settings, notifications, account,
   appearance and about. Works for chairpersons and faculty.
   ============================================================ */
(function () {
  'use strict';

  const app = window.atlasApp;
  const page = document.body.dataset.page;
  const LOGIN = '../pages/login.html';

  if (!sessionStorage.getItem('atlasUser')) {
    window.location.replace(LOGIN);
    return;
  }

  const session = app.session();
  const isFaculty = session.role === 'faculty';
  const DASHBOARD = isFaculty ? '../faculty/dashboard.html' : '../pages/dashboard.html';
  /* Department scope: only keys of the department chosen at login are read, exported or cleared. */
  const DEPT = (window.atlasDept && window.atlasDept.current()) || 'IT';
  const hasDept = Boolean(session.dept);
  let deptName = DEPT;            // replaced by the `name` of the department's file
  const isDesktop = () => window.matchMedia('(min-width: 901px)').matches;
  const $ = id => document.getElementById(id);

  if (page === 'menu' && isDesktop()) {
    window.location.replace('application-settings.html');
    return;
  }

  /* ---------- Helpers ---------- */
  function toast(message) {
    const el = $('toastNotif');
    el.textContent = message;
    el.className = 'toast-notif show';
    setTimeout(() => { el.className = 'toast-notif'; }, 3000);
  }

  function writeLocal(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
  }

  function download(name, data) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  /* The department's data (from the database, already filtered to this department) plus this device's settings. */
  function exportAll() {
    const data = { device: app.all() };
    const store = window.atlasData;
    if (store && store.dept() === DEPT && !isFaculty) {
      data.department = DEPT;
      data.faculty = store.faculty.list();
      data.classSizes = store.classSizes.get();
      data.rooms = store.rooms.get();
      data.period = store.settings.period();
      data.solver = store.settings.solver();
    }
    download('atlas-psu-data.json', data);
    toast('Data downloaded');
  }

  async function logout() {
    try { if (window.atlasLogout) await window.atlasLogout(); else sessionStorage.clear(); } catch { /* go to login anyway */ }
    window.location.href = LOGIN;
  }

  /* ---------- Navigation shell ---------- */
  const ICONS = {
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    notifications: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    account: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    appearance: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    about: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>'
  };
  const SECTIONS = [
    ['application-settings.html', 'settings', 'Application settings'],
    ['notifications.html', 'notifications', 'Notification settings'],
    ['account.html', 'account', 'Account settings'],
    ['appearance.html', 'appearance', 'Appearance'],
    ['about.html', 'about', 'About']
  ];
  const svg = (name, cls) => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  const THEME_LABELS = { light: 'Light', dark: 'Night', auto: 'Automatic', schedule: 'By time' };

  function renderNav() {
    $('appNav').innerHTML = SECTIONS.map(([href, key, label]) => `
      <a class="app-nav-link" href="${href}"${page === key ? ' aria-current="page"' : ''}>
        ${svg(key, 'app-nav-ic')}<span>${label}</span>
        ${key === 'appearance' ? `<em class="app-nav-value" id="navTheme">${THEME_LABELS[app.get('theme')]}</em>` : ''}
        <svg class="app-chev" viewBox="0 0 24 24" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>
      </a>`).join('');
  }

  function renderBack() {
    const back = $('appBack');
    const text = document.createElement('span');
    text.className = 'app-back-text';
    text.textContent = 'Dashboard';
    back.appendChild(text);
    const update = () => { back.href = (isDesktop() || page === 'menu') ? DASHBOARD : 'menu.html'; };
    update();
    window.addEventListener('resize', update);
    // Phone: Back from a settings page returns to the Menu, and Back from the Menu returns to the dashboard section
    // it was opened from (Rooms). Using the history keeps that section and avoids stacking extra pages.
    back.addEventListener('click', e => {
      if (isDesktop() || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
      let ref = '';
      try { ref = new URL(document.referrer).pathname; } catch (x) { return; }
      const fromMenu = page !== 'menu' && /\/menu\.html$/.test(ref);
      const fromDash = page === 'menu' && /\/dashboard\.html$/.test(ref);
      if ((fromMenu || fromDash) && history.length > 1) { e.preventDefault(); history.back(); }
    });
  }

  /* ---------- Generic bindings ---------- */
  function bindSwitches() {
    document.querySelectorAll('[data-switch]').forEach(input => {
      input.checked = Boolean(app.get(input.dataset.switch));
      input.addEventListener('change', () => { app.set(input.dataset.switch, input.checked); syncQuiet(); });
    });
  }

  function bindSegments() {
    document.querySelectorAll('[data-seg]').forEach(group => {
      const key = group.dataset.seg;
      const paint = () => group.querySelectorAll('button').forEach(b =>
        b.setAttribute('aria-pressed', String(b.dataset.value === app.get(key))));
      group.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
        app.set(key, b.dataset.value);
        document.querySelectorAll(`[data-seg="${key}"]`).forEach(g => g.querySelectorAll('button').forEach(x =>
          x.setAttribute('aria-pressed', String(x.dataset.value === app.get(key)))));
      }));
      paint();
    });
  }

  function bindTimes() {
    document.querySelectorAll('[data-time]').forEach(input => {
      input.value = app.get(input.dataset.time);
      input.addEventListener('change', () => {
        if (input.value) app.set(input.dataset.time, input.value);
        if (page === 'appearance') renderThemeNow();
      });
    });
  }

  function syncQuiet() {
    const times = $('quietTimes');
    if (times) times.hidden = !app.get('quiet');
  }

  /* ---------- Application settings ---------- */
  function initSettings() {
    const select = $('startPage');
    const options = isFaculty
      ? ['Schedule', 'Settings']
      : ['Dashboard', 'Workload Optimization', 'Reports', 'Faculty and Subjects', 'Settings'];
    select.innerHTML = options.map((label, i) => `<option value="${i}">${label}</option>`).join('');
    select.value = String(app.get('startPage'));
    if (!select.value) select.value = '0';
    select.addEventListener('change', () => { app.set('startPage', select.value); toast('Saved'); });

    /* Counts come from the database copy loaded by data-store.js (chairperson); a faculty member sees their own run. */
    async function renderStats() {
      const store = window.atlasData;
      let classes = 0, facultyCount = 0, rooms = 0;
      try {
        await store.init();
        facultyCount = store.faculty.list().length;
        if (isFaculty) {
          const run = store.self.run();
          classes = run && Array.isArray(run.result) ? run.result.length : 0;
        } else {
          const run = await store.runs.latest();
          classes = run && Array.isArray(run.result) ? run.result.length : 0;
          const r = store.rooms.get();
          rooms = r ? r.lecture.length + r.lab.length : 0;
        }
      } catch { /* the cards stay at zero when the database cannot be reached */ }
      $('dataStats').innerHTML = [
        [classes, 'Classes'],
        [facultyCount, 'Faculty'],
        [rooms, 'Rooms']
      ].map(([n, label]) => `<div class="app-stat"><strong>${n}</strong><span>${label}</span></div>`).join('');
    }
    renderStats();

    $('btnExport').addEventListener('click', exportAll);
    // Schedules live in saved runs in the database, not on this device, so there is nothing to clear here.
    const clearBtn = $('btnClearSchedule');
    if (clearBtn) { clearBtn.hidden = true; clearBtn.disabled = true; }
    $('btnResetSettings').addEventListener('click', async () => {
      if (!(await window.atlasDialog.confirm('Reset all application settings to their defaults?', { title: 'Reset settings?', ok: 'Reset' }))) return;
      app.reset();
      window.location.reload();
    });

    const button = $('btnInstall');
    const hint = $('installHint');
    let deferred = null;
    if (window.matchMedia('(display-mode: standalone)').matches) hint.textContent = 'Installed on this device.';
    else hint.textContent = 'Use your browser menu and choose Add to Home screen.';
    window.addEventListener('beforeinstallprompt', event => {
      event.preventDefault();
      deferred = event;
      hint.textContent = 'Install ATLAS PSU on this device.';
      button.hidden = false;
    });
    button.addEventListener('click', async () => {
      if (!deferred) return;
      deferred.prompt();
      await deferred.userChoice;
      deferred = null;
      button.hidden = true;
    });
    window.addEventListener('appinstalled', () => { hint.textContent = 'Installed on this device.'; button.hidden = true; });
  }

  /* ---------- Notifications ---------- */
  function permissionText() {
    if (!('Notification' in window)) return 'Not supported by this browser';
    if (Notification.permission === 'denied') return 'Blocked in browser settings';
    if (Notification.permission === 'granted') return 'Allowed';
    return 'Asks permission when turned on';
  }

  function initNotifications() {
    document.querySelectorAll('[data-role-only]').forEach(card => {
      card.hidden = card.dataset.roleOnly !== session.role;
    });

    const system = $('swSystem');
    const refreshSystem = () => {
      system.checked = Boolean(app.get('system')) && 'Notification' in window && Notification.permission === 'granted';
      $('permHint').textContent = permissionText();
    };
    refreshSystem();
    system.addEventListener('change', async () => {
      if (!system.checked) { app.set('system', false); refreshSystem(); return; }
      if (!('Notification' in window)) { refreshSystem(); return; }
      const result = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
      app.set('system', result === 'granted');
      refreshSystem();
    });

    $('btnTestAlert').addEventListener('click', () => {
      if (app.isQuiet()) { toast('Quiet hours are on, so sound is muted'); return; }
      toast('Test alert');
      app.alert('Test alert', 'This is how alerts will look.', 'atlas-test');
    });
    syncQuiet();

    if (isFaculty) {
      const key = 'facultySettings::' + DEPT + ':' + session.faculty;
      const defaults = { enabled: true, lead: 10, atStart: true, sound: true, vibrate: true, browser: false };
      const read = () => Object.assign({}, defaults, app.readJSON(key, {}));
      const current = read();
      document.querySelectorAll('[data-faculty-switch]').forEach(input => {
        input.checked = Boolean(current[input.dataset.facultySwitch]);
        input.addEventListener('change', () => {
          const next = read();
          next[input.dataset.facultySwitch] = input.checked;
          writeLocal(key, next);
        });
      });
      const lead = $('facLead');
      lead.value = String(current.lead);
      lead.addEventListener('change', () => { const next = read(); next.lead = Number(lead.value); writeLocal(key, next); });
    }
  }

  /* ---------- Account ---------- */
  function initAccount() {
    /* Name, email, role and department come from the profiles table (display cache); they are read only here. */
    const name = isFaculty ? session.faculty : session.user;
    const email = session.email;

    const nameInput = $('acctInputName');
    const emailInput = $('acctInputEmail');
    nameInput.value = name;
    emailInput.value = email;
    nameInput.readOnly = true;
    emailInput.readOnly = true;

    function paint() {
      const shown = nameInput.value.trim() || emailInput.value.trim() || 'User';
      $('acctName').textContent = shown;
      $('acctAvatar').textContent = shown.charAt(0).toUpperCase();
      $('acctMeta').textContent = (isFaculty ? 'Faculty' : 'Chairperson') + (hasDept ? ' · ' + deptName : '');
    }
    paint();
    const paintDept = () => { $('acctDept').textContent = hasDept ? deptName + ' Department' : 'Not set'; };
    paintDept();
    if (hasDept) {
      fetch('../data/curricula/' + DEPT + '.json', { cache: 'no-cache' })
        .then(r => r.json())
        .then(c => { if (c && c.dept === DEPT && c.name) { deptName = c.name; paint(); paintDept(); } })
        .catch(() => { /* keep the code */ });
    }
    $('acctRole').textContent = isFaculty ? 'Faculty' : 'Department chairperson';

    $('btnExport').addEventListener('click', exportAll);
    $('btnClearAll').addEventListener('click', async () => {
      if (!(await window.atlasDialog.confirm('Clear all saved data on this device and log out? This cannot be undone.', { title: 'Clear data and log out?', ok: 'Clear and log out', danger: true }))) return;
      try { localStorage.clear(); } catch { /* storage unavailable */ }
      logout();
    });
    $('btnSignOut').addEventListener('click', logout);
  }

  /* ---------- Appearance ---------- */
  function renderThemeNow() {
    const mode = app.get('theme');
    const label = app.isDark() ? 'Night' : 'Light';
    $('themeNow').textContent = mode === 'schedule'
      ? `Now: ${label}. Night runs from ${app.get('nightStart')} to ${app.get('nightEnd')} on this device's clock.`
      : `Now: ${label}`;
  }

  function initAppearance() {
    const cards = document.querySelectorAll('.theme-card');
    const paint = () => {
      cards.forEach(card => card.setAttribute('aria-checked', String(card.dataset.themeValue === app.get('theme'))));
      $('scheduleCard').hidden = app.get('theme') !== 'schedule';
      renderThemeNow();
    };
    cards.forEach(card => card.addEventListener('click', () => { app.set('theme', card.dataset.themeValue); paint(); }));
    paint();
  }

  /* ---------- Active academic period (chairperson; saved in the database through the data layer) ---------- */
  function initPeriod() {
    const card = $('periodCard');
    if (!card) return;
    if (isFaculty || !window.atlasData) { card.remove(); return; }
    card.hidden = false;
    const show = () => {
      const p = window.atlasData.settings.period();
      $('periodYear').value = p.year || '';
      $('periodSem').value = p.semester || '1st Semester';
      $('periodNow').textContent = 'Active now: ' + (p.year ? p.year + ' \u00b7 ' : '') + p.semester;
    };
    show();
    $('periodSave').addEventListener('click', () => {
      const year = $('periodYear').value.trim(), err = $('periodErr');
      const m = /^(\d{4})-(\d{4})$/.exec(year);
      if (!m || Number(m[2]) !== Number(m[1]) + 1) {
        err.textContent = 'Use an academic year like 2026-2027.'; err.hidden = false; $('periodYear').focus(); return;
      }
      err.hidden = true;
      window.atlasData.settings.savePeriod(year, $('periodSem').value);
      show();
      toast('Active period set: ' + year + ' \u00b7 ' + $('periodSem').value);
    });
  }

  /* ---------- Audit log (chairperson; GET /audit, read only; the server forces the department) ---------- */
  function initAuditLog() {
    const card = $('auditCard');
    if (!card) return;
    if (session.role !== 'chairperson' || !window.atlasAuth || !window.atlasAuth.fetch) { card.remove(); return; }
    card.hidden = false;
    const PAGE_SIZE = 25;
    const body = card.querySelector('tbody');
    const state = { page: 1, hasMore: false, filled: false };

    function label(action) { return String(action || '').replace(/_/g, ' '); }
    function localDay(value, plusDays) {                       // 'YYYY-MM-DD' (local) -> ISO instant at local midnight
      const p = value.split('-').map(Number);
      return new Date(p[0], p[1] - 1, p[2] + (plusDays || 0)).toISOString();
    }
    function cell(tr, text) { const td = document.createElement('td'); td.style.padding = '6px 8px'; td.textContent = text == null ? '' : String(text); tr.appendChild(td); }
    function setStatus(text) { $('auditStatus').textContent = text || ''; }

    function render(data) {
      body.textContent = '';
      (data.rows || []).forEach(r => {
        const tr = document.createElement('tr');
        const t = r.time ? new Date(r.time) : null;
        cell(tr, t && !isNaN(t) ? t.toLocaleString() : '');
        cell(tr, r.user || 'unknown');
        cell(tr, label(r.action));
        cell(tr, r.entity || '');
        body.appendChild(tr);
      });
      if (!state.filled) {                                      // the action list comes from the server, once
        const sel = $('auditAction');
        (data.actions || []).forEach(a => { const o = document.createElement('option'); o.value = a; o.textContent = label(a); sel.appendChild(o); });
        state.filled = true;
      }
      state.hasMore = !!data.has_more;
      $('auditPrev').disabled = state.page <= 1;
      $('auditNext').disabled = !state.hasMore;
      $('auditPage').textContent = 'Page ' + state.page;
      setStatus((data.rows || []).length ? '' : 'No audit entries match.');
    }

    async function load() {
      const q = new URLSearchParams({ page: String(state.page), page_size: String(PAGE_SIZE) });
      const action = $('auditAction').value, from = $('auditFrom').value, to = $('auditTo').value;
      if (action) q.set('action', action);
      if (from) q.set('from', localDay(from, 0));
      if (to) q.set('to', localDay(to, 1));                     // the "to" day is included
      setStatus('Loading...');
      try {
        const res = await window.atlasAuth.fetch(window.atlasAuth.apiBase() + '/audit?' + q.toString());
        const json = await res.json().catch(() => ({}));
        if (!res.ok) { setStatus(json.code === 'audit_read_failed' ? 'The audit log could not be read. Contact the administrator.' : (json.error || 'Could not load the audit log.')); return; }
        render(json.data || json);
      } catch (e) { setStatus('Could not reach the server.'); }
    }

    $('auditApply').addEventListener('click', () => {
      if ($('auditFrom').value && $('auditTo').value && $('auditFrom').value > $('auditTo').value) { setStatus('The start date must be before the end date.'); return; }
      state.page = 1; load();
    });
    $('auditClear').addEventListener('click', () => { $('auditAction').value = ''; $('auditFrom').value = ''; $('auditTo').value = ''; state.page = 1; load(); });
    $('auditPrev').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; load(); } });
    $('auditNext').addEventListener('click', () => { if (state.hasMore) { state.page += 1; load(); } });
    load();
  }

  /* ---------- Solver settings (chairperson only; values live in atlasSolver) ---------- */
  function initSolverSettings() {
    const card = $('solver');
    if (!card) return;
    if (isFaculty || !window.atlasSolver) { card.remove(); return; }
    const S = window.atlasSolver;
    const ids = { max_units: 'sysMaxUnits', units_per_assignment: 'sysUnitsPerAssignment',
      cp_sat_time_limit: 'sysCpSatTimeLimit', population: 'populationSize', generations: 'numGenerations',
      mutation: 'mutationRate', crossover: 'crossoverRate' };
    const showError = (k, msg) => {
      $('err-' + ids[k]).textContent = msg || '';
      $('err-' + ids[k]).hidden = !msg;
      $(ids[k]).setAttribute('aria-invalid', msg ? 'true' : 'false');
    };
    const paint = values => Object.keys(ids).forEach(k => { $(ids[k]).value = values[k]; showError(k, ''); });
    $('solverDept').textContent = DEPT;
    paint(S.read(DEPT));
    card.hidden = false;
    $('btnSaveSolver').addEventListener('click', () => {
      const raw = {};
      Object.keys(ids).forEach(k => { raw[k] = $(ids[k]).value; });
      const r = S.validate(raw);
      Object.keys(ids).forEach(k => showError(k, r.errors[k]));
      if (Object.keys(r.errors).length) return;
      S.save(DEPT, r.values).then(res => { if (res.ok) toast('Solver settings saved'); });
    });
    $('btnRestoreSolver').addEventListener('click', () => {
      S.save(DEPT, S.DEFAULTS).then(res => { if (res.ok) toast('Defaults restored'); });
      paint(S.DEFAULTS);
    });
    if (window.location.hash === '#solver') card.scrollIntoView();
  }

  /* ---------- Start ---------- */
  renderNav();
  renderBack();
  bindSwitches();
  bindSegments();
  bindTimes();
  if (page === 'settings') {
    initSettings();
    // the solver card reads the database copy, so it waits for the data to be loaded
    // The academic period, solver and audit log cards all appear together, after the data is ready. The page loader
    // (app-core.js) stays up until then, so nothing pops in one card at a time.
    if (!isFaculty && window.atlasData) {
      window.atlasPageReady = window.atlasData.init().then(
        () => { initPeriod(); initSolverSettings(); initAuditLog(); },
        () => { ['solver', 'periodCard'].forEach(id => { const c = $(id); if (c) c.remove(); }); initAuditLog(); });
    } else { const c = $('periodCard'); if (c) c.remove(); initSolverSettings(); initAuditLog(); }
  }
  // Phone: the top bar slips away while scrolling down and returns on scroll up
  (function () {
    const bar = document.querySelector('.app-top');
    if (!bar) return;
    let last = window.scrollY;
    window.addEventListener('scroll', () => {
      const y = window.scrollY, d = y - last;
      if (window.matchMedia('(min-width: 901px)').matches) { bar.classList.remove('is-away'); last = y; return; }
      if (y <= 4) bar.classList.remove('is-away');
      else if (d > 6 && y > 56) bar.classList.add('is-away');
      else if (d < -6) bar.classList.remove('is-away');
      last = y;
    }, { passive: true });
  })();
  if (page === 'notifications') initNotifications();
  if (page === 'account') initAccount();
  if (page === 'appearance') initAppearance();
})();