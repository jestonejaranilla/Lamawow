/* ============================================================
   ATLAS PSU - shared UI behaviour (chairperson + faculty pages)
   - top bar title and back button, bottom tab bar (mobile navigation)
   - draggable scroll handle (touch devices)
   - zoomable schedule viewer
   ============================================================ */
(function () {
  'use strict';

  const syncers = [];   // re-run after the start page is applied
  let restoreIdx = null, acted = false;   // returning from the Menu: reopen a section with no slide until the user acts
  let noSlide = false;  // set while a finished swipe switches section (the swipe already animated)

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
      back.classList.add('is-hidden');                       // the top bar has no back button; the phone back button navigates
      const more = document.querySelector('.nav-more');
      if (more) more.classList.toggle('is-hidden', index !== panels.length - 1);   // Menu only on the last section (Rooms)
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


  /* ---------- Mobile gestures: swipe between sections + pull down to refresh ----------
     Swipe left or right: the neighbouring section follows your finger, like Instagram or Facebook.
     Pull down at the top of a section: release to refresh (the page reloads on the same section). */
  function initMobileGestures() {
    const wrapper = document.querySelector('.panels-wrapper');
    const container = wrapper && wrapper.querySelector('.panels-container');
    if (!container || !('ontouchstart' in window)) return;

    const mobile = window.matchMedia('(max-width:900px)');
    const BLOCK = 'input, select, textarea, [contenteditable], [role="dialog"], .modal-overlay, .tt-viewer, [data-no-swipe]';
    const PULL_AT = 50;      // pixels shown before release triggers a refresh
    const PULL_MAX = 80;
    const SAVE_KEY = 'atlasRefreshPanel';
    const reduce = () => document.documentElement.getAttribute('data-motion') === 'reduce';
    const ease = 'cubic-bezier(0.22, 0.8, 0.3, 1)';
    const panels = () => Array.from(container.querySelectorAll('.panel'));
    const activeIndex = () => panels().findIndex(p => p.classList.contains('active'));

    /* pull indicator */
    const ptr = document.createElement('div');
    ptr.className = 'ptr';
    ptr.setAttribute('aria-hidden', 'true');
    ptr.innerHTML = '<span class="ic ic-refresh"></span>';
    document.body.appendChild(ptr);

    function setPull(offset, instant) {
      container.style.transition = instant || reduce() ? 'none' : 'transform 0.25s ' + ease;
      container.style.transform = offset ? 'translate3d(0,' + offset + 'px,0)' : '';
      const progress = Math.min(1, offset / PULL_AT);
      ptr.style.transition = instant || reduce() ? 'none' : 'opacity 0.2s, transform 0.25s ' + ease;
      ptr.style.opacity = progress;
      ptr.style.transform = 'translate3d(-50%,' + Math.max(0, offset / 2 - 18) + 'px,0) scale(' + (0.6 + 0.4 * progress) + ')';
      ptr.firstChild.style.transform = 'rotate(' + Math.round(progress * 270) + 'deg)';
    }

    function refresh() {
      g = null;
      busy = true;
      ptr.classList.add('spin');
      setPull(PULL_AT, false);
      try { sessionStorage.setItem(SAVE_KEY, String(activeIndex())); sessionStorage.setItem('atlasRefreshed', '1'); } catch { /* storage unavailable */ }
      setTimeout(() => location.reload(), reduce() ? 0 : 900);
    }

    /* small "Refreshed" confirmation after the page came back */
    try {
      if (sessionStorage.getItem('atlasRefreshed') === '1') {
        sessionStorage.removeItem('atlasRefreshed');
        const done = document.createElement('div');
        done.className = 'ptr-done';
        done.setAttribute('role', 'status');
        done.textContent = 'Refreshed';
        window.addEventListener('load', () => {
          document.body.appendChild(done);
          requestAnimationFrame(() => done.classList.add('on'));
          setTimeout(() => { done.classList.remove('on'); setTimeout(() => done.remove(), 400); }, 1500);
        });
      }
    } catch { /* storage unavailable */ }

    /* come back to the same section after a refresh */
    try {
      const saved = sessionStorage.getItem(SAVE_KEY);
      if (saved !== null) {
        sessionStorage.removeItem(SAVE_KEY);
        const index = Number(saved);
        const go = () => { if (activeIndex() !== index && window.switchPanel) window.switchPanel(index); };
        document.addEventListener('DOMContentLoaded', () => setTimeout(go, 0));
        window.addEventListener('load', go);
      }
    } catch { /* storage unavailable */ }

    /* swipe helpers */
    let g = null;
    let busy = false;
    let sideEl = null;      // the neighbouring panel being dragged in
    let sideDir = 0;
    let sideSaved = '';

    function releaseSide() {
      if (sideEl) { sideEl.style.cssText = sideSaved; sideEl = null; sideDir = 0; }
    }

    function showSide(dir) {
      if (sideDir === dir) return;
      releaseSide();
      const list = panels();
      const next = list[activeIndex() + dir];
      if (!next) return;
      sideEl = next;
      sideDir = dir;
      sideSaved = next.style.cssText;
      next.style.cssText += ';display:block;position:absolute;top:0;left:0;animation:none;will-change:transform;';
    }

    function drag(dx) {
      const active = g.panel;
      const width = container.clientWidth || window.innerWidth;
      const dir = dx < 0 ? 1 : -1;
      showSide(dir);
      const shown = sideEl ? dx : dx * 0.3;     // no neighbour: rubber band
      active.style.transition = 'none';
      active.style.willChange = 'transform';
      active.style.transform = 'translate3d(' + shown + 'px,0,0)';
      if (sideEl) {
        sideEl.style.transition = 'none';
        sideEl.style.transform = 'translate3d(' + (dir * width + dx) + 'px,0,0)';
      }
    }

    function settle(commit, dir) {
      const active = g.panel;
      const width = container.clientWidth || window.innerWidth;
      const side = sideEl;
      const index = activeIndex();
      const t = reduce() ? 'none' : 'transform 0.28s ' + ease;
      busy = true;
      active.style.transition = t;
      active.style.transform = 'translate3d(' + (commit ? -dir * width : 0) + 'px,0,0)';
      if (side) {
        side.style.transition = t;
        side.style.transform = 'translate3d(' + (commit ? 0 : dir * width) + 'px,0,0)';
      }
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        active.style.transition = '';
        active.style.transform = '';
        active.style.willChange = '';
        releaseSide();
        if (commit && side && window.switchPanel) { noSlide = true; window.switchPanel(index + dir); setTimeout(() => { noSlide = false; }, 50); }
        busy = false;
      };
      setTimeout(finish, reduce() ? 0 : 300);
    }

    function inHorizontalScroller(el, stop) {
      for (; el && el !== stop; el = el.parentElement) {
        if (el.scrollWidth > el.clientWidth + 2) {
          const overflow = getComputedStyle(el).overflowX;
          if (overflow === 'auto' || overflow === 'scroll') return true;
        }
      }
      return false;
    }

    wrapper.addEventListener('touchstart', e => {
      if (busy || !mobile.matches || e.touches.length !== 1) { g = null; return; }
      const panel = container.querySelector('.panel.active');
      const target = e.target;
      if (!panel || !panel.contains(target) || target.closest(BLOCK)) { g = null; return; }
      const touch = e.touches[0];
      g = {
        x: touch.clientX, y: touch.clientY, time: Date.now(), panel,
        mode: null, dx: 0, offset: 0,
        atTop: panel.scrollTop <= 0,
        scroller: inHorizontalScroller(target, panel)
      };
    }, { passive: true });

    wrapper.addEventListener('touchmove', e => {
      if (!g || busy) return;
      const touch = e.touches[0];
      const dx = touch.clientX - g.x;
      const dy = touch.clientY - g.y;

      if (!g.mode) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        if (Math.abs(dx) > Math.abs(dy) * 1.2) g.mode = g.scroller ? 'ignore' : 'swipe';
        else g.mode = dy > 0 && g.atTop ? 'pull' : 'ignore';
      }

      if (g.mode === 'swipe') {
        g.dx = dx;
        if (e.cancelable) e.preventDefault();
        drag(dx);
      } else if (g.mode === 'pull') {
        if (g.panel.scrollTop > 0) { g.mode = 'ignore'; setPull(0, false); return; }
        g.offset = Math.max(0, Math.min(PULL_MAX, dy * 0.5));
        if (e.cancelable) e.preventDefault();
        setPull(g.offset, true);
      }
    }, { passive: false });

    function end() {
      if (!g) return;
      const state = g;
      if (state.mode === 'swipe') {
        const elapsed = Math.max(1, Date.now() - state.time);
        const width = container.clientWidth || window.innerWidth;
        const dir = state.dx < 0 ? 1 : -1;
        const fast = Math.abs(state.dx) > 40 && Math.abs(state.dx) / elapsed > 0.35;
        const far = Math.abs(state.dx) > width * 0.28;
        settle(Boolean(sideEl) && (fast || far), dir);
      } else if (state.mode === 'pull') {
        if (state.offset >= PULL_AT) refresh();
        else setPull(0, false);
      }
      g = null;
    }
    wrapper.addEventListener('touchend', end);
    wrapper.addEventListener('touchcancel', end);
  }

  /* ---------- Mobile: slide between sections, and a logical phone back button ---------- */
  const mobile = () => window.matchMedia('(max-width: 900px)').matches;
  const panelList = () => Array.from(document.querySelectorAll('.panel'));
  const panelIndex = () => panelList().findIndex(p => p.classList.contains('active'));
  const reducedMotion = () => document.documentElement.getAttribute('data-motion') === 'reduce' ||
    (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function injectNavCss() {
    const st = document.createElement('style');
    st.id = 'atlasNavCss';
    st.textContent =
      '.nav-more.is-hidden{visibility:hidden;pointer-events:none}' +
      '@media (max-width:900px){' +
      '.top-navbar{transition:transform .32s cubic-bezier(.32,.72,.2,1),background var(--transition-slow),border-color var(--transition-slow),box-shadow .32s ease}' +
      '.panels-wrapper{transition:margin-top .32s cubic-bezier(.32,.72,.2,1),height .32s cubic-bezier(.32,.72,.2,1)}' +
      'html.atlas-nav-away .top-navbar{transform:translate3d(0,-100%,0);box-shadow:none}' +
      'html.atlas-nav-away .panels-wrapper{margin-top:env(safe-area-inset-top,0px);height:calc(100vh - var(--bottom-nav-h) - env(safe-area-inset-top,0px));height:calc(100dvh - var(--bottom-nav-h) - env(safe-area-inset-top,0px))}' +
      '}' +
      '@keyframes atlas-in-r{from{transform:translate3d(100%,0,0)}to{transform:translate3d(0,0,0)}}' +
      '@keyframes atlas-in-l{from{transform:translate3d(-100%,0,0)}to{transform:translate3d(0,0,0)}}' +
      '@keyframes atlas-out-l{from{transform:translate3d(0,0,0)}to{transform:translate3d(-100%,0,0)}}' +
      '@keyframes atlas-out-r{from{transform:translate3d(0,0,0)}to{transform:translate3d(100%,0,0)}}' +
      '@media (max-width:900px){' +
      '.panels-container.atlas-slide{overflow:hidden}' +
      '.panel.atlas-in-r{z-index:2;animation:atlas-in-r .32s cubic-bezier(.32,.72,.2,1) both!important;will-change:transform}' +
      '.panel.atlas-in-l{z-index:2;animation:atlas-in-l .32s cubic-bezier(.32,.72,.2,1) both!important;will-change:transform}' +
      '.panel.atlas-out-l,.panel.atlas-out-r{display:block!important;position:absolute!important;top:0;left:0;right:0;bottom:0;z-index:1;overflow:hidden!important;pointer-events:none;will-change:transform}' +
      '.panel.atlas-out-l{animation:atlas-out-l .32s cubic-bezier(.32,.72,.2,1) both!important}' +
      '.panel.atlas-out-r{animation:atlas-out-r .32s cubic-bezier(.32,.72,.2,1) both!important}' +
      '}';
    document.head.appendChild(st);
  }

  function initSectionSlide() {
    const main = document.querySelector('main');
    const container = document.querySelector('.panels-container');
    if (!main || !container) return;
    const CLS = ['atlas-in-r', 'atlas-in-l', 'atlas-out-l', 'atlas-out-r'];
    let last = panelIndex();
    let timer = 0;
    document.addEventListener('scroll', e => { const t = e.target; if (t && t.classList && t.classList.contains('panel') && !t.classList.contains('atlas-out-l') && !t.classList.contains('atlas-out-r')) t.__atlasTop = t.scrollTop; }, true);
    function clean() {
      clearTimeout(timer);
      panelList().forEach(p => p.classList.remove(...CLS));
      container.classList.remove('atlas-slide');
    }
    new MutationObserver(() => {
      const now = panelIndex();
      if (now === last) return;
      const prev = last;
      last = now;
      if (noSlide || (restoreIdx !== null && !acted)) { noSlide = false; clean(); return; }
      if (prev < 0 || now < 0 || !mobile() || reducedMotion() || document.readyState !== 'complete') return;
      clean();
      const list = panelList(), fwd = now > prev;
      container.classList.add('atlas-slide');
      list[now].classList.add(fwd ? 'atlas-in-r' : 'atlas-in-l');
      list[prev].classList.add(fwd ? 'atlas-out-l' : 'atlas-out-r');
      if (list[prev].__atlasTop) list[prev].scrollTop = list[prev].__atlasTop;
      timer = setTimeout(clean, 380);
    }).observe(main, { attributes: true, subtree: true, attributeFilter: ['class'] });
  }

  /* Phone back button (mobile dashboards): Home exits the app, any other section goes to Home.
     Entry 1 is Home. The first move away from Home pushes one entry; moves between other sections replace it,
     so a single Back always lands on Home. The Menu page is reached from Rooms and Back returns to Rooms. */
  function initPhoneBack() {
    if (!window.history || !history.pushState || !panelList().length) return;
    const stateIdx = () => (history.state && Number.isInteger(history.state.atlasPanel)) ? history.state.atlasPanel : null;
    let busy = false, ready = false;
    ['pointerdown', 'touchstart', 'keydown'].forEach(t => window.addEventListener(t, () => { acted = true; restoreIdx = null; }, true));

    function start() {
      ready = true;
      const saved = stateIdx(), now = panelIndex();
      if (saved !== null && saved !== now && saved < panelList().length && window.switchPanel) {
        restoreIdx = saved;                                // coming back from the Menu: reopen the section it was opened from
        window.switchPanel(saved);                         // (the page may apply its own start section a moment later; keep ours until the user acts)
      } else if (saved === null) {
        history.replaceState({ atlasPanel: 0 }, '');
        if (now > 0) history.pushState({ atlasPanel: now }, '');   // a start page other than Home keeps Home underneath
      }
    }

    function onChange() {
      if (!ready || busy || !mobile()) return;
      const now = panelIndex(), saved = stateIdx();
      if (now < 0 || saved === now) return;
      if (!acted && restoreIdx !== null && now !== restoreIdx && window.switchPanel) { window.switchPanel(restoreIdx); return; }
      if (now > 0 && (saved === 0 || saved === null)) history.pushState({ atlasPanel: now }, '');
      else if (now > 0) history.replaceState({ atlasPanel: now }, '');
      else if (saved > 0) { busy = true; history.back(); setTimeout(() => { busy = false; }, 120); }   // Home by tab: drop the extra entry
    }

    window.addEventListener('popstate', () => {
      if (!mobile()) return;
      const idx = stateIdx() === null ? 0 : stateIdx();
      if (idx !== panelIndex() && window.switchPanel) { busy = true; window.switchPanel(idx); setTimeout(() => { busy = false; }, 120); }
    });
    new MutationObserver(() => onChange()).observe(document.querySelector('main') || document.body,
      { attributes: true, subtree: true, attributeFilter: ['class'] });
    if (document.readyState === 'complete') start(); else window.addEventListener('load', start);
  }

  /* Top bar hides while scrolling down and returns on scroll up (mobile dashboards). The section below grows into the freed space. */
  function initNavAutoHide() {
    const root = document.documentElement;
    if (!document.querySelector('.top-navbar') || !document.querySelector('.panel')) return;
    const last = new WeakMap();
    let lock = 0, idx = panelIndex();
    function setAway(v) {
      if (root.classList.contains('atlas-nav-away') === v) return;
      root.classList.toggle('atlas-nav-away', v);
      lock = performance.now() + 420;                    // the resize this causes must not count as a scroll
    }
    document.addEventListener('scroll', e => {
      const t = e.target;
      if (!mobile() || !t || !t.classList || !t.classList.contains('panel') || !t.classList.contains('active')) return;
      const y = t.scrollTop, prev = last.has(t) ? last.get(t) : y;
      last.set(t, y);
      if (performance.now() < lock) return;
      if (y <= 4) { setAway(false); return; }
      const d = y - prev;
      if (Math.abs(d) < 6) return;
      if (d > 0) { if (y > 56 && t.scrollHeight - t.clientHeight > 160) setAway(true); }
      else setAway(false);
    }, true);
    syncers.push(() => { const now = panelIndex(); if (now !== idx) { idx = now; setAway(false); } });
    window.matchMedia('(max-width: 900px)').addEventListener('change', () => root.classList.remove('atlas-nav-away'));
  }

  injectNavCss();
  initBottomNav();
  initTopBar();
  watchPanels();
  initSectionSlide();
  initNavAutoHide();
  initPhoneBack();
  initScrollHandle();
  initViewer();
  initMobileGestures();
})();