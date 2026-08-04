import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  ComboboxOption,
  useComboboxNavigation,
} from "@/components/ui/combobox";

const OPTIONS = ["Alpha", "Beta", "Gamma"];

function ComboboxHarness({ options = OPTIONS }: { options?: readonly string[] }) {
  const [open, setOpen] = useState(true);
  const [selected, setSelected] = useState("Beta");
  const navigation = useComboboxNavigation({
    open,
    values: options,
    selectedValue: selected,
    onSelect: setSelected,
    onClose: () => setOpen(false),
  });

  return (
    <>
      <input aria-label="Options" {...navigation.inputProps} />
      <button type="button" onClick={() => setOpen((current) => !current)}>
        {open ? "Close options" : "Open options"}
      </button>
      {open && options.length ? (
        <div {...navigation.listProps} aria-label="Available options">
          {options.map((option) => (
            <ComboboxOption key={option} {...navigation.getOptionProps(option)}>
              {option}
            </ComboboxOption>
          ))}
        </div>
      ) : null}
      <output aria-label="Selection">{selected}</output>
    </>
  );
}

describe("combobox navigation", () => {
  it("exposes listbox semantics and selects the active option from the keyboard", () => {
    render(<ComboboxHarness />);

    const input = screen.getByRole("combobox", { name: "Options" });
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("option", { name: "Beta" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "Beta" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(screen.getByRole("option", { name: "Gamma" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      screen.getByRole("option", { name: "Gamma" }).id,
    );
    fireEvent.keyDown(input, { key: "Enter" });

    expect(screen.getByRole("status", { name: "Selection" })).toHaveTextContent("Gamma");
  });

  it("preserves native text editing keys", () => {
    render(<ComboboxHarness />);

    const input = screen.getByRole("combobox", { name: "Options" });
    for (const key of ["Home", "End"]) {
      const event = createEvent.keyDown(input, { key });
      fireEvent(input, event);
      expect(event.defaultPrevented).toBe(false);
    }
  });

  it("restores the selected option after closing without a selection", () => {
    render(<ComboboxHarness />);

    const input = screen.getByRole("combobox", { name: "Options" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox", { name: "Available options" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open options" }));

    const selectedOption = screen.getByRole("option", { name: "Beta" });
    expect(input).toHaveAttribute("aria-activedescendant", selectedOption.id);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("status", { name: "Selection" })).toHaveTextContent("Beta");
  });

  it("collapses the combobox when no options are available", () => {
    render(<ComboboxHarness options={[]} />);

    const input = screen.getByRole("combobox", { name: "Options" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).not.toHaveAttribute("aria-controls");
    expect(input).not.toHaveAttribute("aria-activedescendant");

    const event = createEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent(input, event);
    expect(event.defaultPrevented).toBe(false);
  });

});
