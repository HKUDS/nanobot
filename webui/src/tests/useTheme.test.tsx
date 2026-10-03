import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useTheme } from "@/hooks/useTheme";

describe("useTheme", () => {
  beforeEach(() => {
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
});
