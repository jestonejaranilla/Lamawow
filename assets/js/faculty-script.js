/* ============================================================
   ATLAS PSU - faculty side (faculty/dashboard.html)
   Reads the schedule the chairperson saved in this browser
   (localStorage) and shows each faculty member their own classes,
   their week, and the whole department. A live clock tracks the time
   and reminds the faculty member before a class starts.
   ============================================================ */
(function () {
  'use strict';

  /* ---------- Constants ---------- */
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const SLOT_ROWS = [[7, 9], [9, 11], [13, 15], [15, 17], [17, 19]];
  const MINUTES_PER_DAY = 1440;
  const MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY;
  const DEPARTMENTS = {
    IT: 'Information Technology', CS: 'Computer Science', MB: 'Marine Biology',
    ES: 'Environmental Science', MedB: 'Medical Biology'
  };
  const DATA_KEYS = ['lastGAResult', 'facultyData', 'academicMode', 'subjectsData', 'systemSettings'];
  const DEFAULT_SETTINGS = { enabled: true, lead: 10, atStart: true, sound: true, vibrate: true, browser: false };
  const LOGIN_URL = '../pages/login.html';

  /* ---------- Session guard ---------- */
  const session = {
    role: sessionStorage.getItem('atlasRole'),
    name: sessionStorage.getItem('atlasFaculty'),
    email: sessionStorage.getItem('atlasEmail') || '',
    dept: sessionStorage.getItem('atlasDept') || ''
  };
  if (session.role !== 'faculty' || !session.name) {
    window.location.replace(LOGIN_URL);
    return;
  }

  /* ---------- Helpers ---------- */
  const $ = id => document.getElementById(id);

  function escapeHTML(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function readJSON(storage, key, fallback) {
    try {
      const value = JSON.parse(storage.getItem(key));
      return value == null ? fallback : value;
    } catch { return fallback; }
  }

  function writeJSON(storage, key, value) {
    try { storage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
  }

  const isMobile = () => window.matchMedia('(max-width:768px)').matches;

  function formatHour(h) {
    const suffix = h >= 12 ? 'PM' : 'AM';
    return `${h > 12 ? h - 12 : h}:00 ${suffix}`;
  }

  function formatRange(c) {
    return `${formatHour(c.startH)} - ${formatHour(c.endH)}`;
  }

  /* minutes since Monday 00:00 for a Date (Sunday counts as day 6) */
  function weekMinute(date) {
    return ((date.getDay() + 6) % 7) * MINUTES_PER_DAY + date.getHours() * 60 + date.getMinutes();
  }

  function formatDuration(minutes) {
    const m = Math.max(0, Math.ceil(minutes));
    const days = Math.floor(m / MINUTES_PER_DAY);
    const hours = Math.floor((m % MINUTES_PER_DAY) / 60);
    const mins = m % 60;
    if (days) return `${days}d ${hours}h`;
    if (hours) return `${hours}h ${String(mins).padStart(2, '0')}m`;
    return `${mins} min`;
  }

  /* ---------- Cached data (written by the chairperson dashboard) ---------- */
  function normalize(item) {
    const match = /^(\w+):\s*(\d+):\d+\s*-\s*(\d+):\d+/.exec(item.slot || '');
    if (!match) return null;
    const day = DAYS.indexOf(match[1]);
    if (day < 0) return null;
    const startH = Number(match[2]);
    const endH = Number(match[3]);
    return {
      faculty: item.faculty || '',
      subject: item.subject || '',
      classType: (item.class_type || 'LECTURE').toUpperCase(),
      room: item.room || '',
      section: item.section || '',
      day,
      startH,
      endH,
      start: day * MINUTES_PER_DAY + startH * 60,
      end: day * MINUTES_PER_DAY + endH * 60
    };
  }

  function loadSchedule() {
    let items = readJSON(localStorage, 'lastGAResult', []);
    if (!Array.isArray(items)) items = [];
    const mode = readJSON(localStorage, 'academicMode', null);
    if (mode && mode.semester) {
      const valid = new Set(
        readJSON(localStorage, 'subjectsData', [])
          .filter(s => s.semester === mode.semester)
          .map(s => s.name)
      );
      if (valid.size) items = items.filter(i => valid.has(i.subject));
    }
    return items.map(normalize).filter(Boolean).sort((a, b) => a.start - b.start);
  }

  function loadFacultyNames() {
    const names = readJSON(localStorage, 'facultyData', []).map(f => f && f.name).filter(Boolean);
    if (!names.includes(session.name)) names.push(session.name);
    return Array.from(new Set(names)).sort();
  }

  function unitsPerAssignment() {
    const settings = readJSON(localStorage, 'systemSettings', {});
    return parseInt(settings.units_per_assignment, 10) || 2;
  }

  /* ---------- State ---------- */
  const state = { schedule: [], mine: [], names: [], day: null };

  function reloadData() {
    state.schedule = loadSchedule();
    state.mine = state.schedule.filter(c => c.faculty === session.name);
    state.names = loadFacultyNames();
  }

  /* ---------- Reminder settings (per faculty member, per device) ---------- */
  const settingsKey = () => 'facultySettings:' + session.name;
  let settings = Object.assign({}, DEFAULT_SETTINGS, readJSON(localStorage, settingsKey(), {}));
  const saveSettings = () => writeJSON(localStorage, settingsKey(), settings);

  /* ---------- Navigation ---------- */
  function switchPanel(index) {
    document.querySelectorAll('.panel').forEach((p, i) => p.classList.toggle('active', i === index));
    document.querySelectorAll('.nav-item[data-panel]').forEach((n, i) => n.classList.toggle('active', i === index));
  }
  window.switchPanel = switchPanel;

  function initNavigation() {
    document.querySelectorAll('.nav-item[data-panel]').forEach(item => {
      item.addEventListener('click', () => switchPanel(Number(item.dataset.panel)));
      item.addEventListener('keydown', e => { if (e.key === 'Enter') item.click(); });
    });
    const menu = document.querySelector('.nav-item.dropdown');
    if (menu) {
      menu.addEventListener('click', e => { e.stopPropagation(); menu.classList.toggle('open'); });
      document.addEventListener('click', () => menu.classList.remove('open'));
    }
    document.querySelectorAll('[data-logout]').forEach(link =>
      link.addEventListener('click', () => sessionStorage.clear()));
    switchPanel(window.atlasApp ? window.atlasApp.startPanel(document.querySelectorAll('.panel').length) : 0);
  }

  function initTabs() {
    const buttons = document.querySelectorAll('.fs-tab');
    buttons.forEach(button => button.addEventListener('click', () => {
      buttons.forEach(b => {
        const active = b === button;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active);
        $('fsTab' + b.dataset.tab).hidden = !active;
      });
    }));
  }

  /* ---------- Rendering: identity, header, stats ---------- */
  function renderIdentity() {
    const deptName = DEPARTMENTS[session.dept] ? DEPARTMENTS[session.dept] + ' Department' : '';
    $('fsBannerName').textContent = deptName || 'Department not set';
    $('fsGreeting').textContent = 'Welcome, ' + session.name;
    const short = session.dept ? ' \u00b7 ' + session.dept : '';
    $('navUserLabel').textContent = session.name + short;

    const mode = readJSON(localStorage, 'academicMode', null);
    const badge = $('fsSemBadge');
    if (mode && mode.semester) {
      badge.textContent = 'Showing: ' + (mode.year ? mode.year + ' \u00b7 ' : '') + mode.semester;
      badge.style.display = 'inline-flex';
    } else {
      badge.style.display = 'none';
    }
  }

  function todayIndex(now) {
    return (now.getDay() + 6) % 7;
  }

  function renderStats(now) {
    const today = state.mine.filter(c => c.day === todayIndex(now));
    $('fsStatClasses').textContent = state.mine.length;
    $('fsStatUnits').textContent = state.mine.length * unitsPerAssignment();
    $('fsStatToday').textContent = today.length;
    $('fsStatTodaySub').textContent = todayIndex(now) > 5 ? 'no classes on Sunday' : DAY_NAMES[todayIndex(now)];
  }

  /* ---------- Rendering: schedule lists ---------- */
  function classCard(c, now) {
    const nowMinute = weekMinute(now);
    let chip = '';
    if (nowMinute >= c.start && nowMinute < c.end) chip = '<span class="fs-chip fs-chip-live">In progress</span>';
    else if (c.day === todayIndex(now) && nowMinute >= c.end) chip = '<span class="fs-chip fs-chip-done">Done</span>';
    else if (c.day === todayIndex(now)) chip = '<span class="fs-chip fs-chip-today">Today</span>';
    const type = c.classType.toLowerCase();
    return `
      <div class="fs-class">
        <div class="fs-class-time">${formatHour(c.startH)}<small>to ${formatHour(c.endH)}</small></div>
        <div class="fs-class-body">
          <div class="fs-class-subject">${escapeHTML(c.subject)}</div>
          <div class="fs-class-tags">
            <span class="class-type-tag ${type}">${escapeHTML(c.classType)}</span>
            ${c.section ? `<span class="section-badge">${escapeHTML(c.section)}</span>` : ''}
            ${c.room ? `<span class="fs-room">${escapeHTML(c.room)}</span>` : ''}
            ${chip}
          </div>
        </div>
      </div>`;
  }

  function emptyState(text) {
    return `<div class="fs-empty">${text}</div>`;
  }

  const NO_DATA = 'No schedule on this device yet';

  function renderMine(now) {
    const host = $('fsMineList');
    if (!state.mine.length) {
      host.innerHTML = emptyState(state.schedule.length
        ? 'No classes assigned to you' : NO_DATA);
      return;
    }
    const today = todayIndex(now);
    const html = DAYS.map((day, d) => {
      if (state.day !== null && state.day !== d) return '';
      const items = state.mine.filter(c => c.day === d);
      if (!items.length) return '';
      return `
        <section class="fs-day${d === today ? ' fs-day-today' : ''}">
          <h3>${DAY_NAMES[d]}${d === today ? '<span class="fs-chip fs-chip-today">Today</span>' : ''}</h3>
          ${items.map(c => classCard(c, now)).join('')}
        </section>`;
    }).join('');
    host.innerHTML = html || emptyState(state.day === null ? 'No classes assigned to you' : 'No classes on ' + DAY_NAMES[state.day]);
  }

  /* day picker: Mon-Sat of the current week plus "All" */
  function renderWeekStrip(now) {
    const today = todayIndex(now);
    const buttons = DAYS.map((name, d) => {
      const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() - today + d);
      const classes = ['fs-day-btn'];
      if (d === today) classes.push('today');
      if (state.day === d) classes.push('selected');
      if (state.mine.some(c => c.day === d)) classes.push('has-class');
      return `<button type="button" class="${classes.join(' ')}" data-day="${d}" aria-pressed="${state.day === d}"><small>${name}</small>${date.getDate()}</button>`;
    });
    buttons.push(`<button type="button" class="fs-day-btn fs-day-all${state.day === null ? ' selected' : ''}" data-day="all" aria-pressed="${state.day === null}"><small>Week</small>All</button>`);
    $('fsWeekStrip').innerHTML = buttons.join('');
  }

  /* weekly timetable; entries optionally show the faculty name */
  function timetableHTML(items, showFaculty, now) {
    const nowMinute = weekMinute(now);
    let html = '<div class="timetable-scroll"><table class="timetable-grid"><thead><tr><th class="tt-time-col">Time</th>';
    DAYS.forEach(d => { html += `<th class="tt-day-col tt-hd-${d}">${d}</th>`; });
    html += '</tr></thead><tbody>';
    SLOT_ROWS.forEach(([startH, endH]) => {
      html += `<tr><td class="tt-time-label">${startH}-${endH}</td>`;
      DAYS.forEach((day, d) => {
        const entries = items.filter(c => c.day === d && c.startH === startH && c.endH === endH);
        if (!entries.length) { html += '<td class="tt-cell tt-empty"></td>'; return; }
        const live = nowMinute >= d * MINUTES_PER_DAY + startH * 60 && nowMinute < d * MINUTES_PER_DAY + endH * 60;
        html += `<td class="tt-cell tt-filled tt-bg-${day}${live ? ' fs-live-cell' : ''}">`;
        entries.forEach(c => {
          html += `<div class="tt-entry">
            <span class="tt-class-tag ${c.classType.toLowerCase()}">${escapeHTML(c.classType)}</span>
            ${c.section ? `<span class="tt-section-tag">${escapeHTML(c.section)}</span>` : ''}
            ${showFaculty ? `<div class="tt-faculty-tag">${escapeHTML(c.faculty)}</div>` : ''}
            <div class="tt-subject-tag">${escapeHTML(c.subject)}</div>
            ${c.room ? `<span class="tt-room-tag">${escapeHTML(c.room)}</span>` : ''}
          </div>`;
        });
        html += '</td>';
      });
      html += '</tr>';
    });
    return html + '</tbody></table></div>';
  }

  function renderWeek(now) {
    $('fsWeekTimetable').innerHTML = state.mine.length
      ? timetableHTML(state.mine, false, now) : emptyState(state.schedule.length
        ? 'No classes assigned to you' : NO_DATA);
  }

  function renderAll(now) {
    const filter = $('fsFacultyFilter');
    const chosen = filter.value || '__all';
    filter.innerHTML = '<option value="__all">All faculty</option>' +
      state.names.map(n => `<option value="${escapeHTML(n)}">${escapeHTML(n)}</option>`).join('');
    filter.value = Array.from(filter.options).some(o => o.value === chosen) ? chosen : '__all';

    const visible = filter.value === '__all'
      ? state.schedule : state.schedule.filter(c => c.faculty === filter.value);
    const names = Array.from(new Set(visible.map(c => c.faculty))).sort();

    $('fsAllTimetable').innerHTML = timetableHTML(visible, true, now);

    if (!names.length) {
      $('fsAllList').innerHTML = emptyState(state.schedule.length ? 'No classes found' : NO_DATA);
      return;
    }
    const openAll = !isMobile();
    $('fsAllList').innerHTML = names.map(name => {
      const items = visible.filter(c => c.faculty === name);
      const mineFlag = name === session.name;
      return `
        <details class="fs-faculty"${openAll || mineFlag ? ' open' : ''}>
          <summary>
            <span class="fs-faculty-name">${escapeHTML(name)}${mineFlag ? '<span class="fs-chip fs-chip-today">You</span>' : ''}</span>
            <span class="fs-faculty-count">${items.length} ${items.length === 1 ? 'class' : 'classes'}</span>
          </summary>
          <div class="fs-faculty-body">
            ${items.map(c => `
              <div class="fs-class fs-class-compact">
                <div class="fs-class-time">${DAYS[c.day]}<small>${formatHour(c.startH)}</small></div>
                <div class="fs-class-body">
                  <div class="fs-class-subject">${escapeHTML(c.subject)}</div>
                  <div class="fs-class-tags">
                    <span class="class-type-tag ${c.classType.toLowerCase()}">${escapeHTML(c.classType)}</span>
                    ${c.section ? `<span class="section-badge">${escapeHTML(c.section)}</span>` : ''}
                    ${c.room ? `<span class="fs-room">${escapeHTML(c.room)}</span>` : ''}
                    <span class="fs-time-inline">${formatRange(c)}</span>
                  </div>
                </div>
              </div>`).join('')}
          </div>
        </details>`;
    }).join('');
  }

  function renderSchedules(now) {
    renderStats(now);
    renderWeekStrip(now);
    renderMine(now);
    renderWeek(now);
    renderAll(now);
  }

  /* ---------- Live status (clock, current / next class) ---------- */
  function currentAndNext(nowMinute) {
    const current = state.mine.find(c => nowMinute >= c.start && nowMinute < c.end) || null;
    let next = state.mine.find(c => c.start > nowMinute) || null;
    let wrapped = false;
    if (!next && state.mine.length) { next = state.mine[0]; wrapped = true; }
    return { current, next, wrapped };
  }

  function renderStatus(now) {
    $('fsClock').textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    $('fsDate').textContent = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });

    const label = $('fsStatusLabel');
    const title = $('fsStatusTitle');
    const meta = $('fsStatusMeta');
    const count = $('fsStatusCount');
    const box = $('fsStatus');
    const nowMinute = weekMinute(now);
    const { current, next, wrapped } = currentAndNext(nowMinute);

    box.classList.toggle('fs-status-live', Boolean(current));
    if (current) {
      label.textContent = 'In class now';
      title.textContent = current.subject;
      meta.textContent = [current.room, formatRange(current)].filter(Boolean).join(' \u00b7 ');
      count.textContent = 'Ends in ' + formatDuration(current.end - nowMinute);
    } else if (next) {
      const wait = (wrapped ? next.start + MINUTES_PER_WEEK : next.start) - nowMinute;
      label.textContent = 'Next class';
      title.textContent = next.subject;
      meta.textContent = [DAY_NAMES[next.day], formatRange(next), next.room].filter(Boolean).join(' \u00b7 ');
      count.textContent = 'Starts in ' + formatDuration(wait);
    } else {
      label.textContent = 'No classes';
      title.textContent = state.schedule.length ? 'Nothing assigned yet' : 'No schedule on this device';
      meta.textContent = '';
      count.textContent = '';
    }
  }

  /* ---------- Reminders ---------- */
  function toast(message) {
    const el = $('toastNotif');
    el.textContent = message;
    el.className = 'toast-notif show';
    setTimeout(() => { el.className = 'toast-notif'; }, 4000);
  }

  const baseTitle = document.title;
  function showAlert(title, body) {
    $('fsAlertTitle').textContent = title;
    $('fsAlertBody').textContent = body;
    $('fsAlert').hidden = false;
    document.title = '\u25CF ' + title;
  }
  function hideAlert() {
    $('fsAlert').hidden = true;
    document.title = baseTitle;
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

  function notify(title, body, tag) {
    showAlert(title, body);
    toast(title);
    const quiet = window.atlasApp && window.atlasApp.isQuiet();
    if (settings.sound && !quiet) beep();
    if (settings.vibrate && !quiet && navigator.vibrate) navigator.vibrate([200, 100, 200]);
    if (settings.browser && !quiet && 'Notification' in window && Notification.permission === 'granted') {
      try { new Notification(title, { body, tag, icon: '../assets/images/favicon.png' }); } catch { /* blocked */ }
    }
  }

  const firedKey = 'atlasFacultyFired';
  const fired = new Set(readJSON(sessionStorage, firedKey, []));
  function fireOnce(id, title, body) {
    if (fired.has(id)) return;
    fired.add(id);
    writeJSON(sessionStorage, firedKey, Array.from(fired));
    notify(title, body, id);
  }

  function checkReminders(now) {
    if (!settings.enabled || !state.mine.length) return;
    const nowMinute = weekMinute(now);
    const dateId = now.toDateString();
    state.mine.forEach(c => {
      const detail = [c.subject, c.room].filter(Boolean).join(' \u00b7 ');
      const untilStart = c.start - nowMinute;
      if (untilStart > 0 && untilStart <= settings.lead) {
        fireOnce(`${dateId}|${c.start}|pre`, `Class in ${formatDuration(untilStart)}`, `${detail} at ${formatHour(c.startH)}`);
      } else if (settings.atStart && nowMinute >= c.start && nowMinute < c.start + 5) {
        fireOnce(`${dateId}|${c.start}|start`, 'Your class is starting', `${detail} (${formatRange(c)})`);
      }
    });
  }

  /* ---------- Settings panel ---------- */
  function browserHelp() {
    if (!('Notification' in window)) return 'Not supported by this browser';
    if (Notification.permission === 'denied') return 'Blocked in browser settings';
    if (Notification.permission === 'granted') return 'Allowed';
    return 'Asks permission when turned on';
  }

  function renderSettings() {
    $('fsSetEnabled').checked = settings.enabled;
    $('fsSetLead').value = String(settings.lead);
    $('fsSetStart').checked = settings.atStart;
    $('fsSetSound').checked = settings.sound;
    $('fsSetVibrate').checked = settings.vibrate;
    $('fsSetBrowser').checked = settings.browser && 'Notification' in window && Notification.permission === 'granted';
    $('fsBrowserHelp').textContent = browserHelp();
  }

  function renderProfile() {
    $('fsProfileFaculty').innerHTML = state.names
      .map(n => `<option value="${escapeHTML(n)}">${escapeHTML(n)}</option>`).join('');
    $('fsProfileFaculty').value = session.name;
    $('fsProfileEmail').value = session.email;
    $('fsProfileDept').textContent = DEPARTMENTS[session.dept] ? DEPARTMENTS[session.dept] + ' Department' : 'Not set';
  }

  function renderDataInfo() {
    $('fsDataInfo').textContent = state.schedule.length
      ? `${state.schedule.length} classes \u00b7 ${new Set(state.schedule.map(c => c.faculty)).size} faculty`
      : NO_DATA;
  }

  function initSettings() {
    ['fsSetEnabled', 'fsSetStart', 'fsSetSound', 'fsSetVibrate'].forEach(id => {
      const key = { fsSetEnabled: 'enabled', fsSetStart: 'atStart', fsSetSound: 'sound', fsSetVibrate: 'vibrate' }[id];
      $(id).addEventListener('change', e => { settings[key] = e.target.checked; saveSettings(); });
    });
    $('fsSetLead').addEventListener('change', e => { settings.lead = Number(e.target.value); saveSettings(); });

    $('fsSetBrowser').addEventListener('change', async e => {
      if (!e.target.checked) { settings.browser = false; saveSettings(); return; }
      if (!('Notification' in window)) { e.target.checked = false; return; }
      const result = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
      settings.browser = result === 'granted';
      e.target.checked = settings.browser;
      saveSettings();
      $('fsBrowserHelp').textContent = browserHelp();
    });

    $('fsTestReminder').addEventListener('click', () =>
      notify('Test reminder', 'This is how your class reminders will look.', 'atlas-test'));

    $('fsReloadData').addEventListener('click', () => { refreshAll(); toast('Schedule reloaded'); });

    $('fsSaveProfile').addEventListener('click', () => {
      const error = $('fsProfileError');
      const email = $('fsProfileEmail').value.trim();
      if (!/^[a-zA-Z0-9._%+-]+@psu\.palawan\.edu\.ph$/i.test(email)) {
        error.textContent = 'Please use your PSU corporate email (name@psu.palawan.edu.ph).';
        error.hidden = false;
        return;
      }
      error.hidden = true;
      const name = $('fsProfileFaculty').value;
      const profiles = readJSON(localStorage, 'facultyProfiles', {});
      profiles[name] = { email, dept: session.dept };
      writeJSON(localStorage, 'facultyProfiles', profiles);
      sessionStorage.setItem('atlasFaculty', name);
      sessionStorage.setItem('atlasUser', name);
      sessionStorage.setItem('atlasEmail', email);
      session.name = name;
      session.email = email;
      settings = Object.assign({}, DEFAULT_SETTINGS, readJSON(localStorage, settingsKey(), {}));
      refreshAll();
      toast('Profile saved');
    });
  }

  /* ---------- Refresh ---------- */
  function refreshAll() {
    reloadData();
    const now = new Date();
    renderIdentity();
    renderSchedules(now);
    renderStatus(now);
    renderProfile();
    renderSettings();
    renderDataInfo();
  }

  /* ---------- Start ---------- */
  initNavigation();
  initTabs();
  initSettings();
  $('fsAlertClose').addEventListener('click', hideAlert);
  $('fsWeekStrip').addEventListener('click', e => {
    const button = e.target.closest('.fs-day-btn');
    if (!button) return;
    state.day = button.dataset.day === 'all' ? null : Number(button.dataset.day);
    const now = new Date();
    renderWeekStrip(now);
    renderMine(now);
  });
  $('fsFacultyFilter').addEventListener('change', () => renderAll(new Date()));
  window.addEventListener('storage', e => { if (e.key === null || DATA_KEYS.includes(e.key)) refreshAll(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { const n = new Date(); renderStatus(n); checkReminders(n); } });

  const startDay = todayIndex(new Date());
  state.day = startDay <= 5 ? startDay : null;
  refreshAll();

  let lastMinute = -1;
  setInterval(() => {
    const now = new Date();
    renderStatus(now);
    checkReminders(now);
    if (now.getMinutes() !== lastMinute) {          // re-mark "in progress" / "done" once a minute
      lastMinute = now.getMinutes();
      renderStats(now);
      renderWeekStrip(now);
      renderMine(now);
      renderWeek(now);
    }
  }, 1000);
})();