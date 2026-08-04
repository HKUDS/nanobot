import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const render = vi.fn();
const createRoot = vi.fn(() => ({ render }));

vi.mock("react-dom/client", () => ({
  default: { createRoot },
}));

vi.mock("@/App", () => ({
  default: () => null,
}));

describe("main entry crypto shim", () => {
  const originalRandomUUID = globalThis.crypto.randomUUID;

  beforeEach(() => {
    vi.resetModules();
    createRoot.mockClear();
    render.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
    delete (globalThis.crypto as Crypto & { randomUUID?: Crypto["randomUUID"] }).randomUUID;
  });

  afterEach(() => {
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      value: originalRandomUUID,
      configurable: true,
    });
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
});
