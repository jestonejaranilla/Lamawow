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