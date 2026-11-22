import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import postcss, { type Document, type Rule } from "postcss";
import tailwindcss from "tailwindcss";
import loadConfig from "tailwindcss/loadConfig";
import { describe, expect, it } from "vitest";

import { compiledGlobalCss } from "./compiled-global-css";

describe("sidebar touch hover isolation", () => {
  it("shows sidebar actions with roomy targets only for coarse pointers", async () => {
    const css = await compiledGlobalCss('class="sidebar-action-trigger touch-target opacity-0 h-6 w-6"');
    let hiddenIndex = -1;
    let visibleIndex = -1;
    let index = 0;
    let touchTarget = false;
    css.walkRules((rule) => {
      index++;
      if (rule.selector === ".opacity-0") {
        hiddenIndex = index;
        expect(rule.nodes).toContainEqual(expect.objectContaining({ prop: "opacity", value: "0" }));
      }
      if (rule.selector === ".sidebar-action-trigger") {
        visibleIndex = index;
        expect(rule.parent).toMatchObject({ type: "atrule", name: "media", params: "(pointer: coarse)" });
        expect(rule.nodes).toContainEqual(expect.objectContaining({ prop: "opacity", value: "1" }));
      }
      if (rule.selector === ".touch-target") {
        touchTarget = true;
        expect(rule.parent).toMatchObject({ type: "atrule", name: "media", params: "(pointer: coarse)" });
        for (const prop of ["min-width", "min-height"]) {
          expect(rule.nodes).toContainEqual(expect.objectContaining({ prop, value: "2.75rem" }));
        }
      }
    });
    expect(hiddenIndex).toBeGreaterThan(0);
    expect(visibleIndex).toBeGreaterThan(hiddenIndex);
    expect(touchTarget).toBe(true);
  });

  it("gates ordinary and named-group hover CSS without gating keyboard focus", async () => {
    const config = loadConfig(resolve(process.cwd(), "tailwind.config.js"));
    const source = readFileSync(
      resolve(process.cwd(), "src/components/ChatList.tsx"), "utf8",
    );
    const result = await postcss([tailwindcss({
      ...config,
      content: [{ raw: source, extension: "tsx" }],
    })]).process("@tailwind utilities;", { from: undefined });
    const hoverSelectors: string[] = [];
    const focusSelectors: string[] = [];
    result.root.walkRules((rule) => {
      if (rule.selector.includes(":hover")) {
        hoverSelectors.push(rule.selector);
        let parent: Rule["parent"] | Document = rule.parent;
        let hoverMedia = false;
        while (parent) {
          if (parent.type === "atrule" && "name" in parent
            && parent.name === "media" && parent.params === "(hover: hover)") {
            hoverMedia = true;
          }
          parent = parent.parent;
        }
        expect(hoverMedia, rule.selector).toBe(true);
      }
      if (rule.selector.includes(":focus-visible")) {
        focusSelectors.push(rule.selector);
        expect(rule.parent?.type).toBe("root");
      }
    });
    expect(hoverSelectors.some((selector) => selector.includes("group:hover"))).toBe(true);
    expect(hoverSelectors.some((selector) => selector.includes("group\\/tab:hover"))).toBe(true);
    expect(hoverSelectors.some((selector) => selector.includes("group\\/pane:hover"))).toBe(true);
    expect(focusSelectors.length).toBeGreaterThan(0);
  });
});
