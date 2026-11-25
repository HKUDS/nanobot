import { fireEvent, render as renderUI, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReactElement } from "react";
import { ThreadToastViewport } from "@/components/ui/toast";
import { RecoveryNotice } from "@/components/thread/RecoveryNotice";

const render = (element: ReactElement) => renderUI(element, { wrapper: ThreadToastViewport });
const openDetails = () => fireEvent.click(screen.getByRole("button", { name: "Details" }));

const INTERRUPTED = {
  status: "awaiting_user" as const,
  recovery_id: "recovery-1",
  reason: "tool_state_unknown",
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

  it("keeps an active continuation hidden after remounting", async () => {
    const onContinue = vi.fn().mockResolvedValue(undefined);
    const onDismiss = vi.fn().mockResolvedValue(undefined);
    const { unmount } = render(
      <RecoveryNotice state={INTERRUPTED} onContinue={onContinue} onDismiss={onDismiss} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    unmount();

    render(
      <RecoveryNotice
        state={{ status: "resuming", recovery_id: "recovery-1" }}
        onContinue={onContinue}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the uncertain tool decision available and explains that tools are not replayed", () => {
    render(<RecoveryNotice state={INTERRUPTED} onContinue={vi.fn()} onDismiss={vi.fn()} />);
    const notice = screen.getByRole("alert");
    expect(notice).toHaveTextContent("A tool may already have run");
    expect(notice.closest(".toast-card")).toHaveAttribute("data-toast-timed", "false");
    openDetails();
    expect(screen.getByRole("dialog")).toHaveTextContent("Tools will not be replayed automatically.");
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
      expect(screen.getByRole("alert")).toHaveTextContent("Try the recovery action again");
    });
  });

  it.each(["awaiting_user", "failed"] as const)(
    "shows the decision surface again when a continuation returns to %s",
    async (status) => {
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
          state={{ ...INTERRUPTED, status, reason: "loop_guard" }}
          onContinue={onContinue}
          onDismiss={vi.fn().mockResolvedValue(undefined)}
        />,
      );

      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    },
  );

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

  it("keeps image recovery available without offering the same blocked retry", () => {
    const onInspectImagePreset = vi.fn();
    const state = { ...INTERRUPTED, reason: "model_request_failed", failure_error_kind: "unsupported_image" };
    const actions = { onContinue: vi.fn(), onDismiss: vi.fn(), onInspectImagePreset };
    const { rerender } = render(<RecoveryNotice state={state} {...actions} imageInputBlocked />);
    openDetails();
    expect(screen.getByRole("dialog")).toHaveTextContent("This request includes images");
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View preset" }));
    expect(onInspectImagePreset).toHaveBeenCalledOnce();

    rerender(<RecoveryNotice state={state} {...actions} imageInputBlocked={false} />);
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("shows model authorization recovery after loading saved state", () => {
    const onOpenSettings = vi.fn();
    render(
      <RecoveryNotice
        state={{ ...INTERRUPTED, reason: "model_request_failed", failure_error_kind: "authentication" }}
        onContinue={vi.fn().mockResolvedValue(undefined)}
        onDismiss={vi.fn().mockResolvedValue(undefined)}
        onOpenSettings={onOpenSettings}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Model provider authorization failed");
    expect(screen.getByRole("alert")).not.toHaveTextContent("Task interrupted");
    openDetails();
    fireEvent.click(screen.getByRole("button", { name: "Open model settings" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });
});


it("shows a saved reply without treating the failed request as completed", async () => {
  const onContinue = vi.fn().mockResolvedValue(undefined);
  const onDismiss = vi.fn().mockResolvedValue(undefined);
  const { rerender } = render(
    <RecoveryNotice
      state={{ ...INTERRUPTED, reason: "model_request_failed", failure_error_kind: "connection", reply_preserved: true }}
      onContinue={onContinue}
      onDismiss={onDismiss}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent("Model connection failed");
  openDetails();
  expect(screen.getByRole("dialog")).toHaveTextContent("Reply saved. You can continue.");
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(onContinue).toHaveBeenCalledOnce();

  rerender(
    <RecoveryNotice
      state={{ ...INTERRUPTED, recovery_id: "no-output", reason: "model_request_failed", failure_error_kind: "connection" }}
      onContinue={onContinue}
      onDismiss={onDismiss}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Model connection failed");
  openDetails();
  expect(screen.getByRole("dialog")).toHaveTextContent("Try again later or choose another model.");
});
