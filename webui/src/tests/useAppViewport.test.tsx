import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAppViewport } from "@/hooks/useAppViewport";

let touch = true;
let native = false;
vi.mock("@/hooks/useMediaQuery", () => ({ useMediaQuery: () => touch }));
vi.mock("@/lib/runtime", () => ({ isNativeRuntime: () => native }));

function AppSurface() {
  useAppViewport();
  return <><header>Navigation</header><textarea aria-label="Draft" defaultValue="中文草稿" /></>;
}

describe("app visual viewport", () => {
  let root: HTMLDivElement;
  let viewport: EventTarget & { height: number; offsetTop: number; scale: number };
  beforeEach(() => {
    touch = true;
    native = false;
    root = document.createElement("div");
    root.id = "root";
    document.body.append(root);
    viewport = Object.assign(new EventTarget(), { height: 746, offsetTop: 0, scale: 1 });
    vi.stubGlobal("visualViewport", viewport);
  });
  afterEach(() => { cleanup(); root.remove(); vi.unstubAllGlobals(); });

  function resize(height: number, offsetTop: number, scale = 1) {
    act(() => {
      Object.assign(viewport, { height, offsetTop, scale });
      viewport.dispatchEvent(new Event("resize"));
    });
  }

  it("fits the whole app to keyboard height and pan, preserving draft and focus through dismissal", () => {
    render(<AppSurface />, { container: root });
    const input = root.querySelector("textarea")!;
    input.focus();
    resize(396, 350);
    expect(root).toHaveClass("visual-viewport");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-height")).toBe("396px");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("350px");
    act(() => {
      viewport.offsetTop = 320;
      viewport.dispatchEvent(new Event("scroll"));
    });
    expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("320px");
    expect(document.activeElement).toBe(input);
    expect(input).toHaveValue("中文草稿");
    resize(746, 0);
    expect(document.documentElement.style.getPropertyValue("--app-viewport-height")).toBe("746px");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("0px");
  });

  it("does not reflow or chase the viewport during pinch zoom, then resumes on reset", () => {
    render(<AppSurface />, { container: root });
    resize(373, 120, 2);
    expect(document.documentElement.style.getPropertyValue("--app-viewport-height")).toBe("746px");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("0px");
    resize(320, 0);
    expect(document.documentElement.style.getPropertyValue("--app-viewport-height")).toBe("320px");
  });

  it("keeps navigation below the top edge when a focused PWA rotates with negative WebKit overscroll", () => {
    render(<AppSurface />, { container: root });
    resize(128, -68);
    expect(root).toHaveClass("short-visual-viewport");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-height")).toBe("128px");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("0px");
    resize(428, 416);
    expect(root).not.toHaveClass("short-visual-viewport");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("416px");
  });

  it.each(["desktop", "native", "unsupported"])("leaves %s layout ownership unchanged", (kind) => {
    touch = kind !== "desktop";
    native = kind === "native";
    if (kind === "unsupported") vi.stubGlobal("visualViewport", undefined);
    render(<AppSurface />, { container: root });
    resize(396, 350);
    expect(root).not.toHaveClass("visual-viewport");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-height")).toBe("");
  });

  it("releases listeners and owned styles when touch layout is disabled or the app unmounts", () => {
    const { rerender, unmount } = render(<AppSurface />, { container: root });
    touch = false;
    rerender(<AppSurface />);
    resize(396, 350);
    expect(root).not.toHaveClass("visual-viewport");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-height")).toBe("");
    touch = true;
    rerender(<AppSurface />);
    expect(root).toHaveClass("visual-viewport");
    unmount();
    resize(746, 0);
    expect(root).not.toHaveClass("visual-viewport");
    expect(root).not.toHaveClass("short-visual-viewport");
    expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("");
  });
});
