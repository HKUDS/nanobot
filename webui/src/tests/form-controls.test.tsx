import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

describe("form control focus styles", () => {
  it.each([
    ["input", <Input aria-label="input" />],
    ["textarea", <Textarea aria-label="textarea" />],
  ])("uses a subdued inset focus ring for the %s", (label, control) => {
    render(control);

    const element = screen.getByLabelText(label);
    expect(element).toHaveClass(
      "focus-visible:ring-2",
      "focus-visible:ring-inset",
      "focus-visible:ring-ring/50",
    );
    expect(element).not.toHaveClass(
      "ring-offset-background",
      "focus-visible:ring-ring",
      "focus-visible:ring-offset-2",
    );
  });
});
