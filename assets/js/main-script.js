/* ============================================================
   ATLAS PSU - main-script.js
   A Teaching Load Assignment and Management System for Department Chairpersons of the College of Sciences at Palawan State University
   Chairperson dashboard logic (landing and login pages have their own scripts).
   ============================================================ */

/* ── Auth guard (dashboard only, runs before DOMContentLoaded) ── */
(function authGuard() {
  if (document.getElementById('navUserLabel') !== null) return; // DOM not ready yet; handled in initDashboardPage
  // Check via URL path so the guard only fires on the dashboard page
  if (window.location.pathname.includes('dashboard') && !sessionStorage.getItem('atlasUser')) {
    window.location.href = 'login.html';
  }
})();

'use strict';

/* ============================================================
   1. CONSTANTS & STATE
   ============================================================ */
/* Flask on :5000 -> same origin; other localhost ports -> http://localhost:5000; anything else
   (Render static site, custom domain) -> the Render backend. Logic lives in display.js. */
const AD = window.AtlasDisplay;
const API_BASE = AD.resolveApiBase(location);

/* The department of the signed-in profile (sessionStorage 'atlasDept' is only a display cache). Its data is read from
   and saved to Supabase through assets/js/data-store.js; the browser keeps no per-department data. */
const DEPT = (window.atlasDept && window.atlasDept.current()) || 'IT';

const DAY_MAP = {
  Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday',
  Thu: 'Thursday', Fri: 'Friday', Sat: 'Saturday'
};

const DAY_ORDER = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5 };

// MAX_UNITS is dynamic - read from the department's saved solver settings (database), default 24
function getMaxUnits() {
  return window.atlasSolver.read(DEPT).max_units;
}
// Keep a live reference updated on each access
Object.defineProperty(window, 'MAX_UNITS', { get: getMaxUnits });

// UNITS_PER_ASSIGNMENT - dynamic, read from the department's saved solver settings (database), default 2
function getUnitsPerAssignment() {
  return window.atlasSolver.read(DEPT).units_per_assignment;
}

// Per-faculty max_units lookup (falls back to global Standard Max Units)
function getFacultyMaxUnitsMap() {
  const map = {};
  (typeof getFacultyFromTable === 'function' ? getFacultyFromTable() : []).forEach(f => {
    map[f.name] = f.max_units || getMaxUnits();
  });
  return map;
}

const DEFAULT_PERIOD = { year: '2026-2027', semester: '1st Semester' };   // active period until the chairperson sets one

// Specialization tags of the active department: the file's `specializations` (see loadCurriculumData).
let SPECIALIZATIONS = [];

// Offline fallback only: the IT and CS room list ("default" rooms in their files), mirroring
// config/settings.py. The department's real rooms come from GET /rooms?dept=<DEPT>.
const LECTURE_ROOMS = [
  'CL1','CL2','CL3',
  'IT Room 1','IT Room 2','IT Room 3',
  'GA Bldg 16','GA Bldg 17','GA Bldg 18','GA Bldg 19','GA Bldg 20',
  'GA Bldg 21','GA Bldg 22','GA Bldg 23','GA Bldg 24','GA Bldg 25'
];

const LABORATORY_ROOMS = ['MTC1','MTC2','IT101','NIT1','NIT3'];

const DEFAULT_ROOM_CAPACITY = {
  'CL1':       { recommended: 35, max: 52 },
  'CL2':       { recommended: 35, max: 52 },
  'CL3':       { recommended: 35, max: 52 },
  'IT Room 1': { recommended: 45, max: 60 },
  'IT Room 2': { recommended: 45, max: 60 },
  'IT Room 3': { recommended: 45, max: 60 },
  'GA Bldg 16':{ recommended: 40, max: 55 },
  'GA Bldg 17':{ recommended: 40, max: 55 },
  'GA Bldg 18':{ recommended: 40, max: 55 },
  'GA Bldg 19':{ recommended: 40, max: 55 },
  'GA Bldg 20':{ recommended: 40, max: 55 },
  'GA Bldg 21':{ recommended: 40, max: 55 },
  'GA Bldg 22':{ recommended: 40, max: 55 },
  'GA Bldg 23':{ recommended: 40, max: 55 },
  'GA Bldg 24':{ recommended: 40, max: 55 },
  'GA Bldg 25':{ recommended: 40, max: 55 },
  'MTC1':      { recommended: 32, max: 45 },
  'MTC2':      { recommended: 32, max: 45 },
  'IT101':     { recommended: 30, max: 40 },
  'NIT1':      { recommended: 40, max: 45 },
  'NIT3':      { recommended: 40, max: 45 },
};

// Class sizes and blocks per year come from the department's file (see defaultClassSizes()).

// Everything the department owns by default (subjects, blocks, class sizes, tags, rooms flags)
// comes from data/curricula/<DEPT>.json, loaded at startup - see loadCurriculumData().
let ATLAS_CURRICULUM = null;

function applyCurriculum(cur) {
  ATLAS_CURRICULUM = cur && cur.dept === DEPT ? cur : null;
  SPECIALIZATIONS = ATLAS_CURRICULUM ? [...(ATLAS_CURRICULUM.specializations || [])] : [];
}

// The static file first (same relative path and exact-case name on Render), the backend second.
async function loadCurriculumData() {
  const urls = [`../data/curricula/${DEPT}.json`, `${API_BASE}/curriculum/${DEPT}`];
  try {
    applyCurriculum(await AtlasCurriculum.loadCurriculum(DEPT, urls));
  } catch (e) {
    applyCurriculum(null);
    if (!ATLAS_CURRICULUM) console.error('Curriculum could not be loaded:', e);
  }
  return ATLAS_CURRICULUM;
}

function deptName() {
  return (ATLAS_CURRICULUM && ATLAS_CURRICULUM.name) || DEPT;
}

function defaultClassSizes() {
  return ATLAS_CURRICULUM ? JSON.parse(JSON.stringify(ATLAS_CURRICULUM.class_sizes || {})) : {};
}

// A department file may carry its own starting pool (IT: `default_faculty`); the others get 8 placeholders.
function defaultFaculty() {
  if (!ATLAS_CURRICULUM) return [];
  if (Array.isArray(ATLAS_CURRICULUM.default_faculty) && ATLAS_CURRICULUM.default_faculty.length) {
    return ATLAS_CURRICULUM.default_faculty;
  }
  return AtlasCurriculum.placeholderFaculty(ATLAS_CURRICULUM, 8);
}

// The department's rooms when the backend cannot be reached: its file, then the IT/CS list.
function roomDefaultsFromFile() {
  const spec = (ATLAS_CURRICULUM && ATLAS_CURRICULUM.rooms) || {};
  const part = (v, fallback) => (v && v !== 'default')
    ? { rooms: Object.keys(v), cap: v }
    : { rooms: [...fallback], cap: DEFAULT_ROOM_CAPACITY };
  const lec = part(spec.lecture, LECTURE_ROOMS);
  const lab = part(spec.lab, LABORATORY_ROOMS);
  const capacity = {};
  [...lec.rooms.map(r => [r, lec.cap]), ...lab.rooms.map(r => [r, lab.cap])].forEach(([r, c]) => {
    if (c[r]) capacity[r] = { ...c[r] };
  });
  return { lecture: lec.rooms, lab: lab.rooms, capacity };
}

// The department's rooms from the backend (GET /rooms?dept=X), file defaults when it is unreachable.
async function fetchRoomDefaults() {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), 6000) : null;
  try {
    const res = await window.atlasAuth.fetch(`${API_BASE}/rooms?dept=${encodeURIComponent(DEPT)}`, ctl ? { signal: ctl.signal } : {});
    const d = await res.json();
    if (!res.ok || d.dept !== DEPT || !Array.isArray(d.lecture_rooms)) throw new Error('bad /rooms response');
    return { lecture: d.lecture_rooms, lab: d.laboratory_rooms || [], capacity: d.room_capacity || {} };
  } catch {
    return roomDefaultsFromFile();
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// Table sort state
let lastSort = { key: 'slot', ascending: true };

// Last known GA result for re-rendering
let lastGAResult = [];
let currentRunDbId = null;      // id of the saved run (schedule_runs) shown on screen, if any
let currentRunStatus = null;
let screenSemester = null;     // semester of the saved run on screen (so another semester's run is not filtered away)
let savedRunsCtl = null;       // controller of the Saved runs card (assets/js/saved-runs.js)
let roomsSyncedSig = '';        // rooms last sent to the engine (so a run does not resend an unchanged list)
let lastCoverage = null;   // {coverage: {assigned,total}, errors: [...]} of the last run (this department)

/* Coverage summary ("30 of 30 block-courses assigned") and the list of coverage_errors */
function renderCoverageSummary(cov) {
  const box = document.getElementById('coverageSummary');
  if (!box) return;
  if (!cov || !cov.coverage || !cov.coverage.total) { box.innerHTML = ''; box.classList.add('hidden'); return; }
  const errs = cov.errors || [];
  const full = errs.length === 0 && cov.coverage.assigned === cov.coverage.total;
  box.className = 'coverage-summary ' + (full ? 'coverage-ok' : 'coverage-warn');
  box.innerHTML = `<strong>Coverage:</strong> ${escapeHTML(AD.coverageText(cov.coverage))}` +
    (errs.length ? `<details><summary>${errs.length} not covered</summary><ul>${
      errs.map(e => `<li>${escapeHTML(AD.coverageErrorText(e))}</li>`).join('')}</ul></details>` : '');
}

/* ============================================================
   SECTION LABEL UTILITY
   Maps year field to section keys e.g. "1st Year" → ["IT1B1","IT1B2"]
   ============================================================ */
function getSectionLabelsForYear(year) {
  const sizes = getClassSizes();
  const labels = Object.entries(sizes)
    .filter(([, v]) => v.year === year)
    .map(([k]) => k)
    .sort();
  return labels;
}

function getSectionBadgeHTML(year) {
  if (!year) return '';
  const labels = getSectionLabelsForYear(year);
  if (!labels.length) return '';
  return labels.map(l =>
    `<span class="section-badge">${escapeHTML(l)}</span>`
  ).join('');
}

/* ============================================================
   2. CHART INSTANCES
   ============================================================ */
let dashboardChart = null;
let reportsChart    = null;
let reportsBarChart = null;
let miniDashChart   = null;

/* Chart palette: every colour comes from the --chart-* tokens in main-style.css, so light and dark
   (and auto / schedule, which switch while the page is open) share one source of truth. */
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
const THEME = { series: [] };
function readTheme() {
  THEME.ink = cssVar('--chart-ink');
  THEME.tooltipText = cssVar('--chart-tooltip-text');
  THEME.muted = cssVar('--chart-muted');
  THEME.grid = cssVar('--chart-grid');
  THEME.surface = cssVar('--chart-surface');
  THEME.ok = cssVar('--chart-ok');
  THEME.warn = cssVar('--chart-warn');
  THEME.bad = cssVar('--chart-bad');
  THEME.series = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(i => cssVar('--chart-s' + i));
}
readTheme();

function styleChartDefaults() {
  const d = Chart.defaults;
  d.font.family = "'DM Sans', system-ui, sans-serif";
  d.font.size = 12;
  d.color = THEME.muted;
  d.plugins.legend.labels.usePointStyle = true;
  d.plugins.legend.labels.pointStyle = 'circle';
  d.plugins.legend.labels.boxWidth = 8;
  d.plugins.legend.labels.boxHeight = 8;
  d.plugins.legend.labels.padding = 16;
  Object.assign(d.plugins.tooltip, {
    backgroundColor: THEME.ink, titleColor: THEME.tooltipText, bodyColor: THEME.tooltipText,
    padding: 10, cornerRadius: 8, boxPadding: 4, displayColors: false
  });
}

/* Theme changed (light/dark/auto/schedule): re-read the tokens, recolour every chart and redraw. */
function applyChartTheme() {
  if (typeof Chart === 'undefined') return;
  const old = { ok: THEME.ok, warn: THEME.warn, bad: THEME.bad, series: THEME.series.slice() };
  readTheme();
  const map = new Map([[old.ok, THEME.ok], [old.warn, THEME.warn], [old.bad, THEME.bad]]);
  old.series.forEach((c, i) => { if (!map.has(c)) map.set(c, THEME.series[i]); });
  const remap = c => (map.has(c) ? map.get(c) : c);
  styleChartDefaults();
  [dashboardChart, miniDashChart, reportsChart, reportsBarChart].forEach(ch => {
    if (!ch) return;
    ch.data.datasets.forEach(ds => {
      if (Array.isArray(ds.backgroundColor)) ds.backgroundColor = ds.backgroundColor.map(remap);
      else if (ds.backgroundColor) ds.backgroundColor = remap(ds.backgroundColor);
    });
    const sc = ch.options.scales || {};
    Object.values(sc).forEach(ax => { if (ax.grid && ax.grid.color) ax.grid.color = THEME.grid; });
    ch.update('none');
  });
  if (reportsChart) {
    reportsChart.data.datasets.forEach(ds => { ds.borderColor = THEME.surface; });
    reportsChart.update('none');
  }
}
new MutationObserver(applyChartTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

function initCharts() {
  if (typeof Chart === 'undefined') { console.warn('Chart.js is not loaded; charts are skipped.'); return; }
  styleChartDefaults();
  // Dashboard bar chart
  const ctxDash = document.getElementById('dashboardChart');
  if (ctxDash) {
    dashboardChart = new Chart(ctxDash, {
      type: 'bar',
      data: { labels: [], datasets: [{ label: 'Units per Faculty', data: [], backgroundColor: [], borderRadius: 8, borderSkipped: false, maxBarThickness: 40 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { beginAtZero: true, border: { display: false }, grid: { color: THEME.grid }, ticks: { padding: 8, precision: 0 } },
          x: { border: { display: false }, grid: { display: false } }
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              generateLabels: () => [
                { text: 'Normal',          fillStyle: THEME.ok,   strokeStyle: THEME.ok,   pointStyle: 'circle' },
                { text: 'Max Load',        fillStyle: THEME.warn, strokeStyle: THEME.warn, pointStyle: 'circle' },
                { text: 'Over/Under Load', fillStyle: THEME.bad,  strokeStyle: THEME.bad,  pointStyle: 'circle' }
              ]
            },
            onClick: (e, legendItem, legend) => {
              const selColor = legendItem.fillStyle;
              const chart = legend.chart;
              const ds = chart.data.datasets[0];
              let combined = chart.data.labels.map((label, i) => ({
                label, value: ds.data[i], color: ds.backgroundColor[i]
              }));
              if (!chart.sortOrder) chart.sortOrder = 'asc';
              const orderMap = { [THEME.ok]: 0, [THEME.warn]: 1, [THEME.bad]: 2 };
              combined.sort((a, b) => {
                if (a.color === selColor) return -1;
                if (b.color === selColor) return 1;
                return (orderMap[a.color] - orderMap[b.color]);
              });
              chart.data.labels = combined.map(d => d.label);
              ds.data = combined.map(d => d.value);
              ds.backgroundColor = combined.map(d => d.color);
              chart.update();
            }
          },
          tooltip: {
            callbacks: {
              label: ctx => {
                const v = ctx.raw;
                const fmax = getFacultyMaxUnitsMap()[ctx.label] || MAX_UNITS;
                let status = v > fmax ? ' OVERLOAD' : v === fmax ? ' MAX LOAD' : v <= 2 ? ' TOO LOW' : '';
                return `${ctx.label}: ${v} units${status}`;
              }
            }
          }
        }
      }
    });
  }

  // Reports pie chart
  const ctxPie = document.getElementById('reportsChart');
  if (ctxPie) {
    reportsChart = new Chart(ctxPie, {
      type: 'doughnut',
      data: {
        labels: [],
        datasets: [{
          data: [],
          backgroundColor: THEME.series,
          borderColor: THEME.surface,
          borderWidth: 3,
          hoverOffset: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '64%',
        plugins: {
          legend: { position: window.innerWidth < 768 ? 'bottom' : 'right' },
          tooltip: {
            callbacks: {
              label: ctx => {
                const v = ctx.raw;
                const fmax = getFacultyMaxUnitsMap()[ctx.label] || MAX_UNITS;
                const status = v > fmax ? ' (OVERLOAD)' : v === fmax ? ' (MAX LOAD)' : '';
                return `${ctx.label}: ${v} units${status}`;
              }
            }
          }
        }
      }
    });
  }

  // Reports bar chart
  const ctxBar = document.getElementById('reportsBarChart');
  if (ctxBar) {
    reportsBarChart = new Chart(ctxBar, {
      type: 'bar',
      data: { labels: [], datasets: [{ label: 'Total Teaching Units', data: [], backgroundColor: [], borderRadius: 6, borderSkipped: false, barThickness: 18 }] },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, border: { display: false }, grid: { color: THEME.grid }, ticks: { precision: 0 } },
          y: { border: { display: false }, grid: { display: false }, ticks: { autoSkip: false } }
        }
      }
    });
  }

  // Mini live chart
  const ctxMini = document.getElementById('miniDashChart');
  if (ctxMini) {
    miniDashChart = new Chart(ctxMini, {
      type: 'bar',
      data: { labels: [], datasets: [{ label: 'Load', data: [], backgroundColor: [], borderRadius: 3, borderSkipped: false }] },
      options: {
        responsive: false,
        animation: { duration: 150 },
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, max: 35, grid: { display: false } }, x: { grid: { display: false }, ticks: { font: { size: 8 } } } }
      }
    });
  }
}

/* ============================================================
   3. PANEL NAVIGATION
   ============================================================ */
function initNavigation() {
  const panels   = document.querySelectorAll('.panel');
  const navItems = document.querySelectorAll('.nav-item[data-panel]');

  if (!panels.length) return;

  navItems.forEach(item => {
    item.addEventListener('click', () => {
      const idx = parseInt(item.dataset.panel, 10);
      switchPanel(idx);
    });
  });

  // Switch to panel 0 on load
  switchPanel(window.atlasApp ? window.atlasApp.startPanel(document.querySelectorAll('.panel').length) : 0);

  // Resize chart on window resize
  window.addEventListener('resize', debounce(() => {
    if (dashboardChart) dashboardChart.resize();
  }, 200));
}

function switchPanel(index) {
  const panels    = document.querySelectorAll('.panel');
  const navItems  = document.querySelectorAll('.nav-item[data-panel]');

  panels.forEach((p, i) => p.classList.toggle('active', i === index));
  navItems.forEach((item, i) => item.classList.toggle('active', i === index));

  // Resize charts after panel is visible
  setTimeout(() => {
    if (dashboardChart) dashboardChart.resize();
    if (reportsChart)   reportsChart.resize();
    if (reportsBarChart) reportsBarChart.resize();
  }, 50);
}

/* ============================================================
   4. COLOR HELPERS
   ============================================================ */
function getLoadColor(value, max = MAX_UNITS) {
  if (value > max) return THEME.bad;
  if (value === max) return THEME.warn;
  if (value <= 2) return THEME.bad;
  return THEME.ok;
}

function getProgressColor() {
  return '#c0440a';
}

/* ============================================================
   5. CHART UPDATE FUNCTIONS
   ============================================================ */
function updateCharts(data) {
  if (!data || !data.length) return;

  const upa = getUnitsPerAssignment();
  const facMaxMap = getFacultyMaxUnitsMap();

  const counts = {};
  data.forEach(item => {
    if (!item.faculty) return;
    counts[item.faculty] = (counts[item.faculty] || 0) + upa;
  });

  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const labels = sorted.map(x => x[0]);
  const values = sorted.map(x => x[1]);
  const colors = values.map((v, i) => getLoadColor(v, facMaxMap[labels[i]] || MAX_UNITS));

  if (dashboardChart) {
    dashboardChart.data.labels = labels;
    dashboardChart.data.datasets[0].data = values;
    dashboardChart.data.datasets[0].backgroundColor = colors;
    dashboardChart.update();
  }
  if (miniDashChart) {
    miniDashChart.data.labels = labels;
    miniDashChart.data.datasets[0].data = values;
    miniDashChart.data.datasets[0].backgroundColor = colors;
    miniDashChart.update();
  }
  if (reportsChart) {
    reportsChart.data.labels = labels;
    reportsChart.data.datasets[0].data = values;
    reportsChart.update();
  }
  if (reportsBarChart) {
    reportsBarChart.data.labels = labels;
    reportsBarChart.data.datasets[0].data = values;
    reportsBarChart.data.datasets[0].backgroundColor = colors;
    reportsBarChart.update();
  }

  updateDashboardStats(counts, facMaxMap);
}

/* ============================================================
   5b. DASHBOARD STAT CARDS
   ============================================================ */
function updateDashboardStats(counts, facMaxMap = {}) {
  const values = Object.values(counts);
  if (!values.length) return;
  const avg = (values.reduce((a, b) => a + b, 0) / values.length).toFixed(1);
  const overloaded = Object.entries(counts).filter(([name, v]) => v > (facMaxMap[name] || MAX_UNITS)).length;
  const wlm = (window.__atlasAnalytics || {}).workload_metrics;
  const balance = wlm && wlm.jain_exact !== undefined ? Math.round(wlm.jain_exact * 100) : null;   // same number as Saved runs and Reports
  const elAvg  = document.getElementById('statAvgLoad');
  const elOver = document.getElementById('statOverloaded');
  const elBal  = document.getElementById('statBalance');
  if (elAvg)  elAvg.textContent  = avg;
  if (elOver) elOver.textContent = overloaded;
  if (elBal)  elBal.textContent  = balance === null ? '-' : balance + '%';
}

/* ============================================================
   5b-2. CAPACITY METRICS DASHBOARD CARD
   ============================================================ */
function renderCapacityMetrics(capacityMetrics) {
  const card = document.getElementById('capacitySummaryCard');
  if (!card) return;

  card.style.display = '';

  if (!capacityMetrics) capacityMetrics = {};

  card.style.display = '';

  const total  = capacityMetrics.total_evaluated || 0;
  const okCnt  = capacityMetrics.within_recommended_count || 0;
  const warnCt = capacityMetrics.over_recommended_count   || 0;
  const hardCt = capacityMetrics.hard_violation_count     || 0;

  const pct = n => total > 0 ? ((n / total) * 100).toFixed(1) + '%' : '-';

  document.getElementById('capMetricTotal').textContent   = total;
  document.getElementById('capMetricOk').textContent      = okCnt;
  document.getElementById('capMetricOkPct').textContent   = pct(okCnt);
  document.getElementById('capMetricWarn').textContent    = warnCt;
  document.getElementById('capMetricWarnPct').textContent = pct(warnCt);
  document.getElementById('capMetricHard').textContent    = hardCt;
  document.getElementById('capMetricHardPct').textContent = pct(hardCt);

  // Overall status badge
  const badge = document.getElementById('capacityOverallBadge');
  if (badge) {
    if (hardCt > 0) {
      badge.textContent = `${hardCt} Hard Violation${hardCt > 1 ? 's' : ''}`;
      badge.className = 'capacity-overall-badge badge-hard';
    } else if (warnCt > 0) {
      badge.textContent = `${warnCt} Over Recommended`;
      badge.className = 'capacity-overall-badge badge-warn';
    } else {
      badge.textContent = 'All Rooms Within Capacity';
      badge.className = 'capacity-overall-badge badge-ok';
    }
  }

  // Hard violations detail list
  const violList = document.getElementById('capacityHardViolationsList');
  const violItems = document.getElementById('capacityHardViolationsItems');
  const violations = capacityMetrics.hard_violations || [];
  if (violList && violItems) {
    if (violations.length > 0) {
      violList.style.display = '';
      violItems.innerHTML = violations.map(v => `
        <div class="capacity-violation-row">
          <span class="viol-room">${escapeHTML(v.room || '?')}</span>
          <span class="viol-detail">
            ${escapeHTML(v.subject || '')} · ${escapeHTML(v.section || '')}
            <span class="viol-counts">${v.student_count} students / max ${v.max_cap} (+${v.excess})</span>
          </span>
        </div>
      `).join('');
    } else {
      violList.style.display = 'none';
    }
  }
}

/* ============================================================
   5c. TIMETABLE RENDER
   ============================================================ */
function renderTimetable(data) {
  const container = document.getElementById('facultyTimetableContainer');
  if (!container) return;

  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const SLOT_DEFS = [
    { label: '7-9',   startH: 7,  endH: 9  },
    { label: '9-11',  startH: 9,  endH: 11 },
    { label: '13-15', startH: 13, endH: 15 },
    { label: '15-17', startH: 15, endH: 17 },
    { label: '17-19', startH: 17, endH: 19 },
  ];

  // Build lookup keyed by "Day-startH-endH"
  const lookup = {};
  data.forEach(item => {
    const slot = item.slot || '';
    const dayMatch  = slot.match(/^(\w+):/);
    const timeMatch = slot.match(/(\d+):00-(\d+):00/);
    if (!dayMatch || !timeMatch) return;
    const day    = dayMatch[1].trim();
    const startH = parseInt(timeMatch[1], 10);
    const endH   = parseInt(timeMatch[2], 10);
    const key    = `${day}-${startH}-${endH}`;
    if (!lookup[key]) lookup[key] = [];
    lookup[key].push({
      faculty:      item.faculty,
      subject:      item.subject,
      class_type:   item.class_type || 'LECTURE',
      room:         item.room || '',
      slot_display: item.slot_display || item.slot,
      section:      AD.rowLabel(item),
      year:         item.year || ''
    });
  });

  let html = '<div class="timetable-scroll"><table class="timetable-grid"><thead><tr>';
  html += '<th class="tt-time-col">Time</th>';
  DAYS.forEach(d => { html += `<th class="tt-day-col tt-hd-${d}">${d}</th>`; });
  html += '</tr></thead><tbody>';

  SLOT_DEFS.forEach(({ label, startH, endH }) => {
    html += `<tr><td class="tt-time-label">${label}</td>`;
    DAYS.forEach(day => {
      const key     = `${day}-${startH}-${endH}`;
      const entries = lookup[key] || [];
      if (!entries.length) {
        html += `<td class="tt-cell tt-empty"></td>`;
      } else {
        html += `<td class="tt-cell tt-filled tt-bg-${day}">`;
        entries.forEach(e => {
          const ctClass = (e.class_type || 'LECTURE').toLowerCase();
          const secTag = e.section ? `<span class="tt-section-tag">${escapeHTML(e.section)}</span>` : '';
          html += `<div class="tt-entry">
            <span class="tt-class-tag ${ctClass}">${escapeHTML(e.class_type || 'LECTURE')}</span>
            ${secTag}
            <div class="tt-faculty-tag">${escapeHTML(e.faculty)}</div>
            <div class="tt-subject-tag">${escapeHTML(e.subject)}</div>
            ${e.room ? `<span class="tt-room-tag"> ${escapeHTML(e.room)}</span>` : ''}
          </div>`;
        });
        html += `</td>`;
      }
    });
    html += '</tr>';
  });

  html += '</tbody></table></div>';
  container.innerHTML = html;
}

/* ============================================================
   5d. REPORTS SUMMARY TABLE
   ============================================================ */
function updateReportsPanel(data) {
  if (!data || !data.length) return;

  const byFaculty = {};
  data.forEach(item => {
    if (!item.faculty) return;
    if (!byFaculty[item.faculty]) byFaculty[item.faculty] = [];
    byFaculty[item.faculty].push(item);
  });

  // Find the legacy table wrapper - we replace its parent or insert sibling
  const legacyTable = document.getElementById('reportsSummaryTable');
  if (!legacyTable) return;

  // Build or reuse the summary grid container
  let grid = document.getElementById('reportsSummaryGrid');
  if (!grid) {
    grid = document.createElement('div');
    grid.id = 'reportsSummaryGrid';
    grid.className = 'summary-faculty-grid';
    legacyTable.parentNode.insertBefore(grid, legacyTable);
    legacyTable.style.display = 'none'; // hide old table
  }
  grid.innerHTML = '';

  const sortedFaculty = Object.keys(byFaculty).sort();

  const upa = getUnitsPerAssignment();
  const facMaxMap = getFacultyMaxUnitsMap();

  sortedFaculty.forEach(faculty => {
    const assignments = byFaculty[faculty];
    const totalUnits  = assignments.length * upa;
    const fmax        = facMaxMap[faculty] || MAX_UNITS;
    const unitsCls    = totalUnits > fmax ? 'units-over' : totalUnits === fmax ? 'units-max' : 'units-ok';

    // Sort assignments: by day order then time
    const sorted = [...assignments].sort((a, b) => {
      const parseSlot = s => {
        const [d, t] = (s || '').split(':');
        return (DAY_ORDER[d.trim()] || 0) * 100 + parseInt(t || '0');
      };
      return parseSlot(a.slot) - parseSlot(b.slot);
    });

    const rowsHTML = sorted.map(item => {
      const displaySlot = item.slot_display || item.slot || '';
      const [slotDay, ...slotRest] = displaySlot.split(':');
      const slotTime = slotRest.join(':').trim();
      const ctClass  = (item.class_type || 'LECTURE').toLowerCase();
      const noRoom = AD.isNoClassroom(item);
      const sectionTag = AD.rowLabel(item)
        ? `<span class="section-badge">${escapeHTML(AD.rowLabel(item))}</span>`
        : (item.year ? `<span class="subject-year-badge">${escapeHTML(item.year.replace(' Year','Y'))}</span>` : '');
      const students = item.student_count > 0 ? `<span class="summary-students">${item.student_count} students</span>` : '';

      return `
        <tr>
          <td>
            <div class="summary-subj-name">${escapeHTML(item.subject)}</div>
            <div class="summary-subj-meta">
              <span class="class-type-tag ${ctClass}">${escapeHTML(AD.classTypeText(item))}</span>
              ${sectionTag}
            </div>
          </td>
          <td>
            ${noRoom ? '<span class="text-muted">-</span>' : displaySlot ? `<div class="summary-slot-day">${escapeHTML(slotDay.trim())}</div><div class="summary-slot-time">${escapeHTML(slotTime)}</div>` : '<span class="text-muted">-</span>'}
          </td>
          <td>
            <div class="summary-room">${noRoom ? escapeHTML(AD.NO_CLASSROOM_TEXT) : item.room ? escapeHTML(item.room) : '<span class="text-muted">-</span>'}</div>
            <div class="summary-room-meta">${students}${buildCapacityBadge(item)}</div>
          </td>
        </tr>`;
    }).join('');

    const initials = faculty.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();

    const card = document.createElement('div');
    card.className = 'summary-faculty-card';
    card.innerHTML = `
      <div class="summary-fac-header">
        <div class="summary-fac-avatar">${escapeHTML(initials)}</div>
        <div class="summary-fac-info">
          <div class="summary-fac-name">${escapeHTML(faculty)}</div>
          <div class="summary-fac-count">${assignments.length} assignment${assignments.length !== 1 ? 's' : ''}</div>
        </div>
        <div class="summary-fac-actions">
          <span class="units-badge ${unitsCls}">${totalUnits} units</span>
          <button class="btn-edit-faculty btn" data-faculty="${escapeAttr(faculty)}">&#9998; Edit</button>
        </div>
      </div>
      <table class="summary-assignments-table">
        <colgroup>
          <col class="col-subject">
          <col class="col-schedule">
          <col class="col-room">
        </colgroup>
        <thead>
          <tr>
            <th>Subject</th>
            <th>Schedule</th>
            <th>Room</th>
          </tr>
        </thead>
        <tbody>${rowsHTML}</tbody>
      </table>`;

    grid.appendChild(card);
  });
}


// Same qualification rule as the backend, using the tags of the department's own file.
function specMatchesCourse(specList, subjectTitle) {
  if (!ATLAS_CURRICULUM) return true;
  return AtlasCurriculum.qualifies(specList, AtlasCurriculum.courseTags(ATLAS_CURRICULUM, subjectTitle));
}

function computeFairnessReport(data) {
  if (!data || !data.length) return;

  // Every number comes from the backend analytics payload (services/analytics_service.py). Nothing is recomputed here.
  const an = window.__atlasAnalytics || {};
  const wl = an.workload_metrics && an.workload_metrics.per_professor ? an.workload_metrics : null;
  const sp = an.specialization_metrics && an.specialization_metrics.scored_group_count !== undefined ? an.specialization_metrics : null;
  const el = id => document.getElementById(id);
  const set = (id, text) => { const n = el(id); if (n) n.textContent = text; };

  if (wl) {
    const bands = wl.bands || { good: 0.9, warning: 0.8 };
    const cls = wl.jain >= bands.good ? 'good' : wl.jain >= bands.warning ? 'warning' : 'danger';
    const label = cls === 'good' ? 'Good - evenly balanced' : cls === 'warning' ? 'Moderate - minor imbalances' : 'Poor - significant imbalances';
    set('fairnessScore', Math.round(wl.jain_exact * 100) + '%');
    el('fairnessScore').className = 'fairness-card-value ' + cls;
    set('fairnessScoreLabel', label + (window.__atlasAnalyticsStale ? ' (generated run, not updated for manual edits)' : ''));
    set('fairnessJain', wl.jain.toFixed(4));
    set('fairnessStdDev', wl.std.toFixed(2) + ' u');
    set('fairnessMinMax', wl.min + ' / ' + wl.max + ' u');
    set('fairnessZeroLoad', String(wl.zero_load_count));
  } else {
    ['fairnessScore', 'fairnessJain', 'fairnessStdDev', 'fairnessMinMax', 'fairnessZeroLoad'].forEach(id => set(id, '-'));
    set('fairnessScoreLabel', 'Not available for this run');
  }
  if (sp) {
    set('fairnessMatchRate', sp.primary_tag_match_pct.toFixed(1) + '%');
    set('fairnessQualified', sp.any_tag_match_pct.toFixed(1) + '%');
    set('fairnessElectiveGroups', String(sp.elective_group_count));
  } else {
    ['fairnessMatchRate', 'fairnessQualified', 'fairnessElectiveGroups'].forEach(id => set(id, '-'));
  }

  const facultyData = getFacultyFromTable();
  const facMeta = {};
  facultyData.forEach(f => { facMeta[f.name] = f; });
  const perFaculty = {};
  const specByFac = {};
  ((sp && sp.per_faculty) || []).forEach(d => { specByFac[d.faculty] = d; });
  ((wl && wl.per_professor) || []).forEach(p => {
    const s = specByFac[p.faculty] || { groups: 0, primary: 0 };
    perFaculty[p.faculty] = { total: s.groups, matched: s.primary, load: p.units, max: p.max_units };
  });

  // Per-faculty table
  const container = document.getElementById('fairnessPerFaculty');
  if (!container) return;

  const rows = Object.keys(perFaculty).sort().map(name => {
    const d = perFaculty[name];
    const pct = d.total ? Math.round((d.matched / d.total) * 100) : 0;
    const cls = pct === 100 ? 'match-yes' : pct >= 50 ? 'match-partial' : 'match-no';
    const facMax = d.max || facMeta[name]?.max_units || MAX_UNITS;
    const loadCls = d.load > facMax ? 'badge-danger' : d.load === facMax ? 'badge-warning' : 'badge-success';

    return `
      <tr>
        <td><strong>${escapeHTML(name)}</strong></td>
        <td><span class="load-badge ${loadCls}">${d.load} / ${d.max || facMeta[name]?.max_units || 24} u</span></td>
        <td>${d.total} scored course groups</td>
        <td><span class="match-indicator ${cls}">${pct}% primary tag (${d.matched}/${d.total})</span></td>
      </tr>
    `;
  });

  container.innerHTML = `
    <table class="data-table layout-fixed">
      <thead>
        <tr>
          <th>Faculty Member</th>
          <th>Workload Status</th>
          <th>Course Groups</th>
          <th>Primary Tag Match</th>
        </tr>
      </thead>
      <tbody>
        ${rows.join('') || '<tr><td colspan="4" class="empty-state-msg">No faculty metrics computed yet.</td></tr>'}
      </tbody>
    </table>
  `;
}

/* ============================================================
   7. TABLE RENDERING & SORTING
   ============================================================ */
function renderTable(data) {
  const tbody = document.querySelector('#gaScheduleTable tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (!data || !data.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-state-msg">No optimal assignments found. Adjust parameters and click "Run Engine".</td></tr>';
    return;
  }

  // Pre-sort by Day Order then Slot Order by default
  const sorted = [...data].sort((a, b) => {
    const parseSlot = s => {
      const [dayPart, timePart] = (s || '').split(':');
      return { day: dayPart.trim(), unit: parseInt((timePart || '0').trim()) };
    };
    const sA = parseSlot(a.slot), sB = parseSlot(b.slot);
    return ((DAY_ORDER[sA.day] ?? 99) - (DAY_ORDER[sB.day] ?? 99)) || (sA.unit - sB.unit);
  });

  // Apply current sort
  applySort(sorted, lastSort.key, lastSort.ascending);

  sorted.forEach(item => {
    const day = (item.slot || '').split(':')[0].trim();
    const displaySlot = item.slot_display || item.slot || 'N/A';
    const tr = document.createElement('tr');
    tr.dataset.day = day;
    const noRoom = AD.isNoClassroom(item);
    const sectionHTML = AD.rowLabel(item)
      ? `<span class="section-badge">${escapeHTML(AD.rowLabel(item))}</span>`
      : (item.year ? getSectionBadgeHTML(item.year) : '<span class="text-muted">N/A</span>');
    tr.innerHTML = `
      <td>${escapeHTML(item.faculty)}</td>
      <td>${escapeHTML(item.subject)}</td>
      <td class="section-cell">${sectionHTML}</td>
      <td>${escapeHTML(item.type)}</td>
      <td><span class="class-type-tag ${(item.class_type||'LECTURE').toLowerCase()}">${escapeHTML(AD.classTypeText(item))}</span></td>
      <td>${noRoom ? '<span class="text-muted">-</span>' : escapeHTML(displaySlot)}</td>
      <td>${noRoom ? `<span class="text-muted">${escapeHTML(AD.NO_CLASSROOM_TEXT)}</span>` : item.room ? `<span class="room-badge"> ${escapeHTML(item.room)}</span>` : '<span class="text-muted">N/A</span>'}</td>
      <td>${item.student_count > 0 ? `<span class="student-count-tag">${item.student_count}</span>` : '<span class="text-muted">-</span>'}</td>
      <td>${buildCapacityBadge(item)}</td>
    `;
    tbody.appendChild(tr);
  });

  enableTableSort();
}

function applySort(data, key, ascending) {
  data.sort((a, b) => {
    const dir = ascending ? 1 : -1;
    if (key === 'slot') {
      const ps = s => {
        const [d, t] = (s || '').split(':');
        return ((DAY_ORDER[d.trim()] ?? 99) * 100) + (parseInt(t || '0') || 0);
      };
      return (ps(a.slot) - ps(b.slot)) * dir;
    }
    return (a[key] || '').localeCompare(b[key] || '') * dir;
  });
}

function enableTableSort() {
  document.querySelectorAll('#gaScheduleTable th[data-key]').forEach(th => {
    // Clean old listeners
    const cloned = th.cloneNode(true);
    th.parentNode.replaceChild(cloned, th);

    // Active arrow indicator
    if (cloned.dataset.key === lastSort.key) {
      cloned.classList.add('sorted-active');
      cloned.classList.toggle('sorted-desc', !lastSort.ascending);
    } else {
      cloned.classList.remove('sorted-active', 'sorted-desc');
    }

    cloned.addEventListener('click', () => {
      if (lastSort.key === cloned.dataset.key) {
        lastSort.ascending = !lastSort.ascending;
      } else {
        lastSort.key = cloned.dataset.key;
        lastSort.ascending = true;
      }
      renderTable(lastGAResult);
    });
  });
}

/* ============================================================
   8. RUN GENETIC ALGORITHM ENGINE
   ============================================================ */
let progressInterval = null;
let currentRun = null;          // {dept, run_id} of the run this session started
const progressFill = document.querySelector('#gaProgressBar .fill');

async function triggerGARunAPI() {
  const sysCfg = getSystemSettings();      // read at click time: a change made in the menu settings applies now
  const { population, generations, mutation, crossover } = sysCfg;

  if (!ATLAS_CURRICULUM) await loadCurriculumData();
  if (!ATLAS_CURRICULUM) {
    throw new Error('Curriculum file could not be loaded. Check your connection and reload.');
  }

  const mode = getActiveSemester();
  const classSizes = getClassSizes();
  const tableRows = getSubjectsFromTable();

  // Every in-scope course x every block of its year (rule R1). The table only
  // supplies edited units/types, matched by prospectus code.
  const built = AtlasCurriculum.buildPayloadSubjects(
    ATLAS_CURRICULUM, mode ? mode.semester : null, classSizes, tableRows
  );
  const expandedSubjects = built.subjects;

  if (built.errors.length) {
    console.warn('[ATLAS] Courses without blocks:', built.errors);
  }
  const customRows = tableRows.filter(r => r.name && !r.code).length;
  if (customRows) {
    console.warn(`[ATLAS] ${customRows} subject row(s) have no prospectus code and are not scheduled.`);
  }

  if (!expandedSubjects.length) {
    throw new Error(
      mode
        ? `No courses found for ${mode.semester}. Check the class sizes and the active period.`
        : 'No courses to schedule. Check the curriculum and class sizes.'
    );
  }

  // Everything below comes from what was loaded from (and saved to) the database, never from the browser's storage.
  if (window.atlasData.pendingSaves() > 0) {
    throw new Error('Some changes are not saved yet. Wait for "Saved" (or press Retry), then run again.');
  }
  const dbFaculty = window.atlasData.faculty.list().map(f => ({
    name: f.name, specialization: f.specialization, max_units: f.max_units, overload_buffer: f.overload_buffer,
    absolute_max_units: f.max_units + f.overload_buffer, availability: f.availability
  }));
  if (!dbFaculty.length) throw new Error('No faculty are saved for this department. Add faculty or load the sample faculty first.');

  // Preferences and leave dates (leave goes in as leave_dates, which the engine already scores as unavailable dates)
  const softConstraints = loadSoftConstraintsFromStorage();
  await ensureRoomsSynced();

  const payload = {
    dept:             DEPT,
    academic_year:    mode ? mode.year : null,
    faculty:          dbFaculty,
    subjects:         expandedSubjects,
    population,
    generations,
    mutation,
    crossover,
    soft_constraints: softConstraints,
    active_semester:  mode ? mode.semester : null,
    class_sizes:      getClassSizes(),
    room_capacity:    runtimeRoomCapacity,
    units_per_assignment: sysCfg.units_per_assignment,
    cp_sat_time_limit:    sysCfg.cp_sat_time_limit,
  };

  const response = await window.atlasAuth.fetch(`${API_BASE}/run-ga`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const raw = await response.text();
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; } catch (e) { /* not JSON */ }
  if (!response.ok && !data.status) {
    throw new Error(data.error || ('Server answered ' + response.status + (raw ? '' : ' with an empty reply') + '. Check the Render logs.'));
  }
  if (!data.status) throw new Error(data.error || 'GA start failed');
  if (data.dept !== DEPT) throw new Error('The engine answered for another department.');
  currentRun = { dept: DEPT, run_id: data.run_id };
}

function initRunGA() {
  const runBtn = document.getElementById('runGA');
  const loading = document.getElementById('gaLoading');
  const tableWrapper= document.getElementById('gaTableWrapper');
  const genCounter = document.getElementById('generationCounter');

  if (!runBtn) return;

  runBtn.addEventListener('click', async () => {
    loading.classList.remove('hidden');
    tableWrapper.classList.add('hidden');
    runBtn.disabled = true;
    if (progressFill) {
      progressFill.style.width = '0%';
    }

    try {
      await triggerGARunAPI();

      // Poll progress endpoint loop integration routine
      progressInterval = setInterval(async () => {
        try {
          if (!currentRun) return;
          const res = await window.atlasAuth.fetch(`${API_BASE}/progress?dept=${encodeURIComponent(DEPT)}&run_id=${encodeURIComponent(currentRun.run_id)}`);
          const status = await res.json();
          // Ignore any answer that belongs to another department or another run.
          if (!currentRun || status.dept !== DEPT || status.run_id !== currentRun.run_id) return;

          if (status.total > 0) {
            const pct = Math.min(100, Math.round((status.current / status.total) * 100));
            if (progressFill) {
              progressFill.style.width = pct + '%';
              progressFill.style.backgroundColor = getProgressColor(pct);
            }
            if (genCounter) {
              const phaseLabel = status.phase === 'cp_sat' ? 'CP-SAT Solving'
                : status.phase === 'ga' ? 'GA Optimizing'
                : status.phase === 'analytics' ? 'Computing Analytics'
                : 'Processing';
              genCounter.textContent = `${phaseLabel}: ${pct}%`;
            }
          }

          if (!status.running) {
            clearInterval(progressInterval);
            loading.classList.add('hidden');
            tableWrapper.classList.remove('hidden');
            runBtn.disabled = false;

            screenSemester = null;                           // a new run belongs to the active period
            lastGAResult = status.result || [];
            window.__atlasAnalytics = status.analytics && Object.keys(status.analytics).length ? status.analytics : null;
            window.__atlasAnalyticsStale = false;
            if (status.analytics && status.analytics.capacity_metrics) {
              mergeCapacityStatuses(status.analytics);
            }
            const displayResult = filterResultBySemester(lastGAResult);
            renderTable(displayResult);
            updateCharts(displayResult);
            computeFairnessReport(displayResult);
            renderDashboardAssignments(displayResult);
            renderTimetable(displayResult);
            updateReportsPanel(displayResult);
            renderSubjectsGrouped();

            // Store analytics from backend if available
            if (status.analytics && Object.keys(status.analytics).length > 0) {
              try {
                window.__atlasAnalytics = status.analytics;
                renderCapacityMetrics(resolveCapacityMetrics(status.analytics));
                renderCapacityAnalytics(status.analytics);
              } catch(e) { console.warn('Analytics render error:', e); }
            }
            // Display backend warnings
            if (status.warnings && status.warnings.length > 0) {
              status.warnings.forEach(w => console.warn('[ATLAS]', w));
            }

            currentRunDbId = status.saved_run_id || null;     // the server saved this run as a draft in Supabase
            currentRunStatus = currentRunDbId ? 'draft' : null;
            screenSemester = null;
            if (savedRunsCtl && currentRunDbId) savedRunsCtl.noteFreshRun(currentRunDbId);   // banner, "Save this run", list
            lastCoverage = { coverage: status.coverage || {assigned: 0, total: 0}, errors: status.coverage_errors || [] };
            renderCoverageSummary(lastCoverage);
            const metricsSuffix = status.metrics && status.metrics.solve_time_sec
              ? ` (CP-SAT: ${status.metrics.solve_time_sec}s, GA: ${status.metrics.ga_time_sec || 0}s)`
              : '';
            showToast('Optimization Complete!' + metricsSuffix, 'success');
            // Coverage (R3): report every group the engine could not staff (shown last so it is not overwritten)
            if (status.coverage_errors && status.coverage_errors.length > 0) {
              console.warn('[ATLAS] Coverage errors:', status.coverage_errors);
              const cov = status.coverage || {};
              showToast(`${status.coverage_errors.length} class group(s) not covered (${cov.assigned}/${cov.total}). See the coverage list.`, 'warning');
            }
            announceOptimization(displayResult.length, status.analytics);
          }
        } catch (err) {
          console.error('Polling error:', err);
        }
      }, 400);

    } catch (e) {
      clearInterval(progressInterval);
      currentRun = null;
      loading.classList.add('hidden');
      runBtn.disabled = false;
      const unreachable = e instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(e.message));
      if (/not saved yet/i.test(String(e.message))) { window.atlasDialog.alert(e.message, { title: 'Finish saving first', tone: 'warn' }); return; }
      alert(unreachable
        ? 'Cannot reach the ATLAS server at ' + API_BASE + '. Start it with "py app.py" (local) or wait about a minute if Render is waking up, then try again.'
        : 'Failed to connect to backend engine: ' + e.message);
    }
  });
}

/* ============================================================
   9. FACULTY MANAGEMENT SYSTEM
   ============================================================ */
function addFacultyRow(data = {}) {
  const tbody = document.querySelector('#facultyTable tbody');
  if (!tbody) return;

  const tr = document.createElement('tr');
  if (data.id) tr.dataset.fid = data.id;        // the database id: later saves update this row

  const nameValue     = data.name || '';
  const specsSelected = data.specialization || [];
  const maxUnits      = data.max_units !== undefined ? data.max_units : getSystemSettings().max_units;
  const overloadBuffer = data.overload_buffer !== undefined ? data.overload_buffer : 6;
  // Availability is stored and sent to the backend as short names (Mon, Tue, Wed, Thu, Fri, Sat)
  // matching DAYS in app.py. Normalize any legacy long-name values on load.
  const DAY_LONG_TO_SHORT = { Monday:'Mon', Tuesday:'Tue', Wednesday:'Wed', Thursday:'Thu', Friday:'Fri', Saturday:'Sat' };
  const rawAvail = data.availability || ['Mon','Tue','Wed','Thu','Fri','Sat'];
  const daysSelected = rawAvail.map(d => DAY_LONG_TO_SHORT[d] || d);

  const checkboxHTML = SPECIALIZATIONS.map(spec => `
    <label>
      <input type="checkbox" value="${escapeAttr(spec)}" ${specsSelected.includes(spec) ? 'checked' : ''}>
      ${escapeHTML(spec)}
    </label>
  `).join('');

  // Checkbox value is the short name (Mon/Tue/…) - this is what getFacultyFromTable
  // reads and what app.py expects in the availability array.
  const daysHTML = Object.entries(DAY_MAP).map(([short, long]) => `
    <label>
      <input type="checkbox" value="${short}" ${daysSelected.includes(short) ? 'checked' : ''}>${short}
    </label>
  `).join('');

  const displayText = specsSelected.length ? specsSelected.join(', ') : 'Choose Specialization';

  tr.innerHTML = `
    <td><input type="text" placeholder="Enter Name" value="${escapeAttr(nameValue)}"></td>
    <td>
      <div class="multi-select-dropdown">
        <div class="dropdown-btn" title="${escapeAttr(displayText)}">${escapeHTML(displayText.length > 45 ? displayText.substring(0, 45) + '...' : displayText)}</div>
        <div class="dropdown-content">
          ${checkboxHTML}
          <button type="button" class="dropdown-ok-btn btn">OK</button>
        </div>
      </div>
    </td>
    <td><input type="number" value="${maxUnits}" min="0" max="50" title="Max Units"></td>
    <td><input type="number" value="${overloadBuffer}" min="0" max="20" title="Overload Buffer (added to Max Units for absolute hard cap)"></td>
    <td><div class="avail-checkboxes">${daysHTML}</div></td>
    <td><button type="button" class="btn-delete row-action-btn" title="Delete Row">Delete</button></td>
  `;

  // Bind dropdown toggle action handler listener sequence hook event context capture bubble logic
  const btn = tr.querySelector('.dropdown-btn');
  const dropdown = tr.querySelector('.multi-select-dropdown');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = dropdown.classList.contains('open');
    document.querySelectorAll('.multi-select-dropdown.open').forEach(d => d.classList.remove('open'));
    if (!open) {
      dropdown.classList.add('open');
      repositionDropdown(dropdown);
    }
  });

  // Bind OK button handler loop cycle tracking event trigger layer
  tr.querySelector('.dropdown-ok-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    dropdown.classList.remove('open');
    updateDropdownLabel(dropdown);
    saveFaculty();
  });

  // Checkbox change tracker hooks
  dropdown.querySelectorAll('input[type="checkbox"]').forEach(chk => {
    chk.addEventListener('change', () => {
      updateDropdownLabel(dropdown);
      saveFaculty();
    });
  });

  // Input fields change auto save triggers
  tr.querySelectorAll('input[type="text"], input[type="number"]').forEach(input => {
    input.addEventListener('input', debounce(saveFaculty, 500));
  });

  tr.querySelectorAll('.avail-checkboxes input').forEach(chk => {
    chk.addEventListener('change', () => {
      saveFaculty();
      updateAllSelectAllBtnStates();
    });
  });

  // Row delete handler action integration layer
  tr.querySelector('.btn-delete').addEventListener('click', () => {
    const fid = tr.dataset.fid;
    tr.remove();
    if (fid) window.atlasData.faculty.remove(fid);     // explicit delete: the only way a professor leaves the database
    saveFaculty();
    populateSCFacultyDropdown();
    updateAllSelectAllBtnStates();
  });

  tbody.appendChild(tr);
}

function updateDropdownLabel(dropdown) {
  const checked = Array.from(dropdown.querySelectorAll('.dropdown-content input:checked')).map(c => c.value);
  const btn = dropdown.querySelector('.dropdown-btn');
  const txt = checked.length ? checked.join(', ') : 'Choose Specialization';
  btn.textContent = txt.length > 45 ? txt.substring(0, 45) + '...' : txt;
  btn.title = txt;
}

function repositionDropdown(dropdown) {
  const content = dropdown.querySelector('.dropdown-content');
  const rect = dropdown.getBoundingClientRect();
  
  content.style.position = 'fixed';
  content.style.top = (rect.bottom + window.scrollY) + 'px';
  content.style.left = (rect.left + window.scrollX) + 'px';
  content.style.width = rect.width + 'px';
  content.style.zIndex = '9999';
}

function selectAllByDay(dayShort) {
  // Checkboxes now use short names as values (Mon, Tue, …) - query directly by dayShort.
  const checkboxes = document.querySelectorAll(`#facultyTable tbody .avail-checkboxes input[value="${dayShort}"]`);
  if (!checkboxes.length) return;

  const allChecked = Array.from(checkboxes).every(c => c.checked);
  checkboxes.forEach(c => { c.checked = !allChecked; });

  saveFaculty();
  updateAllSelectAllBtnStates();
}

function updateAllSelectAllBtnStates() {
  Object.entries(DAY_MAP).forEach(([short, long]) => {
    const btn = document.querySelector(`.btn-select-day[data-day="${short}"]`);
    if (!btn) return;

    // Checkboxes use short names as values - query by short name.
    const checkboxes = document.querySelectorAll(`#facultyTable tbody .avail-checkboxes input[value="${short}"]`);
    if (!checkboxes.length) {
      btn.classList.remove('active');
      return;
    }

    const allChecked = Array.from(checkboxes).every(c => c.checked);
    btn.classList.toggle('active', allChecked);
  });
}

function getFacultyFromTable() {
  return Array.from(document.querySelectorAll('#facultyTable tbody tr')).map(row => {
    const name = row.querySelector('input[type="text"]').value.trim();
    const specs = Array.from(row.querySelectorAll('.dropdown-content input:checked')).map(c => c.value);
    const numInputs = row.querySelectorAll('input[type="number"]');
    const maxUnits = parseInt(numInputs[0]?.value, 10) || 24;
    const overloadBuffer = parseInt(numInputs[1]?.value, 10) || 6;
    const avail = Array.from(row.querySelectorAll('.avail-checkboxes input:checked')).map(c => c.value);

    return {
      name,
      specialization: specs,
      max_units: maxUnits,
      overload_buffer: overloadBuffer,
      absolute_max_units: maxUnits + overloadBuffer,
      availability: avail
    };
  }).filter(f => f.name);
}

/* Rows with their database id, for saving. A row gets its id on the first save (insert); later saves update it. */
function getFacultyRowsForSync() {
  return Array.from(document.querySelectorAll('#facultyTable tbody tr')).map(row => {
    const num = row.querySelectorAll('input[type="number"]');
    const units = parseInt(num[0]?.value, 10);
    const buffer = parseInt(num[1]?.value, 10);
    return {
      name: row.querySelector('input[type="text"]').value.trim(),
      specialization: Array.from(row.querySelectorAll('.dropdown-content input:checked')).map(c => c.value),
      max_units: Number.isNaN(units) ? 24 : units,
      overload_buffer: Number.isNaN(buffer) ? 6 : buffer,
      availability: Array.from(row.querySelectorAll('.avail-checkboxes input:checked')).map(c => c.value),
      getId: () => row.dataset.fid || '',
      setId: id => { row.dataset.fid = id; }
    };
  });
}

// Saves to the database (debounced by the callers). Shows Saving / Saved / Not saved; keeps what was typed on a failure.
function saveFaculty() {
  updateAllSelectAllBtnStates();
  refreshFacultyEmptyNotice();
  return window.atlasData.faculty.save(getFacultyRowsForSync());
}

function facultyIdByName(name) {
  const row = Array.from(document.querySelectorAll('#facultyTable tbody tr'))
    .find(r => r.querySelector('input[type="text"]').value.trim() === name);
  return row && row.dataset.fid ? row.dataset.fid : '';
}

// First visit of a department with no faculty in the database: offer the sample pool, never write it silently.
function refreshFacultyEmptyNotice() {
  const notice = document.getElementById('facultyEmptyNotice');
  if (!notice) return;
  notice.hidden = !(window.atlasData.faculty.isEmpty() && !document.querySelector('#facultyTable tbody tr'));
}

function initSampleFaculty() {
  document.getElementById('loadSampleFaculty')?.addEventListener('click', async e => {
    const btn = e.currentTarget;
    btn.disabled = true;
    const pool = defaultFaculty().map(f => ({
      name: f.name, specialization: f.specialization || [],
      max_units: f.max_units != null ? f.max_units : 24, overload_buffer: f.overload_buffer != null ? f.overload_buffer : 6,
      availability: f.availability || ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    }));
    const res = await window.atlasData.faculty.loadSample(pool);
    btn.disabled = false;
    if (!res.ok) { showToast(res.error, 'info'); return; }
    document.querySelector('#facultyTable tbody').innerHTML = '';
    res.rows.forEach(f => addFacultyRow(f));
    populateSCFacultyDropdown();
    updateAllSelectAllBtnStates();
    refreshFacultyEmptyNotice();
    showToast(`Loaded ${res.rows.length} sample faculty.`, 'success');
  });
}

function initEditFacultyModal() {
  const modal       = document.getElementById('editModal');
  const closeBtn    = document.getElementById('editModalClose');
  const cancelBtn   = document.getElementById('editModalCancel');
  const saveBtn     = document.getElementById('editModalSave');
  const nameInput   = document.getElementById('editFacultyName');
  const unitsInput  = document.getElementById('editMaxUnits');
  const titleEl     = document.getElementById('editModalTitle');
  if (!modal) return;

  // ── Build the expanded modal body once ──────────────────────────────
  const existingBody = modal.querySelector('.modal-body');
  if (existingBody && !existingBody.querySelector('.modal-section-label')) {
    // Append assignment editor below the units field
    existingBody.insertAdjacentHTML('beforeend', `
      <hr class="modal-section-divider">
      <div class="modal-section-label">Assigned Subjects, Times &amp; Rooms</div>
      <div id="editAssignmentList" class="modal-assignment-list"></div>
      <button type="button" id="editAddAssignment" class="modal-add-assignment-btn">
        <span style="font-size:1.1em;">+</span> Add Assignment
      </button>
    `);
  }

  const TIME_SLOTS = [
    'Mon: 7:00-9:00',   'Mon: 9:00-11:00',
    'Mon: 13:00-15:00', 'Mon: 15:00-17:00',   'Mon: 17:00-19:00',
    'Tue: 7:00-9:00',   'Tue: 9:00-11:00',
    'Tue: 13:00-15:00', 'Tue: 15:00-17:00',   'Tue: 17:00-19:00',
    'Wed: 7:00-9:00',   'Wed: 9:00-11:00',
    'Wed: 13:00-15:00', 'Wed: 15:00-17:00',   'Wed: 17:00-19:00',
    'Thu: 7:00-9:00',   'Thu: 9:00-11:00',
    'Thu: 13:00-15:00', 'Thu: 15:00-17:00',   'Thu: 17:00-19:00',
    'Fri: 7:00-9:00',   'Fri: 9:00-11:00',
    'Fri: 13:00-15:00', 'Fri: 15:00-17:00',   'Fri: 17:00-19:00',
    'Sat: 7:00-9:00',   'Sat: 9:00-11:00',
    'Sat: 13:00-15:00', 'Sat: 15:00-17:00',   'Sat: 17:00-19:00',
  ];

  function buildSlotOptions(selected) {
    return TIME_SLOTS.map(s =>
      `<option value="${escapeAttr(s)}" ${selected === s ? 'selected' : ''}>${escapeHTML(s)}</option>`
    ).join('');
  }

  function buildRoomOptions(selected) {
    const rooms = [...runtimeLectureRooms, ...runtimeLabRooms];
    const opts = rooms.map(r =>
      `<option value="${escapeAttr(r)}" ${selected === r ? 'selected' : ''}>${escapeHTML(r)}</option>`
    ).join('');
    return `<option value="">Select room</option>${opts}`;
  }

  function buildSubjectOptions(selected) {
    const subjects = getSubjectsFromTable().filter(s => s.name);
    const opts = subjects.map(s =>
      `<option value="${escapeAttr(s.name)}" ${selected === s.name ? 'selected' : ''}>${escapeHTML(s.name)}</option>`
    ).join('');
    return `<option value="">Select subject</option>${opts}`;
  }

  function addAssignmentRow(item = {}) {
    const list = document.getElementById('editAssignmentList');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'modal-assign-row';
    row.innerHTML = `
      <label class="modal-assign-field modal-assign-subject"><span>Subject</span>
        <select class="edit-assign-subject">${buildSubjectOptions(item.subject || '')}</select>
      </label>
      <label class="modal-assign-field"><span>Day and time</span>
        <select class="edit-assign-slot">${buildSlotOptions(item.slot || '')}</select>
      </label>
      <label class="modal-assign-field"><span>Room</span>
        <select class="edit-assign-room">${buildRoomOptions(item.room || '')}</select>
      </label>
      <button type="button" class="modal-assign-delete" title="Remove" aria-label="Remove assignment">&times;</button>
    `;
    row.querySelector('.modal-assign-delete').addEventListener('click', () => row.remove());
    list.appendChild(row);
  }

  function openModal(facultyName) {
    const rows = Array.from(document.querySelectorAll('#facultyTable tbody tr'));
    const row  = rows.find(r => r.querySelector('input[type="text"]')?.value.trim() === facultyName);
    const currentUnits = row ? (parseInt(row.querySelector('input[type="number"]')?.value, 10) || 24) : 24;

    nameInput.value  = facultyName;
    unitsInput.value = currentUnits;
    if (titleEl) titleEl.textContent = `Edit: ${facultyName}`;

    // Populate assignment list from lastGAResult
    const list = document.getElementById('editAssignmentList');
    if (list) {
      list.innerHTML = '';
      const assignments = lastGAResult.filter(item => item.faculty === facultyName);
      assignments.forEach(item => addAssignmentRow(item));
    }

    modal.classList.add('open');
    modal.removeAttribute('aria-hidden');
    unitsInput.focus();
  }

  function closeModal() {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }

  // Delegate: reports table Edit button
  document.addEventListener('click', e => {
    const btn = e.target.closest('.btn-edit-faculty');
    if (!btn) return;
    e.stopPropagation();
    openModal(btn.dataset.faculty);
  });

  document.getElementById('editAddAssignment')?.addEventListener('click', () => addAssignmentRow());

  if (closeBtn)  closeBtn.addEventListener('click',  closeModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal.classList.contains('open')) closeModal(); });

  if (saveBtn) {
    saveBtn.addEventListener('click', () => {
      const name     = nameInput.value.trim();
      const newUnits = parseInt(unitsInput.value, 10);
      if (!name || isNaN(newUnits) || newUnits < 0) return;

      // 1. Update max units in faculty table
      const rows = Array.from(document.querySelectorAll('#facultyTable tbody tr'));
      const row  = rows.find(r => r.querySelector('input[type="text"]')?.value.trim() === name);
      if (row) {
        const numInput = row.querySelector('input[type="number"]');
        if (numInput) { numInput.value = newUnits; saveFaculty(); }
      }

      // The approved schedule is frozen: edits only apply to a new run or a loaded draft/saved run.
      if (savedRunsCtl && savedRunsCtl.editsBlocked()) {
        showToast('The approved schedule cannot be edited. Run Optimization or load a saved run to make changes.', 'info');
        return;
      }

      // 2. Apply edited assignments back to lastGAResult
      const assignRows = document.querySelectorAll('#editAssignmentList .modal-assign-row');
      if (assignRows.length) {
        // Remove all current assignments for this faculty
        lastGAResult = lastGAResult.filter(item => item.faculty !== name);

        // Add updated ones
        assignRows.forEach(r => {
          const subject = r.querySelector('.edit-assign-subject')?.value || '';
          const slot    = r.querySelector('.edit-assign-slot')?.value   || '';
          const room    = r.querySelector('.edit-assign-room')?.value   || '';
          if (!subject || !slot) return;

          // Find original item data to preserve type/section/year/class_type
          const subjectData = getSubjectsFromTable().find(s => s.name === subject) || {};
          const daySlotMatch = slot.match(/^(\w+):\s*(\d+):00-(\d+):00/);
          const slotDisplay = daySlotMatch
            ? `${DAY_MAP[daySlotMatch[1]] || daySlotMatch[1]}: ${
                parseInt(daySlotMatch[2]) >= 12
                  ? `${parseInt(daySlotMatch[2]) - 12 || 12}:00 PM`
                  : `${parseInt(daySlotMatch[2])}:00 AM`
              } - ${
                parseInt(daySlotMatch[3]) >= 12
                  ? `${parseInt(daySlotMatch[3]) - 12 || 12}:00 PM`
                  : `${parseInt(daySlotMatch[3])}:00 AM`
              }`
            : slot;

          lastGAResult.push({
            faculty:      name,
            subject,
            slot,
            slot_display: slotDisplay,
            room,
            type:         subjectData.type || '',
            year:         subjectData.year || '',
            semester:     subjectData.semester || '',
            class_type:   room && runtimeLabRooms.includes(room) ? 'LAB' : 'LECTURE',
            section:      ''
          });
        });

        // Re-render all panels
        persistEditedResult();
        window.__atlasAnalyticsStale = true;      // the payload describes the generated run, not this manual edit
        const displayResult = filterResultBySemester(lastGAResult);
        renderTable(displayResult);
        updateCharts(displayResult);
        computeFairnessReport(displayResult);
        renderDashboardAssignments(displayResult);
        renderTimetable(displayResult);
        updateReportsPanel(displayResult);
      }

      closeModal();
      showToast(`${name} updated successfully.`, 'success');
    });
  }
}

function initFacultyManagement() {
  const addBtn = document.getElementById('addFacultyRow');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      addFacultyRow();
      saveFaculty();
      updateAllSelectAllBtnStates();
    });
  }
  initEditFacultyModal();

  // Bind Select-All-Day buttons in the Availability header
  document.querySelectorAll('.btn-select-day').forEach(btn => {
    btn.addEventListener('click', () => {
      selectAllByDay(btn.dataset.day);
    });
  });

  // Close dropdowns on outside click
  document.addEventListener('click', e => {
    if (!e.target.closest('.multi-select-dropdown')) {
      document.querySelectorAll('.multi-select-dropdown.open').forEach(d => d.classList.remove('open'));
    }
  });

  // Reposition on scroll/resize - keeps fixed dropdown aligned with button
  const reposition = () => {
    document.querySelectorAll('.multi-select-dropdown.open').forEach(repositionDropdown);
  };
  window.addEventListener('scroll', reposition, true);
  window.addEventListener('resize', reposition);
}

/* ============================================================
   10. SUBJECTS MANAGEMENT SYSTEM
   ============================================================ */
function addSubjectRow(data = {}) {
  const tbody = document.querySelector('#subjectsTable tbody');
  if (!tbody) return;

  const tr = document.createElement('tr');
  // Prospectus identity (not editable in the table, kept on the row)
  tr.dataset.code      = data.code || '';
  tr.dataset.category  = data.category || '';
  tr.dataset.scheduled = data.scheduled === false ? 'false' : 'true';

  const year     = data.year || '1st Year';
  const semester = data.semester || '1st Semester';
  const name     = data.name || '';
  const type     = data.type || SPECIALIZATIONS[0] || '';
  const lec      = data.lec_units !== undefined ? data.lec_units : 2;
  const lab      = data.lab_units !== undefined ? data.lab_units : 1;
  const typeOptions = (SPECIALIZATIONS.includes(type) ? SPECIALIZATIONS : [type, ...SPECIALIZATIONS])
    .filter(Boolean)
    .map(t => `<option ${t === type ? 'selected' : ''}>${escapeHTML(t)}</option>`).join('');
  // `confirm` / `verify` flags of the course file: a small marker whose tooltip is the flag text
  const flagCourse = ATLAS_CURRICULUM && data.code
    ? (ATLAS_CURRICULUM.courses || []).find(c => c.code === data.code) : null;
  const flagText = flagCourse ? (flagCourse.confirm || flagCourse.verify || '') : '';
  const flagHTML = flagText
    ? `<span class="course-flag" title="${escapeAttr(flagText)}" aria-label="${escapeAttr(flagText)}" tabindex="0">!</span>` : '';

  tr.innerHTML = `
    <td>
      <select class="subject-year">
        <option ${year==='1st Year'?'selected':''}>1st Year</option>
        <option ${year==='2nd Year'?'selected':''}>2nd Year</option>
        <option ${year==='3rd Year'?'selected':''}>3rd Year</option>
        <option ${year==='4th Year'?'selected':''}>4th Year</option>
      </select>
    </td>
    <td>
      <select class="subject-semester">
        <option ${semester==='1st Semester'?'selected':''}>1st Semester</option>
        <option ${semester==='2nd Semester'?'selected':''}>2nd Semester</option>
        <option ${semester==='Summer'?'selected':''}>Summer</option>
      </select>
    </td>
    <td><input type="text" class="subject-name" placeholder="Subject Title" value="${escapeAttr(name)}">${flagHTML}</td>
    <td>
      <select class="subject-type">${typeOptions}</select>
    </td>
    <td><input type="number" class="unit-input lec" value="${lec}" min="0" max="10"></td>
    <td><input type="number" class="unit-input lab" value="${lab}" min="0" max="10"></td>
    <td class="total-cell txt-center">${lec + lab}</td>
    <td><button type="button" class="btn-delete row-action-btn" title="Delete Row">Delete</button></td>
  `;

  // Dynamic change tracker loops listeners attachments
  const updateTotal = () => {
    const l = parseInt(tr.querySelector('.lec')?.value || 0);
    const b = parseInt(tr.querySelector('.lab')?.value || 0);
    const tc = tr.querySelector('.total-cell');
    if (tc) tc.textContent = l + b;
  };
  tr.querySelectorAll('select, input').forEach(el => {
    el.addEventListener('change', () => { saveSubjects(); updateTotal(); });
    if(el.tagName === 'INPUT') {
      el.addEventListener('input', debounce(() => { saveSubjects(); updateTotal(); }, 500));
    }
  });

  tr.querySelector('.btn-delete').addEventListener('click', () => {
    tr.remove();
    saveSubjects();
  });

  tbody.appendChild(tr);
}

function getSubjectsFromTable() {
  return Array.from(document.querySelectorAll('#subjectsTable tbody tr')).map(row => ({
    code:     row.dataset.code || '',
    category: row.dataset.category || '',
    scheduled: row.dataset.scheduled !== 'false',
    year:     row.querySelector('.subject-year')?.value || '',
    semester: row.querySelector('.subject-semester')?.value || '',
    name:     row.querySelector('.subject-name')?.value || '',
    type:     row.querySelector('.subject-type')?.value || '',
    lec_units:Number(row.querySelector('.lec')?.value || 0),
    lab_units:Number(row.querySelector('.lab')?.value || 0),
    hours:    (Number(row.querySelector('.lec')?.value || 0)) + (Number(row.querySelector('.lab')?.value || 0) * 3)
  }));
}

// Subjects come from the department's curriculum file; the table only holds edits of units and types for the
// current page. There is no subjects table in the database, so nothing is stored in the browser.
function saveSubjects() { /* edits live in the table until the page is closed */ }

function loadSubjectsFromStorage() { return null; }

function renderSubjectsGrouped() {
  const container = document.getElementById('subjectsContainer');
  if (!container) return;

  const subjects = getSubjectsFromTable().filter(s => s.name);
  const grouped = {};

  subjects.forEach(s => {
    const key = `${s.year} - ${s.semester}`;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(s);
  });

  if (!Object.keys(grouped).length) {
    container.innerHTML = '<p class="empty-state-msg">No subjects configured yet.</p>';
    return;
  }

  let html = '<div class="curriculum-summary-wrap">';
  Object.keys(grouped).sort().forEach(key => {
    html += `
      <div class="curriculum-group">
        <div class="curriculum-header">${escapeHTML(key)}</div>
        <table class="curriculum-table">
          <thead>
            <tr>
              <th>Subject Name</th>
              <th>Type</th>
              <th class="txt-center">Lec</th>
              <th class="txt-center">Lab</th>
              <th class="txt-center">Hours</th>
            </tr>
          </thead>
          <tbody>
            ${grouped[key].map(s => `
              <tr>
                <td><strong>${escapeHTML(s.name)}</strong></td>
                <td><span class="type-tag ${s.type.toLowerCase().replace(/[\s&\/]+/g,'-')}">${escapeHTML(s.type)}</span></td>
                <td class="txt-center">${s.lec_units}</td>
                <td class="txt-center">${s.lab_units}</td>
                <td class="txt-center font-mono">${s.hours}h</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
}

function initSubjectsManagement() {
  const addBtn = document.getElementById('addSubjectRow');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      addSubjectRow();
      saveSubjects();
    });
  }
}

/* ============================================================
   11. DASHBOARD OVERVIEW ASSIGNMENT STREAM
   ============================================================ */
function renderDashboardAssignments(data) {
  const container = document.getElementById('dashboardFacultyAssignments');
  if (!container) return;

  const byFaculty = {};
  data.forEach(item => {
    if (!item.faculty) return;
    if (!byFaculty[item.faculty]) byFaculty[item.faculty] = [];
    byFaculty[item.faculty].push(item);
  });

  if (!Object.keys(byFaculty).length) {
    container.innerHTML = '<p class="empty-state-msg">No assignments to display.</p>';
    return;
  }

  const upa = getUnitsPerAssignment();
  const facMaxMap = getFacultyMaxUnitsMap();

  let html = '<div class="fac-assign-grid">';
  Object.keys(byFaculty).sort().forEach(faculty => {
    const items = byFaculty[faculty];
    const units = items.length * upa;
    const fmax  = facMaxMap[faculty] || MAX_UNITS;
    const colorClass = units > fmax ? 'units-over' : units === fmax ? 'units-max' : 'units-ok';

    // Sort items: by subject name then section
    const sorted = [...items].sort((a, b) => {
      const sc = (a.subject || '').localeCompare(b.subject || '');
      if (sc !== 0) return sc;
      return (a.section || '').localeCompare(b.section || '');
    });

    // Group rows by subject for a cleaner visual
    const rows = sorted.map(item => {
      const ctClass = (item.class_type || 'LECTURE').toLowerCase();
      const displaySlot = item.slot_display || item.slot || '';
      const dayAbbr = (item.slot || '').split(':')[0].trim();
      const noRoom = AD.isNoClassroom(item);
      const sectionHTML = AD.rowLabel(item)
        ? `<span class="section-badge fac-assign-section">${escapeHTML(AD.rowLabel(item))}</span>`
        : '';
      const stuTag   = item.student_count > 0 ? `<span class="student-count-tag">${item.student_count}</span>` : '';
      const capBadge = buildCapacityBadge(item);
      return `
        <li class="fac-assign-item-full">
          <span class="fac-assign-ct-dot ct-dot-${ctClass}"></span>
          <span class="fac-assign-item-inner">
            <span class="fac-assign-subject-name" title="${escapeAttr(item.subject)}">${escapeHTML(item.subject)}</span>
            <span class="fac-assign-meta">
              <span class="class-type-tag ${ctClass}">${escapeHTML(AD.classTypeText(item))}</span>
              ${sectionHTML}
              ${noRoom ? '' : displaySlot ? `<span class="fac-assign-slot slot-day-${escapeHTML(dayAbbr)}">${escapeHTML(displaySlot)}</span>` : ''}
              ${noRoom ? `<span class="fac-assign-room">${escapeHTML(AD.NO_CLASSROOM_TEXT)}</span>` : item.room ? `<span class="fac-assign-room">${escapeHTML(item.room)}</span>` : ''}
              ${stuTag}
              ${capBadge}
            </span>
          </span>
        </li>`;
    }).join('');

    html += `
      <div class="fac-assign-card">
        <div class="fac-assign-header">
          <span class="fac-assign-avatar">${escapeHTML(faculty.charAt(0))}</span>
          <div class="fac-assign-header-info">
            <span class="fac-assign-name">${escapeHTML(faculty)}</span>
            <span class="fac-assign-count">${items.length} assignment${items.length !== 1 ? 's' : ''}</span>
          </div>
          <span class="units-badge ${colorClass}">${units}u</span>
          <button class="btn-edit-faculty btn" data-faculty="${escapeAttr(faculty)}" title="Edit ${escapeAttr(faculty)}">&#9998;</button>
        </div>
        <div class="fac-assign-body">
          <ul class="fac-assign-list">${rows}</ul>
        </div>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
}

/* ============================================================
   12. EXPORT AND PRINT UTILITIES (CSV / PRINT REPORT EXPORTS)
   ============================================================ */
function initExports() {
  const csvBtn = document.getElementById('exportCSV');
  const pdfBtn = document.getElementById('exportPDF');

  if (csvBtn) {
    csvBtn.addEventListener('click', () => {
      if (!lastGAResult || !lastGAResult.length) {
        alert('Run the optimization framework engine first before exporting data records.');
        return;
      }
      const exportData = filterResultBySemester(lastGAResult);
      const mode = getActiveSemester();
      const semLabel = mode ? (mode.year ? `${mode.year}_${mode.semester}` : mode.semester) : 'all';
      const headers = [
        'Faculty Member',
        'Subject Title',
        'Year',
        'Section',
        'Classification Type',
        'Class Type',
        'Schedule Slot',
        'Room',
        'Semester'
      ];
      const rows = exportData.map(item => [
        `"${(item.faculty||'').replace(/"/g,'""')}"`,
        `"${(item.subject||'').replace(/"/g,'""')}"`,
        `"${(item.year||'').replace(/"/g,'""')}"`,
        `"${AD.rowLabel(item).replace(/"/g,'""')}"`,
        `"${(item.type||'').replace(/"/g,'""')}"`,
        `"${(item.class_type||'LECTURE').replace(/"/g,'""')}"`,
        `"${(AD.isNoClassroom(item) ? '' : (item.slot_display||item.slot||'')).replace(/"/g,'""')}"`,
        `"${(AD.isNoClassroom(item) ? AD.NO_CLASSROOM_TEXT : (item.room||'')).replace(/"/g,'""')}"`,
        `"${(item.semester||mode?.semester||'').replace(/"/g,'""')}"`
      ].join(','));

      const csv = [headers.join(',')].concat(rows).join('\n');
      const fileName = `atlas_psu_${semLabel.replace(/[^a-zA-Z0-9_-]/g,'_')}.csv`;
      downloadFile(csv, fileName, 'text/csv');
    });
  }

  if (pdfBtn) {
    pdfBtn.addEventListener('click', generatePrintReport);
  }
}

function generatePrintReport() {
  if (!lastGAResult || !lastGAResult.length) {
    alert('Run the optimization first to generate a report.');
    return;
  }

  const user = sessionStorage.getItem('atlasUser') || 'Administrator';
  const deptFull = deptName();

  const mode = getActiveSemester();
  const semesterLabel = mode ? (mode.year ? `${mode.year} - ${mode.semester}` : mode.semester) : 'All Semesters';

  const reportData = filterResultBySemester(lastGAResult);

  const now = new Date();
  const dateStr = now.toLocaleDateString('en-PH', { year: 'numeric', month: 'long', day: 'numeric' });
  const timeStr = now.toLocaleTimeString('en-PH', { hour: '2-digit', minute: '2-digit' });

  // Compute breakdown mapping metric profiles internally
  const byFaculty = {};
  reportData.forEach(item => {
    if (!item.faculty) return;
    if (!byFaculty[item.faculty]) byFaculty[item.faculty] = [];
    byFaculty[item.faculty].push(item);
  });

  const upa = getUnitsPerAssignment();
  const facMaxMap = getFacultyMaxUnitsMap();

  const facultyRows = Object.keys(byFaculty).sort().map((facName, i) => {
    const items = byFaculty[facName];
    const units = items.length * upa;
    const fmax  = facMaxMap[facName] || MAX_UNITS;
    const subjectsList = Array.from(new Set(items.map(it => it.subject))).join(', ');
    const loadStatus = units > fmax ? 'Overload' : units === fmax ? 'Max load' : 'Normal';
    return `
      <tr>
        <td class="num">${i + 1}</td>
        <td><strong>${escapeHTML(facName)}</strong></td>
        <td class="txt-center">${units}</td>
        <td class="${units > fmax ? 'status-overload' : ''}">${loadStatus}</td>
        <td>${escapeHTML(subjectsList)}</td>
      </tr>`;
  }).join('');

  const scheduleRows = [...reportData].sort((a, b) => {
    const ps = s => {
      const [d, t] = (s || '').split(':');
      return ((DAY_ORDER[d.trim()] ?? 99) * 100) + (parseInt(t || '0') || 0);
    };
    return ps(a.slot) - ps(b.slot);
  }).map((item, i) => {
    const slot = item.slot_display || item.slot || '';
    const [slotDay, ...slotRest] = slot.split(':');
    return `
    <tr>
      <td class="num">${i + 1}</td>
      <td class="when"><strong>${escapeHTML(slotDay.trim())}</strong><div>${escapeHTML(slotRest.join(':').trim())}</div></td>
      <td>${escapeHTML(item.subject)}<div class="sub-type">${escapeHTML([AD.rowLabel(item), item.type].filter(Boolean).join(' · '))}</div></td>
      <td>${escapeHTML(item.faculty || 'Unassigned')}</td>
      <td class="${AD.isNoClassroom(item) ? '' : 'nowrap'}">${escapeHTML(AD.isNoClassroom(item) ? AD.NO_CLASSROOM_TEXT : (item.room || 'N/A'))}</td>
      <td>${AD.isNoClassroom(item) ? 'No classroom' : (item.class_type || 'LECTURE') === 'LAB' ? 'Laboratory' : 'Lecture'}</td>
    </tr>`;
  }).join('');

  // Extract analytics stats directly safely
  const fScore  = document.getElementById('fairnessScore').textContent;
  const fJain   = document.getElementById('fairnessJain').textContent;
  const fMatch  = document.getElementById('fairnessMatchRate').textContent;
  const fQual   = document.getElementById('fairnessQualified').textContent;
  const fStdDev = document.getElementById('fairnessStdDev').textContent;

  const html = `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Teaching Load Assignment Report - ${escapeHTML(deptFull)} Department</title>
  <style>
    /* Pages are laid out as fixed A4 sheets below, so the margins hold
       whatever "Margins" option the print dialog is set to. */
    @page { size: A4 portrait; margin: 0; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { background: #fff; }
    body { font-family: 'Times New Roman', Times, serif; font-size: 11pt; line-height: 1.45; color: #111; }
    strong { font-weight: 700; }

    .sheet { position: relative; width: 210mm; height: 296mm; padding: 22mm 20mm 24mm 25mm; page-break-after: always; overflow: hidden; background: #fff; }
    .sheet:last-of-type { page-break-after: auto; }
    .sheet-body { height: 250mm; overflow: hidden; }
    .sheet-foot { position: absolute; left: 25mm; right: 20mm; bottom: 11mm; display: flex; justify-content: space-between; padding-top: 2mm; border-top: 0.5pt solid #bbb; font-size: 8.5pt; color: #555; }
    @media screen { html { background: #d9d9d9; } .sheet { margin: 8mm auto; box-shadow: 0 1px 6px rgba(0, 0, 0, 0.3); } }

    .letterhead { text-align: center; padding-bottom: 5mm; border-bottom: 1.5pt solid #111; }
    .letterhead .rp   { font-size: 9pt; letter-spacing: 0.06em; text-transform: uppercase; }
    .letterhead .univ { margin-top: 1.5mm; font-size: 15pt; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; }
    .letterhead .unit { margin-top: 1mm; font-size: 11pt; }
    .letterhead .addr { margin-top: 0.5mm; font-size: 9.5pt; color: #444; }

    .cover { display: flex; flex-direction: column; height: 100%; }
    .doc-title { margin: 32mm 0 14mm; text-align: center; }
    .doc-title h1 { font-size: 20pt; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; line-height: 1.25; }
    .doc-title p  { margin-top: 4mm; font-size: 12pt; }
    .meta-table { width: 125mm; margin: 0 auto; border-collapse: collapse; }
    .meta-table td { padding: 2.5mm 3mm; border-bottom: 0.5pt solid #bbb; font-size: 10.5pt; }
    .meta-table td.k { width: 40%; font-weight: 700; }
    .meta-table tr:first-child td { border-top: 1pt solid #111; }
    .meta-table tr:last-child td { border-bottom: 1pt solid #111; }
    .cover-note { margin-top: auto; text-align: center; font-size: 9pt; font-style: italic; color: #444; }

    .section-title { margin-bottom: 5mm; padding-bottom: 1.5mm; border-bottom: 1pt solid #111; font-size: 12pt; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; }
    .subhead { margin: 6mm 0 3mm; font-size: 11pt; font-weight: 700; }

    .metrics { width: 100%; margin-bottom: 2mm; border-collapse: collapse; border-top: 1.2pt solid #111; border-bottom: 1.2pt solid #111; }
    .metrics td { width: 25%; padding: 3.5mm 2mm; text-align: center; border-left: 0.5pt solid #bbb; }
    .metrics td:first-child { border-left: 0; }
    .metrics .v { font-size: 16pt; font-weight: 700; line-height: 1.1; }
    .metrics .l { margin-top: 1mm; font-size: 8pt; letter-spacing: 0.05em; text-transform: uppercase; color: #444; }

    .report-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 9.5pt; }
    .report-table th { padding: 2mm; text-align: left; white-space: nowrap; font-size: 8.5pt; letter-spacing: 0.04em; text-transform: uppercase; border-top: 1.2pt solid #111; border-bottom: 1pt solid #111; }
    .report-table td { padding: 2mm; vertical-align: top; overflow-wrap: anywhere; border-bottom: 0.5pt solid #ccc; }
    .report-table tbody tr:last-child td { border-bottom: 1pt solid #111; }
    .report-table .num { width: 8mm; color: #555; }
    .report-table .nowrap { white-space: nowrap; overflow-wrap: normal; }
    .txt-center { text-align: center !important; }
    .when div { font-size: 9pt; color: #333; }
    .sub-type { font-size: 8.5pt; font-style: italic; color: #555; }
    .status-overload { font-weight: 700; }

    .sign-zone { display: flex; justify-content: space-between; margin-top: 18mm; }
    .sign-block { width: 68mm; text-align: center; }
    .sign-label { margin-bottom: 14mm; font-size: 9.5pt; text-align: left; color: #444; }
    .sign-line { padding-top: 1.5mm; border-top: 0.75pt solid #111; }
    .sign-title { font-size: 9.5pt; color: #444; }
  </style>
</head>
<body>

  <!-- Source content. The script below flows it onto A4 sheets. -->
  <div id="src" style="display:none">

    <div id="srcCover" class="cover">
      <div class="letterhead">
        <div class="rp">Republic of the Philippines</div>
        <div class="univ">Palawan State University</div>
        <div class="unit">College of Sciences &middot; ${escapeHTML(deptFull)} Department</div>
        <div class="addr">Puerto Princesa City, Palawan</div>
      </div>
      <div class="doc-title">
        <h1>Teaching Load<br>Assignment Report</h1>
        <p>${escapeHTML(semesterLabel)}</p>
      </div>
      <table class="meta-table">
        <tr><td class="k">Department</td><td>${escapeHTML(deptFull)}</td></tr>
        <tr><td class="k">Academic period</td><td>${escapeHTML(semesterLabel)}</td></tr>
        <tr><td class="k">Faculty members</td><td>${Object.keys(byFaculty).length}</td></tr>
        <tr><td class="k">Coverage</td><td>${escapeHTML(lastCoverage && lastCoverage.coverage ? AD.coverageText(lastCoverage.coverage) : 'n/a')}${
          lastCoverage && lastCoverage.errors && lastCoverage.errors.length
            ? '<br>Not covered: ' + escapeHTML(lastCoverage.errors.map(AD.coverageErrorText).join('; ')) : ''}</td></tr>
        <tr><td class="k">Prepared by</td><td>${escapeHTML(user)}</td></tr>
        <tr><td class="k">Date generated</td><td>${dateStr}, ${timeStr}</td></tr>
      </table>
      <div class="cover-note">Generated by ATLAS PSU: A Teaching Load Assignment and Management System</div>
    </div>

    <h2 id="srcTitle1" class="section-title">I. Workload Distribution Summary</h2>
    <div id="srcSub1" class="subhead">Workload Balance Indicators</div>
    <table id="srcMetrics" class="metrics">
      <tr>
        <td><div class="v">${fScore}</div><div class="l">Balance score</div></td>
        <td><div class="v">${fJain}</div><div class="l">Jain's index</div></td>
        <td><div class="v">${fMatch}</div><div class="l">Primary tag match (qualified ${fQual})</div></td>
        <td><div class="v">${fStdDev}</div><div class="l">Load std. deviation</div></td>
      </tr>
    </table>
    <div id="srcSub2" class="subhead">Faculty Workload Status</div>

    <table id="srcFaculty" class="report-table">
      <colgroup><col style="width: 8mm"><col style="width: 34mm"><col style="width: 14mm"><col style="width: 22mm"><col></colgroup>
      <thead>
        <tr>
          <th class="num">No.</th>
          <th>Faculty</th>
          <th class="txt-center">Units</th>
          <th>Status</th>
          <th>Assigned subjects</th>
        </tr>
      </thead>
      <tbody>${facultyRows}</tbody>
    </table>

    <h2 id="srcTitle2" class="section-title">II. Master Schedule of Assignments</h2>
    <table id="srcSchedule" class="report-table">
      <colgroup><col style="width: 8mm"><col style="width: 31mm"><col><col style="width: 28mm"><col style="width: 22mm"><col style="width: 21mm"></colgroup>
      <thead>
        <tr>
          <th class="num">No.</th>
          <th>Day and time</th>
          <th>Subject</th>
          <th>Faculty</th>
          <th>Room</th>
          <th>Class</th>
        </tr>
      </thead>
      <tbody>${scheduleRows}</tbody>
    </table>

    <div id="srcSign" class="sign-zone">
      <div class="sign-block">
        <div class="sign-label">Prepared by:</div>
        <div class="sign-line"><strong>${escapeHTML(user)}</strong></div>
        <div class="sign-title">Department Chairperson</div>
      </div>
      <div class="sign-block">
        <div class="sign-label">Approved by:</div>
        <div class="sign-line"><strong>&nbsp;</strong></div>
        <div class="sign-title">College Dean</div>
      </div>
    </div>
  </div>

  <script>
    window.onload = function () {
      var src = document.getElementById('src');
      var sheets = [];
      var body = null;

      function newSheet() {
        var sheet = document.createElement('section');
        sheet.className = 'sheet';
        sheet.innerHTML = '<div class="sheet-body"></div><div class="sheet-foot"><span>ATLAS PSU</span><span class="pg"></span></div>';
        document.body.insertBefore(sheet, src);
        sheets.push(sheet);
        body = sheet.querySelector('.sheet-body');
      }
      function fits() { return body.scrollHeight <= body.clientHeight + 1; }
      function grab(id) { return src.querySelector('#' + id); }

      /* a block that moves to a new sheet when it does not fit */
      function addBlock(node) {
        body.appendChild(node);
        if (!fits() && body.children.length > 1) {
          body.removeChild(node);
          newSheet();
          body.appendChild(node);
        }
      }

      /* a table whose rows continue onto new sheets with the header repeated */
      function addTable(source) {
        var rows = Array.prototype.slice.call(source.tBodies[0].rows);
        var table, tbody;
        function start() {
          table = source.cloneNode(false);
          table.removeAttribute('id');
          var cg = source.querySelector('colgroup');
          if (cg) table.appendChild(cg.cloneNode(true));
          table.appendChild(source.tHead.cloneNode(true));
          tbody = document.createElement('tbody');
          table.appendChild(tbody);
          body.appendChild(table);
        }
        start();
        rows.forEach(function (row) {
          var copy = row.cloneNode(true);
          tbody.appendChild(copy);
          if (fits()) return;
          if (tbody.rows.length > 1) {
            tbody.removeChild(copy);
            newSheet();
            start();
            tbody.appendChild(copy);
          } else {
            body.removeChild(table);
            newSheet();
            start();
            tbody.appendChild(copy);
          }
        });
      }

      /* cover */
      newSheet();
      body.appendChild(grab('srcCover'));

      /* I. summary */
      newSheet();
      body.appendChild(grab('srcTitle1'));
      body.appendChild(grab('srcSub1'));
      body.appendChild(grab('srcMetrics'));
      body.appendChild(grab('srcSub2'));
      addTable(grab('srcFaculty'));

      /* II. schedule and signatures */
      newSheet();
      body.appendChild(grab('srcTitle2'));
      addTable(grab('srcSchedule'));
      addBlock(grab('srcSign'));

      sheets.forEach(function (sheet, i) {
        sheet.querySelector('.pg').textContent = 'Page ' + (i + 1) + ' of ' + sheets.length;
      });
      src.parentNode.removeChild(src);
      window.print();
    };
  <\/script>
</body>
</html>`;

  const win = window.open('', '_blank', 'width=900,height=700');
  if (!win) {
    alert('Please allow pop-ups to generate the PDF report.');
    return;
  }
  win.document.write(html);
  win.document.close();
}

function downloadFile(content, fileName, mimeType) {
  const a = document.createElement('a');
  const blob = new Blob([content], { type: mimeType });
  a.href = URL.createObjectURL(blob);
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/* ============================================================
   13. SANITIZATION & STRING ESCAPE UTILITIES
   ============================================================ */
function escapeHTML(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeAttr(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

/* ============================================================
   14. INITIALIZATION
   ============================================================ */
window.addEventListener('DOMContentLoaded', async () => {
  if (!document.getElementById('facultyTable')) return;   // not the chairperson dashboard

  // The department's data comes from Supabase (RLS returns only this department). Nothing is read from the browser's storage.
  try {
    await window.atlasData.init();
  } catch (e) {
    showToast('Cannot load this department\'s data from the database. Check your connection and reload.', 'error');
    return;
  }

  // The department's file decides the defaults: tags, subjects, blocks and class sizes
  await loadCurriculumData();
  if (!ATLAS_CURRICULUM) showToast('Curriculum could not be loaded.', 'error');
  await loadRuntimeRooms();
  applyDeptLabels();

  // Class sizes: the saved ones, or the curriculum defaults on screen until the chairperson saves (never written silently)

  initCharts();
  initNavigation();
  initRunGA();
  initFacultyManagement();
  initSubjectsManagement();
  initExports();
  initRoomManagement();
  initClassSizesManagement();
  initAcademicMode();
  refreshSolverSummary();
  window.addEventListener('pageshow', refreshSolverSummary);
  window.addEventListener('focus', refreshSolverSummary);
  window.addEventListener('storage', refreshSolverSummary);

  // Load faculty
  window.atlasData.faculty.list().forEach(f => addFacultyRow(f));
  initSampleFaculty();
  refreshFacultyEmptyNotice();
  updateAllSelectAllBtnStates();

  // Load subjects (defaults come from the department's curriculum file)
  let savedSubjects = loadSubjectsFromStorage();
  // Rows saved before prospectus codes existed are replaced by the curriculum defaults
  if (savedSubjects && savedSubjects.length && !savedSubjects.some(s => s.code)) savedSubjects = null;
  if (savedSubjects && savedSubjects.length > 0) {
    savedSubjects.forEach(s => addSubjectRow(s));
  } else if (ATLAS_CURRICULUM) {
    AtlasCurriculum.defaultSubjects(ATLAS_CURRICULUM).forEach(s => addSubjectRow(s));
  } else {
    showToast('Curriculum could not be loaded.', 'error');
  }
  saveSubjects();
  renderSubjectsGrouped();

  // Init soft constraints (needs faculty loaded first)
  initSoftConstraints();

  // Update semester badges now that subjects are loaded
  updateAllSemesterBadges();

  // Restore this department's newest saved run (Supabase) and re-render all views
  await initSavedRuns();
});

/* ---------- Saved runs (Part 17) ---------- */
// Flask API call with the Bearer token; throws {status, message} for a non-2xx answer.
async function runsApi(path, opts) {
  const res = await window.atlasAuth.fetch(`${API_BASE}${path}`, opts);
  let body = {};
  try { body = await res.json(); } catch { /* no JSON body */ }
  if (!res.ok || body.success === false) {
    const err = new Error(body.error || body.message || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return body.data || {};
}

// Puts a run on screen in every view (table, dashboard, reports, timetable, coverage, analytics). null = empty views.
function applyRunToScreen(run) {
  lastGAResult = run && Array.isArray(run.result) ? run.result : [];
  currentRunDbId = run ? run.id : null;
  currentRunStatus = run ? run.status : null;
  screenSemester = run && run.semester && run.semester !== 'unspecified' ? run.semester : null;
  window.__atlasAnalytics = run && run.analytics && Object.keys(run.analytics).length ? run.analytics : null;
  window.__atlasAnalyticsStale = false;
  const displayResult = filterResultBySemester(lastGAResult);
  renderTable(displayResult);
  updateCharts(displayResult);
  computeFairnessReport(displayResult);
  renderDashboardAssignments(displayResult);
  renderTimetable(displayResult);
  updateReportsPanel(displayResult);
  const box = document.getElementById('coverageSummary');
  const cov = run && run.coverage ? run.coverage : null;
  const sum = cov ? (cov.summary || cov) : null;
  if (sum && (sum.total !== undefined || sum.assigned !== undefined)) {
    lastCoverage = { coverage: { assigned: sum.assigned || 0, total: sum.total || 0 }, errors: cov.errors || [] };
    renderCoverageSummary(lastCoverage);
  } else {
    lastCoverage = null;
    if (box) { box.innerHTML = ''; box.classList.add('hidden'); }
  }
  const analytics = run && run.analytics && Object.keys(run.analytics).length ? run.analytics : null;
  window.__atlasAnalytics = analytics;
  if (analytics) {
    try {
      mergeCapacityStatuses(analytics);
      renderCapacityMetrics(resolveCapacityMetrics(analytics));
      renderCapacityAnalytics(analytics);
    } catch (e) { console.warn('Analytics render error:', e); }
  }
}

async function lookupRunnerNames(ids) {
  const out = {};
  const r = await window.atlasSupabase.from('profiles').select('id,full_name').in('id', ids);
  (r.data || []).forEach(p => { if (p.full_name) out[p.id] = p.full_name; });
  return out;
}

// The default view is the approved run; the Saved runs card loads others on request.
async function initSavedRuns() {
  const ui = window.AtlasSavedRuns.createDomUi(document, {
    applyRun: applyRunToScreen, toast: showToast, confirm: (msg, o) => window.atlasDialog ? window.atlasDialog.confirm(msg, o) : Promise.resolve(window.confirm(msg))
  });
  savedRunsCtl = window.AtlasSavedRuns.createController({
    api: runsApi, ui, dept: DEPT, now: () => new Date(),
    userId: window.atlasAuth.user && window.atlasAuth.user.id,
    semester: () => (getActiveSemester() || {}).semester || '',
    lookupNames: lookupRunnerNames
  });
  ui.bind(savedRunsCtl);
  await savedRunsCtl.init();
}

// A manual edit of the result is saved into the draft or saved run on screen. The approved run is frozen.
async function persistEditedResult() {
  if (!currentRunDbId) { showToast('This edit is shown on screen only. Run Optimization to save a run first.', 'info'); return; }
  if (currentRunStatus === 'approved') return;
  await window.atlasData.runs.saveResult(currentRunDbId, lastGAResult);
}

// The active period comes from dept_settings (database); until one is saved the default period applies.
function getActiveSemester() {
  const mode = window.atlasData && window.atlasData.dept() === DEPT ? window.atlasData.settings.period() : null;
  return mode && mode.semester ? mode : DEFAULT_PERIOD_MODE();
}
function DEFAULT_PERIOD_MODE() { return { year: DEFAULT_PERIOD.year, semester: DEFAULT_PERIOD.semester }; }

function getActiveSemesterLabel() {
  const mode = getActiveSemester();
  if (!mode) return null;
  return mode.year ? `${mode.year} · ${mode.semester}` : mode.semester;
}

function updateAllSemesterBadges() {
  const mode = getActiveSemester();
  const label = getActiveSemesterLabel();

  // Panel context badges
  ['dashboardSemContext', 'optimizationSemContext', 'reportsSemContext'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (mode) {
      el.textContent = `Showing: ${label}`;
      el.style.display = 'inline-flex';
    } else {
      el.style.display = 'none';
    }
  });

  // Active banner in Settings
  const banner = document.getElementById('academicModeActiveBanner');
  const bannerText = document.getElementById('academicActiveBannerText');
  if (banner && bannerText) {
    if (mode) {
      bannerText.textContent = `Active Period: ${label}`;
      banner.classList.remove('hidden');
    } else {
      banner.classList.add('hidden');
    }
  }
}

function filterResultBySemester(data) {
  // lastGAResult items carry the subject name; we filter by checking the subjects table
  // If no active semester set, return all
  const mode = screenSemester ? { semester: screenSemester } : getActiveSemester();
  if (!mode) return data;
  const semester = mode.semester;

  // Build a set of subject names valid for this semester
  const allSubjects = getSubjectsFromTable();
  const validNames = new Set(
    allSubjects.filter(s => s.semester === semester).map(s => s.name)
  );
  if (!validNames.size) return data; // no subject list to filter against, return all

  return data.filter(item => validNames.has(item.subject));
}

/* ============================================================
   SYSTEM SETTINGS (max_units, units_per_assignment, cp_sat_time_limit, GA parameters)
   ============================================================ */
// The values are edited in app/application-settings.html and kept by assets/js/solver-settings.js
// (one source of truth). Every call reads storage again.
function getSystemSettings() {
  return window.atlasSolver.read(DEPT);
}

function refreshSolverSummary() {
  const el = document.getElementById('solverSummary');
  if (el) el.textContent = window.atlasSolver.summary(getSystemSettings());
}

function initAcademicMode() {
  const yearInput = document.getElementById('academicYear');
  const semSel    = document.getElementById('academicSemester');
  const saveBtn   = document.getElementById('saveAcademicMode');
  const savedMsg  = document.getElementById('academicModeSaved');
  if (!yearInput || !semSel || !saveBtn) return;

  const saved = getActiveSemester();
  if (saved) {
    yearInput.value = saved.year || '';
    semSel.value    = saved.semester || '1st Semester';
  }

  updateAllSemesterBadges();

  saveBtn.addEventListener('click', () => {
    const year     = yearInput.value.trim();
    const semester = semSel.value;
    if (!year) {
      showToast('Please enter an Academic Year (e.g. 2024-2025).', 'info');
      yearInput.focus();
      return;
    }
    window.atlasData.settings.savePeriod(year, semester);
    updateAllSemesterBadges();
    if (savedMsg) {
      savedMsg.style.display = 'inline-flex';
      setTimeout(() => { savedMsg.style.display = 'none'; }, 2500);
    }
    showToast(`Active Period set: ${year} · ${semester}`, 'success');

    // If a GA result is loaded, re-filter and re-render views to respect new semester
    if (lastGAResult && lastGAResult.length) {
      const filtered = filterResultBySemester(lastGAResult);
      renderTable(filtered);
      updateCharts(filtered);
      computeFairnessReport(filtered);
      renderDashboardAssignments(filtered);
      renderTimetable(filtered);
      updateReportsPanel(filtered);
    }
  });
}

/* ============================================================
   CLASS SIZE STORAGE
   ============================================================ */
function loadClassSizesFromStorage() {
  return window.atlasData.classSizes.has() ? window.atlasData.classSizes.get() : null;
}

function saveClassSizes(sizes) {
  return window.atlasData.classSizes.save(sizes);
}

function getClassSizes() {
  return loadClassSizesFromStorage() || defaultClassSizes();
}

/* ============================================================
   ROOM MANAGEMENT UI
   ============================================================ */
// The active department's rooms. The saved rooms (database) win; otherwise they come from
// the backend (GET /rooms?dept=<DEPT>).
let runtimeLectureRooms = [];
let runtimeLabRooms = [];
let runtimeRoomCapacity = {};

async function loadRuntimeRooms() {
  const stored = window.atlasData.rooms.has() ? window.atlasData.rooms.get() : null;
  const src = stored && Array.isArray(stored.lecture)
    ? { lecture: stored.lecture, lab: stored.lab || [], capacity: stored.capacity || {} }
    : await fetchRoomDefaults();
  runtimeLectureRooms = [...src.lecture];
  runtimeLabRooms = [...src.lab];
  runtimeRoomCapacity = JSON.parse(JSON.stringify(src.capacity || {}));
}

async function syncRoomsToBackend() {
  try {
    const res = await window.atlasAuth.fetch(`${API_BASE}/rooms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dept: DEPT,
        lecture_rooms: runtimeLectureRooms,
        laboratory_rooms: runtimeLabRooms,
        room_capacity: runtimeRoomCapacity
      })
    });
    if (res.ok) roomsSyncedSig = JSON.stringify([runtimeLectureRooms, runtimeLabRooms, runtimeRoomCapacity]);
  } catch { /* the engine copy is refreshed again before the next run */ }
}

// Rooms are saved to the database (rooms table); the engine copy is refreshed with syncRoomsToBackend().
function saveRoomsToStorage() {
  return window.atlasData.rooms.save({ lecture: runtimeLectureRooms, lab: runtimeLabRooms, capacity: runtimeRoomCapacity });
}

async function ensureRoomsSynced() {
  const sig = JSON.stringify([runtimeLectureRooms, runtimeLabRooms, runtimeRoomCapacity]);
  if (sig !== roomsSyncedSig) await syncRoomsToBackend();
}

function renderRoomList(containerId, rooms) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '';
  rooms.forEach((room, idx) => {
    const cap = runtimeRoomCapacity[room] || { recommended: '', max: '' };
    const item = document.createElement('div');
    item.className = 'room-item';
    item.innerHTML = `
      <input type="text" value="${escapeAttr(room)}" placeholder="Room name" class="room-name-input" style="flex:2;min-width:0;">
      <input type="number" value="${cap.recommended !== '' ? cap.recommended : ''}" placeholder="Rec." class="room-cap-input room-rec-input" min="1" max="999" title="Recommended capacity">
      <input type="number" value="${cap.max !== '' ? cap.max : ''}" placeholder="Max" class="room-cap-input room-max-input" min="1" max="999" title="Hard max capacity">
      <button class="room-item-del" data-idx="${idx}" title="Delete">&times;</button>
    `;
    const nameInp = item.querySelector('.room-name-input');
    const recInp  = item.querySelector('.room-rec-input');
    const maxInp  = item.querySelector('.room-max-input');
    const isList  = containerId === 'lectureRoomsList';
    const list    = isList ? runtimeLectureRooms : runtimeLabRooms;

    nameInp.addEventListener('input', debounce(() => {
      const oldName = list[idx];
      const newName = nameInp.value.trim();
      // Migrate capacity key if name changed
      if (oldName !== newName) {
        if (runtimeRoomCapacity[oldName] !== undefined) {
          runtimeRoomCapacity[newName] = runtimeRoomCapacity[oldName];
          delete runtimeRoomCapacity[oldName];
        }
      }
      list[idx] = newName;
    }, 300));

    recInp.addEventListener('input', debounce(() => {
      const name = list[idx] || nameInp.value.trim();
      if (!runtimeRoomCapacity[name]) runtimeRoomCapacity[name] = {};
      runtimeRoomCapacity[name].recommended = parseInt(recInp.value) || '';
    }, 300));

    maxInp.addEventListener('input', debounce(() => {
      const name = list[idx] || nameInp.value.trim();
      if (!runtimeRoomCapacity[name]) runtimeRoomCapacity[name] = {};
      runtimeRoomCapacity[name].max = parseInt(maxInp.value) || '';
    }, 300));

    item.querySelector('.room-item-del').addEventListener('click', () => {
      if (isList) {
        runtimeLectureRooms.splice(idx, 1);
        renderRoomList('lectureRoomsList', runtimeLectureRooms);
      } else {
        runtimeLabRooms.splice(idx, 1);
        renderRoomList('labRoomsList', runtimeLabRooms);
      }
    });
    container.appendChild(item);
  });
}

function initRoomManagement() {
  renderRoomList('lectureRoomsList', runtimeLectureRooms);
  renderRoomList('labRoomsList', runtimeLabRooms);

  document.getElementById('addLectureRoom')?.addEventListener('click', () => {
    runtimeLectureRooms.push('');
    renderRoomList('lectureRoomsList', runtimeLectureRooms);
  });

  document.getElementById('addLabRoom')?.addEventListener('click', () => {
    runtimeLabRooms.push('');
    renderRoomList('labRoomsList', runtimeLabRooms);
  });

  document.getElementById('saveRooms')?.addEventListener('click', async () => {
    // Sync name+capacity from DOM inputs before saving
    document.querySelectorAll('#lectureRoomsList .room-item').forEach((item, i) => {
      const name = item.querySelector('.room-name-input')?.value.trim() || '';
      const rec  = parseInt(item.querySelector('.room-rec-input')?.value) || '';
      const max  = parseInt(item.querySelector('.room-max-input')?.value) || '';
      runtimeLectureRooms[i] = name;
      if (name) runtimeRoomCapacity[name] = { recommended: rec, max };
    });
    document.querySelectorAll('#labRoomsList .room-item').forEach((item, i) => {
      const name = item.querySelector('.room-name-input')?.value.trim() || '';
      const rec  = parseInt(item.querySelector('.room-rec-input')?.value) || '';
      const max  = parseInt(item.querySelector('.room-max-input')?.value) || '';
      runtimeLabRooms[i] = name;
      if (name) runtimeRoomCapacity[name] = { recommended: rec, max };
    });
    runtimeLectureRooms = runtimeLectureRooms.filter(r => r);
    runtimeLabRooms = runtimeLabRooms.filter(r => r);
    const savedRooms = await saveRoomsToStorage();
    populateSCRoomDropdown();
    populateSCBuildingDropdown();
    if (!savedRooms.ok) return;
    showToast('Rooms saved successfully.', 'success');
    await syncRoomsToBackend();
  });

  document.getElementById('resetRooms')?.addEventListener('click', async () => {
    const d = roomDefaultsFromFile();
    runtimeLectureRooms = [...d.lecture];
    runtimeLabRooms = [...d.lab];
    runtimeRoomCapacity = JSON.parse(JSON.stringify(d.capacity));
    renderRoomList('lectureRoomsList', runtimeLectureRooms);
    renderRoomList('labRoomsList', runtimeLabRooms);
    const resetRooms = await saveRoomsToStorage();
    populateSCRoomDropdown();
    populateSCBuildingDropdown();
    if (!resetRooms.ok) return;
    showToast('Rooms reset to defaults.', 'info');
    await syncRoomsToBackend();
  });
}

/* ============================================================
   CLASS SIZES MANAGEMENT UI
   ============================================================ */
function renderClassSizesTable() {
  const tbody = document.querySelector('#classSizesTable tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  const sizes = getClassSizes();
  Object.entries(sizes).forEach(([key, val]) => {
    const tr = document.createElement('tr');
    tr.dataset.key = key;
    tr.innerHTML = `
      <td><span class="cs-key-badge">${escapeHTML(key)}</span><input type="hidden" class="cs-key" value="${escapeAttr(key)}"></td>
      <td>
        <select class="cs-year">
          <option ${val.year==='1st Year'?'selected':''}>1st Year</option>
          <option ${val.year==='2nd Year'?'selected':''}>2nd Year</option>
          <option ${val.year==='3rd Year'?'selected':''}>3rd Year</option>
          <option ${val.year==='4th Year'?'selected':''}>4th Year</option>
        </select>
      </td>
      <td><input type="text" class="cs-block" value="${escapeAttr(val.block||'')}" placeholder="e.g. B1" style="max-width:80px;"></td>
      <td><input type="number" class="cs-size" value="${val.size||0}" min="1" max="200" style="max-width:100px;"></td>
      <td><button type="button" class="btn-delete row-action-btn cs-del" title="Delete">Delete</button></td>
    `;
    tr.querySelector('.cs-del').addEventListener('click', () => {
      tr.remove();
    });
    tbody.appendChild(tr);
  });
}

function getClassSizesFromTable() {
  const result = {};
  document.querySelectorAll('#classSizesTable tbody tr').forEach(tr => {
    const key = tr.querySelector('.cs-key')?.value?.trim();
    if (!key) return;
    result[key] = {
      year:  tr.querySelector('.cs-year')?.value || '1st Year',
      block: tr.querySelector('.cs-block')?.value?.trim() || '',
      size:  parseInt(tr.querySelector('.cs-size')?.value || 0, 10)
    };
  });
  return result;
}

function initClassSizesManagement() {
  renderClassSizesTable();

  document.getElementById('saveClassSizes')?.addEventListener('click', async () => {
    const sizes = getClassSizesFromTable();
    const saved = await saveClassSizes(sizes);
    if (!saved.ok) return;
    showToast('Class sizes saved.', 'success');
    try {
      await window.atlasAuth.fetch(`${API_BASE}/class-sizes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dept: DEPT, ...sizes })
      });
    } catch { /* optional backend sync */ }
  });

  document.getElementById('addClassSizeRow')?.addEventListener('click', () => {
    const tbody = document.querySelector('#classSizesTable tbody');
    if (!tbody) return;
    const newKey = `${DEPT}${Math.floor(Math.random()*90)+10}B${Math.floor(Math.random()*3)+1}`;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" class="cs-key" value="${newKey}" placeholder="e.g. ${DEPT}1B1" style="max-width:90px;"></td>
      <td>
        <select class="cs-year">
          <option>1st Year</option>
          <option>2nd Year</option>
          <option>3rd Year</option>
          <option>4th Year</option>
        </select>
      </td>
      <td><input type="text" class="cs-block" value="B1" placeholder="e.g. B1" style="max-width:80px;"></td>
      <td><input type="number" class="cs-size" value="30" min="1" max="200" style="max-width:100px;"></td>
      <td><button type="button" class="btn-delete row-action-btn cs-del" title="Delete">Delete</button></td>
    `;
    tr.querySelector('.cs-del').addEventListener('click', () => tr.remove());
    tbody.appendChild(tr);
  });

  document.getElementById('resetClassSizes')?.addEventListener('click', () => {
    saveClassSizes(defaultClassSizes());
    renderClassSizesTable();
    showToast('Class sizes reset to defaults.', 'info');
  });
}

/* ============================================================
   SOFT CONSTRAINTS (PROFESSOR PREFERENCES) UI
   ============================================================ */
let softConstraintsCache = {};

// Preferences and leave dates of this department's faculty, in the engine's format (from the database).
function loadSoftConstraintsFromStorage() {
  return window.atlasData.softConstraints();
}

function populateSCFacultyDropdown() {
  const sel = document.getElementById('scFacultySelect');
  if (!sel) return;
  const faculty = getFacultyFromTable();
  sel.innerHTML = '<option value="">Select Faculty</option>' +
    faculty.map(f => `<option value="${escapeAttr(f.name)}">${escapeHTML(f.name)}</option>`).join('');
}

function populateSCRoomDropdown() {
  const sel = document.getElementById('scPreferredRoom');
  if (!sel) return;
  const allRooms = [...runtimeLectureRooms, ...runtimeLabRooms];
  sel.innerHTML = '<option value="">No Preference</option>' +
    allRooms.map(r => `<option value="${escapeAttr(r)}">${escapeHTML(r)}</option>`).join('');
}

function populateSCBuildingDropdown() {
  const sel = document.getElementById('scPreferredBuilding');
  if (!sel) return;
  // Derive unique building prefixes from runtime rooms using same logic as backend get_building()
  const allRooms = [...runtimeLectureRooms, ...runtimeLabRooms];
  const buildingSet = new Map();
  allRooms.forEach(r => {
    const name = r.trim();
    let bld, label;
    if (name.startsWith('GA Bldg'))  { bld = 'GA Bldg';  label = 'GA Building'; }
    else if (name.startsWith('IT Room')) { bld = 'IT Room'; label = 'IT Room Building'; }
    else if (name.startsWith('CL'))   { bld = 'CL';       label = 'CL Building'; }
    else if (name.startsWith('MTC'))  { bld = 'MTC';      label = 'MTC Building'; }
    else if (name.startsWith('NIT'))  { bld = 'NIT';      label = 'NIT Building'; }
    else if (name.startsWith('CSLR')) { bld = 'CSLR';     label = 'CSLR Building'; }
    else if (name.startsWith('GE Bldg')) { bld = 'GE Bldg'; label = 'GE Building'; }
    else if (name.startsWith('Physics')) { bld = 'Physics Room'; label = 'Physics Rooms'; }
    else { bld = name; label = name; }
    if (!buildingSet.has(bld)) buildingSet.set(bld, label);
  });
  const current = sel.value;
  sel.innerHTML = '<option value="">- No Preference -</option>' +
    Array.from(buildingSet.entries()).map(([bld, label]) =>
      `<option value="${escapeAttr(bld)}">${escapeHTML(label)}</option>`
    ).join('');
  if (current) sel.value = current;
}

function addUnavailDateEntry(container, value = '') {
  const div = document.createElement('div');
  div.className = 'date-entry';
  div.innerHTML = `
    <input type="date" value="${escapeAttr(value)}" style="flex:1;">
    <button class="date-entry-del" title="Remove">&times;</button>
  `;
  div.querySelector('.date-entry-del').addEventListener('click', () => div.remove());
  container.appendChild(div);
}

function addLeaveDateEntry(container, start = '', end = '') {
  const div = document.createElement('div');
  div.className = 'date-entry';
  div.innerHTML = `
    <input type="date" value="${escapeAttr(start)}" placeholder="Start" style="flex:1;">
    <span style="font-size:0.75rem;color:var(--text-muted);">to</span>
    <input type="date" value="${escapeAttr(end)}" placeholder="End" style="flex:1;">
    <button class="date-entry-del" title="Remove">&times;</button>
  `;
  div.querySelector('.date-entry-del').addEventListener('click', () => div.remove());
  container.appendChild(div);
}

function loadSCFormForFaculty(name) {
  const constraints = softConstraintsCache[name] || {};
  const form = document.getElementById('softConstraintForm');
  if (!form) return;
  form.classList.remove('hidden');

  document.getElementById('scPreferredPeriod').value = constraints.preferred_period || '';
  document.getElementById('scPreferredRoom').value = constraints.preferred_room || '';
  document.getElementById('scPreferredBuilding').value = constraints.preferred_building || '';
  document.getElementById('scPreferredFloor').value = constraints.preferred_floor || '';

  document.querySelectorAll('.sc-restrict-day').forEach(chk => {
    chk.checked = (constraints.restricted_days || []).includes(chk.value);
  });

  const leaveContainer = document.getElementById('leaveDatesContainer');
  leaveContainer.innerHTML = '';
  (constraints.leave_dates || []).forEach(l => addLeaveDateEntry(leaveContainer, l.start, l.end));
}

function getSCFormData() {
  return {
    preferred_period:   document.getElementById('scPreferredPeriod').value || null,
    preferred_room:     document.getElementById('scPreferredRoom').value || null,
    preferred_building: document.getElementById('scPreferredBuilding').value || null,
    preferred_floor:    document.getElementById('scPreferredFloor').value || null,
    restricted_days: Array.from(document.querySelectorAll('.sc-restrict-day:checked')).map(c => c.value),
    leave_dates: Array.from(document.querySelectorAll('#leaveDatesContainer .date-entry')).map(div => {
      const inputs = div.querySelectorAll('input[type="date"]');
      return { start: inputs[0]?.value || '', end: inputs[1]?.value || '' };
    }).filter(l => l.start || l.end)
  };
}

function initSoftConstraints() {
  softConstraintsCache = window.atlasData.softConstraints();
  populateSCFacultyDropdown();
  populateSCRoomDropdown();
  populateSCBuildingDropdown();

  document.getElementById('scLoadBtn')?.addEventListener('click', () => {
    const name = document.getElementById('scFacultySelect')?.value;
    if (!name) { showToast('Select a faculty member first.', 'info'); return; }
    loadSCFormForFaculty(name);
  });

  document.getElementById('addLeaveDate')?.addEventListener('click', () => {
    addLeaveDateEntry(document.getElementById('leaveDatesContainer'));
  });

  document.getElementById('scSaveBtn')?.addEventListener('click', async () => {
    const name = document.getElementById('scFacultySelect')?.value;
    if (!name) { showToast('Select a faculty member first.', 'info'); return; }
    const fid = facultyIdByName(name);
    if (!fid) { showToast('This professor is not saved yet. Wait for "Saved" and try again.', 'info'); return; }
    const c = getSCFormData();
    const dates = c.leave_dates.filter(l => l.start || l.end);
    if (dates.some(l => !l.start || !l.end || l.end < l.start)) {
      showToast('Each leave needs a start date and an end date that is not before it.', 'error');
      return;
    }
    const [a, b] = await Promise.all([
      window.atlasData.prefs.save(fid, {
        preferred_period: c.preferred_period, preferred_room: c.preferred_room, preferred_building: c.preferred_building,
        preferred_floor: c.preferred_floor, avoid_days: c.restricted_days
      }),
      window.atlasData.leave.replace(fid, dates)
    ]);
    softConstraintsCache = window.atlasData.softConstraints();
    if (!a.ok || !b.ok) return;
    showToast(`Preferences saved for ${name}.`, 'success');
    try {
      await window.atlasAuth.fetch(`${API_BASE}/soft-constraints`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dept: DEPT, faculty: name, constraints: softConstraintsCache[name] || {} })
      });
    } catch { /* the engine copy is refreshed with the run payload */ }
  });

  document.getElementById('scClearBtn')?.addEventListener('click', async () => {
    const name = document.getElementById('scFacultySelect')?.value;
    if (!name) return;
    const fid = facultyIdByName(name);
    if (!fid) return;
    const [a, b] = await Promise.all([window.atlasData.prefs.clear(fid), window.atlasData.leave.replace(fid, [])]);
    softConstraintsCache = window.atlasData.softConstraints();
    document.getElementById('softConstraintForm')?.classList.add('hidden');
    if (a.ok && b.ok) showToast(`Preferences cleared for ${name}.`, 'info');
  });
}

/* ============================================================
   GLOBAL EXPORTS & TOAST UTILITY
   ============================================================ */
/* ============================================================
   CAPACITY BADGE HELPER & ANALYTICS PANEL RENDERER
   ============================================================ */

function buildCapacityBadge(item) {
  const status = item._cap_status || item.capacity_status || null;
  if (status === 'hard_violation')   return `<span class="capacity-overall-badge badge-hard" title="Exceeds max capacity">Violation</span>`;
  if (status === 'over_recommended') return `<span class="capacity-overall-badge badge-warn" title="Exceeds recommended">Over Cap</span>`;
  if (status === 'ok')               return `<span class="capacity-overall-badge badge-ok"   title="Within recommended">OK</span>`;
  return '';
}

function mergeCapacityStatuses(analytics) {
  if (!analytics || !analytics.capacity_metrics) return;
  const details = analytics.capacity_metrics.capacity_details || [];
  if (!details.length || !lastGAResult.length) return;
  const lookup = {};
  details.forEach(d => {
    const key = `${d.room}||${d.section}||${d.subject}`;
    lookup[key] = { status: d.status, student_count: d.student_count };
  });
  lastGAResult.forEach(item => {
    const key = `${item.room || ''}||${item.section || ''}||${item.subject || ''}`;
    const match = lookup[key];
    if (match) {
      item._cap_status = match.status;
      if (!item.student_count) item.student_count = match.student_count;
    }
  });
}

/**
 * Capacity metrics come only from the backend (it knows each group's real
 * student count). Nothing is estimated here.
 */
function resolveCapacityMetrics(backendAnalytics) {
  return (backendAnalytics && backendAnalytics.capacity_metrics) || {};
}

function renderCapacityAnalytics(analytics) {
  const cm = resolveCapacityMetrics(analytics);

  const total  = cm.total_evaluated          || 0;
  const okCnt  = cm.within_recommended_count || 0;
  const warnCt = cm.over_recommended_count   || 0;
  const hardCt = cm.hard_violation_count     || 0;
  const pct = n => total > 0 ? ((n / total) * 100).toFixed(1) + '%' : '-';

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set('analyticsCapTotal',          total  != null ? total  : '-');
  set('analyticsCapCompliant',      okCnt  != null ? okCnt  : '-');
  set('analyticsCapCompliantPct',   pct(okCnt));
  set('analyticsCapOver',           warnCt != null ? warnCt : '-');
  set('analyticsCapOverPct',        pct(warnCt));
  set('analyticsCapViolations',     hardCt != null ? hardCt : '-');
  set('analyticsCapViolationsPct',  pct(hardCt));

  // Room utilization table
  const ruBody = document.getElementById('roomUtilCapBody');
  if (ruBody && analytics.room_utilization && analytics.room_utilization.length) {
    ruBody.innerHTML = analytics.room_utilization.map(r => {
      const recCap = r.recommended_cap != null ? r.recommended_cap : 'N/A';
      const maxCap = r.max_cap         != null ? r.max_cap         : 'N/A';
      const cls    = r.occupancy_pct >= 80 ? 'match-no' : r.occupancy_pct >= 50 ? 'match-partial' : 'match-yes';
      return `<tr>
        <td><span class="room-badge">${escapeHTML(r.room)}</span></td>
        <td class="txt-center">${r.assigned_count}</td>
        <td class="txt-center"><span class="${cls}">${r.occupancy_pct}%</span></td>
        <td class="txt-center">${escapeHTML(String(recCap))}</td>
        <td class="txt-center">${escapeHTML(String(maxCap))}</td>
      </tr>`;
    }).join('');
  }

  // Capacity details table
  const details = cm.capacity_details || [];
  const cdBody = document.getElementById('capacityDetailsBody');
  const cdSection = document.getElementById('capacityDetailsSection');
  if (cdBody && details.length) {
    cdBody.innerHTML = details.map(d => {
      const utilPct = d.recommended_cap > 0 ? Math.round(d.student_count / d.recommended_cap * 100) : 0;
      const utilCls = d.status === 'hard_violation' ? 'match-no' : d.status === 'over_recommended' ? 'match-partial' : 'match-yes';
      const badgeCls   = d.status === 'hard_violation' ? 'badge-hard' : d.status === 'over_recommended' ? 'badge-warn' : 'badge-ok';
      const badgeLabel = d.status === 'hard_violation' ? 'Violation' : d.status === 'over_recommended' ? 'Over Cap' : 'OK';
      return `<tr>
        <td><span class="room-badge">${escapeHTML(d.room)}</span></td>
        <td>${d.section ? `<span class="section-badge">${escapeHTML(d.section)}</span>` : '<span class="text-muted">-</span>'}</td>
        <td>${escapeHTML(d.subject || '')}</td>
        <td class="txt-center"><span class="student-count-tag">${d.student_count}</span></td>
        <td class="txt-center">${d.recommended_cap}</td>
        <td class="txt-center">${d.max_cap}</td>
        <td class="txt-center"><span class="${utilCls}">${utilPct}%</span></td>
        <td><span class="capacity-overall-badge ${badgeCls}">${badgeLabel}</span></td>
      </tr>`;
    }).join('');
    if (cdSection) cdSection.style.display = '';
  }
}

/* ============================================================
   GLOBAL EXPORTS & TOAST UTILITY
   ============================================================ */
/* Sound, vibration and system alert when a run finishes (see Notification settings) */
function announceOptimization(count, analytics) {
  const app = window.atlasApp;
  if (!app || !app.get('notifyOptimization')) return;
  const violations = analytics && analytics.capacity_metrics ? analytics.capacity_metrics.hard_violation_count : 0;
  let body = `${count} assignments generated.`;
  if (violations && app.get('notifyViolations')) body += ` ${violations} capacity violation${violations === 1 ? '' : 's'} found.`;
  app.alert('Optimization complete', body, 'atlas-optimization');
}

function showToast(msg, type = 'info') {
  const t = document.getElementById('toastNotif');
  if (!t) return;
  t.textContent = msg;
  t.className = 'toast-notif show' + (type ? ' toast-' + type : '');
  setTimeout(() => { t.className = 'toast-notif'; }, 3000);
}

window.switchPanel = switchPanel;

/* ============================================================
   DEPARTMENT LABELS, NOTICES AND RESET
   ============================================================ */
function applyDeptLabels() {
  const name = deptName();
  const user = sessionStorage.getItem('atlasUser');
  const lbl = document.getElementById('navUserLabel');
  if (lbl && user) lbl.textContent = user + ' \u00b7 ' + name;
  const banner = document.getElementById('deptBanner');
  const bannerName = document.getElementById('deptBannerName');
  if (banner && bannerName) {
    bannerName.textContent = name + ' Department';
    banner.style.display = '';
  }
  renderSampleNotices();
}

// One small notice in the Faculty and Subjects area and one in the class size area.
function renderSampleNotices() {
  const c = ATLAS_CURRICULUM;
  const placeholder = !!(c && (c.class_sizes_placeholder || (c.rooms && c.rooms.capacity_placeholder)));
  ['sampleNoticeFaculty', 'sampleNoticeClassSizes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.hidden = !placeholder;
  });
}

/* Logout, a different department, or a page restored for another department: drop every
   result, analytics, report, faculty, subject and class size held in memory, and empty the
   report and result DOM. The next department then loads only its own keys. */
function resetDepartmentState() {
  if (progressInterval) clearInterval(progressInterval);
  progressInterval = null;
  currentRun = null;
  lastGAResult = [];
  lastCoverage = null;
  renderCoverageSummary(null);
  softConstraintsCache = {};
  window.__atlasAnalytics = null;
  ATLAS_CURRICULUM = null;
  SPECIALIZATIONS = [];
  runtimeLectureRooms = [];
  runtimeLabRooms = [];
  runtimeRoomCapacity = {};

  [dashboardChart, miniDashChart, reportsChart, reportsBarChart].forEach(ch => {
    if (!ch) return;
    ch.data.labels = [];
    ch.data.datasets.forEach(ds => { ds.data = []; });
    try { ch.update('none'); } catch { /* chart already gone */ }
  });

  ['#gaScheduleTable tbody', '#facultyTable tbody', '#subjectsTable tbody', '#classSizesTable tbody']
    .forEach(sel => { const el = document.querySelector(sel); if (el) el.innerHTML = ''; });
  ['facultyTimetableContainer', 'reportsSummaryGrid', 'dashboardFacultyAssignments', 'fairnessPerFaculty',
   'subjectsContainer', 'roomUtilCapBody', 'capacityDetailsBody', 'capacityHardViolationsItems',
   'lectureRoomsList', 'labRoomsList', 'editAssignmentList'
  ].forEach(id => { const el = document.getElementById(id); if (el) el.innerHTML = ''; });
  ['statAvgLoad', 'statOverloaded', 'statBalance', 'fairnessScore', 'fairnessScoreLabel', 'fairnessJain',
   'fairnessStdDev', 'fairnessMatchRate', 'fairnessMinMax', 'fairnessZeroLoad', 'fairnessQualified', 'fairnessElectiveGroups', 'navUserLabel', 'deptBannerName'
  ].forEach(id => { const el = document.getElementById(id); if (el) el.textContent = ''; });
  const card = document.getElementById('capacitySummaryCard');
  if (card) card.style.display = 'none';
  const banner = document.getElementById('deptBanner');
  if (banner) banner.style.display = 'none';
}
window.addEventListener('atlas:logout', resetDepartmentState);

/* ============================================================
   DASHBOARD PAGE - dashboard.html inline script (migrated)
   ============================================================ */
(function initDashboardPage() {
  // Auth guard - runs after defer, DOM is available
  if (window.location.pathname.includes('dashboard') && !sessionStorage.getItem('atlasUser')) {
    window.location.href = 'login.html';
    return;
  }
  if (window.location.pathname.includes('dashboard') && sessionStorage.getItem('atlasRole') === 'faculty') {
    window.location.href = '../faculty/dashboard.html';
    return;
  }

  const navUserLabel = document.getElementById('navUserLabel');
  if (!navUserLabel) return; // not on dashboard

  window.addEventListener('DOMContentLoaded', () => {
    // The department name comes from the department's file (applyDeptLabels runs once it is loaded)
    const user = sessionStorage.getItem('atlasUser');
    const lbl  = document.getElementById('navUserLabel');
    if (lbl && user) lbl.textContent = user + ' · ' + deptName();

    // Profile dropdown - click to open/close
    const profileDrop = document.querySelector('.nav-item.dropdown');
    if (profileDrop) {
      profileDrop.addEventListener('click', e => {
        e.stopPropagation();
        profileDrop.classList.toggle('open');
      });
      document.addEventListener('click', () => {
        profileDrop.classList.remove('open');
      });
    }
  });
})();