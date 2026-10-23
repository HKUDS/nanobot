import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { HoverHint, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

function Hints() {
  return <TooltipProvider>{["First", "Second"].map(label => (
    <Tooltip key={label}>
      <TooltipTrigger asChild><button>{label}</button></TooltipTrigger>
      <TooltipContent>{label} help</TooltipContent>
    </Tooltip>
  ))}</TooltipProvider>;
}

afterEach(() => vi.useRealTimers());

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
