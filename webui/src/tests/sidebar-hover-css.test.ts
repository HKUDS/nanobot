import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import postcss from "postcss";
import tailwindcss from "tailwindcss";
import loadConfig from "tailwindcss/loadConfig";
import { describe, expect, it } from "vitest";

describe("sidebar touch hover isolation", () => {
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
        let parent = rule.parent;
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
