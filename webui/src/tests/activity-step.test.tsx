import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import { ActivityStep } from "@/components/thread/activity/ActivityStep";

afterEach(cleanup);

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
