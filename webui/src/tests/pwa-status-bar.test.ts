import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import postcss, { type Rule } from "postcss";
import { describe, expect, it } from "vitest";

const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
const document = new DOMParser().parseFromString(html, "text/html");
const css = postcss.parse(document.querySelector("style")?.textContent ?? "");
const rules: Rule[] = [];
css.walkRules(".pwa-status-bar-surface", (rule) => { rules.push(rule); });

function declarations(rule: Rule): Record<string, string> {
  const result: Record<string, string> = {};
  rule.walkDecls((decl) => { result[decl.prop] = decl.value; });
  return result;
}

describe("iOS standalone status-bar surface", () => {
  it("exists before React loads and survives root replacement without entering the focus order", () => {
    const surfaces = document.querySelectorAll(".pwa-status-bar-surface");
    expect(surfaces).toHaveLength(1);
    const surface = surfaces[0] as HTMLElement;
    expect(surface.parentElement).toBe(document.body);
    expect(document.getElementById("root")?.contains(surface)).toBe(false);
    expect(surface.getAttribute("aria-hidden")).toBe("true");
    expect(surface.childNodes).toHaveLength(0);
    expect(surface.tabIndex).toBe(-1);
    document.getElementById("root")?.replaceChildren(document.createElement("main"));
    expect(document.body.contains(surface)).toBe(true);
  });

  it("is disabled outside standalone WebKit with text background clipping", () => {
    const base = rules.filter((rule) => rule.parent?.type === "root");
    expect(base).toHaveLength(1);
    expect(declarations(base[0])).toEqual({ display: "none" });

    const enabled = rules.filter((rule) => declarations(rule).display === "block");
    expect(enabled).toHaveLength(1);
    const conditions: Record<string, string> = {};
    for (let parent = enabled[0].parent; parent; parent = parent.parent) {
      if (parent.type === "atrule" && "name" in parent) conditions[parent.name] = parent.params;
    }
    expect(conditions.media).toBe("(display-mode: standalone)");
    expect(conditions.supports).toBe("(-webkit-touch-callout: none) and (background-clip: text)");
  });

  it("keeps the fixed, theme-inheriting, text-clipped and non-interactive CSS contract", () => {
    const enabled = rules.find((rule) => declarations(rule).display === "block");
    expect(enabled).toBeDefined();
    expect(declarations(enabled!)).toEqual({
      display: "block",
      position: "fixed",
      inset: "0 0 auto",
      height: "11px",
      "z-index": "100",
      "pointer-events": "none",
      "background-color": "inherit",
      "-webkit-background-clip": "text",
      "background-clip": "text",
    });
  });
});
