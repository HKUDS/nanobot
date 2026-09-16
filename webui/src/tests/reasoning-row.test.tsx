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

it("bounds reasoning text without repainting a truncated label and keeps the complete tooltip current", async () => {
  const user = userEvent.setup();
  const text = "A long reasoning paragraph. ".repeat(2_000) + "original tail";
  const { container, rerender } = render(<ReasoningRow text={text} streaming />);
  const line = screen.getByTestId("activity-line");

  expect(line.textContent).toBe(text.slice(0, 512) + "…");
  expect(container.querySelector("[data-sheen-text]")).toBeNull();
  expect(screen.getByTestId("activity-reasoning-marker")).toHaveAttribute("data-state", "thinking");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

  await user.tab();
  expect(line).toHaveFocus();
  expect(await screen.findByRole("tooltip")).toHaveTextContent(text);
  rerender(<ReasoningRow text={text + " latest tail"} streaming />);
  expect(screen.getByRole("tooltip")).toHaveTextContent(text + " latest tail");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(line.textContent).toBe(text.slice(0, 512) + "…");
});

it("keeps the existing text animation for short active reasoning", () => {
  const { container } = render(<ReasoningRow text="Short active reasoning" streaming />);
  expect(container.querySelector("[data-sheen-text]")).toHaveAttribute("data-sheen-text", "Short active reasoning");
});

it("does not split a surrogate pair at the reasoning preview boundary", () => {
  render(<ReasoningRow text={"x".repeat(511) + "🚀 tail"} streaming />);
  expect(screen.getByTestId("activity-line").textContent).toBe("x".repeat(511) + "…");
});
