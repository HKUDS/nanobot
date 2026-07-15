import { afterEach, describe, expect, it, vi } from "vitest";

import { getRuntimeHost, isNativeRuntime } from "@/lib/runtime";

afterEach(() => {
  Reflect.deleteProperty(window, "nanobotHost");
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
});
