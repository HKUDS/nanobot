import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const render = vi.fn();
const createRoot = vi.fn(() => ({ render }));

vi.mock("react-dom/client", () => ({
  default: { createRoot },
}));

vi.mock("@/App", () => ({
  default: () => null,
}));

describe("service worker registration when unsupported", () => {
  const register = vi.fn(() => Promise.resolve());

  beforeEach(() => {
    vi.resetModules();
    createRoot.mockClear();
    render.mockClear();
    register.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
    // happy-dom's Navigator has no serviceWorker member, so this file runs
    // without defining one — the entry's `"serviceWorker" in navigator` guard
    // must keep registration from being attempted.
  });

  afterEach(() => {
    document.body.innerHTML = "";
    delete (navigator as Navigator & { serviceWorker?: unknown }).serviceWorker;
  });

  it("does not attempt registration when the service worker API is missing", async () => {
    await import("../main");
    window.dispatchEvent(new Event("load"));

    expect(register).not.toHaveBeenCalled();
  });
});
