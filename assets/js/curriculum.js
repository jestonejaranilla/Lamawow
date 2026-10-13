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
  const IN_SCOPE_PREFIXES = ['CC', 'IT'];
  const NON_CLASSROOM = 'NON_CLASSROOM';

  const yearLabel = n => YEAR_LABELS[n] || `${n}th Year`;
  const semesterLabel = n => SEM_LABELS[n] || String(n);

  function parseSemester(label) {
    const m = /^\s*(\d)/.exec(String(label == null ? '' : label));
    return m ? Number(m[1]) : null;
  }

  /** Scope rule: prospectus code starts with CC or IT (IT E1..E4 included). */
  function isInScope(course) {
    const code = String(course.code || '').trim().toUpperCase();
    return IN_SCOPE_PREFIXES.some(p => code.startsWith(p));
  }

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

  /** Subject-table defaults: one row per in-scope course. */
  function defaultSubjects(curriculum) {
    return curriculum.courses.filter(isInScope).map(c => ({
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
   * R1: every block of every year gets every in-scope course of its year and
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
    curriculum.courses.filter(isInScope).forEach(c => {
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

  /** ceil(lec/2) two-hour LECTURE meetings + one LAB meeting if lab > 0. */
  function groupMeetings(g) {
    if (!g.scheduled) return [meeting(g, NON_CLASSROOM)];
    const out = [];
    for (let i = 0; i < Math.ceil(g.lec / 2); i++) out.push(meeting(g, 'LECTURE'));
    if (g.lab > 0) out.push(meeting(g, 'LAB'));
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

  return {
    NON_CLASSROOM, yearLabel, semesterLabel, parseSemester, isInScope,
    blocksForYear, defaultSubjects, buildGroups, groupMeetings,
    buildPayloadSubjects, loadCurriculum,
  };
});