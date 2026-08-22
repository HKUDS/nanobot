import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SubagentDetailPanel } from "@/components/thread/SubagentDetailPanel";
import type { SubagentDetailSnapshot } from "@/lib/types";

const DETAILS: SubagentDetailSnapshot[] = [
  {
    task_id: "task-a",
    label: "任务 A",
    status: "completed",
    input: "输入 A",
    output: "结果 A",
    steps: [{ kind: "tool_start", name: "读取文件", iteration: 1 }],
  },
  {
    task_id: "task-b",
    label: "任务 B",
    status: "failed",
    input: "输入 B",
    output: "结果 B",
  },
];

describe("SubagentDetailPanel", () => {
  it("shows only the opened tabs and supports closing one tab", () => {
    const onClose = vi.fn();
    render(
      <SubagentDetailPanel
        details={DETAILS}
        selectedTaskId="task-a"
        open
        onOpenChange={vi.fn()}
        onSelect={vi.fn()}
        onClose={onClose}
      />,
    );

    expect(screen.getByText("输入 A")).toBeInTheDocument();
    expect(screen.queryByText("输入 B")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭 任务 A" }));
    expect(onClose).toHaveBeenCalledWith("task-a");
  });

  it("uses the activity disclosure pattern for the execution process", () => {
    render(
      <SubagentDetailPanel
        details={DETAILS}
        selectedTaskId="task-a"
        open
        onOpenChange={vi.fn()}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const execution = screen.getByRole("button", { name: "执行过程" });
    expect(execution).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("读取文件")).not.toBeInTheDocument();

    fireEvent.click(execution);
    expect(execution).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("读取文件")).toBeInTheDocument();
  });

  it("renders as an embedded pane instead of a modal dialog", () => {
    render(
      <SubagentDetailPanel
        details={DETAILS}
        selectedTaskId="task-a"
        open
        onOpenChange={vi.fn()}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByTestId("subagent-detail-panel")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
