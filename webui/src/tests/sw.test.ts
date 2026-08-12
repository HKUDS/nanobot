import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

// Vitest runs with the webui/ directory as the working directory.
const SW_SCRIPT = readFileSync(resolve(process.cwd(), "public/sw.js"), "utf8");

const ORIGIN = "https://nanobot.test";
const CACHE_NAME = "nanobot-static-v2";

/** Minimal Cache-compatible in-memory store with SW-style URL normalization. */
class FakeCacheStore {
  entries = new Map<string, Response>();

  private key(input: Request | string): string {
    return new URL(typeof input === "string" ? input : input.url, ORIGIN).href;
  }

  async addAll(urls: string[]): Promise<void> {
    for (const url of urls) {
      this.entries.set(this.key(url), new Response("ok"));
    }
  }

  async match(input: Request | string): Promise<Response | undefined> {
    return this.entries.get(this.key(input));
  }

  async put(input: Request | string, response: Response): Promise<void> {
    this.entries.set(this.key(input), response);
  }

  async delete(input: Request | string): Promise<boolean> {
    return this.entries.delete(this.key(input));
  }

  async keys(): Promise<Request[]> {
    return [...this.entries.keys()].map((url) => new Request(url));
  }
}

interface LoadedSw {
  store: FakeCacheStore;
  deletedCacheNames: string[];
  fetchMock: ReturnType<typeof vi.fn>;
  skipWaitingMock: ReturnType<typeof vi.fn>;
  claimMock: ReturnType<typeof vi.fn>;
  fire: (type: string, event?: Record<string, unknown>) => Promise<void>;
}

function loadSw(): LoadedSw {
  const listeners = new Map<string, Array<(event: Record<string, unknown>) => void>>();
  const skipWaitingMock = vi.fn();
  const claimMock = vi.fn();
  const self = {
    location: { origin: ORIGIN },
    skipWaiting: skipWaitingMock,
    clients: { claim: claimMock },
    addEventListener: (type: string, cb: (event: Record<string, unknown>) => void) => {
      listeners.set(type, [...(listeners.get(type) ?? []), cb]);
    },
  };
  const store = new FakeCacheStore();
  const deletedCacheNames: string[] = [];
  const caches = {
    open: vi.fn(async () => store),
    match: vi.fn((input: Request | string) => store.match(input)),
    keys: vi.fn(async () => [CACHE_NAME, "nanobot-static-v1", "other-app-cache"]),
    delete: vi.fn(async (name: string) => {
      deletedCacheNames.push(name);
      return true;
    }),
  };
  const fetchMock = vi.fn();
  // Execute the plain public/sw.js script inside a controlled scope so the
  // service worker globals (self/caches/fetch) are fully mocked.
  new Function("self", "caches", "fetch", SW_SCRIPT)(self, caches, fetchMock);

  const fire = async (type: string, event: Record<string, unknown> = {}) => {
    for (const cb of listeners.get(type) ?? []) {
      let waitPromise: Promise<unknown> = Promise.resolve();
      const wrapped = {
        ...event,
        waitUntil: (promise: Promise<unknown>) => {
          waitPromise = promise;
        },
      };
      await cb(wrapped);
      await waitPromise;
    }
  };

  return { store, deletedCacheNames, fetchMock, skipWaitingMock, claimMock, fire };
}

function indexHtml(assetPaths: string[]): Response {
  const refs = assetPaths
    .map(
      (path) =>
        `<script type="module" crossorigin src="${path}"></script><link rel="stylesheet" crossorigin href="${path}">`,
    )
    .join("");
  return new Response(`<!doctype html><html><head>${refs}</head></html>`);
}

function fetchEvent(url: string) {
  const respondWith = vi.fn();
  const event = {
    request: new Request(url, { method: "GET" }),
    respondWith,
  };
  return { event, respondWith };
}

describe("service worker", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("precaches the shell and manifest on install", async () => {
    const sw = loadSw();

    await sw.fire("install");

    expect(sw.skipWaitingMock).toHaveBeenCalledTimes(1);
    expect(sw.store.entries.has(`${ORIGIN}/`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/manifest.json`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/asset-manifest.json`)).toBe(true);
  });

  it("removes stale cache names and prunes unreferenced static entries on activate", async () => {
    const sw = loadSw();
    await sw.fire("install");
    // Simulate the latest loaded build: index.html references only v2 assets.
    await sw.store.put(`${ORIGIN}/`, indexHtml(["/assets/index-v2.js", "/assets/index-v2.css"]));
    await sw.store.put(`${ORIGIN}/assets/index-v2.js`, new Response("v2"));
    await sw.store.put(`${ORIGIN}/assets/index-v2.css`, new Response("v2 css"));
    await sw.store.put(`${ORIGIN}/assets/lazy-v2.js`, new Response("lazy v2"));
    await sw.store.put(`${ORIGIN}/assets/index-v1.js`, new Response("v1"));
    await sw.store.put(`${ORIGIN}/assets/index-v1.css`, new Response("v1 css"));
    await sw.store.put(`${ORIGIN}/asset-manifest.json`, new Response(JSON.stringify({
      "src/main.tsx": {
        file: "assets/index-v2.js",
        css: ["assets/index-v2.css"],
      },
      "src/lazy.tsx": { file: "assets/lazy-v2.js", isDynamicEntry: true },
    })));

    await sw.fire("activate");

    expect(sw.deletedCacheNames).toEqual(["nanobot-static-v1"]);
    expect(sw.claimMock).toHaveBeenCalledTimes(1);
    expect(sw.store.entries.has(`${ORIGIN}/`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/manifest.json`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/asset-manifest.json`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/assets/index-v2.js`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/assets/index-v2.css`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/assets/lazy-v2.js`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/assets/index-v1.js`)).toBe(false);
    expect(sw.store.entries.has(`${ORIGIN}/assets/index-v1.css`)).toBe(false);
  });

  it("does not intercept dynamic or unknown endpoint requests", async () => {
    const sw = loadSw();
    const paths = [
      "/api/v1/models",
      "/auth/session",
      "/__nanobot/ws",
      "/__nanobot/socket.io",
      "/api/chat/completions",
      "/webui/bootstrap",
      "/webui/session/list",
      "/custom-token",
      "/mcp-oauth/callback",
    ];

    for (const path of paths) {
      const { respondWith } = fetchEvent(`${ORIGIN}${path}`);
      await sw.fire("fetch", { request: new Request(`${ORIGIN}${path}`) });
      expect(respondWith, path).not.toHaveBeenCalled();
    }
    expect(sw.fetchMock).not.toHaveBeenCalled();
  });

  it("does not intercept non-GET or cross-origin requests", async () => {
    const sw = loadSw();

    const { respondWith: post } = fetchEvent(`${ORIGIN}/api/v1/models`);
    await sw.fire("fetch", {
      request: new Request(`${ORIGIN}/api/v1/models`, { method: "POST" }),
    });
    expect(post).not.toHaveBeenCalled();

    const { respondWith: cross } = fetchEvent("https://other.test/assets/app.js");
    await sw.fire("fetch", {
      request: new Request("https://other.test/assets/app.js"),
    });
    expect(cross).not.toHaveBeenCalled();
    expect(sw.fetchMock).not.toHaveBeenCalled();
  });

  it("serves cached static assets without touching the network", async () => {
    const sw = loadSw();
    const assetUrl = `${ORIGIN}/assets/index-a1b2c3.js`;
    await sw.store.put(assetUrl, new Response("cached js"));

    const { event, respondWith } = fetchEvent(assetUrl);
    await sw.fire("fetch", event);

    const response = (await respondWith.mock.calls[0][0]) as Response;
    expect(response).toBeDefined();
    expect(await response.text()).toBe("cached js");
    expect(sw.fetchMock).not.toHaveBeenCalled();
  });

  it("fetches static assets on miss and caches the response, passing the original request", async () => {
    const sw = loadSw();
    const assetUrl = `${ORIGIN}/assets/index-x9y8z7.js`;
    const originalRequest = new Request(assetUrl);
    sw.fetchMock.mockResolvedValue(new Response("fresh js"));

    const event = { request: originalRequest, respondWith: vi.fn() };
    await sw.fire("fetch", event);

    const response = (await event.respondWith.mock.calls[0][0]) as Response;
    expect(await response.text()).toBe("fresh js");
    // The exact request object is handed to fetch() — credentials mode and
    // other properties are preserved, never reconstructed.
    expect(sw.fetchMock).toHaveBeenCalledWith(originalRequest);
    expect(sw.store.entries.has(assetUrl)).toBe(true);
  });

  it.each(["private", "no-cache", "no-store"])(
    "does not cache a %s response even under the static asset prefix",
    async (cacheControl) => {
      const sw = loadSw();
      const tokenUrl = `${ORIGIN}/assets/custom-token`;
      const originalRequest = new Request(tokenUrl);
      sw.fetchMock.mockResolvedValue(
        new Response('{"token":"short-lived"}', {
          headers: {
            "Cache-Control": cacheControl,
            "Content-Type": "application/json",
          },
        }),
      );

      const event = { request: originalRequest, respondWith: vi.fn() };
      await sw.fire("fetch", event);

      const response = (await event.respondWith.mock.calls[0][0]) as Response;
      expect(await response.json()).toEqual({ token: "short-lived" });
      expect(sw.store.entries.has(tokenUrl)).toBe(false);
    },
  );

  it("keeps un-hashed brand assets on the network-first path", async () => {
    const sw = loadSw();
    const iconUrl = `${ORIGIN}/brand/nanobot_icon_192.png`;
    const originalRequest = new Request(iconUrl);
    sw.fetchMock.mockResolvedValue(new Response("png bytes"));

    const event = { request: originalRequest, respondWith: vi.fn() };
    await sw.fire("fetch", event);

    const response = (await event.respondWith.mock.calls[0][0]) as Response;
    expect(await response.text()).toBe("png bytes");
    // Unlike hashed /assets/ files, brand icons are fetched every load so a
    // future icon swap reaches installed clients.
    expect(sw.fetchMock).toHaveBeenCalledWith(originalRequest);
    expect(sw.store.entries.has(iconUrl)).toBe(true);
  });

  it("clones network responses before yielding their body to the browser", async () => {
    const sw = loadSw();
    const request = new Request(`${ORIGIN}/brand/nanobot_icon_192.png`);
    let browserOwnsBody = false;
    let clonedBeforeBrowser = false;
    const response = {
      ok: true,
      clone: vi.fn(() => {
        clonedBeforeBrowser = !browserOwnsBody;
        return new Response("cached png bytes");
      }),
    } as unknown as Response;
    sw.fetchMock.mockResolvedValue(response);
    const respondWith = vi.fn((pending: Promise<Response>) => {
      void pending.then(() => {
        browserOwnsBody = true;
      });
    });

    await sw.fire("fetch", { request, respondWith });

    expect(clonedBeforeBrowser).toBe(true);
    expect(response.clone).toHaveBeenCalledTimes(1);
  });

  it("serves navigation network-first, prunes on shell refresh, and falls back when offline", async () => {
    const sw = loadSw();
    await sw.store.put(`${ORIGIN}/`, indexHtml(["/assets/index-v2.js"]));
    // Assets from an older build, still referenced by the cached v2 shell.
    await sw.store.put(`${ORIGIN}/assets/index-v2.js`, new Response("v2"));
    await sw.store.put(`${ORIGIN}/assets/index-v1.js`, new Response("v1"));

    // Offline: network rejects, cached shell is returned.
    sw.fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const offlineEvent = {
      request: new Request(`${ORIGIN}/`),
      respondWith: vi.fn(),
    };
    await sw.fire("fetch", offlineEvent);
    const offlineResponse = (await offlineEvent.respondWith.mock.calls[0][0]) as Response;
    expect(await offlineResponse.text()).toContain("assets/index-v2.js");

    // Online: network response wins, refreshes the cached shell, and prunes
    // entries the new index.html no longer references.
    const freshShell = indexHtml(["/assets/index-v3.js"]);
    sw.fetchMock.mockImplementation((input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, ORIGIN);
      if (url.pathname === "/asset-manifest.json") {
        return Promise.resolve(new Response(JSON.stringify({
          "src/main.tsx": { file: "assets/index-v3.js" },
        })));
      }
      return Promise.resolve(freshShell.clone());
    });
    const onlineEvent = {
      request: new Request(`${ORIGIN}/`),
      respondWith: vi.fn(),
    };
    await sw.fire("fetch", onlineEvent);
    const onlineResponse = (await onlineEvent.respondWith.mock.calls[0][0]) as Response;
    expect(await onlineResponse.text()).toContain("assets/index-v3.js");
    // The prune is fire-and-forget; give its microtasks a chance to settle.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(sw.store.entries.has(`${ORIGIN}/`)).toBe(true);
    expect(sw.store.entries.has(`${ORIGIN}/assets/index-v1.js`)).toBe(false);
    expect(sw.store.entries.has(`${ORIGIN}/assets/index-v2.js`)).toBe(false);
  });

  it("serves the cached app shell for offline deep-link navigations", async () => {
    const sw = loadSw();
    await sw.store.put(`${ORIGIN}/`, indexHtml(["/assets/index-v2.js"]));
    sw.fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    // happy-dom's Request ignores `mode: "navigate"` in the constructor;
    // force it so the service worker treats this as a navigation.
    const request = new Request(`${ORIGIN}/settings`);
    Object.defineProperty(request, "mode", { value: "navigate" });
    const event = { request, respondWith: vi.fn() };
    await sw.fire("fetch", event);

    const response = (await event.respondWith.mock.calls[0][0]) as Response;
    expect(await response.text()).toContain("assets/index-v2.js");
  });
});
