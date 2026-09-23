import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImageLightbox } from "@/components/ImageLightbox";
import { ZoomableImage } from "@/components/ZoomableImage";

function renderImage() {
  const result = render(<ZoomableImage src="data:image/png;base64,test" alt="Test chart" />);
  const viewport = screen.getByTestId("image-zoom-viewport");
  const image = screen.getByRole("img", { name: "Test chart" });
  Object.defineProperties(viewport, { clientWidth: { value: 800 }, clientHeight: { value: 600 } });
  Object.defineProperties(image, { offsetWidth: { value: 800 }, offsetHeight: { value: 600 } });
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
    fireEvent.click(screen.getByRole("button", { name: "Fit image" }));
    expect(image.style.transform).toBe("translate3d(0px, 0px, 0) scale(1)");
  });

  it("supports trackpad pinch without hijacking browser zoom outside the image", () => {
    const { viewport, image } = renderImage();
    expect(wheel(viewport, 20, false)).toBe(true);
    expect(wheel(viewport, -50)).toBe(false);
    expect(image.style.transform).toContain(`scale(${Math.exp(0.5)})`);
    expect(wheel(document.body, -50)).toBe(true);
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
    fireEvent.keyDown(viewport, { key: "+" });
    expect(screen.getByRole("button", { name: "Fit image" })).toHaveTextContent("150%");
    fireEvent.keyDown(viewport, { key: "0" });
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(image.style.transform).toContain("scale(1)");
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
