import { createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ComposerUsagePopover } from "@/components/thread/ComposerUsagePopover";

function pointer(
  target: HTMLElement,
  type: "pointerDown" | "pointerMove" | "pointerUp" | "pointerCancel" | "lostPointerCapture",
  { y, x = 160, time = 1000, id = 1 }: { y: number; x?: number; time?: number; id?: number },
) {
  const event = createEvent[type](target, {
    pointerId: id, pointerType: "touch", isPrimary: true, button: 0, clientX: x, clientY: y,
  });
  Object.defineProperty(event, "timeStamp", { value: time });
  fireEvent(target, event);
}

async function openSheet() {
  const user = userEvent.setup();
  render(
    <ComposerUsagePopover
      bottomSheet
      showLabel
      context={{ contextTokens: 10000, contextWindowTokens: 200000 }}
      rounds={[
        { id: "round", timestamp: 0, inputTokens: 10000, cachedTokens: 8000 },
        { id: "round-2", timestamp: 60000, inputTokens: 14000, outputTokens: 280 },
      ]}
    />,
  );
  const trigger = screen.getByTestId("composer-context-usage");
  await user.click(trigger);
  const sheet = screen.getByRole("dialog", { name: "Context usage" });
  const handle = within(sheet).getByRole("button", { name: "Close" });
  return { user, trigger, sheet, handle };
}

describe("Mobile context usage sheet", () => {
  it("keeps tiny rounds tappable without exaggerating their visual token usage", async () => {
    const user = userEvent.setup();
    render(<ComposerUsagePopover bottomSheet context={null} rounds={[
      { id: "small", timestamp: 0, inputTokens: 1000 },
      { id: "large", timestamp: 60000, inputTokens: 500000 },
    ]} />);
    await user.click(screen.getByTestId("composer-context-usage"));
    const [small, large] = screen.getAllByTestId("round-usage-bar");
    for (const bar of [small, large]) {
      expect(bar.parentElement).toHaveClass("relative", "h-full", "flex-1");
      expect(bar).toHaveClass("before:absolute", "before:inset-0");
    }
    expect(small).toHaveStyle({ height: "0.216px" });
    expect(large).toHaveStyle({ height: "108px" });
    await user.pointer([{ keys: "[TouchA>]", target: small }, { keys: "[/TouchA]", target: small }]);
    expect(within(screen.getByRole("dialog", { name: "Context usage" })).getByRole("dialog"))
      .toHaveTextContent("1,000");
  });

  it("replaces the X with a keyboard-accessible drag handle", async () => {
    const { user, handle, sheet, trigger } = await openSheet();
    expect(within(sheet).getAllByRole("button", { name: "Close" })).toEqual([handle]);
    expect(handle.querySelector("svg")).toBeNull();
    expect(handle).toHaveClass("touch-none", "h-11");
    handle.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("keeps tapped round details open, switches rounds, and toggles the same bar closed", async () => {
    const { user, sheet } = await openSheet();
    const [first, second] = within(sheet).getAllByTestId("round-usage-bar");
    const tap = (target: HTMLElement) => user.pointer([
      { keys: "[TouchA>]", target },
      { keys: "[/TouchA]", target },
    ]);

    expect(first.tagName).toBe("BUTTON");
    await tap(first);
    const details = within(sheet).getByRole("dialog");
    expect(details).toHaveTextContent("10,000");
    expect(details).toHaveTextContent("80%");
    expect(first).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.pointerLeave(first, { pointerType: "touch" });
    expect(details).toBeVisible();

    await tap(second);
    await waitFor(() => expect(within(sheet).getAllByRole("dialog")).toHaveLength(1));
    expect(within(sheet).getByRole("dialog")).toHaveTextContent("14,000");
    expect(within(sheet).getByRole("dialog")).toHaveTextContent("280");
    expect(first).toHaveAttribute("aria-expanded", "false");
    expect(second).toHaveAttribute("aria-expanded", "true");

    await tap(second);
    await waitFor(() => expect(within(sheet).queryByRole("dialog")).not.toBeInTheDocument());
    expect(sheet).toBeVisible();
    await tap(first);
    await tap(within(sheet).getByRole("heading", { name: "Context usage" }));
    await waitFor(() => expect(within(sheet).queryByRole("dialog")).not.toBeInTheDocument());
    expect(sheet).toBeVisible();
  });

  it("dismisses nested round details with Escape before the sheet, and supports dragging with details open", async () => {
    const { user, sheet, handle, trigger } = await openSheet();
    const first = within(sheet).getAllByTestId("round-usage-bar")[0];
    first.focus();
    await user.keyboard("{Enter}");
    expect(within(sheet).getByRole("dialog")).toBeVisible();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(within(sheet).queryByRole("dialog")).not.toBeInTheDocument());
    expect(sheet).toBeVisible();
    expect(first).toHaveFocus();

    await user.click(first);
    pointer(handle, "pointerDown", { y: 400 });
    pointer(handle, "pointerMove", { y: 520, time: 1400 });
    pointer(handle, "pointerUp", { y: 520, time: 1500 });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body).not.toHaveStyle({ pointerEvents: "none" });
    expect(trigger).toHaveFocus();
  });

  it.each([
    [100, 500], // Deliberate pull.
    [32, 40], // Short, quick downward flick.
  ])("dismisses after dragging %dpx in %dms and opens at the original position", async (distance, duration) => {
    const { user, handle, sheet, trigger } = await openSheet();
    pointer(handle, "pointerDown", { y: 400 });
    pointer(handle, "pointerMove", { y: 400 + distance, time: 1000 + duration });
    // happy-dom doesn't expose individual transforms through getComputedStyle.
    expect(sheet.style.translate).toBe(`0 ${distance}px`);
    expect(sheet).toHaveStyle({ transition: "none" });
    pointer(handle, "pointerUp", { y: 400 + distance, time: 1000 + duration });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body).not.toHaveStyle({ pointerEvents: "none" });
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    expect(screen.getByRole("dialog").style.translate).toBe("0 0px");
  });

  it.each([
    { end: "pointerUp" as const, y: 432, x: 160 },
    { end: "pointerUp" as const, y: 370, x: 160 },
    { end: "pointerUp" as const, y: 460, x: 260 },
    { end: "pointerCancel" as const, y: 500, x: 160 },
    { end: "lostPointerCapture" as const, y: 500, x: 160 },
  ])("snaps back without a click-through on $end at ($x, $y)", async ({ end, y, x }) => {
    const { user, handle, sheet } = await openSheet();
    pointer(handle, "pointerDown", { y: 400 });
    pointer(handle, "pointerMove", { y, x, time: 1400 });
    pointer(handle, end, { y, x, time: 1500 });
    expect(sheet.style.translate).toBe("0 0px");
    expect(sheet.style.transition).toBe("");
    fireEvent.click(handle, { detail: 1 });
    expect(screen.getByRole("dialog")).toBeVisible();
    // A real subsequent tap must still close the sheet.
    await user.click(handle);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body).not.toHaveStyle({ pointerEvents: "none" });
  });

  it("does not capture content scrolling or let another pointer finish the drag", async () => {
    const { user, handle, sheet } = await openSheet();
    const content = within(sheet).getByRole("group", { name: "Input tokens" });
    pointer(content, "pointerDown", { y: 480 });
    pointer(content, "pointerMove", { y: 580 });
    pointer(content, "pointerUp", { y: 580, time: 1500 });
    expect(sheet.style.translate).toBe("0 0px");

    pointer(handle, "pointerDown", { y: 400 });
    pointer(handle, "pointerMove", { y: 412 });
    pointer(handle, "pointerDown", { y: 412, id: 2 });
    pointer(handle, "pointerUp", { y: 600, id: 2 });
    expect(sheet.style.translate).toBe("0 12px");
    pointer(handle, "pointerUp", { y: 412, time: 1500 });
    expect(sheet.style.translate).toBe("0 0px");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
