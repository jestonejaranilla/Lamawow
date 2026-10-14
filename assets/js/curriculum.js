/* ============================================================
   ATLAS PSU - curriculum.js
   Pure helpers (no DOM) that read the same curriculum file the
   backend reads: data/curricula/<DEPT>.json.
   Exposed as window.AtlasCurriculum (and module.exports for tests).
   ============================================================ */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AtlasCurriculum = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  const YEAR_LABELS = { 1: '1st Year', 2: '2nd Year', 3: '3rd Year', 4: '4th Year' };
  const SEM_LABELS  = { 1: '1st Semester', 2: '2nd Semester', 3: 'Summer' };
  const NON_CLASSROOM = 'NON_CLASSROOM';

  const yearLabel = n => YEAR_LABELS[n] || `${n}th Year`;
  const semesterLabel = n => SEM_LABELS[n] || String(n);

  function parseSemester(label) {
    const m = /^\s*(\d)/.exec(String(label == null ? '' : label));
    return m ? Number(m[1]) : null;
  }

  /* SCOPE: a course is in scope when it is in the department's file.
     There is no code-prefix rule anywhere. */

  /** [{key, size}] for a year, from class sizes such as IT3B1..IT3B3. */
  function blocksForYear(classSizes, dept, yearNo) {
    const pat = new RegExp('^' + dept + '(\\d+)B(\\d+)$');
    const found = [];
    Object.entries(classSizes || {}).forEach(([key, entry]) => {
      const m = pat.exec(key);
      if (!m || Number(m[1]) !== yearNo) return;
      const size = entry && typeof entry === 'object' ? Number(entry.size) || 0 : Number(entry) || 0;
      found.push({ n: Number(m[2]), key, size });
    });
    return found.sort((a, b) => a.n - b.n).map(({ key, size }) => ({ key, size }));
  }

  /** Subject-table defaults: one row per course of the department's file. */
  function defaultSubjects(curriculum) {
    return curriculum.courses.map(c => ({
      code: c.code,
      name: c.title,
      type: (c.specialization && c.specialization[0]) || 'Elective',
      year: yearLabel(c.year),
      semester: semesterLabel(c.semester),
      lec_units: c.lec,
      lab_units: c.lab,
      category: c.category || '',
      scheduled: c.scheduled !== false,
    }));
  }

  /**
   * R1: every block of every year gets every course of its year and
   * the active semester. `tableRows` (optional) carry user-edited units/type,
   * matched by course code.
   */
  function buildGroups(curriculum, semester, classSizes, tableRows) {
    const dept = curriculum.dept;
    const sem = parseSemester(semester);
    const edits = {};
    (tableRows || []).forEach(r => { if (r.code) edits[r.code] = r; });

    const groups = [];
    const errors = [];
    curriculum.courses.forEach(c => {
      if (sem !== null && c.semester !== sem) return;
      const blocks = blocksForYear(classSizes, dept, c.year);
      if (!blocks.length) {
        errors.push({ course: c.code, reason: `no blocks defined for ${yearLabel(c.year)}` });
        return;
      }
      const edit = edits[c.code] || {};
      blocks.forEach(b => groups.push({
        group_id: `${b.key}|${c.code}`,
        section: b.key,
        course_code: c.code,
        title: c.title,
        year: yearLabel(c.year),
        semester: semesterLabel(c.semester),
        type: edit.type || (c.specialization && c.specialization[0]) || 'Elective',
        lec: edit.lec_units !== undefined ? Number(edit.lec_units) : c.lec,
        lab: edit.lab_units !== undefined ? Number(edit.lab_units) : c.lab,
        scheduled: c.scheduled !== false,
        student_count: b.size,
      }));
    });
    return { groups, errors };
  }

  function meeting(g, classType) {
    return {
      name: g.title, type: g.type, class_type: classType, hours: 2,
      semester: g.semester, year: g.year, section: g.section,
      student_count: g.student_count, group_id: g.group_id, course_code: g.course_code,
    };
  }

  /** ceil(lec/2) two-hour LECTURE meetings + one LAB meeting per lab unit (same rule as the backend). */
  function groupMeetings(g) {
    if (!g.scheduled) return [meeting(g, NON_CLASSROOM)];
    const out = [];
    for (let i = 0; i < Math.ceil(g.lec / 2); i++) out.push(meeting(g, 'LECTURE'));
    for (let i = 0; i < g.lab; i++) out.push(meeting(g, 'LAB'));
    return out;
  }

  /** Everything the dashboard sends as `subjects` in the /run-ga payload. */
  function buildPayloadSubjects(curriculum, semester, classSizes, tableRows) {
    const { groups, errors } = buildGroups(curriculum, semester, classSizes, tableRows);
    const subjects = [];
    groups.forEach(g => groupMeetings(g).forEach(m => subjects.push(m)));
    return { subjects, groups, errors };
  }

  /** Static file first (same file the backend reads), backend endpoint second. */
  async function loadCurriculum(dept, urls) {
    let lastErr = null;
    for (const url of urls) {
      try {
        const res = await fetch(url, { cache: 'no-cache' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data && Array.isArray(data.courses)) return data;
      } catch (e) { lastErr = e; }
    }
    throw lastErr || new Error('Curriculum could not be loaded');
  }

  /** Tags a course asks for. Only "Elective" (or none) means any professor may teach it. */
  function courseTags(curriculum, title) {
    const c = (curriculum.courses || []).find(x => x.title === title);
    return c ? (c.specialization || []) : [];
  }

  /** Same rule as the backend: overlap with a listed tag, or an open (Elective-only) course. */
  function qualifies(facultyTags, tags) {
    if (!tags.length || tags.every(t => t === 'Elective')) return true;
    return tags.some(t => (facultyTags || []).includes(t));
  }

  /**
   * Default faculty for a department without saved data: 8 editable placeholders
   * (Prof A to H), 1 or 2 tags each from the department's own vocabulary, every tag
   * covered, Mon to Thu, max_units 24, absolute_max_units 30. Deterministic.
   * Primary tags follow the teaching demand of the file, so no tag is starved.
   */
  function placeholderFaculty(curriculum, size) {
    size = size || 8;
    const tags = (curriculum.specializations || []).slice();
    const demand = {};
    tags.forEach(t => { demand[t] = 0; });
    (curriculum.courses || []).forEach(c => {
      if (c.scheduled === false) return;
      const own = (c.specialization || []).filter(t => t !== 'Elective' && t in demand);
      if (!own.length) return;
      const units = 2 * (Math.ceil((c.lec || 0) / 2) + (c.lab || 0));
      own.forEach(t => { demand[t] += units / own.length; });
    });
    const holders = {};
    tags.forEach(t => { holders[t] = 0; });
    const specs = [];
    for (let i = 0; i < size; i++) {
      let best = tags[0];
      tags.forEach(t => {
        if (demand[t] / (holders[t] + 1) > demand[best] / (holders[best] + 1)) best = t;
      });
      holders[best] += 1;
      specs.push([best]);
    }
    // tags nobody holds yet go to the professor whose primary tag is least in demand per holder
    const order = specs.map((s, i) => i)
      .sort((a, b) => (demand[specs[a][0]] / holders[specs[a][0]]) - (demand[specs[b][0]] / holders[specs[b][0]]) || a - b);
    tags.filter(t => holders[t] === 0).forEach(t => {
      const target = order.find(i => specs[i].length < 2) ?? order[0];
      specs[target].push(t);
      holders[t] += 1;
    });
    return specs.map((spec, i) => ({
      name: 'Prof ' + String.fromCharCode(65 + i),
      specialization: spec,
      max_units: 24,
      absolute_max_units: 30,
      availability: ['Mon', 'Tue', 'Wed', 'Thu'],
    }));
  }

  return {
    NON_CLASSROOM, yearLabel, semesterLabel, parseSemester,
    blocksForYear, defaultSubjects, buildGroups, groupMeetings,
    buildPayloadSubjects, loadCurriculum, courseTags, qualifies, placeholderFaculty,
  };
});