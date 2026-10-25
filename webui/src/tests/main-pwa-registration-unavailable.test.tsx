import { waitFor } from "@testing-library/react";
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
  beforeEach(() => {
    vi.resetModules();
    createRoot.mockClear();
    render.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
    Reflect.deleteProperty(navigator, "serviceWorker");
  });

  afterEach(() => {
    document.body.innerHTML = "";
    Reflect.deleteProperty(navigator, "serviceWorker");
  });

  it("renders the app when the service worker API is missing", async () => {
    expect("serviceWorker" in navigator).toBe(false);

    await import("../main");
    window.dispatchEvent(new Event("load"));

    await waitFor(() => {
      expect(createRoot).toHaveBeenCalledWith(document.getElementById("root"));
      expect(render).toHaveBeenCalledTimes(1);
    });
  });
});
