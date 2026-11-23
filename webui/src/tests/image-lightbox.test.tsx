import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImageLightbox } from "@/components/ImageLightbox";
import { ImageViewport } from "@/components/ui/image-viewport";

afterEach(() => vi.unstubAllGlobals());

function renderImage() {
  const result = render(<ImageViewport src="data:image/png;base64,test" alt="Test chart" />);
  const viewport = screen.getByTestId("image-viewport");
  const image = screen.getByRole("img", { name: "Test chart" });
  Object.defineProperties(viewport, { clientWidth: { value: 800, configurable: true }, clientHeight: { value: 600, configurable: true } });
  Object.defineProperties(image, { offsetWidth: { value: 800, configurable: true }, offsetHeight: { value: 600, configurable: true } });
  viewport.getBoundingClientRect = () => new DOMRect(0, 0, 800, 600);
  return { ...result, viewport, image };
}

function wheel(target: Element, deltaY: number, ctrlKey = true) {
  const event = new WheelEvent("wheel", { deltaY, bubbles: true, cancelable: true });
  // happy-dom 16's WheelEvent extends UIEvent instead of MouseEvent and drops these fields.
  Object.defineProperties(event, { ctrlKey: { value: ctrlKey }, clientX: { value: 400 }, clientY: { value: 300 } });
  return fireEvent(target, event);
}

describe("image zoom", () => {
  it("pinches around the two-finger midpoint, then drags with the remaining finger", () => {
    const { viewport, image } = renderImage();
    fireEvent.pointerDown(viewport, { pointerId: 1, pointerType: "touch", button: 0, clientX: 300, clientY: 300 });
    fireEvent.pointerDown(viewport, { pointerId: 2, pointerType: "touch", button: 0, clientX: 500, clientY: 300 });
    fireEvent.pointerMove(viewport, { pointerId: 2, pointerType: "touch", clientX: 700, clientY: 300 });
    expect(image.style.transform).toBe("translate3d(100px, 0px, 0) scale(2)");
    fireEvent.pointerUp(viewport, { pointerId: 2, pointerType: "touch" });
    fireEvent.pointerMove(viewport, { pointerId: 1, pointerType: "touch", clientX: 400, clientY: 300 });
    expect(image.style.transform).toBe("translate3d(200px, 0px, 0) scale(2)");
    fireEvent.pointerMove(viewport, { pointerId: 1, pointerType: "touch", clientX: 9000, clientY: 9000 });
    expect(image.style.transform).toBe("translate3d(400px, 300px, 0) scale(2)");
    fireEvent.pointerCancel(viewport, { pointerId: 1 });
    fireEvent.pointerMove(viewport, { pointerId: 1, clientX: 300, clientY: 300 });
    expect(image.style.transform).toBe("translate3d(400px, 300px, 0) scale(2)");
    expect(viewport.className).not.toContain("cursor-grabbing");
    fireEvent.pointerDown(viewport, { pointerId: 3, button: 0, clientX: 400, clientY: 300 });
    fireEvent.pointerMove(viewport, { pointerId: 3, clientX: 300, clientY: 300 });
    expect(image.style.transform).toBe("translate3d(300px, 300px, 0) scale(2)");
    fireEvent.lostPointerCapture(viewport, { pointerId: 3 });
    fireEvent.pointerMove(viewport, { pointerId: 3, clientX: 200, clientY: 300 });
    expect(image.style.transform).toBe("translate3d(300px, 300px, 0) scale(2)");
    expect(viewport.className).not.toContain("cursor-grabbing");
    fireEvent.click(screen.getByRole("button", { name: "Fit image" }));
    expect(image.style.transform).toBe("translate3d(0px, 0px, 0) scale(1)");
  });

  it("supports trackpad pinch without hijacking browser zoom outside the image", () => {
    const { viewport, image } = renderImage();
    expect(wheel(viewport, 20, false)).toBe(true);
    expect(wheel(viewport, -50)).toBe(false);
    expect(image.style.transform).toContain(`scale(${Math.exp(0.5)})`);
    expect(wheel(document.body, -50)).toBe(true);
    expect(wheel(document.body, 20, false)).toBe(true);
    expect(wheel(viewport, 20, false)).toBe(false);
    expect(image.style.transform).toContain("-20px");
    for (let i = 0; i < 10; i++) wheel(viewport, -50);
    expect(image.style.transform).toContain("scale(8)");
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeDisabled();
    for (let i = 0; i < 10; i++) wheel(viewport, 50);
    expect(image.style.transform).toBe("translate3d(0px, 0px, 0) scale(1)");
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
  });

  it("supports double-click, keyboard and visible controls", () => {
    const { viewport, image } = renderImage();
    fireEvent.doubleClick(viewport, { clientX: 400, clientY: 300 });
    expect(image.style.transform).toContain("scale(2)");
    fireEvent.doubleClick(viewport, { clientX: 400, clientY: 300 });
    expect(image.style.transform).toContain("scale(1)");
    fireEvent.keyDown(viewport, { key: "=" });
    expect(screen.getByRole("button", { name: "Fit image" })).toHaveTextContent("150%");
    fireEvent.keyDown(viewport, { key: "-" });
    expect(image.style.transform).toContain("scale(1)");
    fireEvent.keyDown(viewport, { key: "+" });
    expect(screen.getByRole("button", { name: "Fit image" })).toHaveTextContent("150%");
    fireEvent.keyDown(viewport, { key: "0" });
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(image.style.transform).toContain("scale(1)");
  });

  it("pans with focused arrow keys within the image bounds", () => {
    const { viewport, image } = renderImage();
    viewport.focus();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(fireEvent.keyDown(viewport, { key: "ArrowRight" })).toBe(false);
    expect(image.style.transform).toBe("translate3d(-40px, 0px, 0) scale(1.5)");
    fireEvent.keyDown(viewport, { key: "ArrowDown" });
    expect(image.style.transform).toBe("translate3d(-40px, -40px, 0) scale(1.5)");
    fireEvent.keyDown(viewport, { key: "ArrowLeft" });
    fireEvent.keyDown(viewport, { key: "ArrowUp" });
    expect(image.style.transform).toBe("translate3d(0px, 0px, 0) scale(1.5)");
    for (let i = 0; i < 10; i++) {
      fireEvent.keyDown(viewport, { key: "ArrowRight" });
      fireEvent.keyDown(viewport, { key: "ArrowDown" });
    }
    expect(image.style.transform).toBe("translate3d(-200px, -150px, 0) scale(1.5)");
    fireEvent.keyDown(viewport, { key: "0" });
    expect(image.style.transform).toBe("translate3d(0px, 0px, 0) scale(1)");
  });

  it("leaves outside keys and browser zoom shortcuts alone", () => {
    const { viewport, image } = renderImage();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(fireEvent.keyDown(document.body, { key: "+" })).toBe(true);
    expect(fireEvent.keyDown(document.body, { key: "ArrowRight" })).toBe(true);
    expect(fireEvent.keyDown(viewport, { key: "+", ctrlKey: true })).toBe(true);
    expect(fireEvent.keyDown(viewport, { key: "0", metaKey: true })).toBe(true);
    expect(image.style.transform).toBe("translate3d(0px, 0px, 0) scale(1.5)");
  });

  it("reclamps on resize and image load, then releases observers, wheel and pointer capture", () => {
    let onResize: (() => void) | undefined;
    const observe = vi.fn();
    const disconnect = vi.fn();
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: () => void) { onResize = callback; }
      observe = observe;
      disconnect = disconnect;
    });
    const { viewport, image, unmount } = renderImage();
    const captured = new Set<number>();
    viewport.setPointerCapture = (id) => { captured.add(id); };
    viewport.hasPointerCapture = (id) => captured.has(id);
    const release = vi.fn((id: number) => { captured.delete(id); });
    viewport.releasePointerCapture = release;
    expect(observe).toHaveBeenCalledWith(viewport);
    fireEvent.doubleClick(viewport, { clientX: 400, clientY: 300 });
    fireEvent.pointerDown(viewport, { pointerId: 1, button: 0, clientX: 400, clientY: 300 });
    fireEvent.pointerMove(viewport, { pointerId: 1, clientX: 9000, clientY: 9000 });
    expect(image.style.transform).toBe("translate3d(400px, 300px, 0) scale(2)");
    Object.defineProperties(viewport, { clientWidth: { value: 1200 }, clientHeight: { value: 900 } });
    act(() => onResize?.());
    expect(image.style.transform).toBe("translate3d(200px, 150px, 0) scale(2)");
    Object.defineProperties(image, { offsetWidth: { value: 500 }, offsetHeight: { value: 400 } });
    fireEvent.load(image);
    expect(image.style.transform).toBe("translate3d(0px, 0px, 0) scale(2)");
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(release).toHaveBeenCalledWith(1);
    expect(wheel(viewport, -50)).toBe(true);
  });

  it("preserves left/right gallery navigation from the focused, zoomed photo viewport", () => {
    const images = [{ url: "data:image/png;base64,a", name: "A" }, { url: "data:image/png;base64,b", name: "B" }, { url: "data:image/png;base64,c", name: "C" }];
    const onIndexChange = vi.fn();
    render(<ImageLightbox images={images} index={1} onIndexChange={onIndexChange} onOpenChange={() => {}} />);
    const viewport = screen.getByTestId("image-zoom-viewport");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    viewport.focus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(onIndexChange.mock.calls).toEqual([[0], [2]]);
    expect(screen.getByRole("button", { name: "Fit image" })).toHaveTextContent("150%");
  });

  it("resets zoom when switching images and reopening the lightbox", () => {
    const images = [{ url: "data:image/png;base64,a", name: "A" }, { url: "data:image/png;base64,b", name: "B" }];
    const view = (index: number | null) => <ImageLightbox images={images} index={index} onIndexChange={() => {}} onOpenChange={() => {}} />;
    const { rerender } = render(view(0));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("button", { name: "Fit image" })).toHaveTextContent("150%");
    rerender(view(1));
    expect(within(screen.getByRole("dialog")).getByRole("img", { name: "B" }).style.transform).toContain("scale(1)");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    rerender(view(null));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    rerender(view(1));
    expect(screen.getByRole("button", { name: "Fit image" })).toHaveTextContent("100%");
  });
});
