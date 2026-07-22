import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getRuntimeHost,
  initializeLoopbackRuntimeHost,
  isNativeRuntime,
} from "@/lib/runtime";

afterEach(() => {
  Reflect.deleteProperty(window, "nanobotHost");
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
  initializeLoopbackRuntimeHost();
  vi.unstubAllGlobals();
});

describe("runtime host facade", () => {
  it("defaults to browser runtime without host actions", () => {
    const host = getRuntimeHost();

    expect(host.surface).toBe("browser");
    expect(host.pickFolder).toBeUndefined();
    expect(isNativeRuntime()).toBe(false);
  });

  it("wraps native host actions behind the runtime facade", async () => {
    const pickFolder = vi.fn(async () => "/tmp/project");
    const restartEngine = vi.fn(async () => undefined);
    Object.defineProperty(window, "nanobotHost", {
      configurable: true,
      value: {
        getRuntimeInfo: vi.fn(),
        restartEngine,
        pickFolder,
        openLogs: vi.fn(async () => undefined),
        exportDiagnostics: vi.fn(async () => "/tmp/diagnostics.txt"),
      },
    });

    const host = getRuntimeHost();

    expect(host.surface).toBe("native");
    expect(isNativeRuntime()).toBe(true);
    await expect(host.pickFolder?.()).resolves.toBe("/tmp/project");
    await host.restartEngine?.();
    expect(pickFolder).toHaveBeenCalledTimes(1);
    expect(restartEngine).toHaveBeenCalledTimes(1);
  });

  it("treats server-reported native surface as native for UI labels", () => {
    expect(isNativeRuntime("native")).toBe(true);
  });

  it("installs an authenticated loopback folder picker from the URL fragment", async () => {
    const token = "a".repeat(43);
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ path: "/Users/test/project" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(
      null,
      "",
      `/#/new?bootstrapSecret=secret&nativeHostPort=43123&nativeHostToken=${token}`,
    );

    expect(initializeLoopbackRuntimeHost()).toBe(true);
    expect(window.location.hash).toBe("#/new?bootstrapSecret=secret");
    expect(isNativeRuntime()).toBe(true);
    await expect(getRuntimeHost().pickFolder?.()).resolves.toBe("/Users/test/project");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:43123/v1/pick-folder",
      expect.objectContaining({
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }),
    );

    window.history.replaceState(null, "", "/#/new");
    expect(initializeLoopbackRuntimeHost()).toBe(true);
    await expect(getRuntimeHost().pickFolder?.()).resolves.toBe("/Users/test/project");
  });

  it("rejects invalid loopback bridge bootstrap values", () => {
    window.history.replaceState(
      null,
      "",
      "/#/new?nativeHostPort=70000&nativeHostToken=too-short",
    );

    expect(initializeLoopbackRuntimeHost()).toBe(false);
    expect(window.location.hash).toBe("#/new");
    expect(getRuntimeHost().pickFolder).toBeUndefined();
  });
});
