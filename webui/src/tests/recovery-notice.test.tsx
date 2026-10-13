import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecoveryNotice } from "@/components/thread/RecoveryNotice";

const INTERRUPTED = {
  status: "awaiting_user" as const,
  recovery_id: "recovery-1",
  reason: "tool_state_uncertain",
};

describe("RecoveryNotice", () => {
  it("hides the internal resuming state after Continue is accepted", async () => {
    const onContinue = vi.fn().mockResolvedValue(undefined);

    render(
      <RecoveryNotice
        state={INTERRUPTED}
        onContinue={onContinue}
        onDismiss={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(onContinue).toHaveBeenCalledOnce();
  });

  it("uses the shared status surface and motion treatment", () => {
    render(
      <RecoveryNotice
        state={{ status: "resuming", recovery_id: "recovery-1" }}
        onContinue={vi.fn().mockResolvedValue(undefined)}
        onDismiss={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const notice = screen.getByRole("status");
    expect(notice).toHaveAttribute("data-recovery-status", "resuming");
    expect(notice).toHaveAttribute("aria-live", "polite");
    expect(notice).toHaveClass(
      "max-w-[49.5rem]",
      "rounded-control",
      "animate-in",
      "fade-in-0",
      "slide-in-from-bottom-1",
      "duration-200",
      "motion-reduce:animate-none",
    );
  });

  it("keeps the notice visible when Continue fails", async () => {
    const onContinue = vi.fn().mockRejectedValue(new Error("offline"));

    render(
      <RecoveryNotice
        state={INTERRUPTED}
        onContinue={onContinue}
        onDismiss={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Recovery action failed");
    });
  });

  it("shows the decision surface again when a continuation is interrupted", async () => {
    const onContinue = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <RecoveryNotice
        state={INTERRUPTED}
        onContinue={onContinue}
        onDismiss={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());

    rerender(
      <RecoveryNotice
        state={{ status: "resuming", recovery_id: "recovery-1" }}
        onContinue={onContinue}
        onDismiss={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    rerender(
      <RecoveryNotice
        state={{ ...INTERRUPTED, reason: "loop_guard" }}
        onContinue={onContinue}
        onDismiss={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("does not offer Continue when saved conversation context is unavailable", () => {
    render(
      <RecoveryNotice
        state={{ ...INTERRUPTED, can_continue: false }}
        onContinue={vi.fn().mockResolvedValue(undefined)}
        onDismiss={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });
});
