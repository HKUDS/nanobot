import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTheme } from "@/hooks/useTheme";

describe("useTheme", () => {
  let systemDark = false;
  let mediaEvents: EventTarget;

  function changeSystemTheme(dark: boolean) {
    act(() => {
      systemDark = dark;
      mediaEvents.dispatchEvent(new Event("change"));
    });
  }

  function notifyStorageChange(key: string | null = "nanobot-webui.theme") {
    act(() => window.dispatchEvent(new StorageEvent("storage", { key })));
  }

  beforeEach(() => {
    vi.useFakeTimers();
    systemDark = false;
    mediaEvents = new EventTarget();
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      get matches() { return systemDark; },
      addEventListener: mediaEvents.addEventListener.bind(mediaEvents),
      removeEventListener: mediaEvents.removeEventListener.bind(mediaEvents),
    })));
    localStorage.removeItem("nanobot-webui.theme");
    document.documentElement.classList.remove("dark");

    const themeColor = document.createElement("meta");
    themeColor.name = "theme-color";
    themeColor.content = "#ffffff";
    themeColor.dataset.themeColorLight = "#ffffff";
    themeColor.dataset.themeColorDark = "#303030";
    document.head.append(themeColor);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete document.documentElement.dataset.themeTransition;
    document.querySelector('meta[name="theme-color"]')?.remove();
    document.documentElement.classList.remove("dark");
    localStorage.removeItem("nanobot-webui.theme");
  });

  it("keeps browser chrome in sync with the selected app theme", () => {
    localStorage.setItem("nanobot-webui.theme", "dark");
    const { result } = renderHook(useTheme);
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');

    expect(document.documentElement).toHaveClass("dark");
    expect(themeColor?.content).toBe("#303030");

    act(() => result.current.setTheme("light"));

    expect(document.documentElement).not.toHaveClass("dark");
    expect(themeColor?.content).toBe("#ffffff");
    expect(localStorage.getItem("nanobot-webui.theme")).toBe("light");
    expect(result.current.preference).toBe("light");
  });

  it.each(["light", "dark"] as const)("preserves a previously saved %s choice", (saved) => {
    systemDark = saved === "light";
    localStorage.setItem("nanobot-webui.theme", saved);
    const { result } = renderHook(useTheme);

    expect(result.current.preference).toBe(saved);
    expect(result.current.theme).toBe(saved);
    expect(localStorage.getItem("nanobot-webui.theme")).toBe(saved);
  });

  it("defaults to system and follows live changes without persisting the resolved theme", () => {
    const { result } = renderHook(useTheme);
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("light");

    changeSystemTheme(true);
    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement).toHaveClass("dark");
    expect(themeColor?.content).toBe("#303030");

    changeSystemTheme(false);
    expect(result.current.theme).toBe("light");
    expect(document.documentElement).not.toHaveClass("dark");
    expect(themeColor?.content).toBe("#ffffff");
    expect(localStorage.getItem("nanobot-webui.theme")).toBeNull();
  });

  it("restores system preference against the current system theme", () => {
    localStorage.setItem("nanobot-webui.theme", "system");
    systemDark = true;
    const { result } = renderHook(useTheme);

    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("dark");
    changeSystemTheme(false);
    expect(result.current.theme).toBe("light");
    expect(localStorage.getItem("nanobot-webui.theme")).toBe("system");
  });

  it("ignores system changes in explicit mode and resumes the latest system theme", () => {
    const { result } = renderHook(useTheme);
    act(() => result.current.setTheme("light"));
    changeSystemTheme(true);

    expect(result.current.preference).toBe("light");
    expect(result.current.theme).toBe("light");
    expect(document.documentElement).not.toHaveClass("dark");

    act(() => result.current.setTheme("system"));
    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("nanobot-webui.theme")).toBe("system");
  });

  it.each([false, true])("toggles the resolved system theme into an explicit choice: dark=%s", (dark) => {
    systemDark = dark;
    const { result } = renderHook(useTheme);
    const selected = dark ? "light" : "dark";

    act(() => result.current.toggle());
    expect(result.current.preference).toBe(selected);
    expect(result.current.theme).toBe(selected);
    expect(localStorage.getItem("nanobot-webui.theme")).toBe(selected);

    changeSystemTheme(!dark);
    changeSystemTheme(dark);
    expect(result.current.theme).toBe(selected);

    act(() => vi.advanceTimersByTime(600));
    act(() => result.current.toggle());
    expect(result.current.preference).toBe(dark ? "dark" : "light");
    expect(result.current.theme).toBe(dark ? "dark" : "light");
  });

  it("synchronizes other tabs and storage removal without writing back", () => {
    const { result } = renderHook(useTheme);
    const write = vi.spyOn(Storage.prototype, "setItem");
    localStorage.setItem("nanobot-webui.theme", "dark");
    write.mockClear();

    notifyStorageChange("nanobot.locale");
    expect(result.current.preference).toBe("system");
    notifyStorageChange();
    expect(result.current.preference).toBe("dark");
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement).toHaveClass("dark");
    expect(write).not.toHaveBeenCalled();

    localStorage.removeItem("nanobot-webui.theme");
    notifyStorageChange();
    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("light");

    localStorage.setItem("nanobot-webui.theme", "dark");
    notifyStorageChange();
    localStorage.clear();
    write.mockClear();
    notifyStorageChange(null);
    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("light");
    expect(write).not.toHaveBeenCalled();
  });

  it("uses system for unrecognized stored preferences", () => {
    systemDark = true;
    localStorage.setItem("nanobot-webui.theme", "invalid");
    const { result } = renderHook(useTheme);

    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("dark");
  });

  it("keeps theme controls usable when browser storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Storage blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage blocked"); });
    const { result } = renderHook(useTheme);

    expect(result.current.preference).toBe("system");
    act(() => result.current.setTheme("dark"));
    expect(result.current.preference).toBe("dark");
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement).toHaveClass("dark");
  });

  it("can select system during a same-palette transition and still follows OS changes", () => {
    systemDark = true;
    localStorage.setItem("nanobot-webui.theme", "light");
    const { result } = renderHook(useTheme);
    act(() => result.current.setTheme("dark"));
    expect(document.documentElement).toHaveAttribute("data-theme-transition", "dark");
    act(() => result.current.setTheme("system"));
    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("dark");
    expect(localStorage.getItem("nanobot-webui.theme")).toBe("system");
    changeSystemTheme(false);
    expect(result.current.theme).toBe("light");
    expect(localStorage.getItem("nanobot-webui.theme")).toBe("system");
    act(() => vi.advanceTimersByTime(600));
    expect(document.documentElement).not.toHaveAttribute("data-theme-transition");
    expect(result.current.theme).toBe("light");
  });

  it("ignores rapid reversals for 600ms without replaying them later", () => {
    localStorage.setItem("nanobot-webui.theme", "light");
    const { result } = renderHook(useTheme);
    expect(document.documentElement).not.toHaveAttribute("data-theme-transition");

    act(() => result.current.toggle());
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement).toHaveAttribute("data-theme-transition", "dark");
    act(() => {
      result.current.toggle();
      result.current.setTheme("light");
      vi.advanceTimersByTime(599);
    });
    act(() => result.current.toggle());
    expect(result.current.theme).toBe("dark");
    expect(localStorage.getItem("nanobot-webui.theme")).toBe("dark");

    act(() => vi.advanceTimersByTime(1));
    expect(document.documentElement).not.toHaveAttribute("data-theme-transition");
    act(() => vi.advanceTimersByTime(600));
    expect(result.current.theme).toBe("dark");
    act(() => result.current.toggle());
    expect(result.current.theme).toBe("light");
    expect(localStorage.getItem("nanobot-webui.theme")).toBe("light");
  });

  it("releases the temporary transition styles when its owner unmounts", () => {
    const { result, unmount } = renderHook(useTheme);
    act(() => result.current.toggle());
    expect(document.documentElement).toHaveAttribute("data-theme-transition");
    unmount();
    expect(document.documentElement).not.toHaveAttribute("data-theme-transition");
    expect(vi.getTimerCount()).toBe(0);
  });
});
