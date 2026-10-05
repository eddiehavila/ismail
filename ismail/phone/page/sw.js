// The page installs as an app; only its shell is cached. The stream, the api and offered files always go to the server.
const SHELL = 'ismail-phone-v1';
self.addEventListener('install', (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['./', 'app.js', 'icon.svg', 'manifest.webmanifest']))); self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || /\/(api|files|stream\.mp3|health)/.test(u.pathname)) return;
  e.respondWith(fetch(e.request).then((r) => { const c = r.clone(); caches.open(SHELL).then((s) => s.put(e.request, c)); return r; })
    .catch(() => caches.match(e.request)));
});
