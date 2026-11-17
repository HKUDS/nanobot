import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { expect, it } from "vitest";

import { ModelOptionsControl } from "@/components/thread/ModelOptionsControl";
import type { SessionModelOptions } from "@/lib/types";

function Control({ fast = true }: { fast?: boolean }) {
  const [value, setValue] = useState<SessionModelOptions>({ reasoning_effort: null, codex_fast_mode: null });
  return <ModelOptionsControl data={{ value, efforts: ["low", "high"], capability: {
    reasoning_effort: { default: "low", values: ["low", "high"] },
    ...(fast ? { codex_fast_mode: { default: true } } : {}),
  } }} onChange={setValue} />;
}
it("keeps explicit inherit separate from the default, and allows on, off and inherit for Codex Fast mode", () => {
  render(<Control />);
  const effort = within(screen.getByRole("radiogroup", { name: "Reasoning effort" }));
  const fast = within(screen.getByRole("radiogroup", { name: "Codex Fast mode" }));
  expect(effort.getByRole("radio", { name: "Inherit" })).toBeChecked();
  expect(fast.getByRole("radio", { name: "Inherit" })).toBeChecked();
  fireEvent.click(effort.getByRole("radio", { name: "low" }));
  expect(effort.getByRole("radio", { name: "low" })).toBeChecked();
  expect(effort.getByRole("radio", { name: "Inherit" })).not.toBeChecked();
  for (const name of ["On", "Off", "Inherit"]) {
    fireEvent.click(fast.getByRole("radio", { name }));
    expect(fast.getByRole("radio", { name })).toBeChecked();
  }
  fireEvent.keyDown(effort.getByRole("radio", { name: "low" }), { key: "Home" });
  expect(effort.getByRole("radio", { name: "Inherit" })).toBeChecked();
});
it("uses the capability description rather than the provider name to expose Fast mode", () => {
  render(<Control fast={false} />);
  expect(screen.getByRole("radiogroup", { name: "Reasoning effort" })).toBeVisible();
  expect(screen.queryByRole("radiogroup", { name: "Codex Fast mode" })).not.toBeInTheDocument();
});
