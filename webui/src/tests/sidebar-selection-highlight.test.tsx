import { useRef } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SidebarSelectionHighlight } from "@/components/SidebarSelectionHighlight";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function Harness({ activeId, targetByRef }: { activeId: string | null; targetByRef: boolean }) {
  const target = useRef<HTMLButtonElement>(null);
  return <SidebarSelectionHighlight activeId={activeId} scope="test" data-testid="highlight-container"
    targetRef={targetByRef ? target : undefined}
    targetSelector={targetByRef ? undefined : "[aria-current=page]"}>
    <button ref={activeId === "first" ? target : undefined} aria-current={activeId === "first" ? "page" : undefined}>First</button>
    <button ref={activeId === "second" ? target : undefined} aria-current={activeId === "second" ? "page" : undefined}>Second</button>
  </SidebarSelectionHighlight>;
}

describe("sidebar selection highlight geometry", () => {
  it.each([true, false])("updates the animated width as its target resizes (target by ref: %s)", (targetByRef) => {
    let width = 272;
    let frameId = 0;
    const frames = new Map<number, FrameRequestCallback>();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      frames.set(++frameId, callback);
      return frameId;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
      frames.delete(id);
    });
    const paint = () => act(() => {
      const callbacks = [...frames.values()];
      frames.clear();
      callbacks.forEach((callback) => callback(performance.now()));
    });
    const resizes: Array<() => void> = [];
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: () => void) { resizes.push(callback); }
      observe() {}
      disconnect() {}
    });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const container = this.dataset.testid === "highlight-container";
      const second = this.textContent === "Second";
      const inset = container ? 0 : second ? 24 : 8;
      const x = 100 + inset;
      const y = container ? 20 : second ? 100 : 60;
      const w = container ? width : width - inset - 8;
      return { x, y, left: x, top: y, right: x + w, bottom: y + 32, width: w, height: 32, toJSON() {} };
    });
    const { rerender } = render(<Harness activeId="first" targetByRef={targetByRef} />);
    const highlight = screen.getByTestId("test-selection-highlight");
    expect(highlight).toHaveStyle({ width: "256px", height: "32px", transform: "translate3d(8px, 40px, 0)" });
    paint();

    // After initial placement, every observer update changes the animation's
    // destination rather than waiting for a pointer-up or resize-end event.
    rerender(<Harness activeId="first" targetByRef={targetByRef} />);
    width = 300;
    act(() => resizes.at(-1)?.());
    width = 420;
    act(() => resizes.at(-1)?.());
    expect(frames.size).toBe(1);
    expect(highlight).toHaveStyle({ width: "256px" });
    paint();
    expect(highlight).toHaveStyle({ width: "404px" });
    expect(highlight.style.transitionProperty).not.toBe("none");
    width = 320;
    act(() => resizes.at(-1)?.());
    paint();
    expect(highlight).toHaveStyle({ width: "304px" });
    expect(highlight.style.transitionProperty).not.toBe("none");
    rerender(<Harness activeId="second" targetByRef={targetByRef} />);
    paint();
    expect(highlight).toHaveStyle({ width: "288px", transform: "translate3d(24px, 80px, 0)" });
    expect(highlight.style.transitionProperty).not.toBe("none");
    act(() => resizes.at(-1)?.());
    expect(frames.size).toBe(1);
    rerender(<Harness activeId={null} targetByRef={targetByRef} />);
    expect(frames.size).toBe(0);
    expect(highlight).toHaveStyle({ opacity: "0" });
  });
});
