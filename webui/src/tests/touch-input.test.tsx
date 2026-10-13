import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import loadConfig from "tailwindcss/loadConfig";
import { describe, expect, it } from "vitest";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

describe("touch form typography", () => {
  it("keeps the touch baseline on compact shared fields without changing desktop classes", () => {
    render(<>
      <Input aria-label="Name" />
      <Input aria-label="Address" className="text-[13px]" />
      <Textarea aria-label="Pairing code" className="font-mono text-xs" />
    </>);
    for (const field of screen.getAllByRole("textbox")) {
      expect(field).toHaveClass("touch-text-input");
    }
    expect(screen.getByLabelText("Name")).toHaveClass("text-sm");
    expect(screen.getByLabelText("Address")).toHaveClass("text-[13px]");
    expect(screen.getByLabelText("Pairing code")).toHaveClass("text-xs", "font-mono");
  });

  it("emits the baseline after compact utilities, only for opted-in touch fields", async () => {
    const config = loadConfig(resolve(process.cwd(), "tailwind.config.js"));
    const source = readFileSync(resolve(process.cwd(), "src/globals.css"), "utf8");
    const result = await postcss([tailwindcss({ ...config, content: [{
      raw: 'class="touch-text-input text-xs text-sm text-[13px] text-[19px]"',
    }] })]).process(source, { from: undefined });
    let baseline = -1;
    let index = 0;
    const compact: number[] = [];
    result.root.walkRules((rule) => {
      index++;
      if ([".text-xs", ".text-sm", ".text-\\[13px\\]"].includes(rule.selector)) compact.push(index);
      if (rule.selector !== ".touch-text-input") return;
      baseline = index;
      expect(rule.parent).toMatchObject({ type: "atrule", name: "media", params: "(pointer: coarse)" });
      expect(rule.nodes).toContainEqual(expect.objectContaining({ prop: "font-size", value: "max(16px, 1rem)" }));
    });
    expect(compact).toHaveLength(3);
    expect(baseline).toBeGreaterThan(Math.max(...compact));
  });
});
