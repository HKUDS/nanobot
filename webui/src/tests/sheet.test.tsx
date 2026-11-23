import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

describe("sheet close button", () => {
  it("reserves the focus ring for keyboard navigation and restores focus after closing", async () => {
    const user = userEvent.setup();
    render(<Sheet>
      <SheetTrigger>Open details</SheetTrigger>
      <SheetContent>
        <SheetTitle>Task details</SheetTitle>
        <SheetDescription>Delegated task</SheetDescription>
      </SheetContent>
    </Sheet>);

    const trigger = screen.getByRole("button", { name: "Open details" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Task details" });
    const close = within(dialog).getByRole("button", { name: "Close" });
    expect(close).toHaveClass("focus-visible:ring-2", "focus-visible:ring-ring", "focus-visible:ring-offset-2");
    expect(close).not.toHaveClass("focus:ring-2");

    await user.click(close);
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
