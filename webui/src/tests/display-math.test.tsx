import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DisplayMath } from "@/components/DisplayMath";

let availableWidth: number;
let formulaWidth: number;
let formulaHeight: number;
let resize: () => void;

beforeEach(() => {
  availableWidth = 1000;
  formulaWidth = 800;
  formulaHeight = 80;
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("math-fit") ? availableWidth : 0;
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("math-fit-content") ? formulaWidth : 0;
  });
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("math-fit-content") ? formulaHeight : 0;
  });
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { resize = callback; }
    observe() {}
    disconnect() {}
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("fits a wide formula on resize and restores its size without enlarging it", () => {
  const { container } = render(<DisplayMath><span>long equation</span></DisplayMath>);
  const frame = container.querySelector<HTMLElement>(".math-fit")!;
  const formula = container.querySelector<HTMLElement>(".math-fit-content")!;
  expect(frame.style.height).toBe("80px");
  expect(formula.style.transform).toContain("scale(1)");

  act(() => { availableWidth = 400; resize(); });
  expect(frame.style.height).toBe("40px");
  expect(formula.style.transform).toContain("scale(0.5)");
  expect(frame.textContent).toBe("long equation");

  act(() => { availableWidth = 1200; resize(); });
  expect(frame.style.height).toBe("80px");
  expect(formula.style.transform).toContain("scale(1)");
});

it("recalculates width and occupied height when a streaming formula grows", () => {
  availableWidth = 400;
  formulaWidth = 200;
  formulaHeight = 40;
  const { container, rerender } = render(<DisplayMath><span>initial equation</span></DisplayMath>);
  const frame = container.querySelector<HTMLElement>(".math-fit")!;
  expect(frame.style.height).toBe("40px");

  formulaWidth = 800;
  formulaHeight = 120;
  rerender(<DisplayMath><span>completed equation</span></DisplayMath>);
  expect(frame.style.height).toBe("60px");
  expect(container.querySelector<HTMLElement>(".math-fit-content")!.style.transform).toContain("scale(0.5)");
  expect(frame.textContent).toBe("completed equation");
});
