/* 404 / offline page: no inline script (Content-Security-Policy) */
window.__atlasOfflineFallback = !/404\.html$/.test(location.pathname);
document.addEventListener('DOMContentLoaded', function () {
  var b = document.getElementById('nfBack');
  if (b) b.addEventListener('click', function () { history.length > 1 ? history.back() : location.assign('/'); });
});