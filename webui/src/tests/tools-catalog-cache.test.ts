import { afterEach, describe, expect, it, vi } from "vitest";

import { getToolsCatalog, invalidateToolsCatalog, TOOLS_CATALOG_TTL_MS } from "@/lib/tools-catalog-cache";
import type { CliAppsPayload, McpPresetsPayload } from "@/lib/types";

const cli: CliAppsPayload = { apps: [], installed_count: 0 };
const mcp: McpPresetsPayload = { presets: [], installed_count: 0 };
const response = (payload: unknown) => new Response(JSON.stringify(payload), { headers: { "content-type": "application/json" } });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(res => { resolve = res; });
  return { promise, resolve };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("tools catalog cache", () => {
  it("isolates host clients and changed credentials, including late responses", async () => {
    const client = {};
    const old = getToolsCatalog(client, "old-token");
    const pending = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(() => pending.promise));
    const loading = old.loadCliApps();
    const next = getToolsCatalog(client, "new-token");
    const otherHost = getToolsCatalog({}, "old-token");
    pending.resolve(response(cli));
    await loading;
    expect(old.getSnapshot().cliApps).toEqual(cli);
    expect(next.getSnapshot().cliApps).toBeNull();
    expect(otherHost.getSnapshot().cliApps).toBeNull();
    expect(getToolsCatalog(client, "old-token").getSnapshot().cliApps).toBeNull();
    expect(vi.mocked(fetch).mock.calls[0][1]?.headers).toEqual({ Authorization: "Bearer old-token" });
  });

  it("deduplicates in-flight reads and does not overwrite mutation payloads with older GETs", async () => {
    const client = {};
    const cache = getToolsCatalog(client, "token");
    const cliRead = deferred<Response>();
    const mcpRead = deferred<Response>();
    const fetch = vi.fn((url: string) => url.endsWith("cli-apps") ? cliRead.promise : mcpRead.promise);
    vi.stubGlobal("fetch", fetch);
    const first = cache.loadCliApps();
    expect(cache.loadCliApps()).toBe(first);
    const second = cache.loadMcpPresets();
    const changedCli = { ...cli, installed_count: 1 };
    const changedMcp = { ...mcp, installed_count: 1 };
    cache.setCliApps(changedCli);
    cache.setMcpPresets(changedMcp);
    cliRead.resolve(response(cli));
    mcpRead.resolve(response(mcp));
    await Promise.all([first, second]);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(getToolsCatalog(client, "token").getSnapshot()).toMatchObject({ cliApps: changedCli, mcpPresets: changedMcp });
  });

  it("retains expired and invalidated data, but refreshes it rather than treating it as fresh", async () => {
    const client = {};
    const cache = getToolsCatalog(client, "token");
    cache.setCliApps(cli);
    cache.setMcpPresets(mcp);
    expect(cache.cliFresh()).toBe(true);
    expect(cache.mcpFresh()).toBe(true);
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + TOOLS_CATALOG_TTL_MS);
    expect(cache.cliFresh()).toBe(false);
    expect(cache.mcpFresh()).toBe(false);
    cache.setCliApps(cli);
    cache.setMcpPresets(mcp);
    invalidateToolsCatalog(client);
    expect(cache.cliFresh()).toBe(false);
    expect(cache.mcpFresh()).toBe(false);
    expect(cache.getSnapshot()).toMatchObject({ cliApps: cli, mcpPresets: mcp });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url.endsWith("cli-apps") ? cli : mcp)));
    await Promise.all([cache.loadCliApps(), cache.loadMcpPresets()]);
    expect(cache.cliFresh()).toBe(true);
    expect(cache.mcpFresh()).toBe(true);
  });

  it("does not surface an older GET failure after a mutation has succeeded", async () => {
    const cache = getToolsCatalog({}, "token");
    let reject!: (reason: Error) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((_, fail) => { reject = fail; })));
    const loading = cache.loadMcpPresets();
    cache.setMcpPresets(mcp);
    reject(new Error("old read failed"));
    await expect(loading).resolves.toBeUndefined();
    expect(cache.getSnapshot().mcpPresets).toEqual(mcp);
  });

  it("leaves failures retryable and preserves stale payloads on a refresh failure", async () => {
    const cache = getToolsCatalog({}, "token");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response(cli)).mockRejectedValueOnce(new Error("offline")));
    await expect(cache.loadCliApps()).rejects.toThrow("offline");
    expect(cache.getSnapshot().cliApps).toBeNull();
    expect(cache.cliFresh()).toBe(false);
    await cache.loadCliApps();
    cache.invalidate();
    await expect(cache.loadCliApps()).rejects.toThrow("offline");
    expect(cache.getSnapshot().cliApps).toEqual(cli);
    expect(cache.cliFresh()).toBe(false);
  });
});
