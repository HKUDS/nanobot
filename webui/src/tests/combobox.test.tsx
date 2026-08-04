import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  ComboboxOption,
  useComboboxNavigation,
} from "@/components/ui/combobox";

const OPTIONS = ["Alpha", "Beta", "Gamma"];

function ComboboxHarness() {
  const [open, setOpen] = useState(true);
  const [selected, setSelected] = useState("Beta");
  const navigation = useComboboxNavigation({
    open,
    values: OPTIONS,
    selectedValue: selected,
    onSelect: setSelected,
    onClose: () => setOpen(false),
  });

  return (
    <>
      <input aria-label="Options" {...navigation.inputProps} />
      {open ? (
        <div {...navigation.listProps} aria-label="Available options">
          {OPTIONS.map((option) => (
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
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      screen.getByRole("option", { name: "Gamma" }).id,
    );
    fireEvent.keyDown(input, { key: "Enter" });

    expect(screen.getByRole("status", { name: "Selection" })).toHaveTextContent("Gamma");
  });

  it("closes the listbox on Escape", () => {
    render(<ComboboxHarness />);

    fireEvent.keyDown(screen.getByRole("combobox", { name: "Options" }), {
      key: "Escape",
    });

    expect(screen.queryByRole("listbox", { name: "Available options" })).not.toBeInTheDocument();
  });
});
