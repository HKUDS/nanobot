/// <reference lib="webworker" />

const CACHE_NAME = "nanobot-webui-v1";
const STATIC_CACHE = [
  "/",
];

// Install: cache critical static assets.
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_CACHE);
    })
  );
  // Activate immediately without waiting for page refresh.
  self.skipWaiting();
});

// Activate: clean up old caches.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

// Fetch: network-first, fallback to cache.
self.addEventListener("fetch", (event) => {
  // Skip non-GET and browser extension requests.
  if (event.request.method !== "GET") return;

  // Skip API and WebSocket upgrade paths.
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful responses for the same origin.
        if (
          response.status === 200 &&
          new URL(event.request.url).origin === self.location.origin
        ) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, clone);
          });
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});

// Helper: parse push payload safely.
function parsePushPayload(data) {
  try {
    if (data instanceof ArrayBuffer || data instanceof Uint8Array) {
      const decoder = new TextDecoder();
      return JSON.parse(decoder.decode(data));
    }
    if (typeof data === "string") {
      return JSON.parse(data);
    }
    if (data.text) {
      return data.text().then((t) => JSON.parse(t));
    }
    return { title: "nanobot", body: "新消息" };
  } catch {
    return { title: "nanobot", body: "新消息" };
  }
}

// Push event: show notification.
self.addEventListener("push", (event) => {
  let payload = { title: "nanobot", body: "新消息", url: "" };

  if (event.data) {
    const parsed = parsePushPayload(event.data);
    if (parsed) {
      payload = { ...payload, ...parsed };
    }
  }

  const options = {
    body: payload.body,
    icon: "/brand/nanobot_icon_192.png",
    badge: "/brand/nanobot_icon_192.png",
    tag: "nanobot-notification",
    data: {
      url: payload.url || "/",
    },
    vibrate: [200, 100, 200],
    requireInteraction: true,
  };

  event.waitUntil(self.registration.showNotification(payload.title, options));
});

// Notification click: focus or open the app window.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const url = event.notification.data?.url || "/";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windowClients) => {
        // Focus an existing tab if it exists.
        for (const client of windowClients) {
          if (client.url && new URL(client.url).origin === self.location.origin) {
            return client.focus();
          }
        }
        // Otherwise open a new window.
        return self.clients.openWindow(url);
      })
  );
});
