/* Runs the controller of assets/js/saved-runs.js against a fake API that follows run_routes.py
   (list without the large fields, full run on open, save, approve swaps the approved run, delete of an approved run is 409).
   Prints one line per check and "ALL OK", or exits 1. Used by tests/test_part17.py. */
'use strict';
const path = require('path');
const SR = require(path.join(__dirname, '../../assets/js/saved-runs.js'));

let failures = 0;
function check(name, ok, extra) {
  console.log((ok ? 'ok   ' : 'FAIL ') + name + (ok || !extra ? '' : '  ' + extra));
  if (!ok) failures++;
}

function fakeServer(initial) {
  const s = { runs: initial.slice(), calls: [] };
  const err = (status, message) => Object.assign(new Error(message), { status });
  s.api = async function (p, opts) {
    const method = (opts && opts.method) || 'GET';
    s.calls.push(method + ' ' + p.split('?')[0]);
    let m;
    if (method === 'GET' && p.startsWith('/runs?')) {
      return { runs: s.runs.map(r => { const { result, analytics, ...head } = r; return head; }).sort((a, b) => (a.created_at < b.created_at ? 1 : -1)) };
    }
    if (method === 'GET' && (m = p.match(/^\/runs\/([\w-]+)$/))) {
      const r = s.runs.find(x => x.id === m[1]);
      if (!r) throw err(404, 'Run not found.');
      return { run: Object.assign({}, r) };
    }
    if (method === 'POST' && (m = p.match(/^\/runs\/([\w-]+)\/save$/))) {
      const r = s.runs.find(x => x.id === m[1]);
      if (r.status === 'approved') throw err(409, 'An approved run is already saved.');
      r.status = 'saved'; r.label = JSON.parse(opts.body).label;
      return { run: { id: r.id } };
    }
    if (method === 'POST' && (m = p.match(/^\/runs\/([\w-]+)\/approve$/))) {
      const r = s.runs.find(x => x.id === m[1]);
      s.runs.forEach(x => { if (x.status === 'approved' && x.dept === r.dept) x.status = 'saved'; });
      r.status = 'approved';
      return { run: { id: r.id, status: 'approved' } };
    }
    if (method === 'DELETE' && (m = p.match(/^\/runs\/([\w-]+)$/))) {
      const r = s.runs.find(x => x.id === m[1]);
      if (r.status === 'approved') throw err(409, 'An approved run cannot be deleted. Approve another run first.');
      s.runs = s.runs.filter(x => x !== r);
      return { id: r.id, deleted: true };
    }
    throw err(500, 'unexpected ' + method + ' ' + p);
  };
  return s;
}

function fakeUi(answers) {
  const ui = { toasts: [], applied: [], lists: [], banners: [], saveBars: [], confirms: [], answer: answers === undefined ? true : answers };
  ui.confirm = msg => { ui.confirms.push(msg); return ui.answer; };
  ui.toast = (msg, kind) => ui.toasts.push([kind, msg]);
  ui.applyRun = run => ui.applied.push(run ? run.id : null);
  ui.renderList = m => ui.lists.push(m);
  ui.showBanner = m => ui.banners.push(m);
  ui.showSaveBar = m => ui.saveBars.push(m);
  ui.last = a => ui[a][ui[a].length - 1];
  return ui;
}

const NOW = new Date('2026-10-15T09:30:00Z');
const run = (id, status, extra) => Object.assign({
  id, dept: 'IT', status, label: id, academic_year: '2026-2027', semester: '1st Semester', created_by: 'me',
  created_at: '2026-10-1' + (id.length % 10) + 'T01:00:00Z', metrics: { balance_score: 87.4 },
  coverage: { summary: { assigned: 28, total: 29 }, errors: [{ g: 1 }] }, result: [{ big: id }], analytics: { a: 1 }
}, extra);

function make(initial, answers) {
  const server = fakeServer(initial);
  const ui = fakeUi(answers);
  const ctl = SR.createController({ api: server.api, ui, dept: 'IT', userId: 'me', now: () => NOW, semester: () => '1st Semester',
    lookupNames: async ids => Object.fromEntries(ids.map(i => [i, 'Dr. ' + i])) });
  return { server, ui, ctl };
}

(async () => {
  /* helpers */
  check('time is formatted like "15 Oct 2026 5:30 PM"', /^15 Oct 2026 \d{1,2}:30 (AM|PM)$/.test(SR.formatRunTime('2026-10-15T09:30:00Z')), SR.formatRunTime('2026-10-15T09:30:00Z'));
  check('default label is "<Dept> <Semester> <date time>"', SR.defaultLabel('IT', '1st Semester', NOW).startsWith('IT 1st Semester 15 Oct 2026 '));
  check('coverage reads the saved summary', SR.coverageText(run('a', 'draft')) === '28 of 29 (1 gaps)' && SR.coverageText({}) === '\u2014');
  check('balance score shown as a percentage', SR.balanceText(run('a', 'draft')) === '87%' && SR.balanceText({ metrics: {} }) === '\u2014');

  /* 0 saved runs */
  let t = make([]);
  await t.ctl.init();
  check('0 runs: empty list, no banner, empty views', t.ui.last('lists').count === 0 && t.ui.last('banners') === null && t.ui.last('applied') === null);
  check('0 runs: edits are not blocked (nothing approved to protect)', t.ctl.editsBlocked() === false);

  /* the list never carries the large fields and opens a run only on request */
  const many = [];
  for (let i = 0; i < 50; i++) many.push(run('r' + i, i === 7 ? 'approved' : i % 2 ? 'saved' : 'draft', { created_at: new Date(2026, 9, 1, 0, i).toISOString() }));
  t = make(many);
  await t.ctl.init();
  check('50 runs: all listed', t.ui.last('lists').count === 50 && t.ui.last('lists').rows.length === 50);
  check('50 runs: the list rows carry no result or analytics', t.ui.last('lists').rows.every(r => !('result' in r) && !('analytics' in r)));
  check('50 runs: only the approved run was opened at start', t.server.calls.filter(c => c === 'GET /runs').length === 1 && t.server.calls.filter(c => c.startsWith('GET /runs/')).length === 1 && t.ui.applied.join() === 'r7');
  check('50 runs: statuses and who ran them', t.ui.last('lists').rows.find(r => r.id === 'r7').statusLabel === 'Approved' && t.ui.last('lists').rows[0].who === 'You');

  /* save */
  t = make([run('ap', 'approved'), run('new', 'draft')]);
  await t.ctl.init();
  await t.ctl.noteFreshRun('new');
  check('after a run: banner says it is not the approved schedule', /not the approved schedule/.test(t.ui.last('banners').text) && /Draft/.test(t.ui.last('banners').text));
  check('after a run: "Save this run" is offered with the default label', t.ui.last('saveBars') && t.ui.last('saveBars').label.startsWith('IT 1st Semester '));
  check('edits are allowed on the new run', t.ctl.editsBlocked() === false);
  await t.ctl.save('  Final plan  ');
  check('save sends the trimmed label and the run becomes Saved', t.server.runs.find(r => r.id === 'new').label === 'Final plan' && t.server.runs.find(r => r.id === 'new').status === 'saved');
  check('after saving the save bar is hidden and the list shows Saved', t.ui.last('saveBars') === null && t.ui.last('lists').rows.find(r => r.id === 'new').statusLabel === 'Saved');
  await t.ctl.noteFreshRun('new'); t.server.runs.find(r => r.id === 'new').status = 'draft';
  await t.ctl.save('');
  check('an empty label falls back to the default label', t.server.runs.find(r => r.id === 'new').label.startsWith('IT 1st Semester '));

  /* load + unload */
  t = make([run('ap', 'approved'), run('old', 'saved', { created_at: '2026-10-02T04:00:00Z' })]);
  await t.ctl.init();
  await t.ctl.load('old');
  check('load shows the run and the banner with its date and time', t.ui.last('applied') === 'old' && /^Viewing saved run from 2 Oct 2026 \d{1,2}:00 (AM|PM), not the approved schedule\.$/.test(t.ui.last('banners').text), JSON.stringify(t.ui.last('banners')));
  check('while a run is loaded the approved schedule is not editable target and the run row offers Unload', t.ctl.editsBlocked() === false && t.ui.last('lists').rows.find(r => r.id === 'old').canUnload === true);
  await t.ctl.unload();
  check('unload goes back to the approved schedule and removes the banner', t.ui.last('applied') === 'ap' && t.ui.last('banners') === null && t.ctl.viewing() === null);
  check('with the approved schedule on screen, edits are blocked', t.ctl.editsBlocked() === true);

  /* unload with no approved run -> empty */
  t = make([run('only', 'saved')]);
  await t.ctl.init();
  await t.ctl.load('only');
  await t.ctl.unload();
  check('unload with no approved run goes to the empty view', t.ui.last('applied') === null && t.ui.last('banners') === null);

  /* a new run while another is loaded never touches the approved run */
  t = make([run('ap', 'approved'), run('old', 'saved'), run('fresh', 'draft')]);
  await t.ctl.init();
  await t.ctl.load('old');
  await t.ctl.noteFreshRun('fresh');
  check('a new run replaces the loaded one on screen as a draft, approved run untouched', t.ctl.viewing().id === 'fresh' && t.server.runs.find(r => r.id === 'ap').status === 'approved');

  /* approve twice */
  t = make([run('ap', 'approved'), run('b', 'saved'), run('c', 'draft')]);
  await t.ctl.init();
  await t.ctl.approve('b');
  check('approve asks for confirmation first', t.ui.confirms.length === 1 && /Approve "b"/.test(t.ui.confirms[0]) && /becomes Saved/.test(t.ui.confirms[0]));
  check('first approve: b is Approved, the old one is Saved', t.server.runs.find(r => r.id === 'b').status === 'approved' && t.server.runs.find(r => r.id === 'ap').status === 'saved');
  check('the default view follows the new approved run', t.ui.last('applied') === 'b' && t.ctl.approvedId() === 'b');
  await t.ctl.approve('c');
  const st = Object.fromEntries(t.server.runs.map(r => [r.id, r.status]));
  check('second approve: c Approved, b becomes Saved, exactly one Approved', st.c === 'approved' && st.b === 'saved' && st.ap === 'saved' && Object.values(st).filter(x => x === 'approved').length === 1, JSON.stringify(st));
  t.ui.answer = false;
  const before = t.server.calls.length;
  check('declining the confirmation approves nothing', (await t.ctl.approve('ap')) === false && t.server.calls.length === before);

  /* approving the run on screen removes the banner */
  t = make([run('ap', 'approved'), run('d', 'draft')]);
  await t.ctl.init();
  await t.ctl.load('d');
  await t.ctl.approve('d');
  check('approving the run on screen clears the banner', t.ui.last('banners') === null && t.ctl.viewing() === null && t.ctl.approvedId() === 'd');

  /* delete */
  t = make([run('ap', 'approved'), run('x', 'saved')]);
  await t.ctl.init();
  const callsBefore = t.server.calls.length;
  check('delete of the approved run is refused without calling the API', (await t.ctl.remove('ap')) === false && t.server.calls.length === callsBefore && /cannot be deleted/.test(t.ui.last('toasts')[1]));
  check('the approved row offers no Delete button', t.ui.last('lists').rows.find(r => r.id === 'ap').canDelete === false);
  const forced = await t.server.api('/runs/ap', { method: 'DELETE' }).catch(e => e);
  check('and the API itself answers 409', forced.status === 409);
  await t.ctl.remove('x');
  check('a saved run is deleted after confirmation', t.server.runs.length === 1 && t.ui.confirms.some(c => /Delete "x"/.test(c)));
  await t.ctl.load('ap');
  t = make([run('ap', 'approved'), run('v', 'saved')]);
  await t.ctl.init();
  await t.ctl.load('v');
  await t.ctl.remove('v');
  check('deleting the run on screen first returns to the approved schedule', t.ui.last('applied') === 'ap' && t.ui.last('banners') === null && t.server.runs.length === 1);

  /* errors */
  const bad = { api: async () => { throw Object.assign(new Error('x'), { status: 503 }); } };
  const ui2 = fakeUi();
  const c2 = SR.createController({ api: bad.api, ui: ui2, dept: 'IT', userId: 'me', now: () => NOW });
  await c2.init();
  check('no database: the list says so and the page still works', /database/.test(ui2.last('lists').message) && ui2.last('applied') === null);

  console.log(failures ? failures + ' FAILED' : 'ALL OK');
  process.exit(failures ? 1 : 0);
})().catch(e => { console.log('FAIL harness crashed: ' + (e && e.stack || e)); process.exit(1); });