import { act, screen } from "@testing-library/react";
import ReactDOM from "react-dom/client";
import { expect, it, vi } from "vitest";

const events = vi.hoisted(() => [] as string[]);
vi.mock("@/mount", async (original) => {
  events.push("mount module");
  return original<typeof import("@/mount")>();
});
vi.mock("@/components/thread/ThreadShell", () => {
  events.push("thread module");
  return { ThreadShell: () => null };
});

it("starts the fragment-authenticated request and chat import before mount, then consumes even a fast 401 once", async () => {
  const root = document.createElement("div");
  root.id = "root";
  root.innerHTML = '<main data-startup-surface="chat" aria-busy="true"></main>';
  document.body.append(root);
  const css = document.createElement("link");
  css.dataset.appStylesheet = "";
  document.head.append(css);
  window.history.replaceState(null, "", "/#/?bootstrapSecret=from-fragment&keep=1");
  const createRoot = vi.spyOn(ReactDOM, "createRoot");
  const request = vi.fn(async () => {
    events.push("bootstrap");
    return new Response(null, { status: 401 });
  });
  vi.stubGlobal("fetch", request);
  try {
    await import("@/main");
    await vi.dynamicImportSettled();
    expect(events[0]).toBe("bootstrap");
    expect(events).toContain("thread module");
    expect(events).toContain("mount module");
    expect(request).toHaveBeenCalledWith("/webui/bootstrap", expect.objectContaining({
      credentials: "same-origin", cache: "no-store", headers: { "X-Nanobot-Auth": "from-fragment" },
    }));
    expect(window.location.hash).toBe("#/?keep=1");
    expect(createRoot).not.toHaveBeenCalled();
    expect(root.querySelector("input, textarea")).toBeNull();

    await act(async () => { css.dispatchEvent(new Event("load")); });
    expect(await screen.findByLabelText("WebUI password")).toBeVisible();
    expect(request).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem("nanobot-webui.bootstrap-secret")).toBeNull();
  } finally {
    await act(async () => { createRoot.mock.results[0]?.value?.unmount(); });
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
    css.remove();
    root.remove();
  }
});
