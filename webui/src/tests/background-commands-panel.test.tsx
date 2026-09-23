import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BackgroundCommandsPanel, readCommandDetail, readCommands } from "@/components/thread/BackgroundCommandsPanel";
import { setAppLanguage } from "@/i18n";

const row = { session_id: "123456789abc", command: "build --watch", cwd: "/workspace/demo", state: "running",
  elapsed_ms: 12000, exit_code: null };
const detail = { ...row, chunks: [{ seq: 1, stream: "stdout", text: "<script>synthetic</script>" }], omitted_chars: 0 };

describe("BackgroundCommandsPanel", () => {
  beforeEach(async () => { await setAppLanguage("en"); });
  it("shows literal output, follows logs, and confirms a targeted stop", async () => {
    const user = userEvent.setup();
    let stopped = false;
    const requestMutation = vi.fn().mockImplementation(async (action) => {
      if (action === "background.stop") stopped = true;
      const current = { ...row, state: stopped ? "stopped" : "running" };
      return action === "background.list" ? { commands: [current] } : { command: { ...detail, ...current } };
    });
    const { container } = render(<BackgroundCommandsPanel chatId="a" client={{ requestMutation }} />);
    await user.click(await screen.findByRole("button", { name: "Commands (1)" }));
    await user.click(screen.getByRole("button", { name: /build --watch/ }));
    expect(await screen.findByText("<script>synthetic</script>")).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Pause auto-scroll" }));
    expect(screen.getByRole("button", { name: "Follow output" })).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "Stop command" }));
    expect(requestMutation.mock.calls.some(([action]) => action === "background.stop")).toBe(false);
    await user.click(screen.getAllByRole("button", { name: "Stop command" })[1]);
    await waitFor(() => expect(screen.getByText("Stopped")).toBeVisible());
    expect(requestMutation).toHaveBeenCalledWith("background.stop", { chat_id: "a", session_id: row.session_id }, 15000);
  });
  it("isolates sessions even when the caller does not provide a React key", async () => {
    const user = userEvent.setup();
    let resolve!: (value: unknown) => void;
    const requestMutation = vi.fn().mockImplementation((action, payload) => {
      if (payload.chat_id === "b") return Promise.resolve({ commands: [] });
      if (action === "background.read") return new Promise((r) => { resolve = r; });
      return Promise.resolve({ commands: [row] });
    });
    const client = { requestMutation };
    const { rerender } = render(<BackgroundCommandsPanel chatId="a" client={client} />);
    await user.click(await screen.findByRole("button", { name: "Commands (1)" }));
    await user.click(screen.getByRole("button", { name: /build --watch/ }));
    await waitFor(() => expect(resolve).toBeDefined());
    rerender(<BackgroundCommandsPanel chatId="b" client={client} />);
    await act(async () => resolve({ command: detail }));
    expect(screen.queryByText("<script>synthetic</script>")).toBeNull();
    expect(screen.queryByRole("button", { name: "Commands (1)" })).toBeNull();
  });
  it("does not present stale running status as live and retries", async () => {
    const user = userEvent.setup();
    const requestMutation = vi.fn().mockResolvedValueOnce({ commands: [row] }).mockRejectedValue(new Error("offline"));
    render(<BackgroundCommandsPanel chatId="a" client={{ requestMutation }} />);
    await user.click(await screen.findByRole("button", { name: "Commands (1)" }));
    expect(await screen.findByText(/Connection lost/)).toBeVisible();
    expect(screen.getByText("Unknown")).toBeVisible();
    requestMutation.mockResolvedValue({ commands: [{ ...row, state: "completed", exit_code: 0 }] });
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Completed")).toBeVisible();
  });
  it("validates bounded output without rejecting supplementary Unicode characters", () => {
    expect(() => readCommands({ commands: [{ ...row, state: "magic" }] })).toThrow();
    expect(() => readCommands({ commands: Array(41).fill(row) })).toThrow();
    expect(() => readCommandDetail({ command: { ...detail, chunks: [{ seq: 1, stream: "html", text: "x" }] } })).toThrow();
    expect(readCommandDetail({ command: { ...detail, chunks: [{ seq: 1, stream: "stdout", text: "🙂".repeat(100000) }] } }).chunks).toHaveLength(1);
  });
  it("reports stop failures without claiming the command was stopped", async () => {
    const user = userEvent.setup();
    const requestMutation = vi.fn().mockImplementation(async (action) => {
      if (action === "background.stop") throw new Error("stop failed");
      return action === "background.list" ? { commands: [row] } : { command: detail };
    });
    render(<BackgroundCommandsPanel chatId="a" client={{ requestMutation }} />);
    await user.click(await screen.findByRole("button", { name: "Commands (1)" }));
    await user.click(screen.getByRole("button", { name: /build --watch/ }));
    await screen.findByText("<script>synthetic</script>");
    await user.click(screen.getByRole("button", { name: "Stop command" }));
    await user.click(screen.getAllByRole("button", { name: "Stop command" })[1]);
    expect(await screen.findByRole("alert")).toHaveTextContent("The action failed");
    expect(screen.getByText("Running")).toBeVisible();
    expect(screen.queryByText("Stopped")).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });
});
