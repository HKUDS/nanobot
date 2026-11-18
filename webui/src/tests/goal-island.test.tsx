import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GoalIsland } from "@/components/thread/GoalIsland";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { ToastProvider } from "@/components/ui/toast";

const goal = { active: true, ui_summary: "Ship the release", objective: "Verify the full release checklist." };

function Conversation({ blocked = false }: { blocked?: boolean }) {
  return <>
    <ThreadHeader title="Release planning" onToggleSidebar={vi.fn()} theme="light" onToggleTheme={vi.fn()}
      goal={<GoalIsland goal={{ ...goal, active: !blocked, status: blocked ? "blocked" : "active", ...(blocked ? { recap: "Waiting for approval." } : {}) }} cancelDisabled={false} onCancel={async () => {}} />} />
    <ThreadComposer onSend={vi.fn()} persistDraft={false} goalState={goal} />
  </>;
}

describe("GoalIsland", () => {
  it("announces a rejected cancellation without closing the goal or disabling retry", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn().mockRejectedValueOnce(new Error("Could not cancel"));
    render(<GoalIsland goal={goal} cancelDisabled={false} onCancel={onCancel} />, { wrapper: ToastProvider });
    await user.click(screen.getByRole("button", { name: "Show full goal" }));
    const cancel = screen.getByRole("button", { name: "Cancel goal" });
    await user.click(cancel);
    const alert = await screen.findByRole("alert");
    expect(alert.closest("[data-toast-tone=error]")).not.toBeNull();
    expect(alert).toHaveTextContent("Could not cancel goal. Try again.");
    expect(screen.getByRole("dialog", { name: "Goal" })).toBeVisible();
    await user.click(cancel);
    expect(onCancel).toHaveBeenCalledTimes(2);
  });
  it("shows the summary and complete objective, dismissing through Escape and outside input without losing its draft", async () => {
    const user = userEvent.setup();
    render(<Conversation />);
    const input = screen.getByRole("textbox", { name: "Message input" });
    await user.type(input, "Keep my draft");
    const trigger = screen.getByRole("button", { name: "Show full goal" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Goal" });
    expect(dialog).toHaveTextContent(goal.ui_summary);
    expect(dialog).toHaveTextContent(goal.objective);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(input).toHaveFocus();
    await user.click(trigger);
    await user.click(input);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(input).toHaveValue("Keep my draft");
    expect(input).toHaveFocus();
  });

  it("returns keyboard-opened details to their trigger on Escape", async () => {
    const user = userEvent.setup();
    render(<Conversation />);
    await user.click(screen.getByRole("textbox", { name: "Message input" }));
    const trigger = screen.getByRole("button", { name: "Show full goal" });
    trigger.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog", { name: "Goal" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("updates the active goal to blocked with the gateway recap while keeping the expanded view", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Conversation />);
    await user.click(screen.getByRole("button", { name: "Show full goal" }));
    expect(screen.getByRole("heading", { name: goal.ui_summary })).toBeVisible();
    rerender(<Conversation blocked />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Blocked");
    expect(dialog).toHaveTextContent(/Waiting for approval\..*Verify the full release checklist\./);
  });
});
