import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getRuntimeHost,
  isNativeRuntime,
} from "@/lib/runtime";

afterEach(() => {
  Reflect.deleteProperty(window, "nanobotHost");
});

describe("runtime host facade", () => {
  it("defaults to browser runtime without host actions", () => {
    const host = getRuntimeHost();

    expect(host.surface).toBe("browser");
    expect(host.restartEngine).toBeUndefined();
    expect(isNativeRuntime()).toBe(false);
  });

  it("wraps native host actions behind the runtime facade", async () => {
    const restartEngine = vi.fn(async () => undefined);
    const openLogs = vi.fn(async () => undefined);
    const exportDiagnostics = vi.fn(async () => "/tmp/diagnostics.txt");
    Object.defineProperty(window, "nanobotHost", {
      configurable: true,
      value: {
        getRuntimeInfo: vi.fn(),
        restartEngine,
        openLogs,
        exportDiagnostics,
      },
    });

    const host = getRuntimeHost();

    expect(host.surface).toBe("native");
    expect(isNativeRuntime()).toBe(true);
    await host.restartEngine?.();
    await host.openLogs?.();
    await expect(host.exportDiagnostics?.()).resolves.toBe("/tmp/diagnostics.txt");
    expect(restartEngine).toHaveBeenCalledTimes(1);
    expect(openLogs).toHaveBeenCalledTimes(1);
    expect(exportDiagnostics).toHaveBeenCalledTimes(1);
  });

  it("treats server-reported native surface as native for UI labels", () => {
    expect(isNativeRuntime("native")).toBe(true);
  });

});
