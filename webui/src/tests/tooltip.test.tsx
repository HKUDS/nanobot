import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

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
