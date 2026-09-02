import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const render = vi.fn();
const createRoot = vi.fn(() => ({ render }));

vi.mock("react-dom/client", () => ({
  default: { createRoot },
}));

vi.mock("@/App", () => ({
  default: () => null,
}));

describe("service worker registration in main entry", () => {
  const register = vi.fn(() => Promise.resolve());

  beforeEach(() => {
    vi.resetModules();
    createRoot.mockClear();
    render.mockClear();
    register.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
    Object.defineProperty(navigator, "serviceWorker", {
      value: { register },
      configurable: true,
    });
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete (navigator as Navigator & { serviceWorker?: unknown }).serviceWorker;
  });

  it("registers /sw.js with updateViaCache none only after window load", async () => {
    await import("../main");

    expect(register).not.toHaveBeenCalled();

    window.dispatchEvent(new Event("load"));

    expect(register).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalledWith("/sw.js", { updateViaCache: "none" });
  });
});
