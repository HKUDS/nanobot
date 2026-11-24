import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { compiledGlobalCss } from "./compiled-global-css";

describe("touch form typography", () => {
  it("keeps the touch baseline and desktop text roles on compact shared fields", () => {
    render(<>
      <Input aria-label="Name" />
      <Input aria-label="Address" className="text-[13px]" />
      <Textarea aria-label="Pairing code" className="font-mono text-xs" />
    </>);
    for (const field of screen.getAllByRole("textbox")) {
      expect(field).toHaveClass("touch-text-input");
    }
    expect(screen.getByLabelText("Name")).toHaveClass("text-ui-body");
    expect(screen.getByLabelText("Address")).toHaveClass("text-[13px]");
    expect(screen.getByLabelText("Pairing code")).toHaveClass("text-xs", "font-mono");
  });

  it("emits the baseline after compact utilities, only for opted-in touch fields", async () => {
    const css = await compiledGlobalCss('class="touch-text-input text-xs text-sm text-ui-body text-[13px] text-[19px]"');
    let baseline = -1;
    let index = 0;
    const compact: number[] = [];
    css.walkRules((rule) => {
      index++;
      if ([".text-xs", ".text-sm", ".text-ui-body", ".text-\\[13px\\]"].includes(rule.selector)) compact.push(index);
      if (rule.selector !== ".touch-text-input") return;
      baseline = index;
      expect(rule.parent).toMatchObject({ type: "atrule", name: "media", params: "(pointer: coarse)" });
      expect(rule.nodes).toContainEqual(expect.objectContaining({ prop: "font-size", value: "max(16px, 1rem)" }));
    });
    expect(compact).toHaveLength(4);
    expect(baseline).toBeGreaterThan(Math.max(...compact));
  });
});
