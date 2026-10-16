/* ============================================================
   ATLAS PSU - assets/js/saved-runs.js  (Part 17)
   Saved runs on Workload Optimization: "Save this run", the Saved runs list, Load / Unload / Approve / Delete,
   and the banner shown while a run that is not the approved schedule is on screen.

   Two parts:
   - createController(deps): the rules (no DOM). It talks to the Flask API (GET /runs, GET /runs/<id>,
     POST /runs/<id>/save, POST /runs/<id>/approve, DELETE /runs/<id>) through deps.api and to the screen through deps.ui.
   - createDomUi(doc, handlers): the DOM for the card, the save bar and the banners.

   Rules it keeps:
   - The list never carries the large fields (result, analytics); a run's result is fetched only when it is opened.
   - The default view is the approved run. Unload returns to it (or to an empty view when there is none).
   - A new run or an edit only ever changes a draft or saved run; the approved run is never touched from here.
   - The approved run cannot be deleted (the button is not offered and the API answers 409 as well).
   ============================================================ */
(function (root) {
  'use strict';

  var STATUS_LABEL = { draft: 'Draft', saved: 'Saved', approved: 'Approved' };

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* "15 Oct 2026 5:30 PM" */
  function formatRunTime(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    var date = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    var time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(/\u202f/g, ' ');
    return date + ' ' + time;
  }

  /* default label: "<Dept> <Semester> <date time>" */
  function defaultLabel(dept, semester, when) {
    return [dept, semester, formatRunTime(when)].filter(Boolean).join(' ');
  }

  function coverageText(run) {
    var c = run && run.coverage;
    var s = c && (c.summary || c);
    if (!s || s.total === undefined || s.total === null) return '\u2014';
    var gaps = c.errors && c.errors.length ? ' (' + c.errors.length + ' gaps)' : '';
    return (s.assigned || 0) + ' of ' + s.total + gaps;
  }

  function balanceText(run) {
    var b = run && run.metrics && run.metrics.balance_score;
    return typeof b === 'number' ? Math.round(b) + '%' : '\u2014';
  }

  function bannerText(run) {
    if (run.fresh) return 'Viewing the run you just made (' + STATUS_LABEL[run.status] + '), not the approved schedule.';
    return 'Viewing saved run from ' + formatRunTime(run.created_at) + ', not the approved schedule.';
  }

  /* ---------------------------------------------------------------- controller */
  function createController(deps) {
    var api = deps.api, ui = deps.ui;
    var st = { runs: [], approvedId: null, viewing: null, error: '', names: {} };

    function runnerName(r) {
      if (!r.created_by) return 'Unknown';
      if (deps.userId && r.created_by === deps.userId) return 'You';
      return st.names[r.created_by] || 'Chairperson';
    }

    function rowModel(r) {
      var onScreenId = st.viewing ? st.viewing.id : st.approvedId;
      var viewingThis = !!st.viewing && st.viewing.id === r.id;
      return {
        id: r.id, status: r.status, statusLabel: STATUS_LABEL[r.status] || r.status,
        label: r.label || (r.semester ? r.semester + ' run' : 'Run'),
        when: formatRunTime(r.created_at), who: runnerName(r),
        coverage: coverageText(r), balance: balanceText(r),
        onScreen: r.id === onScreenId, viewingThis: viewingThis,
        canLoad: r.id !== onScreenId, canUnload: viewingThis,
        canApprove: r.status !== 'approved', canDelete: r.status !== 'approved'
      };
    }

    function paint() {
      ui.renderList({ rows: st.runs.map(rowModel), count: st.runs.length, message: st.error });
      ui.showBanner(st.viewing ? { text: bannerText(st.viewing) } : null);
      var v = st.viewing;
      ui.showSaveBar(v && v.status === 'draft'
        ? { label: defaultLabel(deps.dept, deps.semester ? deps.semester() : '', deps.now ? deps.now() : new Date()) } : null);
    }

    async function refresh() {
      try {
        var d = await api('/runs?dept=' + encodeURIComponent(deps.dept));
        st.runs = d.runs || [];
        st.error = '';
        if (deps.lookupNames) {
          var missing = st.runs.map(function (r) { return r.created_by; })
            .filter(function (id, i, a) { return id && id !== deps.userId && !st.names[id] && a.indexOf(id) === i; });
          if (missing.length) Object.assign(st.names, await deps.lookupNames(missing).catch(function () { return {}; }));
        }
      } catch (e) {
        st.runs = [];
        st.error = e && e.status === 503 ? 'Saved runs need the database, which is not available right now.' : 'Could not load the saved runs.';
      }
      var ap = st.runs.filter(function (r) { return r.status === 'approved'; })[0];
      st.approvedId = ap ? ap.id : null;
      paint();
    }

    async function showApproved() {
      st.viewing = null;
      if (st.approvedId) {
        try {
          var d = await api('/runs/' + st.approvedId);
          ui.applyRun(d.run);
        } catch (e) {
          ui.applyRun(null);
          ui.toast('Could not load the approved schedule.', 'error');
        }
      } else {
        ui.applyRun(null);
      }
      paint();
    }

    async function init() { await refresh(); await showApproved(); }

    async function load(id) {
      try {
        var d = await api('/runs/' + id);
        var run = d.run;
        ui.applyRun(run);
        st.viewing = run.status === 'approved' ? null
          : { id: run.id, status: run.status, created_at: run.created_at, label: run.label, fresh: false };
        paint();
        return true;
      } catch (e) {
        ui.toast(e && e.message ? e.message : 'Could not open that run.', 'error');
        return false;
      }
    }

    async function unload() { await showApproved(); }

    /* a run that has just finished is a draft on screen, never the approved schedule */
    async function noteFreshRun(id) {
      st.viewing = { id: id, status: 'draft', created_at: (deps.now ? deps.now() : new Date()).toISOString(), label: null, fresh: true };
      paint();
      await refresh();
    }

    async function save(label) {
      var v = st.viewing;
      if (!v || v.status === 'approved') return false;
      var text = String(label || '').trim() || defaultLabel(deps.dept, deps.semester ? deps.semester() : '', deps.now ? deps.now() : new Date());
      try {
        await api('/runs/' + v.id + '/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ label: text }) });
        v.status = 'saved';
        ui.toast('Run saved.', 'success');
        await refresh();
        return true;
      } catch (e) {
        ui.toast(e && e.message ? e.message : 'Could not save the run.', 'error');
        return false;
      }
    }

    async function approve(id) {
      var r = st.runs.filter(function (x) { return x.id === id; })[0];
      if (!r || r.status === 'approved') return false;
      var name = r.label || 'this run';
      if (!ui.confirm('Approve "' + name + '"? It becomes the schedule faculty see, and the current approved run becomes Saved.')) return false;
      try {
        await api('/runs/' + id + '/approve', { method: 'POST' });
      } catch (e) {
        ui.toast(e && e.message ? e.message : 'Could not approve the run.', 'error');
        return false;
      }
      ui.toast('Run approved.', 'success');
      await refresh();
      if (st.viewing && st.viewing.id === id) { st.viewing = null; paint(); }          // the run on screen is now the approved one
      else if (!st.viewing) await showApproved();                                       // the default view follows the new approved run
      return true;
    }

    async function remove(id) {
      var r = st.runs.filter(function (x) { return x.id === id; })[0];
      if (!r) return false;
      if (r.status === 'approved') {
        ui.toast('An approved run cannot be deleted. Approve another run first.', 'info');
        return false;
      }
      if (!ui.confirm('Delete "' + (r.label || 'this run') + '"? This cannot be undone.')) return false;
      if (st.viewing && st.viewing.id === id) await showApproved();                     // leave the run before it disappears
      try {
        await api('/runs/' + id, { method: 'DELETE' });
      } catch (e) {
        ui.toast(e && e.message ? e.message : 'Could not delete the run.', 'error');
        return false;
      }
      ui.toast('Run deleted.', 'info');
      await refresh();
      return true;
    }

    return {
      init: init, refresh: refresh, load: load, unload: unload, save: save, approve: approve, remove: remove,
      noteFreshRun: noteFreshRun, showApproved: showApproved,
      viewing: function () { return st.viewing; },
      approvedId: function () { return st.approvedId; },
      /* the approved schedule is frozen: edits are only allowed on a draft or saved run (or on an unsaved screen) */
      editsBlocked: function () { return !st.viewing && !!st.approvedId; },
      onScreenRunId: function () { return st.viewing ? st.viewing.id : st.approvedId; },
      runs: function () { return st.runs.slice(); }
    };
  }

  /* ---------------------------------------------------------------- DOM */
  function createDomUi(doc, handlers) {
    var ctl = null;
    var $ = function (id) { return doc.getElementById(id); };

    function bannerTargets() {
      var list = [];
      ['.workload-result-card', '#panel-dashboard', '#reportsPanel'].forEach(function (sel) {
        var el = doc.querySelector(sel);
        if (el) list.push(el);
      });
      return list;
    }

    function ensureBanner(host) {
      var b = host.querySelector(':scope > .run-banner');
      if (b) return b;
      b = doc.createElement('div');
      b.className = 'run-banner hidden';
      b.setAttribute('role', 'status');
      b.innerHTML = '<span class="run-banner-text"></span><button type="button" class="btn btn-outline run-banner-unload">Unload</button>';
      b.querySelector('button').addEventListener('click', function () { if (ctl) ctl.unload(); });
      var header = host.querySelector(':scope > .page-header');
      if (header && header.nextSibling) host.insertBefore(b, header.nextSibling);
      else host.insertBefore(b, host.firstChild);
      return b;
    }

    var ui = {
      confirm: handlers.confirm, toast: handlers.toast, applyRun: handlers.applyRun,

      renderList: function (m) {
        var body = $('savedRunsBody');
        if (!body) return;
        var empty = $('savedRunsEmpty');
        $('savedRunsCount').textContent = m.count === 1 ? '1 run' : m.count + ' runs';
        if (empty) {
          empty.hidden = m.count > 0 && !m.message;
          empty.textContent = m.message || 'No saved runs yet. Run Optimization, then use "Save this run".';
        }
        $('savedRunsTable').hidden = m.count === 0;
        body.innerHTML = m.rows.map(function (r) {
          var acts = [];
          if (r.canLoad) acts.push('<button type="button" class="btn btn-outline" data-act="load" data-id="' + esc(r.id) + '">Load</button>');
          if (r.canUnload) acts.push('<button type="button" class="btn btn-outline" data-act="unload" data-id="' + esc(r.id) + '">Unload</button>');
          if (r.canApprove) acts.push('<button type="button" class="btn" data-act="approve" data-id="' + esc(r.id) + '">Approve</button>');
          if (r.canDelete) acts.push('<button type="button" class="btn btn-outline run-delete" data-act="remove" data-id="' + esc(r.id) + '">Delete</button>');
          return '<tr data-run-id="' + esc(r.id) + '"' + (r.onScreen ? ' class="run-on-screen"' : '') + '>' +
            '<td class="run-label">' + esc(r.label) + '</td><td>' + esc(r.when) + '</td><td>' + esc(r.who) + '</td>' +
            '<td>' + esc(r.coverage) + '</td><td>' + esc(r.balance) + '</td>' +
            '<td><span class="run-badge run-' + esc(r.status) + '">' + esc(r.statusLabel) + '</span></td>' +
            '<td><div class="run-actions">' + (acts.length ? acts.join('') : '<span class="run-none">Locked</span>') + '</div></td></tr>';
        }).join('');
      },

      showBanner: function (m) {
        bannerTargets().forEach(function (host) {
          var b = ensureBanner(host);
          b.classList.toggle('hidden', !m);
          if (m) b.querySelector('.run-banner-text').textContent = m.text;
        });
      },

      showSaveBar: function (m) {
        var bar = $('saveRunBar');
        if (!bar) return;
        bar.classList.toggle('hidden', !m);
        if (m) { var input = $('saveRunLabel'); if (!input.dataset.touched || !input.value) { input.value = m.label; input.dataset.touched = ''; } }
      },

      bind: function (controller) {
        ctl = controller;
        var table = $('savedRunsTable');
        if (table) table.addEventListener('click', function (e) {
          var btn = e.target.closest ? e.target.closest('button[data-act]') : null;
          if (!btn || !ctl[btn.dataset.act]) return;
          btn.disabled = true;
          Promise.resolve(ctl[btn.dataset.act](btn.dataset.id)).then(function () { btn.disabled = false; }, function () { btn.disabled = false; });
        });
        var input = $('saveRunLabel');
        if (input) input.addEventListener('input', function () { input.dataset.touched = '1'; });
        var save = $('saveRunBtn');
        if (save) save.addEventListener('click', function () {
          save.disabled = true;
          Promise.resolve(ctl.save(input.value)).then(function (ok) { save.disabled = false; if (ok) input.dataset.touched = ''; }, function () { save.disabled = false; });
        });
      }
    };
    return ui;
  }

  var api = { createController: createController, createDomUi: createDomUi, formatRunTime: formatRunTime,
              defaultLabel: defaultLabel, coverageText: coverageText, balanceText: balanceText, bannerText: bannerText, esc: esc };
  root.AtlasSavedRuns = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);