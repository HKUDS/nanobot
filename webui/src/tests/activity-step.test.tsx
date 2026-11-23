import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileCode2 } from "lucide-react";
import { afterEach, expect, it, vi } from "vitest";

import { ActivityStep } from "@/components/thread/activity/ActivityStep";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("animates a running label with details and keeps the completed activity readable", () => {
  const { rerender } = render(<ActivityStep label="Running Blender" detail="--json project new" active />);

  expect(screen.getByText("Running Blender")).toHaveAttribute("data-sheen-text", "Running Blender");
  expect(screen.getByLabelText("Running Blender, --json project new")).toHaveTextContent("--json project new");

  rerender(<ActivityStep label="Used Blender" detail="--json project new" />);

  expect(screen.getByText("Used Blender")).toHaveClass("text-muted-foreground");
  expect(screen.getByLabelText("Used Blender, --json project new")).toHaveTextContent("Used Blender");
});

it("keeps truncated activity details available on keyboard focus", async () => {
  render(<ActivityStep label="Used Blender" detail="--json project new" />);
  const detail = screen.getByText("--json project new");
  Object.defineProperties(detail, {
    scrollWidth: { value: 240 },
    clientWidth: { value: 80 },
  });

  await userEvent.tab();

  expect(screen.getByLabelText("Used Blender, --json project new")).toHaveFocus();
  const tooltip = await screen.findByRole("tooltip");
  expect(within(tooltip).getByText(/Used Blender/)).toHaveTextContent("--json project new");
});

it("describes a named operation marker on keyboard focus before the file action", async () => {
  render(<ActivityStep icon={FileCode2} markerLabel="Created" label={<button>src/app.tsx</button>} />);

  await userEvent.tab();

  const marker = screen.getByRole("img", { name: "Created" });
  expect(marker).toHaveFocus();
  expect(marker.closest('[aria-hidden="true"]')).toBeNull();
  expect(screen.getByRole("tooltip")).toHaveTextContent("Created");

  await userEvent.tab();
  expect(screen.getByRole("button", { name: "src/app.tsx" })).toHaveFocus();
});

it("uses the shared hover delay for a named operation marker", () => {
  vi.useFakeTimers();
  render(<ActivityStep icon={FileCode2} markerLabel="Created" label={<span>src/app.tsx</span>} />);
  const marker = screen.getByRole("img", { name: "Created" });

  fireEvent.pointerMove(marker, { pointerType: "mouse" });
  act(() => vi.advanceTimersByTime(499));
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  act(() => vi.advanceTimersByTime(1));
  expect(screen.getByRole("tooltip")).toHaveTextContent("Created");
});
