/* nanobot service worker — cache-first for static, network-only for API */

const VERSION = 'v10';
const CACHE   = `nanobot-${VERSION}`;
const PRECACHE = [
  '/',
  '/style.css',
  '/app.js',
  '/nanobot_logo.png',
  '/icon.svg',
  '/manifest.json',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

/* Notify all clients to do a full reload (auth session expired). */
function notifyAuthRedirect() {
  self.clients.matchAll({ includeUncontrolled: true, type: 'window' }).then(clients => {
    clients.forEach(c => c.postMessage({ type: 'AUTH_REDIRECT' }));
  });
}

/* Returns true when a response was redirected to a different origin (auth proxy). */
function isAuthRedirect(res) {
  try {
    return res.redirected && new URL(res.url).origin !== self.location.origin;
  } catch { return false; }
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Always go to network for API calls (SSE streams etc.)
  if (url.pathname.startsWith('/api/')) return;

  // Navigation requests: network-first so the auth proxy can intercept.
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).then(res => {
        if (isAuthRedirect(res)) { notifyAuthRedirect(); return res; }
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Static assets: cache-first, but detect auth redirect on network fallback.
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        if (isAuthRedirect(res)) { notifyAuthRedirect(); return res; }
        if (res.ok && url.origin === self.location.origin) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      });
    })
  );
});
