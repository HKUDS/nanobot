import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToggleButton } from "@/components/settings/ToggleButton";

describe("ToggleButton", () => {
  it("uses shared theme colors and compact dimensions in both states", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ToggleButton checked label="Feature" onChange={onChange} />,
    );
    const toggle = screen.getByRole("switch", { name: "Feature" });
    expect(toggle).toBeChecked();
    expect(toggle).toHaveClass("h-5", "w-9", "bg-foreground", "after:h-11", "after:w-11");
    expect(toggle.firstElementChild).toHaveClass("h-4", "w-4", "bg-background", "translate-x-[16px]");

    fireEvent.click(toggle);
    expect(onChange).toHaveBeenLastCalledWith(false);
    rerender(<ToggleButton checked={false} label="Feature" onChange={onChange} />);
    expect(toggle).not.toBeChecked();
    expect(toggle).toHaveClass("h-5", "w-9", "bg-muted-foreground/25");
    expect(toggle).not.toHaveClass("bg-foreground");
    expect(toggle.firstElementChild).toHaveClass("translate-x-0");
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenLastCalledWith(true);
  });

  it.each([false, true])("does not toggle while disabled (checked=%s)", (checked) => {
    const onChange = vi.fn();
    render(<ToggleButton checked={checked} disabled label="Feature" onChange={onChange} />);
    const toggle = screen.getByRole("switch", { name: "Feature" });
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveClass(checked ? "bg-foreground" : "bg-muted-foreground/25", "opacity-60");
    fireEvent.click(toggle);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps accessible labeling, keyboard activation, and button semantics", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onSubmit = vi.fn((event) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <p id="toggle-help">Enable this feature.</p>
        <ToggleButton
          id="feature-toggle"
          checked={false}
          label="Feature"
          ariaLabel="Enable feature"
          aria-describedby="toggle-help"
          aria-invalid
          onChange={onChange}
        />
      </form>,
    );
    const toggle = screen.getByRole("switch", { name: "Enable feature" });
    expect(toggle).toHaveAttribute("id", "feature-toggle");
    expect(toggle).toHaveAccessibleDescription("Enable this feature.");
    expect(toggle).toHaveAttribute("aria-invalid", "true");
    await user.tab();
    expect(toggle).toHaveFocus();
    await user.keyboard(" ");
    await user.keyboard("{Enter}");
    expect(onChange.mock.calls).toEqual([[true], [true]]);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
