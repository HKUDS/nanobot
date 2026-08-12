const CACHE_PREFIX = "nanobot-static-";
const CACHE_NAME = `${CACHE_PREFIX}v2`;
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

function responseMayBeCached(response) {
  const cacheControl = response.headers?.get("Cache-Control") ?? "";
  return response.ok && !/(?:^|,)\s*(?:private|no-cache|no-store)\b/i.test(cacheControl);
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
            .filter((k) => k.startsWith(CACHE_PREFIX) && k !== CACHE_NAME)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => pruneStaleEntries())
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Only handle same-origin GET requests. Requests are handed to fetch() as-is
  // (never reconstructed), so their credentials mode is preserved and gateway
  // auth cookies flow through on every path we touch. WebSocket upgrades are
  // never dispatched to a service worker's fetch handler, so the WS endpoint
  // cannot be cached. Unknown HTTP endpoints are passed through below.
  if (request.method !== "GET") return;
  if (new URL(request.url).origin !== self.location.origin) return;

  const url = new URL(request.url);
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
