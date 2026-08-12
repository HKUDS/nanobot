const CACHE_NAME = "nanobot-static-v1";
const ASSET_MANIFEST_PATH = "/asset-manifest.json";
const PRECACHE = ["/", "/manifest.json", ASSET_MANIFEST_PATH];

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
            .filter((k) => k !== CACHE_NAME)
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
  // cannot be cached; the /__nanobot exclusion below still protects its HTTP
  // polling/socket bootstrap endpoints.
  if (request.method !== "GET") return;
  if (new URL(request.url).origin !== self.location.origin) return;

  const url = new URL(request.url);
  const path = url.pathname;

  // Never cache API, auth, WebSocket, HMR, or WebUI endpoint paths. In
  // particular /webui/bootstrap issues fresh gateway credentials on every page
  // load and must never be cached or replayed offline. The /auth prefix covers
  // the default token endpoint; custom token_issue_path values should be kept
  // under one of these prefixes.
  if (
    path.startsWith("/api") ||
    path.startsWith("/auth") ||
    path.startsWith("/__nanobot") ||
    path.startsWith("/webui")
  ) {
    return;
  }

  // Static assets: cache-first. Only files under /assets/ carry content hashes
  // (the gateway serves them immutable); brand icons, the favicon and other
  // un-hashed files can change between releases and stay on the network-first
  // path below so updates reach installed clients.
  if (path.startsWith("/assets/")) {
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

  // Everything else: network-first (index.html, manifest, brand assets, etc.)
  const networkResponse = fetch(request);
  event.waitUntil(
    networkResponse
      .then(async (response) => {
        if (!response.ok) return;
        // Clone before the first await. The original response is also handed
        // to respondWith(), which may lock its body as soon as this callback
        // yields to the event loop.
        const cachedResponse = response.clone();
        const cache = await caches.open(CACHE_NAME);
        await cache.put(request, cachedResponse);
        // Refresh the complete build graph before pruning. A deployment can
        // change index.html without changing sw.js, so this cannot rely only
        // on the manifest cached when the worker was installed.
        if (path === "/") {
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
