/* ============================================================
   ATLAS PSU - shared UI behaviour (chairperson + faculty pages)
   - top bar title and back button, bottom tab bar (mobile navigation)
   - draggable scroll handle (touch devices)
   - zoomable schedule viewer
   ============================================================ */
(function () {
  'use strict';

  const syncers = [];   // re-run after the start page is applied

  /* ---------- Bottom tab bar (mobile) ---------- */
  function initBottomNav() {
    const items = document.querySelectorAll('.bn-item[data-go]');
    if (!items.length) return;

    function syncActive() {
      const panels = Array.from(document.querySelectorAll('.panel'));
      const index = panels.findIndex(p => p.classList.contains('active'));
      items.forEach(item => item.classList.toggle('active', Number(item.dataset.go) === index));
    }

    syncers.push(syncActive);
    items.forEach(item => item.addEventListener('click', () => {
      window.switchPanel(Number(item.dataset.go));
      setTimeout(syncActive, 60);
    }));
    document.querySelectorAll('.nav-item[data-panel]').forEach(item =>
      item.addEventListener('click', () => setTimeout(syncActive, 60)));
    syncActive();
  }

  /* ---------- Top bar: title and back button (mobile) ---------- */
  function initTopBar() {
    const back = document.getElementById('navBack');
    const title = document.getElementById('navTitle');
    if (!back || !title) return;

    function sync() {
      const panels = Array.from(document.querySelectorAll('.panel'));
      const index = panels.findIndex(p => p.classList.contains('active'));
      const active = panels[index];
      title.textContent = active ? (active.dataset.title || active.getAttribute('aria-label') || '') : '';
      back.classList.toggle('is-hidden', index <= 0);
    }

    syncers.push(sync);
    back.addEventListener('click', () => window.switchPanel(0));
    document.querySelectorAll('.nav-item[data-panel], .bn-item').forEach(item =>
      item.addEventListener('click', () => setTimeout(sync, 60)));
    sync();
  }

  /* keep the top bar and bottom tab bar in step with the active panel */
  function watchPanels() {
    const main = document.querySelector('main');
    if (!main) return;
    let frame = 0;
    new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(() => { frame = 0; syncers.forEach(sync => sync()); });
    }).observe(main, { attributes: true, subtree: true, attributeFilter: ['class'] });
    syncers.forEach(sync => sync());
  }

  /* ---------- Draggable scroll handle ---------- */
  function initScrollHandle() {
    const handle = document.createElement('div');
    handle.className = 'scroll-handle';
    handle.innerHTML = '<div class="sh-thumb" role="scrollbar" aria-orientation="vertical" aria-label="Scroll page"></div>';
    document.body.appendChild(handle);

    const thumb = handle.firstChild;
    const touchLayout = window.matchMedia('(max-width:768px),(pointer:coarse)');
    let hideTimer = 0;
    let frame = 0;
    let drag = null;

    const activePanel = () => document.querySelector('.panel.active');

    function update() {
      const panel = activePanel();
      if (!panel || !touchLayout.matches) { handle.classList.remove('can'); return; }
      const max = panel.scrollHeight - panel.clientHeight;
      if (max <= 4) { handle.classList.remove('can'); return; }
      handle.classList.add('can');
      const track = handle.clientHeight;
      const size = Math.max(40, track * panel.clientHeight / panel.scrollHeight);
      thumb.style.height = size + 'px';
      thumb.style.top = (panel.scrollTop / max) * (track - size) + 'px';
    }

    function schedule() {
      if (!frame) frame = requestAnimationFrame(() => { frame = 0; update(); });
    }

    function flash() {
      handle.classList.add('on');
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => { if (!drag) handle.classList.remove('on'); }, 1400);
    }

    document.addEventListener('scroll', e => {
      if (e.target.classList && e.target.classList.contains('panel')) { schedule(); flash(); }
    }, true);
    window.addEventListener('resize', schedule);

    const main = document.querySelector('main');
    if (main) {
      new MutationObserver(schedule).observe(main, {
        childList: true, subtree: true, attributes: true, attributeFilter: ['class']
      });
    }

    thumb.addEventListener('pointerdown', e => {
      const panel = activePanel();
      if (!panel) return;
      e.preventDefault();
      thumb.setPointerCapture(e.pointerId);
      drag = { y: e.clientY, top: panel.scrollTop };
      handle.classList.add('drag', 'on');
    });
    thumb.addEventListener('pointermove', e => {
      if (!drag) return;
      const panel = activePanel();
      if (!panel) return;
      const max = panel.scrollHeight - panel.clientHeight;
      panel.scrollTop = drag.top + (e.clientY - drag.y) * max / Math.max(1, handle.clientHeight - thumb.offsetHeight);
    });
    function endDrag() { drag = null; handle.classList.remove('drag'); flash(); }
    thumb.addEventListener('pointerup', endDrag);
    thumb.addEventListener('pointercancel', endDrag);

    schedule();
  }

  /* ---------- Zoomable schedule viewer ----------
     Any element with data-viewer-src="<selector>" opens the HTML of that
     element in a full-screen viewer (pinch / buttons / Ctrl+wheel to zoom). */
  function initViewer() {
    const triggers = document.querySelectorAll('[data-viewer-src]');
    if (!triggers.length) return;

    const viewer = document.createElement('div');
    viewer.className = 'tt-viewer';
    viewer.hidden = true;
    viewer.setAttribute('role', 'dialog');
    viewer.setAttribute('aria-modal', 'true');
    viewer.setAttribute('aria-label', 'Schedule viewer');
    viewer.innerHTML = `
      <div class="tt-viewer-bar">
        <strong id="ttViewerTitle">Schedule</strong>
        <div class="tt-viewer-ctrls">
          <button type="button" id="ttZoomOut" aria-label="Zoom out">&minus;</button>
          <span id="ttZoomLbl">100%</span>
          <button type="button" id="ttZoomIn" aria-label="Zoom in">+</button>
          <button type="button" id="ttFit" aria-label="Fit to screen">Fit</button>
          <button type="button" id="ttClose" aria-label="Close schedule viewer">&#10005;</button>
        </div>
        <p class="tt-viewer-hint">Pinch to zoom, drag to move.</p>
      </div>
      <div class="tt-viewer-body" id="ttViewerBody">
        <div class="tt-sizer" id="ttSizer"><div class="tt-stage" id="ttStage"></div></div>
      </div>`;
    document.body.appendChild(viewer);

    const $ = id => document.getElementById(id);
    const body = $('ttViewerBody');
    const sizer = $('ttSizer');
    const stage = $('ttStage');
    const label = $('ttZoomLbl');
    const MIN = 0.25;
    const MAX = 3;
    let zoom = 1;
    let width = 700;
    let height = 400;
    let opener = null;

    function applyZoom(next, cx, cy) {
      next = Math.min(MAX, Math.max(MIN, next));
      const px = (body.scrollLeft + cx) / zoom;
      const py = (body.scrollTop + cy) / zoom;
      zoom = next;
      stage.style.transform = 'scale(' + zoom + ')';
      sizer.style.width = width * zoom + 'px';
      sizer.style.height = height * zoom + 'px';
      body.scrollLeft = px * zoom - cx;
      body.scrollTop = py * zoom - cy;
      label.textContent = Math.round(zoom * 100) + '%';
    }
    const zoomBy = factor => applyZoom(zoom * factor, body.clientWidth / 2, body.clientHeight / 2);
    function fit() {
      applyZoom((body.clientWidth - 16) / width, 0, 0);
      body.scrollLeft = 0;
      body.scrollTop = 0;
    }

    function open(trigger) {
      const source = document.querySelector(trigger.dataset.viewerSrc);
      if (!source) return;
      opener = trigger;
      $('ttViewerTitle').textContent = trigger.dataset.viewerTitle || 'Schedule';
      stage.innerHTML = source.innerHTML;
      stage.style.transform = 'none';
      viewer.hidden = false;
      width = stage.offsetWidth || 700;
      height = stage.offsetHeight || 400;
      zoom = 1;
      fit();
      $('ttClose').focus();
    }
    function close() {
      viewer.hidden = true;
      if (opener) opener.focus();
    }

    triggers.forEach(t => t.addEventListener('click', () => open(t)));
    $('ttClose').addEventListener('click', close);
    $('ttZoomIn').addEventListener('click', () => zoomBy(1.25));
    $('ttZoomOut').addEventListener('click', () => zoomBy(0.8));
    $('ttFit').addEventListener('click', fit);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !viewer.hidden) close(); });

    body.addEventListener('wheel', e => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const r = body.getBoundingClientRect();
      applyZoom(zoom * (e.deltaY < 0 ? 1.1 : 0.9), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });

    let startDist = 0;
    let startZoom = 1;
    const dist = t => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
    body.addEventListener('touchstart', e => {
      if (e.touches.length === 2) { startDist = dist(e.touches); startZoom = zoom; }
    }, { passive: true });
    body.addEventListener('touchmove', e => {
      if (e.touches.length !== 2 || !startDist) return;
      e.preventDefault();
      const r = body.getBoundingClientRect();
      const cx = (e.touches[0].clientX + e.touches[1].clientX) / 2 - r.left;
      const cy = (e.touches[0].clientY + e.touches[1].clientY) / 2 - r.top;
      applyZoom(startZoom * dist(e.touches) / startDist, cx, cy);
    }, { passive: false });
    body.addEventListener('touchend', e => { if (e.touches.length < 2) startDist = 0; });
  }

  initBottomNav();
  initTopBar();
  watchPanels();
  initScrollHandle();
  initViewer();
})();