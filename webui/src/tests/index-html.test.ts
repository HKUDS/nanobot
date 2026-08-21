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

  it("lets iOS keep standalone content inside the safe area", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const viewport = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/i)?.[1];

    expect(viewport).toContain("viewport-fit=auto");
    expect(viewport).not.toContain("viewport-fit=cover");
  });

  it("matches dark PWA chrome to the app canvas", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const manifest = JSON.parse(
      readFileSync(resolve(process.cwd(), "public/manifest.json"), "utf8"),
    ) as { background_color?: string; theme_color?: string };
    const darkThemeColor = html.match(
      /<meta\s+name="theme-color"\s+content="([^"]+)"\s+media="\(prefers-color-scheme:\s*dark\)"/i,
    )?.[1];
    const darkBodyBackground = html.match(
      /html\.dark body\s*{[^}]*background:\s*([^;]+);/s,
    )?.[1]?.trim();

    expect(darkThemeColor).toBe("#303030");
    expect(darkBodyBackground).toBe("#303030");
    expect(manifest.background_color).toBe("#303030");
    expect(manifest.theme_color).toBe("#303030");
  });
});
