const CACHE_PREFIX = "nanobot-static-";
const CACHE_NAME = `${CACHE_PREFIX}v2`;
const ICON_CACHE_PREFIX = "nanobot-icons-";
const ICON_CACHE_NAME = `${ICON_CACHE_PREFIX}v1`;
const ICON_CACHE_LIMIT = 128;
const NOTICE_CACHE = "nanobot-notification-receipts-v1";
const NOTICE_RECEIPTS = "/__notification_receipts__";
let noticeQueue = Promise.resolve();
let noticeReceipts;
const ASSET_MANIFEST_PATH = "/asset-manifest.json";
const PRECACHE = ["/", "/manifest.json", ASSET_MANIFEST_PATH];
const NETWORK_FIRST_STATIC_PATHS = new Set([
  "/",
  "/manifest.json",
  ASSET_MANIFEST_PATH,
  "/brand/nanobot_apple_touch.png",
  "/brand/nanobot_favicon_32.png",
  "/brand/nanobot_icon_192.png",
  "/brand/nanobot_icon_512.png",
  "/brand/nanobot_icon_maskable.png",
  "/brand/nanobot_mark.svg",
]);

function notificationTarget(value) {
  try {
    const url = new URL(value);
    if (url.origin !== self.location.origin || url.username || url.password || url.search || url.pathname !== "/") return null;
    return /^#\/(?:chat|temporary)\/[^?]+$/.test(url.hash)
      || url.hash === "#/settings?section=appearance"
      || url.hash === "#/settings?section=notifications" ? url.href : null;
  } catch { return null; }
}

async function notifyClient(source, data) {
  const url = notificationTarget(data.url);
  if (!url || typeof data.key !== "string" || data.key.length > 2048 || typeof data.body !== "string" || data.body.length > 300) return "displayFailed";
  // One worker serializes all tabs. Retain bounded receipts even after a
  // notification is dismissed, so a reconnect does not show it again.
  if (!noticeReceipts) {
    try {
      const saved = await (await caches.open(NOTICE_CACHE)).match(NOTICE_RECEIPTS);
      noticeReceipts = saved ? await saved.json() : [];
    } catch { noticeReceipts = []; }
  }
  noticeReceipts = noticeReceipts.filter((item) => item.time > Date.now() - 86_400_000);
  if (noticeReceipts.some((item) => item.key === data.key)) return "skipped";
  const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  const visible = !data.test && windows.some((client) => client.visibilityState === "visible");
  if (!visible) {
    await self.registration.showNotification("nanobot", {
      body: data.body, tag: data.key, icon: "/brand/nanobot_icon_192.png",
      data: { url, clientId: source.id },
    });
  }
  noticeReceipts = [...noticeReceipts, { key: data.key, time: Date.now() }].slice(-256);
  try {
    await (await caches.open(NOTICE_CACHE)).put(NOTICE_RECEIPTS, new Response(JSON.stringify(noticeReceipts)));
  } catch { /* Storage is optional; the worker still deduplicates live tabs. */ }
  return visible ? "skipped" : "submitted";
}

self.addEventListener("message", (event) => {
  if (!event.source?.url || new URL(event.source.url).origin !== self.location.origin) return;
  if (event.data?.type === "nanobot:notification-probe") {
    event.ports[0]?.postMessage(typeof self.registration.showNotification === "function" ? "ready" : "workerUnavailable");
    return;
  }
  if (event.data?.type !== "nanobot:notify") return;
  const work = noticeQueue.then(() => notifyClient(event.source, event.data));
  noticeQueue = work.then(() => undefined, () => undefined);
  event.waitUntil(work.then(
    (result) => event.ports[0]?.postMessage(result),
    () => event.ports[0]?.postMessage("displayFailed"),
  ));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = notificationTarget(event.notification.data?.url);
  if (!url) return;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const source = windows.find((client) => client.id === event.notification.data.clientId);
    const temporary = new URL(url).hash.startsWith("#/temporary/");
    if (source) {
      source.postMessage({ type: "nanobot:notification-click", url });
      await source.focus();
    } else {
      // Other tabs may run older code without the click receiver. Open the
      // destination normally instead of silently focusing an unrelated page.
      // Temporary chats belong to their original connection, not another tab.
      await self.clients.openWindow(temporary ? "/#/new" : url);
    }
  })());
});

function responseMayBeCached(response) {
  const cacheControl = response.headers?.get("Cache-Control") ?? "";
  return response.ok && !/(?:^|,)\s*(?:private|no-cache|no-store)\b/i.test(cacheControl);
}

function isPublicIconRequest(request, url) {
  if (request.destination !== "image" || url.protocol !== "https:") return false;
  const host = url.hostname.toLowerCase();
  const path = url.pathname.toLowerCase();
  if (path.endsWith("/favicon.ico")) return true;
  if (host === "favicon.im") return true;
  if (host === "icons.duckduckgo.com") return path.startsWith("/ip3/");
  return (host === "google.com" || host === "www.google.com")
    && path === "/s2/favicons";
}

function publicIconResponseMayBeCached(response) {
  // Cross-origin <img> requests produce opaque responses, so their status and
  // cache headers cannot be inspected. Only the public icon URLs above reach
  // this path; regular remote images continue to use the browser directly.
  return response.type === "opaque" || responseMayBeCached(response);
}

async function trimIconCache(cache) {
  const keys = await cache.keys();
  const overflow = keys.length - ICON_CACHE_LIMIT;
  if (overflow <= 0) return;
  await Promise.all(keys.slice(0, overflow).map((request) => cache.delete(request)));
}

async function cacheFirstPublicIcon(request) {
  let cache;
  try {
    cache = await caches.open(ICON_CACHE_NAME);
    const cached = await cache.match(request);
    if (cached) return cached;
  } catch {
    return fetch(request);
  }

  const response = await fetch(request);
  if (!publicIconResponseMayBeCached(response)) return response;
  try {
    await cache.put(request, response.clone());
    await trimIconCache(cache);
  } catch {
    // Cache storage is optional; a successful network response still wins.
  }
  return response;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

// Collect same-origin paths referenced by the given HTML document.
function referencedAssetPaths(html) {
  const refs = new Set();
  const re = /(?:src|href)="(\/[^"]*)"/g;
  let match;
  while ((match = re.exec(html))) {
    const url = new URL(match[1], self.location.origin);
    if (url.origin === self.location.origin) refs.add(url.pathname + url.search);
  }
  return refs;
}

// Vite's build manifest contains every emitted entry, static dependency, and
// lazy chunk. The HTML alone only references the entry chunk, so pruning from
// its tags can delete a current build's not-yet-requested dynamic imports.
async function manifestedAssetPaths(cache) {
  const response = await cache.match(ASSET_MANIFEST_PATH);
  if (!response) return new Set();
  try {
    const manifest = await response.json();
    const refs = new Set();
    for (const entry of Object.values(manifest)) {
      if (!entry || typeof entry !== "object") continue;
      for (const file of [entry.file, ...(entry.css ?? []), ...(entry.assets ?? [])]) {
        if (typeof file !== "string") continue;
        const url = new URL(file, self.location.origin);
        if (url.origin === self.location.origin) refs.add(url.pathname + url.search);
      }
    }
    return refs;
  } catch {
    return new Set();
  }
}

async function refreshAssetManifest(cache) {
  const response = await fetch(ASSET_MANIFEST_PATH, { cache: "no-store" });
  if (!response.ok) return false;
  try {
    const manifest = await response.clone().json();
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) return false;
  } catch {
    return false;
  }
  await cache.put(ASSET_MANIFEST_PATH, response);
  return true;
}

// Drop cached entries that the current index.html no longer references.
// CACHE_NAME is stable across deployments, so without this, hashed assets from
// previous builds would pile up in the same cache forever. The cached
// index.html is the latest one this client saw (navigation is network-first
// and overwrites it on every successful visit), so pruning against it keeps
// the offline shell consistent with the last loaded build.
async function pruneStaleEntries() {
  const cache = await caches.open(CACHE_NAME);
  const cachedIndex = await cache.match("/");
  if (!cachedIndex) return;
  const refs = referencedAssetPaths(await cachedIndex.text());
  for (const path of await manifestedAssetPaths(cache)) refs.add(path);
  const keys = await cache.keys();
  await Promise.all(
    keys.map(async (request) => {
      const url = new URL(request.url);
      if (
        url.pathname === "/"
        || url.pathname === "/manifest.json"
        || url.pathname === ASSET_MANIFEST_PATH
      ) return;
      if (refs.has(url.pathname + url.search)) return;
      await cache.delete(request);
    })
  );
}

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) =>
              (k.startsWith(CACHE_PREFIX) && k !== CACHE_NAME)
              || (k.startsWith(ICON_CACHE_PREFIX) && k !== ICON_CACHE_NAME)
            )
            .map((k) => caches.delete(k))
        )
      )
      .then(() => pruneStaleEntries())
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Requests are handed to fetch() as-is (never reconstructed), so their
  // credentials mode is preserved and gateway auth cookies flow through on
  // every path we touch. WebSocket upgrades are never dispatched to a service
  // worker's fetch handler, so the WS endpoint cannot be cached.
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    if (isPublicIconRequest(request, url)) {
      event.respondWith(cacheFirstPublicIcon(request));
    }
    return;
  }

  const path = url.pathname;

  // Static assets: cache-first. Only files under /assets/ carry content hashes
  // (the gateway serves them immutable); brand icons, the favicon and other
  // un-hashed files can change between releases and stay on the network-first
  // path below so updates reach installed clients.
  if (path.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (responseMayBeCached(response)) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // Cache only explicit public files and browser navigations. Dynamic routes
  // are deliberately passed through because token_issue_path and extension
  // endpoints are configurable and cannot be safely identified by prefixes.
  const isNavigation = request.mode === "navigate";
  if (!isNavigation && !NETWORK_FIRST_STATIC_PATHS.has(path)) return;

  // App shell and public files: network-first with an offline fallback.
  const networkResponse = fetch(request);
  event.waitUntil(
    networkResponse
      .then(async (response) => {
        if (!responseMayBeCached(response)) return;
        // Clone before the first await. The original response is also handed
        // to respondWith(), which may lock its body as soon as this callback
        // yields to the event loop.
        const cachedResponse = response.clone();
        const cache = await caches.open(CACHE_NAME);
        await cache.put(isNavigation ? "/" : request, cachedResponse);
        // Refresh the complete build graph before pruning. A deployment can
        // change index.html without changing sw.js, so this cannot rely only
        // on the manifest cached when the worker was installed.
        if (isNavigation || path === "/") {
          if (await refreshAssetManifest(cache)) await pruneStaleEntries();
        }
      })
      .catch(() => undefined)
  );
  event.respondWith(
    networkResponse
      .catch(() => {
        // Offline: serve the app shell for navigations (deep links resolve
        // client-side), the last cached copy for everything else.
        if (request.mode === "navigate") return caches.match("/");
        return caches.match(request);
      })
  );
});
