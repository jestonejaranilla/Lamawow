/* ============================================================
   ATLAS PSU - solver settings: the single source of truth.
   Part 16: the values live in Supabase (dept_settings.solver, through assets/js/data-store.js) and are read from the
   in-memory copy it loaded; nothing is kept in localStorage. The limits below match what /run-ga accepts
   (routes/schedule_routes.py).
   Used by app-script.js (the form) and main-script.js (runs, summary).
   ============================================================ */
(function () {
  'use strict';

  const FIELDS = {
    max_units:            { label: 'Standard Max Units',   min: 1, max: 40,  int: true,  def: 24 },
    units_per_assignment: { label: 'Units Per Assignment', min: 1, max: 10,  int: true,  def: 2 },
    cp_sat_time_limit:    { label: 'CP-SAT Time Limit',    min: 5, max: 40,  int: false, def: 30 },
    population:           { label: 'Population Size',      min: 4, max: 100, int: true,  def: 50 },
    generations:          { label: 'Generations',          min: 1, max: 200, int: true,  def: 100 },
    mutation:             { label: 'Mutation Rate',        min: 0, max: 1,   int: false, def: 0.09 },
    crossover:            { label: 'Crossover Rate',       min: 0, max: 1,   int: false, def: 0.95 },
  };
  const DEFAULTS = Object.fromEntries(Object.entries(FIELDS).map(([k, f]) => [k, f.def]));
  const store = () => window.atlasData || null;

  /* raw: {field: string|number}. Returns {values, errors}; a bad value is reported, never coerced. */
  function validate(raw) {
    const values = {}, errors = {};
    Object.entries(FIELDS).forEach(([k, f]) => {
      const text = String(raw[k] === undefined || raw[k] === null ? '' : raw[k]).trim();
      const n = Number(text);
      if (text === '' || !Number.isFinite(n)) errors[k] = 'Enter a number.';
      else if (f.int && !Number.isInteger(n)) errors[k] = 'Enter a whole number.';
      else if (n < f.min || n > f.max) errors[k] = `Must be between ${f.min} and ${f.max}.`;
      else values[k] = n;
    });
    return { values, errors };
  }

  /* Reads the department's saved values from the data store's memory (filled from the database before the page
     starts). A value that is missing or outside its limit (for example the old 60 s) falls back to the default. */
  function read(dept) {
    const s = store();
    const stored = s && s.dept() === dept ? s.settings.solver() : {};
    const out = {};
    Object.entries(FIELDS).forEach(([k, f]) => {
      const r = validate({ [k]: stored[k] });
      out[k] = r.errors[k] === undefined ? Number(stored[k]) : f.def;
    });
    return out;
  }

  /* Saves to the database. Returns a promise {ok, error?}; the new values apply on screen at once. */
  function save(dept, values) {
    const s = store();
    if (!s || s.dept() !== dept) return Promise.resolve({ ok: false, error: 'Not signed in.' });
    return s.settings.saveSolver(values);
  }

  function summary(s) {
    return `${s.cp_sat_time_limit} s limit, ${s.population} population, ${s.generations} generations`;
  }

  window.atlasSolver = { FIELDS, DEFAULTS, validate, read, save, summary };
})();