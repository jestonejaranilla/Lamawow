/* ============================================================
   ATLAS PSU - display.js
   Pure helpers (no DOM): API base resolution, section / lab group labels,
   NON_CLASSROOM text and the coverage summary. Exposed as window.AtlasDisplay
   (and module.exports for tests).
   ============================================================ */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.AtlasDisplay = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var RENDER_API = 'https://atlas-drsg.onrender.com';
  var LOCAL_API = 'http://localhost:5000';
  var NO_CLASSROOM = 'NON_CLASSROOM';
  var NO_CLASSROOM_TEXT = 'No classroom (professor assigned)';

  /* Where the Flask API is. Three layouts:
     - page opened from this computer or LAN (Flask :5000, VS Code Live Server :5500/:5501, a phone on
       192.168.x.x) -> the same host name on :5000 (keeping the host name avoids the localhost / 127.0.0.1
       and IPv6 mismatch that makes fetch() fail);
     - page served by the Render backend itself (atlas-drsg.onrender.com) -> same origin;
     - anything else (the Render STATIC site atlas-psu.onrender.com, a custom domain) -> the Render backend.
       A static site cannot run the API, so it must never call its own origin.
     config.js API_BASE overrides all of this. */
  function resolveApiBase(loc) {
    var cfg = (typeof window !== 'undefined' && window.ATLAS_CONFIG) || null;
    if (cfg && cfg.API_BASE) return String(cfg.API_BASE).replace(/\/+$/, '');
    var host = (loc && loc.hostname) || '';
    var proto = (loc && loc.protocol) || 'http:';
    var port = String((loc && loc.port) || '');
    var origin = (loc && loc.origin) || (proto + '//' + ((loc && loc.host) || host));
    var onThisNetwork = host === 'localhost' || host === '127.0.0.1' ||
      /^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)/.test(host);
    if (onThisNetwork) return port === '5000' ? origin : proto + '//' + host + ':5000';
    if (host === RENDER_API.replace(/^https?:\/\//, '')) return origin;
    return RENDER_API;
  }

  /* IT1B1, CS2B3, MedB4B2; a split lab group is IT1B1-L1 / IT1B1-L2 (the backend sends it as lab_group). */
  function rowLabel(item) {
    if (!item) return '';
    return item.lab_group || item.section || '';
  }

  function isNoClassroom(item) {
    return !!item && item.class_type === NO_CLASSROOM;
  }

  function classTypeText(item) {
    return isNoClassroom(item) ? 'NO CLASSROOM' : ((item && item.class_type) || 'LECTURE');
  }

  function coverageText(cov) {
    var c = cov || {};
    var total = Number(c.total) || 0;
    var assigned = Number(c.assigned) || 0;
    return assigned + ' of ' + total + ' block-courses assigned';
  }

  function coverageErrorText(e) {
    var who = [e.block, e.course].filter(Boolean).join(' · ');
    var title = e.title ? ' ' + e.title : '';
    return (who + title).trim() + (e.reason ? ': ' + e.reason : '');
  }

  return {
    resolveApiBase: resolveApiBase, rowLabel: rowLabel, isNoClassroom: isNoClassroom,
    classTypeText: classTypeText, coverageText: coverageText, coverageErrorText: coverageErrorText,
    NO_CLASSROOM: NO_CLASSROOM, NO_CLASSROOM_TEXT: NO_CLASSROOM_TEXT,
    RENDER_API: RENDER_API, LOCAL_API: LOCAL_API
  };
}));