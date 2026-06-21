// Bump CACHE on every release (see CLAUDE.md § Automation release-bump checklist):
// prepend a releases.json entry + update its `current` + bump CACHE here — all three
// together, so the new shell + releases.json aren't served from a stale cache.
const CACHE = 'finviz-v19';

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll([
      '/finviz-groups-tracker/',
      '/finviz-groups-tracker/manifest.json',
      '/finviz-groups-tracker/releases.json',
    ]))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Always fetch CSVs fresh from network — stale data defeats the purpose
  if (e.request.url.includes('raw.githubusercontent.com')) return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
