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
  const dk = base => base + '::' + DEPT;
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

  function exportAll() {
    const data = {};
    const suffix = '::' + DEPT;
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      // this department's keys and device-level settings only; never another department's data
      if (!key) continue;
      const mine = key.endsWith(suffix) || key.startsWith('facultySettings::' + DEPT + ':');
      const legacy = (window.atlasDept && window.atlasDept.BASE_KEYS.includes(key)) || key.startsWith('facultySettings:') && !key.startsWith('facultySettings::');
      if ((key.includes('::') && !mine) || legacy) continue;
      try { data[key] = JSON.parse(localStorage.getItem(key)); } catch { data[key] = localStorage.getItem(key); }
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

    function renderStats() {
      const schedule = app.readJSON(dk('lastGAResult'), []);
      const faculty = app.readJSON(dk('facultyData'), []);
      const subjects = app.readJSON(dk('subjectsData'), []);
      $('dataStats').innerHTML = [
        [Array.isArray(schedule) ? schedule.length : 0, 'Classes'],
        [Array.isArray(faculty) ? faculty.length : 0, 'Faculty'],
        [Array.isArray(subjects) ? subjects.length : 0, 'Subjects']
      ].map(([n, label]) => `<div class="app-stat"><strong>${n}</strong><span>${label}</span></div>`).join('');
    }
    renderStats();

    $('btnExport').addEventListener('click', exportAll);
    $('btnClearSchedule').addEventListener('click', () => {
      if (!window.confirm('Clear the saved schedule on this device? Faculty will no longer see it.')) return;
      localStorage.removeItem(dk('lastGAResult'));
      localStorage.removeItem(dk('atlasAnalyticsCache'));
      renderStats();
      toast('Saved schedule cleared');
    });
    $('btnResetSettings').addEventListener('click', () => {
      if (!window.confirm('Reset all application settings to their defaults?')) return;
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
    $('btnClearAll').addEventListener('click', () => {
      if (!window.confirm('Clear all saved data on this device and log out? This cannot be undone.')) return;
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
      S.save(DEPT, r.values);
      toast('Solver settings saved');
    });
    $('btnRestoreSolver').addEventListener('click', () => {
      S.save(DEPT, S.DEFAULTS);
      paint(S.DEFAULTS);
      toast('Defaults restored');
    });
    if (window.location.hash === '#solver') card.scrollIntoView();
  }

  /* ---------- Start ---------- */
  renderNav();
  renderBack();
  bindSwitches();
  bindSegments();
  bindTimes();
  if (page === 'settings') { initSettings(); initSolverSettings(); }
  if (page === 'notifications') initNotifications();
  if (page === 'account') initAccount();
  if (page === 'appearance') initAppearance();
})();