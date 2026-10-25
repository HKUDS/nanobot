import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTheme } from "@/hooks/useTheme";

describe("useTheme", () => {
  beforeEach(() => {
    vi.useFakeTimers();
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
    vi.clearAllTimers();
    vi.useRealTimers();
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
