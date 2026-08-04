import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const render = vi.fn();
const createRoot = vi.fn(() => ({ render }));

vi.mock("react-dom/client", () => ({
  default: { createRoot },
}));

vi.mock("@/App", () => ({
  default: () => null,
}));

describe("main entry safeguards", () => {
  const originalRandomUUID = globalThis.crypto.randomUUID;

  beforeEach(() => {
    vi.resetModules();
    createRoot.mockClear();
    render.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
    sessionStorage.clear();
    delete (globalThis.crypto as Crypto & { randomUUID?: Crypto["randomUUID"] }).randomUUID;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      value: originalRandomUUID,
      configurable: true,
    });
    sessionStorage.clear();
    document.body.innerHTML = "";
  });

  it("installs a randomUUID fallback when the browser omits it", async () => {
    await import("../main");

    expect(globalThis.crypto.randomUUID).toEqual(expect.any(Function));
    expect(globalThis.crypto.randomUUID()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(createRoot).toHaveBeenCalledWith(document.getElementById("root"));
  });

  it("reloads once when a lazy chunk from an earlier deployment is unavailable", async () => {
    const addEventListener = vi.spyOn(window, "addEventListener");
    const reload = vi.spyOn(window.location, "reload").mockImplementation(() => {});

    await import("../main");

    const registration = addEventListener.mock.calls.find(
      ([type]) => type === "vite:preloadError",
    );
    const listener = registration?.[1];
    if (typeof listener !== "function") throw new TypeError("preload listener missing");

    const event = new Event("vite:preloadError", { cancelable: true });
    listener(event);

    expect(event.defaultPrevented).toBe(true);
    expect(reload).toHaveBeenCalledOnce();

    const repeatedEvent = new Event("vite:preloadError", { cancelable: true });
    listener(repeatedEvent);

    expect(repeatedEvent.defaultPrevented).toBe(false);
    expect(reload).toHaveBeenCalledOnce();
  });
});
