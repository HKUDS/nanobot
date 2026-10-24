import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { ModelPresetBadge } from "@/components/thread/ModelPresetBadge";
import { ModelReasoningControl } from "@/components/thread/ModelReasoningControl";

const data = { options: ["none", "low", "max"], value: null, presetValue: "low" };

it("shows the effective preset effort and allows direct session choices in the open model picker", async () => {
  const onChange = vi.fn();
  const onOpen = vi.fn();
  const user = userEvent.setup();
  function Example() {
    const [value, setValue] = useState<string | null>(null);
    return <ModelPresetBadge label="Default" modelPreset="default" isHero onPickerOpenChange={onOpen}
      reasoningControl={<ModelReasoningControl data={{ ...data, value }}
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

it("only offers the available recommendations and stays out of the way when none exist", () => {
  const onChange = vi.fn();
  const view = render(<ModelReasoningControl onChange={onChange} data={{ ...data, options: [] }} />);
  expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  view.rerender(<ModelReasoningControl onChange={onChange} data={data} />);
  expect(screen.getAllByRole("radio").map((radio) => radio.textContent)).toEqual(data.options);
  fireEvent.click(screen.getByRole("radio", { name: "max" }));
  expect(onChange).toHaveBeenCalledWith("max");
});
