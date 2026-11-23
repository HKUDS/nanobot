import { act, createEvent, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

const originalAnimate = Object.getOwnPropertyDescriptor(Element.prototype, "animate");
let finish: (() => void) | null = null;
beforeEach(() => {
  // happy-dom has no WAAPI timeline; explicitly finish the browser-owned settlement.
  Object.defineProperty(Element.prototype, "animate", { configurable: true, value: () => ({
    cancel: vi.fn(),
    set onfinish(callback: () => void) { finish = callback; },
  }) });
});
afterEach(() => {
  if (originalAnimate) Object.defineProperty(Element.prototype, "animate", originalAnimate);
  else Reflect.deleteProperty(Element.prototype, "animate");
  finish = null;
});

function pointer(target: HTMLElement, type: "pointerDown" | "pointerMove" | "pointerUp" | "pointerCancel" | "lostPointerCapture", y: number, id = 1) {
  fireEvent(target, createEvent[type](target, { pointerId: id, pointerType: "touch", isPrimary: id === 1, button: 0, clientY: y }));
}
function openDrawer() {
  render(<Dialog><DialogTrigger>Open drawer</DialogTrigger><DialogContent placement="bottom" aria-describedby={undefined}>
    <DialogTitle>Details</DialogTitle>
  </DialogContent></Dialog>);
  fireEvent.click(screen.getByRole("button", { name: "Open drawer" }));
  const drawer = screen.getByRole("dialog");
  Object.defineProperty(drawer, "offsetHeight", { configurable: true, value: 500 });
  return { drawer, handle: screen.getByRole("button", { name: "Close" }) };
}

describe("shared bottom dialog drag", () => {
  it.each(["pointerUp", "pointerCancel", "lostPointerCapture"] as const)("rebounds without click-through after %s", (end) => {
    const { drawer, handle } = openDrawer();
    pointer(handle, "pointerDown", 100);
    pointer(handle, "pointerMove", end === "pointerUp" ? 115 : 260);
    pointer(handle, end, end === "pointerUp" ? 115 : 260);
    fireEvent.click(handle, { detail: 1 });
    expect(screen.getByRole("dialog")).toBe(drawer);
    act(() => finish?.());
    expect(drawer.style.translate).toBe("0 0px");
    expect(screen.getByRole("dialog")).toBe(drawer);
    fireEvent.click(handle);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ignores another touch ending over the handle while the first touch drags", () => {
    const { drawer, handle } = openDrawer();
    pointer(handle, "pointerDown", 100);
    pointer(handle, "pointerMove", 115);
    pointer(handle, "pointerDown", 115, 2);
    pointer(handle, "pointerUp", 200, 2);
    expect(finish).toBeNull();
    pointer(handle, "pointerMove", 120);
    expect(drawer.style.translate).toBe("0 20px");
    pointer(handle, "pointerCancel", 120);
    act(() => finish?.());
    expect(drawer.style.translate).toBe("0 0px");
  });
});
