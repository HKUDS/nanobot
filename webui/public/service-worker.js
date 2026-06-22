const CACHE_NAME = "nanobot-v1";
const ASSETS_TO_CACHE = [
  "/",
  "/brand/nanobot_icon_192.png",
  "/brand/nanobot_icon_512.png",
  "/brand/nanobot_apple_touch.png",
  "/manifest.json",
];

// Install: cache app shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS_TO_CACHE))
      .then(() => self.skipWaiting()),
  );
});

// Activate: clean old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name !== CACHE_NAME)
            .map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

// Fetch: network-first, fallback to cache
self.addEventListener("fetch", (event) => {
  // Skip non-GET and WebSocket connections
  if (
    event.request.method !== "GET" ||
    event.request.url.startsWith("ws://") ||
    event.request.url.startsWith("wss://")
  ) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful responses
        if (response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request)),
  );
});
