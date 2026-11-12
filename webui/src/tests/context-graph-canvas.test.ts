import { expect, it, vi } from "vitest";
import { fitGraphLabel } from "@/components/thread/graph-canvas";

it("fits long Unicode labels with bounded measurements and complete code points", () => {
  const name = "😀".repeat(255);
  const measure = vi.fn((text: string) => Array.from(text).length);
  const fitted = fitGraphLabel(name, measure);
  expect(fitted).toBe(`${"😀".repeat(127)}…`);
  expect(measure.mock.calls.length).toBeLessThanOrEqual(10);
  expect(fitGraphLabel("a.md", measure)).toBe("a.md");
});
