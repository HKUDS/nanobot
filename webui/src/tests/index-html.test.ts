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

  it("keeps page-level pinch zoom by scoping touch-action to controls", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const document = new DOMParser().parseFromString(html, "text/html");
    const style = document.querySelector("style")?.textContent ?? "";

    // The html {} rule must not globally disable double-tap zoom on iOS.
    expect(style).not.toMatch(/html\s*\{[^}]*touch-action\s*:\s*manipulation/s);
    // Interactive controls still opt out of double-tap zoom.
    expect(style).toMatch(/touch-action\s*:\s*manipulation/s);
  });

  it("declares apple startup splash images across the device table", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const document = new DOMParser().parseFromString(html, "text/html");
    const links = Array.from(
      document.querySelectorAll<HTMLLinkElement>("link[rel='apple-touch-startup-image']"),
    );

    expect(links.length).toBeGreaterThanOrEqual(20);
    for (const link of links) {
      expect(link.media).toMatch(/screen and \(device-width: \d+px\)/);
      expect(link.media).toMatch(/-webkit-device-pixel-ratio: \d/);
      expect(link.href).toMatch(/\/brand\/splash\/nanobot-.*\.png\?v\d/);
    }
    // Both orientations are covered for at least one common iPhone size.
    expect(
      links.some((l) => l.media.includes("390px") && l.media.includes("orientation: portrait")),
    ).toBe(true);
    expect(
      links.some((l) => l.media.includes("844px") && l.media.includes("orientation: landscape")),
    ).toBe(true);
  });
});
