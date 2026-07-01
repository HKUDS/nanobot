const CACHE_NAME = "nanobot-static-v1";
const PRECACHE = ["/", "/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Only handle same-origin GET requests
  if (request.method !== "GET") return;
  if (new URL(request.url).origin !== self.location.origin) return;

  const url = new URL(request.url);
  const path = url.pathname;

  // Never cache API, auth, WebSocket, or HMR paths
  if (
    path.startsWith("/api") ||
    path.startsWith("/auth") ||
    path.startsWith("/__nanobot")
  ) {
    return;
  }

  // Static assets: cache-first (immutable by gateway)
  if (/\.(js|css|png|webp|ico|svg|woff2?|ttf|eot)$/.test(path)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // Everything else: network-first (index.html, manifest, etc.)
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((c) => c.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
