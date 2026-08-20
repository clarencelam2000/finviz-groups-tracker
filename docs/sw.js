// Bump CACHE on every release (see CLAUDE.md § Automation release-bump checklist):
// prepend a releases.json entry + update its `current` + bump CACHE here — all three
// together, so the new shell + releases.json aren't served from a stale cache.
const CACHE = 'finviz-v77';

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
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
      .then(() => self.clients.matchAll({ includeUncontrolled: true }))
      // TODO(SW-UPDATE-UX): if auto-reload proves disruptive (e.g. user mid-session),
      // switch to Option 2: post { type: 'SW_UPDATED' } here and show a "New version —
      // tap to refresh" toast in index.html instead of reloading automatically.
      .then(clients => clients.forEach(c => c.postMessage({ type: 'SW_RELOAD' })))
  );
});

// WS5-4b — data-less exit-signal push (no RFC 8291 payload; see worker-positions/src/push.js). The
// notification is intentionally generic — the Positions confirmation strip names WHICH position.
self.addEventListener('push', event => {
  event.waitUntil(
    self.registration.showNotification('Exit signal', {
      body: "A position hit an exit signal — open the app to confirm your fill or tap 'still holding'.",
      tag: 'finviz-exit',
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const root = '/finviz-groups-tracker/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      for (const c of clients) {
        if (c.url.includes('/finviz-groups-tracker') && 'focus' in c) {
          c.focus();
          c.postMessage({ type: 'OPEN_POSITIONS' });
          return undefined;
        }
      }
      return self.clients.openWindow(root + '#positions');
    })
  );
});

self.addEventListener('fetch', e => {
  // Always fetch CSVs fresh from network — stale data defeats the purpose
  if (e.request.url.includes('raw.githubusercontent.com')) return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
