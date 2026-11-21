import { useRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it } from "vitest";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useOverlayEscapeFocus } from "@/hooks/useOverlayEscapeFocus";
import { mockBrowserFocus } from "./browser-focus";

let restoreBrowserFocus: () => void;
beforeEach(() => { restoreBrowserFocus = mockBrowserFocus(); });
afterEach(() => restoreBrowserFocus());

function FocusFixture({ override = false }: { override?: boolean }) {
  const escapeFocus = useOverlayEscapeFocus();
  const destination = useRef<HTMLInputElement>(null);
  return <>
    <input aria-label="Editing field" />
    <Popover><PopoverTrigger asChild><button {...escapeFocus.triggerProps}>Open information</button></PopoverTrigger>
      <PopoverContent {...escapeFocus.contentProps} onCloseAutoFocus={(event) => {
        if (override) { event.preventDefault(); destination.current?.focus(); }
        escapeFocus.contentProps.onCloseAutoFocus(event);
      }}><input aria-label="Popover field" /></PopoverContent>
    </Popover>
    <input ref={destination} aria-label="Destination field" />
  </>;
}

it("returns pointer-open / Escape to the interrupted editing field", async () => {
  const user = userEvent.setup();
  render(<FocusFixture />);
  const editor = screen.getByRole("textbox", { name: "Editing field" });
  await user.click(editor);
  await user.click(screen.getByRole("button", { name: "Open information" }));
  await user.keyboard("{Escape}");
  await waitFor(() => expect(editor).toHaveFocus());
});

it("returns keyboard-open / Escape to the trigger", async () => {
  const user = userEvent.setup();
  render(<FocusFixture />);
  await user.tab();
  await user.tab();
  const trigger = screen.getByRole("button", { name: "Open information" });
  expect(trigger).toHaveFocus();
  await user.keyboard("{Enter}{Escape}");
  await waitFor(() => expect(trigger).toHaveFocus());
});

it("leaves outside-click focus with the clicked field", async () => {
  const user = userEvent.setup();
  render(<FocusFixture />);
  await user.click(screen.getByRole("textbox", { name: "Editing field" }));
  await user.click(screen.getByRole("button", { name: "Open information" }));
  const destination = screen.getByRole("textbox", { name: "Destination field" });
  await user.click(destination);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(destination).toHaveFocus();
});

it("honors a caller's explicit close-focus handoff", async () => {
  const user = userEvent.setup();
  render(<FocusFixture override />);
  await user.click(screen.getByRole("textbox", { name: "Editing field" }));
  await user.click(screen.getByRole("button", { name: "Open information" }));
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Destination field" })).toHaveFocus());
});
