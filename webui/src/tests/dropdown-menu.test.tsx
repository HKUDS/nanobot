import { createRef, useState, type ComponentProps } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function Menu({
  label = "Sections",
  contentProps,
  ...props
}: ComponentProps<typeof DropdownMenu> & {
  label?: string;
  contentProps?: ComponentProps<typeof DropdownMenuContent>;
}) {
  return (
    <DropdownMenu modal={false} {...props}>
      <DropdownMenuTrigger asChild><Button>{label}</Button></DropdownMenuTrigger>
      <DropdownMenuContent aria-label={`${label} menu`} aria-labelledby={undefined} {...contentProps}>
        <DropdownMenuItem>Overview</DropdownMenuItem>
        <DropdownMenuItem>Models</DropdownMenuItem>
        <DropdownMenuItem disabled>Unavailable</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ControlledMenu() {
  const [open, setOpen] = useState(false);
  return <Menu open={open} onOpenChange={setOpen} />;
}

describe("Dropdown menu focus ownership", () => {
  it.each(["uncontrolled", "controlled"])(
    "keeps a %s touch menu open when the browser returns focus to its trigger",
    async (mode) => {
      const user = userEvent.setup();
      render(mode === "controlled" ? <ControlledMenu /> : <Menu />);
      const trigger = screen.getByRole("button", { name: "Sections" });
      await user.pointer([
        { keys: "[TouchA>]", target: trigger },
        { keys: "[/TouchA]", target: trigger },
      ]);
      expect(screen.getByRole("menu")).toBeVisible();
      // Some mobile browsers focus the trigger after pointerdown has opened the menu.
      act(() => trigger.focus());
      expect(screen.getByRole("menu")).toBeVisible();
      expect(trigger).toHaveAttribute("aria-expanded", "true");
      expect(document.body.style.pointerEvents).not.toBe("none");
      await user.pointer([
        { keys: "[TouchA>]", target: screen.getByRole("menuitem", { name: "Models" }) },
        { keys: "[/TouchA]", target: screen.getByRole("menuitem", { name: "Models" }) },
      ]);
      await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
      expect(trigger).toHaveFocus();
    },
  );

  it("still dismisses when focus moves to a different control", async () => {
    const user = userEvent.setup();
    render(<><Menu /><button>Back to chat</button></>);
    const trigger = screen.getByRole("button", { name: "Sections" });
    await user.click(trigger);
    act(() => trigger.focus());
    act(() => screen.getByRole("button", { name: "Back to chat" }).focus());
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Back to chat" })).toHaveFocus();
  });

  it("does not treat another menu's trigger as its own", async () => {
    const user = userEvent.setup();
    render(<><Menu /><Menu label="Actions" /></>);
    await user.click(screen.getByRole("button", { name: "Sections" }));
    act(() => screen.getByRole("button", { name: "Actions" }).focus());
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menu", { name: "Actions menu" })).toBeVisible();
  });

  it.each(["trigger", "outside", "escape"])("dismisses with %s after trigger refocus", async (method) => {
    const user = userEvent.setup();
    const outsideAction = vi.fn();
    render(<><Menu /><button onClick={outsideAction}>Outside</button></>);
    const trigger = screen.getByRole("button", { name: "Sections" });
    await user.click(trigger);
    act(() => trigger.focus());
    if (method === "escape") await user.keyboard("{Escape}");
    else {
      const target = method === "trigger" ? trigger : screen.getByRole("button", { name: "Outside" });
      await user.pointer([{ keys: "[TouchA>]", target }, { keys: "[/TouchA]", target }]);
    }
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(outsideAction).toHaveBeenCalledTimes(method === "outside" ? 1 : 0);
    expect(method === "outside" ? screen.getByRole("button", { name: "Outside" }) : trigger).toHaveFocus();
    expect(document.body.style.pointerEvents).not.toBe("none");
  });

  it("preserves consumer focus handling and trigger refs", async () => {
    const user = userEvent.setup();
    const triggerRef = createRef<HTMLButtonElement>();
    const onFocusOutside = vi.fn((event: Event) => event.preventDefault());
    render(<>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger ref={triggerRef}>Sections</DropdownMenuTrigger>
        <DropdownMenuContent onFocusOutside={onFocusOutside}>
          <DropdownMenuItem>Overview</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <button>Outside</button>
    </>);
    expect(triggerRef.current).toBe(screen.getByRole("button", { name: "Sections" }));
    await user.click(triggerRef.current!);
    act(() => screen.getByRole("button", { name: "Outside" }).focus());
    expect(onFocusOutside).toHaveBeenCalledOnce();
    expect(screen.getByRole("menu")).toBeVisible();
  });
});
