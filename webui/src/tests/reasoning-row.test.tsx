import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { ReasoningRow } from "@/components/thread/activity/ReasoningRow";

it("shows the reasoning preview in the shared tooltip on hover and keyboard focus", async () => {
  const user = userEvent.setup();
  const text = 'The user is saying "hi" again. I should respond in Chinese, concisely and in a friendly manner.';
  const { container } = render(<ReasoningRow text={text} streaming={false} />);
  const line = screen.getByTestId("activity-line");

  expect(container.querySelector("[title]")).toBeNull();
  await user.hover(line);
  expect(await screen.findByRole("tooltip")).toHaveTextContent(text);
  await user.unhover(line);
  await user.tab();
  expect(line).toHaveFocus();
  expect(await screen.findByRole("tooltip")).toHaveTextContent(text);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
