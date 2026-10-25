import { useRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { HoverHint, Tooltip, TooltipContent, TooltipProvider, TooltipRegion, TooltipTrigger } from "@/components/ui/tooltip";

function Hints() {
  return <TooltipProvider>{["First", "Second"].map(label => (
    <Tooltip key={label}>
      <TooltipTrigger asChild><button>{label}</button></TooltipTrigger>
      <TooltipContent>{label} help</TooltipContent>
    </Tooltip>
  ))}</TooltipProvider>;
}

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("waits 500ms for each hover, including after a recently opened hint", () => {
  vi.useFakeTimers();
  render(<Hints />);
  for (const label of ["First", "Second"]) {
    const trigger = screen.getByRole("button", { name: label });
    fireEvent.pointerMove(trigger, { pointerType: "mouse" });
    act(() => vi.advanceTimersByTime(499));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("tooltip")).toHaveTextContent(`${label} help`);
    fireEvent.pointerLeave(trigger, { pointerType: "mouse" });
    fireEvent.pointerMove(document.body, { pointerType: "mouse", clientX: 1000, clientY: 1000 });
    act(() => vi.advanceTimersByTime(1));
  }
});

it("shows keyboard focus help immediately", () => {
  render(<Hints />);
  fireEvent.focus(screen.getByRole("button", { name: "First" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("First help");
});

it("does not revive a disabled hint without a fresh focus interaction", () => {
  const hint = (enabled: boolean) => <HoverHint enabled={enabled} content="Permission help"><button>Permission</button></HoverHint>;
  const { rerender } = render(hint(true));
  const trigger = screen.getByRole("button", { name: "Permission" });
  fireEvent.focus(trigger);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Permission help");
  rerender(hint(false));
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  rerender(hint(true));
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Permission" })).toBe(trigger);
  fireEvent.blur(trigger);
  fireEvent.focus(trigger);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Permission help");
});

function RegionalHint() {
  const scopeRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  return <TooltipRegion scopeRef={scopeRef} surfaceRef={scopeRef} editorRef={editorRef}>
    <div ref={scopeRef}>
      <textarea ref={editorRef} aria-label="Draft" />
      <HoverHint content="Permission help"><button>Permission</button></HoverHint>
    </div>
  </TooltipRegion>;
}

it("keeps the full hover delay after editing cancels pending and visible regional hints", () => {
  vi.useFakeTimers();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 100, 800, 100));
  render(<RegionalHint />);
  const trigger = screen.getByRole("button", { name: "Permission" });
  const editor = screen.getByRole("textbox", { name: "Draft" });
  const enter = () => {
    fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    fireEvent.pointerMove(trigger, { pointerType: "mouse" });
  };
  enter();
  act(() => vi.advanceTimersByTime(250));
  fireEvent.keyDown(editor, { key: "a" });
  act(() => vi.advanceTimersByTime(500));
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  for (let attempt = 0; attempt < 2; attempt++) {
    fireEvent.pointerLeave(trigger, { pointerType: "mouse" });
    enter();
    act(() => vi.advanceTimersByTime(499));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Permission help");
    fireEvent.keyDown(editor, { key: "a" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  }
  fireEvent.focus(trigger);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Permission help");
});
