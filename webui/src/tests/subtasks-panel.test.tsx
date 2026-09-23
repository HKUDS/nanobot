import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readSubtasks, SubtasksPanel } from "@/components/thread/SubtasksPanel";
import { setAppLanguage } from "@/i18n";

const row = { task_id: "task", turn_id: "turn", label: "Review", revision: 1, state: "completed", iteration: 2,
  elapsed_ms: 12000, output: "Synthetic result", tools: ["read_file"], truncated: false };

describe("SubtasksPanel", () => {
  beforeEach(async () => { await setAppLanguage("en"); });
  it("expands task output without interpreting model HTML", async () => {
    const user = userEvent.setup();
    const requestMutation = vi.fn().mockResolvedValue({ tasks: [{ ...row, output: "<img src=x onerror=alert(1)>" }] });
    const { container } = render(<SubtasksPanel chatId="a" client={{ requestMutation }} />);
    await user.click(await screen.findByRole("button", { name: "Subtasks (1)" }));
    await user.click(screen.getByRole("button", { name: /Review/ }));
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
    expect(requestMutation).toHaveBeenCalledWith("subtasks.snapshot", { chat_id: "a" }, 10000);
  });
  it("unmount/remount isolates sessions and ignores an old reply", async () => {
    let resolve!: (value: unknown) => void;
    const requestMutation = vi.fn().mockImplementationOnce(() => new Promise((r) => { resolve = r; }))
      .mockResolvedValue({ tasks: [{ ...row, label: "B task" }] });
    const { rerender } = render(<SubtasksPanel key="a" chatId="a" client={{ requestMutation }} />);
    rerender(<SubtasksPanel key="b" chatId="b" client={{ requestMutation }} />);
    await screen.findByText("B task");
    await act(async () => resolve({ tasks: [row] }));
    expect(screen.queryByText("Review")).toBeNull();
    expect(screen.getByText("B task")).toBeInTheDocument();
  });
  it("shows stale status and allows retry without dropping a completed result", async () => {
    const user = userEvent.setup();
    const requestMutation = vi.fn().mockResolvedValueOnce({ tasks: [row] }).mockRejectedValue(new Error("offline"));
    render(<SubtasksPanel chatId="a" client={{ requestMutation }} />);
    await user.click(await screen.findByRole("button", { name: "Subtasks (1)" }));
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(await screen.findByText(/Connection unavailable/)).toBeVisible();
    expect(screen.getByText("Completed")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(requestMutation).toHaveBeenCalledTimes(3);
  });
  it("validates snapshots and caps the number of rows", () => {
    expect(() => readSubtasks({})).toThrow();
    expect(readSubtasks({ tasks: [{}, { ...row, state: "unknown" }, row] })).toEqual([row]);
    expect(readSubtasks({ tasks: Array(60).fill(row) })).toHaveLength(32);
  });
});
