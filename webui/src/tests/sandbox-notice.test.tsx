import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SandboxNotice } from "@/components/thread/SandboxNotice";
import { useSandboxNotice } from "@/components/thread/useSandboxNotice";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { InboundEvent, ToolProgressEvent } from "@/lib/types";
import { createStreamClient } from "./stream-client";

function Harness({ client, chatId = "sandbox-chat", enabled = true, onOpen = () => {} }: {
  client: NanobotClient;
  chatId?: string;
  enabled?: boolean;
  onOpen?: () => void;
}) {
  const notice = useSandboxNotice(client, chatId, enabled);
  return <>
    <input aria-label="Draft" defaultValue="Keep my draft" />
    {notice.issue ? <SandboxNotice issue={notice.issue} onDismiss={notice.dismiss} onOpenSettings={onOpen} /> : null}
  </>;
}

function start(receive: (event: InboundEvent) => void, turnId = "turn-one") {
  receive({ event: "user_message", chat_id: "sandbox-chat", turn_id: turnId, starts_turn: true, text: "Run a command" });
}

function tool(receive: (event: InboundEvent) => void, values: Partial<ToolProgressEvent> = {}, turnId = "turn-one") {
  receive({ event: "message", chat_id: "sandbox-chat", turn_id: turnId, text: "", kind: "progress",
    tool_events: [{ name: "exec", phase: "error", call_id: "command-one", error_code: "sandbox_launcher_missing", ...values }] });
}

describe("Live sandbox guidance", () => {
  it.each([
    ["sandbox_path_unavailable", "Check its full path and access permissions"],
    ["sandbox_start_failed", "Check the gateway installation and system restrictions"],
  ])("explains the known launcher failure %s", (error_code, copy) => {
    const { client, receive } = createStreamClient();
    render(<Harness client={client} />);
    act(() => { start(receive); tool(receive, { error_code }); });
    expect(screen.getByRole("status")).toHaveTextContent(copy);
  });
  it("uses structured errors, keeps input focus, and offers one explicit recovery action", () => {
    const { client, receive } = createStreamClient();
    const onOpen = vi.fn();
    render(<Harness client={client} onOpen={onOpen} />);
    const draft = screen.getByRole("textbox", { name: "Draft" });
    draft.focus();
    act(() => {
      start(receive);
      tool(receive, { error_code: undefined, error: "Error: sandbox launcher not found: bwrap" });
      tool(receive, { error_code: "__proto__" });
      tool(receive, { name: "write_file" });
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    act(() => tool(receive));
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(draft).toHaveFocus();
    expect(draft).toHaveValue("Keep my draft");
    expect(screen.getByRole("status")).toHaveTextContent("sandbox launcher");
    expect(screen.getByRole("status")).not.toHaveTextContent(/bwrap|sandbox-exec/);
    expect(onOpen).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Open sandbox settings" }));
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("keeps a repeated failure dismissed for the turn and clears it after a real successful command", () => {
    const { client, receive } = createStreamClient();
    render(<Harness client={client} />);
    act(() => { start(receive); tool(receive); });
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    act(() => tool(receive, { call_id: "command-two" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    act(() => {
      receive({ event: "turn_end", chat_id: "sandbox-chat", turn_id: "turn-one" });
      start(receive, "turn-two");
      tool(receive, { call_id: "command-three" }, "turn-two");
    });
    expect(screen.getByRole("status")).toBeVisible();
    act(() => tool(receive, { phase: "end", error_code: undefined }, "turn-two"));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    act(() => tool(receive, { call_id: "late-command" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not replay old failures when opening a chat or enable controls for old hosts", () => {
    const { client, receive } = createStreamClient();
    start(receive);
    tool(receive);
    const view = render(<Harness client={client} enabled={false} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    view.rerender(<Harness client={client} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    act(() => tool(receive));
    expect(screen.getByRole("status")).toBeVisible();
  });

  it("does not carry a notice or its action into another host or chat", () => {
    const first = createStreamClient();
    const second = createStreamClient();
    const view = render(<Harness client={first.client} />);
    act(() => { start(first.receive); tool(first.receive); });
    expect(screen.getByRole("status")).toBeVisible();
    view.rerender(<Harness client={second.client} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    act(() => tool(first.receive, { error_code: "sandbox_unprotected_installation" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    act(() => { start(second.receive); tool(second.receive, { error_code: "sandbox_unprotected_installation" }); });
    expect(screen.getByRole("status")).toHaveTextContent(/protected location/);
    view.rerender(<Harness client={second.client} chatId="other-chat" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
