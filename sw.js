/* ATLAS PSU - sw.js
   Only job: when a page cannot be fetched (no connection), show the offline / 404 page instead of the browser's
   dinosaur. Pages and data are never cached: the network always wins. */
const CACHE = 'atlas-offline-v1';
const FILES = ['/404.html', '/assets/css/main-style.css', '/assets/js/app-core.js', '/assets/images/logo.svg', '/assets/images/favicon.svg'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => Promise.all(FILES.map(f => c.add(f).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match('/404.html').then(r => r || Response.error())));
  } else if (url.origin === self.location.origin && FILES.includes(url.pathname)) {
    e.respondWith(fetch(req).then(res => { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); return res; }).catch(() => caches.match(req)));
  }
});