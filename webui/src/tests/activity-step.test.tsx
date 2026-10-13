import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import { ActivityStep } from "@/components/thread/activity/ActivityStep";

afterEach(cleanup);

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
