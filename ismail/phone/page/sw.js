// The page installs as an app; only its shell is cached. The stream, the api and offered files always go to the server.
const SHELL = 'ismail-phone-v3';
self.addEventListener('install', (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['./', 'app.js', 'icon.svg', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'cues/start.mp3', 'cues/end.mp3', 'cues/sent.mp3', 'cues/error.mp3']))); self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || /\/(api|files|stream\.mp3|health)/.test(u.pathname)) return;
  e.respondWith(fetch(e.request).then((r) => { const c = r.clone(); caches.open(SHELL).then((s) => s.put(e.request, c)); return r; })
    .catch(() => caches.match(e.request)));
});
// a notification from the DJ opens the page (or brings it forward)
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((cs) => {
    const c = cs.find((x) => 'focus' in x); return c ? c.focus() : self.clients.openWindow('./');
  }));
});
