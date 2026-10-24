import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { ModelPresetBadge } from "@/components/thread/ModelPresetBadge";
import { ModelReasoningControl } from "@/components/thread/ModelReasoningControl";
import type { SessionReasoningEffort } from "@/lib/types";

const data: SessionReasoningEffort = { preset: "default", scope: "scope", options: ["none", "low", "max"], value: null, preset_value: "low" };

it("shows the effective preset effort and allows direct session choices in the open model picker", async () => {
  const onChange = vi.fn();
  const onOpen = vi.fn();
  const user = userEvent.setup();
  function Example() {
    const [value, setValue] = useState<string | null>(null);
    return <ModelPresetBadge label="Default" modelPreset="default" isHero onPickerOpenChange={onOpen}
      reasoningControl={<ModelReasoningControl data={{ ...data, value }} pending={false} error={false}
        onChange={(next) => { onChange(next); setValue(next); }} />} />;
  }
  render(<Example />);
  await user.click(screen.getByRole("button", { name: "Default" }));
  expect(onOpen).toHaveBeenLastCalledWith(true);
  const control = screen.getByRole("radiogroup", { name: "Reasoning effort" });
  expect(within(control).getAllByRole("radio").map((radio) => radio.textContent)).toEqual(data.options);
  expect(within(control).getByRole("radio", { name: "low" })).toBeChecked();
  expect(onChange).not.toHaveBeenCalled();
  const none = within(control).getByRole("radio", { name: "none" });
  await user.click(none);
  expect(onChange).toHaveBeenCalledWith("none");
  expect(none).toBeChecked();
  expect(screen.getByRole("dialog")).toContainElement(control);
  expect(onOpen).toHaveBeenLastCalledWith(true);
  fireEvent.keyDown(none, { key: "ArrowRight" });
  expect(within(control).getByRole("radio", { name: "low" })).toBeChecked();
  expect(within(control).getByRole("radio", { name: "low" })).toHaveFocus();
  expect(onChange).toHaveBeenLastCalledWith("low");
  expect(screen.getByRole("dialog")).toContainElement(control);
});

it("hides unknown capabilities, disables a pending save and makes failure visible", async () => {
  const props = { pending: false, error: false, onChange: vi.fn() };
  const view = render(<ModelReasoningControl {...props} data={{ ...data, options: [] }} />);
  expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  view.rerender(<ModelReasoningControl {...props} data={data} pending />);
  for (const radio of screen.getAllByRole("radio")) expect(radio).toHaveAttribute("aria-disabled", "true");
  const user = userEvent.setup();
  await user.click(screen.getByRole("radio", { name: "max" }));
  fireEvent.keyDown(screen.getByRole("radio", { name: "low" }), { key: "ArrowRight" });
  expect(props.onChange).not.toHaveBeenCalled();
  view.rerender(<ModelReasoningControl {...props} data={data} error />);
  expect(screen.getByRole("alert")).toHaveTextContent("Could not save reasoning effort");
});
