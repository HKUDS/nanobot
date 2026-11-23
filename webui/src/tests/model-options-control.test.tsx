import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { ModelOptionsControl } from "@/components/thread/ModelOptionsControl";
import type { SessionModelOptions } from "@/lib/types";

function Control({ fast = true, defaultEffort = "medium", onChange }: {
  fast?: boolean;
  defaultEffort?: string | null;
  onChange?: (value: SessionModelOptions) => void;
}) {
  const [value, setValue] = useState<SessionModelOptions>({ reasoning_effort: null, codex_fast_mode: null });
  const efforts = ["low", "medium", "high"];
  return <ModelOptionsControl data={{ value, efforts, effortsPending: false, capability: {
    reasoning_effort: { default: defaultEffort, values: efforts },
    ...(fast ? { codex_fast_mode: { default: true } } : {}),
  } }} onChange={(next) => { setValue(next); onChange?.(next); }} />;
}

it("preselects the actual preset values without writing them and saves a reselected value explicitly", () => {
  const onChange = vi.fn();
  render(<Control onChange={onChange} />);
  const effort = screen.getByRole("slider", { name: "Reasoning effort" });
  const fast = screen.getByRole("button", { name: "Fast" });
  expect(effort).toHaveAttribute("aria-valuetext", "medium");
  expect(fast).toHaveAttribute("aria-pressed", "true");
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(effort, { target: { value: "0" } });
  expect(effort).toHaveAttribute("aria-valuetext", "low");
  fireEvent.click(fast);
  expect(fast).toHaveAttribute("aria-pressed", "false");
  fireEvent.change(effort, { target: { value: "1" } });
  expect(onChange).toHaveBeenLastCalledWith({ reasoning_effort: "medium", codex_fast_mode: false });
});

it("lets the model choose the effort when no concrete preset value is known", () => {
  const onChange = vi.fn();
  render(<Control defaultEffort={null} onChange={onChange} />);
  const effort = screen.getByRole("slider", { name: "Reasoning effort" });
  expect(effort).toHaveAttribute("aria-valuetext", "Auto");
  fireEvent.change(effort, { target: { value: "3" } });
  expect(effort).toHaveAttribute("aria-valuetext", "high");
  fireEvent.change(effort, { target: { value: "0" } });
  expect(onChange).toHaveBeenLastCalledWith({ reasoning_effort: null, codex_fast_mode: null });
});

it("keeps a custom preset effort selectable without giving it a position on the scale", () => {
  const onChange = vi.fn();
  render(<Control defaultEffort="extended" onChange={onChange} />);
  const effort = screen.getByRole("combobox", { name: "Reasoning effort" });
  expect(effort).toHaveTextContent("extended");
  fireEvent.keyDown(effort, { key: "Enter" });
  fireEvent.click(screen.getByRole("option", { name: "medium" }));
  expect(effort).toHaveTextContent("medium");
  fireEvent.keyDown(effort, { key: "Enter" });
  fireEvent.click(screen.getByRole("option", { name: "extended" }));
  expect(onChange).toHaveBeenLastCalledWith({ reasoning_effort: "extended", codex_fast_mode: null });
});

it("uses the capability description rather than the provider name to expose Fast mode", () => {
  render(<Control fast={false} />);
  expect(screen.getByRole("slider", { name: "Reasoning effort" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Fast" })).not.toBeInTheDocument();
});
