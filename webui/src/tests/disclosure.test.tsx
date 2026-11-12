import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Disclosure, DisclosureContent } from "@/components/ui/disclosure";
import { ExpandableText } from "@/components/ui/expandable-text";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("shared disclosures", () => {
  it("releases disposable content only after all closing transitions finish", async () => {
    const closed = vi.fn();
    const { container, rerender } = render(<DisclosureContent open onExitComplete={closed}>Diff</DisclosureContent>);
    let finishHeight!: () => void;
    let finishOpacity!: () => void;
    const height = new Promise<void>((resolve) => { finishHeight = resolve; });
    const opacity = new Promise<void>((resolve) => { finishOpacity = resolve; });
    Object.defineProperty(container.firstElementChild, "getAnimations", {
      value: () => [{ finished: height }, { finished: opacity }],
    });
    rerender(<DisclosureContent open={false} onExitComplete={closed}>Diff</DisclosureContent>);
    expect(closed).not.toHaveBeenCalled();
    expect(container.firstElementChild).toHaveAttribute("inert");
    await act(async () => { finishHeight(); });
    expect(closed).not.toHaveBeenCalled();
    await act(async () => { finishOpacity(); });
    expect(closed).toHaveBeenCalledOnce();
  });

  it.each(["reopen", "unmount"])("does not release content after %s interrupts a close", async (action) => {
    const closed = vi.fn();
    let finish!: () => void;
    const finished = new Promise<void>((resolve) => { finish = resolve; });
    const { container, rerender, unmount } = render(<DisclosureContent open onExitComplete={closed}>Diff</DisclosureContent>);
    Object.defineProperty(container.firstElementChild, "getAnimations", { value: () => [{ finished }] });
    rerender(<DisclosureContent open={false} onExitComplete={closed}>Diff</DisclosureContent>);
    if (action === "reopen") rerender(<DisclosureContent open onExitComplete={closed}>Diff</DisclosureContent>);
    else unmount();
    await act(async () => { finish(); });
    expect(closed).not.toHaveBeenCalled();
  });

  it("finishes immediately without motion and also handles a cancelled transition", async () => {
    const closed = vi.fn();
    const { container, rerender } = render(<DisclosureContent open onExitComplete={closed}>Diff</DisclosureContent>);
    const animations = vi.fn((): Array<{ finished: Promise<void> }> => []);
    Object.defineProperty(container.firstElementChild, "getAnimations", { value: animations });
    rerender(<DisclosureContent open={false} onExitComplete={closed}>Diff</DisclosureContent>);
    expect(closed).toHaveBeenCalledOnce();
    rerender(<DisclosureContent open onExitComplete={closed}>Diff</DisclosureContent>);
    let cancel!: () => void;
    const finished = new Promise<void>((_resolve, reject) => { cancel = () => reject(new Error("motion disabled")); });
    animations.mockReturnValue([{ finished }]);
    rerender(<DisclosureContent open={false} onExitComplete={closed}>Diff</DisclosureContent>);
    await act(async () => { cancel(); });
    expect(closed).toHaveBeenCalledTimes(2);
  });

  it("animates both ways without discarding form drafts, and hides collapsed controls", async () => {
    const user = userEvent.setup();
    render(<Disclosure summary="More details"><input aria-label="Draft" defaultValue="initial" /></Disclosure>);
    const toggle = screen.getByRole("button", { name: "More details" });
    const content = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(content).toHaveClass("inline-disclosure");
    expect(content).toHaveAttribute("data-state", "closed");
    expect(content).toHaveAttribute("inert");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(content).not.toHaveAttribute("inert");
    const input = screen.getByRole("textbox", { name: "Draft" });
    await user.clear(input);
    await user.type(input, "unsaved draft");
    await user.click(toggle);
    expect(toggle).toHaveFocus();
    expect(content).toHaveAttribute("data-state", "closed");
    expect(content).toHaveAttribute("aria-hidden", "true");
    expect(content).toHaveAttribute("inert");
    expect(input).toBeInTheDocument();
    await user.keyboard(" ");
    expect(screen.getByRole("textbox", { name: "Draft" })).toBe(input);
    expect(input).toHaveValue("unsaved draft");
  });

  it("keeps independent IDs and handles rapid reversals without timers or stale closing state", () => {
    render(<><Disclosure summary="First">One</Disclosure><Disclosure summary="Second">Two</Disclosure></>);
    const first = screen.getByRole("button", { name: "First" });
    const second = screen.getByRole("button", { name: "Second" });
    expect(first.getAttribute("aria-controls")).not.toBe(second.getAttribute("aria-controls"));
    const content = document.getElementById(first.getAttribute("aria-controls")!)!;
    for (let index = 0; index < 7; index++) fireEvent.click(first);
    expect(content).toHaveAttribute("data-state", "open");
    expect(second).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(first);
    expect(content).toHaveAttribute("data-state", "closed");
  });
});

describe("expandable text", () => {
  it("measures natural text height, handles resize and content changes, and preserves one text node", () => {
    let fullHeight = 280;
    let resize: ResizeObserverCallback | undefined;
    const disconnect = vi.fn();
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(() => fullHeight);
    const getStyle = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((node) => node.tagName === "P"
      ? { lineHeight: "20px" } as CSSStyleDeclaration : getStyle(node));
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: ResizeObserverCallback) { resize = callback; }
      observe() {}
      disconnect = disconnect;
    });
    const { container, rerender, unmount } = render(
      <ExpandableText lines={6} expanded={false}>Long instructions</ExpandableText>,
    );
    const viewport = container.firstElementChild!;
    const text = screen.getByText("Long instructions");
    expect(viewport).toHaveStyle({ height: "120px" });
    rerender(<ExpandableText lines={6} expanded>Long instructions</ExpandableText>);
    expect(viewport).toHaveStyle({ height: "280px" });
    expect(screen.getByText("Long instructions")).toBe(text);
    fullHeight = 380;
    act(() => resize?.([], {} as ResizeObserver));
    expect(viewport).toHaveStyle({ height: "380px" });
    rerender(<ExpandableText lines={6} expanded={false}>Long instructions</ExpandableText>);
    expect(viewport).toHaveStyle({ height: "120px" });
    fullHeight = 40;
    rerender(<ExpandableText lines={6} expanded={false}>Short replacement</ExpandableText>);
    expect(viewport).toHaveStyle({ height: "40px" });
    expect(container.querySelectorAll("p")).toHaveLength(1);
    unmount();
    expect(disconnect).toHaveBeenCalled();
  });
});
