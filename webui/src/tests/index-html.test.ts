import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("index.html", () => {
  it("keeps browser zoom available", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const viewport = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/i)?.[1];

    expect(viewport).toContain("width=device-width");
    expect(viewport).not.toContain("user-scalable=no");
    expect(viewport).not.toMatch(/maximum-scale\s*=\s*1(?:\.0)?(?:,|$)/);
  });

  it("lets the app handle iOS safe-area insets itself", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const viewport = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/i)?.[1];

    // viewport-fit=cover plus env(safe-area-inset-*) padding keeps the header
    // below the status bar; plain `auto` no longer constrains the layout
    // viewport on devices whose WebKit reports no safe-area inset, leaving
    // the header under the translucent status bar.
    expect(viewport).toContain("viewport-fit=cover");
  });

  it("provides light and dark PWA chrome colors", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const manifest = JSON.parse(
      readFileSync(resolve(process.cwd(), "public/manifest.json"), "utf8"),
    ) as {
      background_color?: string;
      theme_color?: string;
      color_scheme_dark?: { background_color?: string; theme_color?: string };
    };
    const document = new DOMParser().parseFromString(html, "text/html");
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    const lightBodyBackground = html.match(/body\s*{[^}]*background:\s*([^;]+);/s)?.[1]?.trim();
    const darkBodyBackground = html.match(
      /html\.dark body\s*{[^}]*background:\s*([^;]+);/s,
    )?.[1]?.trim();

    expect(themeColor?.content).toBe("#ffffff");
    expect(themeColor?.dataset.themeColorLight).toBe("#ffffff");
    expect(themeColor?.dataset.themeColorDark).toBe("#303030");
    expect(lightBodyBackground).toBe("#ffffff");
    expect(darkBodyBackground).toBe("#303030");
    expect(manifest.background_color).toBe("#ffffff");
    expect(manifest.theme_color).toBe("#ffffff");
    expect(manifest.color_scheme_dark?.background_color).toBe("#303030");
    expect(manifest.color_scheme_dark?.theme_color).toBe("#303030");
  });
});
