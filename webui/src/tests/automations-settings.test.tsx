import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { AutomationDeleteDialog, AutomationEditDialog, AutomationsSettings } from "@/components/settings/system/AutomationsSettings";
import type { AutomationFilter } from "@/components/settings/system/AutomationsSettings";
import i18n from "@/i18n";
import type { SessionAutomationJob, SettingsPayload } from "@/lib/types";

const now = Date.now();
const task: SessionAutomationJob = {
  id: "private-job-id", name: "PR watch", enabled: true,
  schedule: { kind: "every", every_ms: 1_800_000 },
  payload: { message: "Check open pull requests and report failed CI." },
  state: { next_run_at_ms: now + 540_000, last_run_at_ms: now - 60_000, last_status: "ok" },
  origin: { channel: "websocket", session_key: "websocket:demo", title: "nanobot-development" },
  created_at_ms: now - 86_400_000,
};
const systemTask: SessionAutomationJob = {
  ...task, id: "heartbeat", name: "heartbeat", protected: true, origin: null,
  payload: { message: "" },
};
const modelSettings = {
  agent: {
    model: "openai/gpt-5-mini",
    provider: "openai",
    resolved_provider: "openai",
    model_preset: "fast",
  },
  model_presets: [
    { name: "fast", model: "openai/gpt-5-mini", provider: "openai", active: true, is_default: false },
    { name: "deep", model: "openai/gpt-5", provider: "openai", active: false, is_default: false },
  ],
  model_call_order: ["fast", "deep"],
  providers: [{ name: "openai", label: "OpenAI", configured: true }],
} as SettingsPayload;
type Props = Partial<React.ComponentProps<typeof AutomationsSettings>>;
const SYSTEM_TASKS_OPEN_STORAGE_KEY = "nanobot-webui.automation-system-tasks-open";

function Harness({ payload = { jobs: [task, systemTask] }, ...props }: Props) {
  const [filter, setFilter] = useState<AutomationFilter>("all");
  return <AutomationsSettings
    payload={payload} loading={false} filter={filter}
    actionKey={null} error={null} onFilterChange={setFilter}
    onAction={() => {}} onRequestEdit={() => {}}
    onRequestDelete={() => {}} {...props}
  />;
}

beforeEach(() => {
  window.localStorage.removeItem(SYSTEM_TASKS_OPEN_STORAGE_KEY);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.localStorage.removeItem(SYSTEM_TASKS_OPEN_STORAGE_KEY);
});

describe("Automation task list and detail sheet", () => {
  it("avoids redundant headings and decorative uppercase group labels", () => {
    render(<Harness />);
    expect(screen.queryByRole("heading", { name: "Your automations" })).not.toBeInTheDocument();
    const month = new Intl.DateTimeFormat("en", { month: "long", year: "numeric" }).format(new Date());
    expect(screen.getByLabelText(month)).toBeVisible();
    const systemToggle = screen.getByRole("button", { name: "System tasks 1" });
    expect(systemToggle).toHaveClass("text-[13px]", "font-medium");
    expect(systemToggle).not.toHaveClass("uppercase", "tracking-[0.08em]");
  });

  it("opens system tasks by default and remembers manual changes across visits", () => {
    const first = render(<Harness />);
    expect(screen.getByRole("button", { name: "System tasks 1" })).toHaveAttribute("aria-expanded", "true");
    expect(window.localStorage.getItem(SYSTEM_TASKS_OPEN_STORAGE_KEY)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "System tasks 1" }));
    first.unmount();

    const second = render(<Harness />);
    expect(screen.getByRole("button", { name: "System tasks 1" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /heartbeat/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "System tasks 1" }));
    second.unmount();

    render(<Harness />);
    expect(screen.getByRole("button", { name: "System tasks 1" })).toHaveAttribute("aria-expanded", "true");
    expect(window.localStorage.getItem(SYSTEM_TASKS_OPEN_STORAGE_KEY)).toBe("true");
  });

  it("keeps the system toggle usable when browser storage is unavailable", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => { throw new Error("Blocked"); });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => { throw new Error("Blocked"); });
    render(<Harness />);
    const toggle = screen.getByRole("button", { name: "System tasks 1" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it.each(["Close", "Escape", "removed", "Edit", "Edit removed"])("finishes the detail exit before cleanup and handoff: %s", async (action) => {
    // Happy DOM has no CSS animations. Give Radix live animation names so its
    // real presence lifecycle runs, including the outer portal's ref boundary.
    const getStyle = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((node) => {
      const style = getStyle(node);
      if (node.getAttribute("role") !== "dialog") return style;
      return new Proxy(style, {
        get(target, property) {
          if (property === "animationName") return node.getAttribute("data-state") === "closed" ? "exit" : "enter";
          const value = Reflect.get(target, property, target);
          return typeof value === "function" ? value.bind(target) : value;
        },
      });
    });
    const user = userEvent.setup();
    const edit = vi.fn();
    const { rerender } = render(<Harness onRequestEdit={edit} />);
    const row = screen.getByRole("button", { name: /PR watch/ });
    await user.click(row);
    const dialog = screen.getByRole("dialog", { name: "PR watch" });
    if (action === "removed") rerender(<Harness payload={{ jobs: [] }} onRequestEdit={edit} />);
    else if (action === "Escape") fireEvent.keyDown(dialog, { key: "Escape" });
    else fireEvent.click(within(dialog).getByRole("button", { name: action.startsWith("Edit") ? "Edit" : action, exact: true }));
    if (action === "Edit removed") rerender(<Harness payload={{ jobs: [] }} onRequestEdit={edit} />);
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("data-state", "closed");
    expect(dialog).toHaveAttribute("inert");
    expect(dialog).toHaveTextContent("PR watch");
    expect(edit).not.toHaveBeenCalled();
    const exit = new Event("animationend", { bubbles: true });
    Object.defineProperty(exit, "animationName", { value: "exit" });
    fireEvent(dialog, exit);
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    if (action.includes("removed")) expect(screen.getByRole("heading", { name: "Automations" })).toHaveFocus();
    else await waitFor(() => expect(row).toHaveFocus());
    if (action === "Edit") {
      expect(edit).toHaveBeenCalledOnce();
      expect(edit).toHaveBeenCalledWith(task);
    }
    else expect(edit).not.toHaveBeenCalled();
  });

  it("keeps the default list quiet and opens details only on request", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Automations" })).toBeVisible();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Active/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /heartbeat/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Create in chat" })).not.toBeInTheDocument();
    const row = screen.getByRole("button", { name: /PR watch/ });
    await user.click(row);
    const dialog = screen.getByRole("dialog", { name: "PR watch" });
    expect(dialog).toHaveAccessibleDescription(/Every 30 minutes/);
    expect(within(dialog).getByText("Instructions")).toBeVisible();
    expect(within(dialog).getByRole("link", { name: "Open a chat" })).toHaveAttribute(
      "href", "#/chat/websocket%3Ademo",
    );
    expect(within(dialog).getByRole("button", { name: "More details" })).toHaveAttribute("aria-expanded", "false");
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(row).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog", { name: "PR watch" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(row).toHaveFocus();
  });

  it("opens both planned and recorded calendar blocks in details before linking to chat", async () => {
    const user = userEvent.setup();
    const jobWithHistory: SessionAutomationJob = {
      ...task,
      state: {
        ...task.state,
        run_history: [{ run_at_ms: now - 60_000, status: "ok", duration_ms: 120_000 }],
      },
    };
    render(<Harness payload={{ jobs: [jobWithHistory] }} />);

    const planned = screen.getByRole("button", { name: /PR watch.*Planned/ });
    const recorded = screen.getByRole("button", { name: /PR watch.*Recorded/ });
    expect(planned).toHaveAttribute("aria-haspopup", "dialog");
    expect(recorded).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.queryByRole("link", { name: /PR watch/ })).not.toBeInTheDocument();

    await user.click(recorded);
    const dialog = screen.getByRole("dialog", { name: "PR watch" });
    expect(within(dialog).getByRole("link", { name: "Open a chat" })).toHaveAttribute(
      "href", "#/chat/websocket%3Ademo",
    );
  });

  it("opens the whole day in a popover and hands off to details without expanding the grid", async () => {
    const user = userEvent.setup();
    const crowded = Array.from({ length: 5 }, (_, index): SessionAutomationJob => ({
      ...task,
      id: `crowded-${index + 1}`,
      name: `Crowded ${index + 1}`,
      state: { next_run_at_ms: now + 540_000 },
    }));
    render(<Harness payload={{ jobs: crowded }} />);

    const more = screen.getByRole("button", { name: "+2 more" });
    const day = more.closest(".automation-calendar-day")!;
    const dayLabel = day.getAttribute("aria-label")!;

    await user.click(more);
    const popover = screen.getByRole("dialog", { name: dayLabel });
    expect(within(popover).getAllByRole("button", { name: /Crowded.*Planned/ })).toHaveLength(5);
    expect(within(day as HTMLElement).getAllByRole("button", { name: /Crowded.*Planned/ })).toHaveLength(3);
    expect(more).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(more).toHaveFocus());
    expect(screen.queryByRole("button", { name: /Crowded 4.*Planned/ })).not.toBeInTheDocument();

    await user.click(more);
    await user.click(within(screen.getByRole("dialog", { name: dayLabel })).getByRole("button", { name: /Crowded 4.*Planned/ }));
    const detail = await screen.findByRole("dialog", { name: "Crowded 4" });
    expect(screen.queryByRole("dialog", { name: dayLabel })).not.toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "Open a chat" })).toBeVisible();
    await user.click(within(detail).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(more).toHaveFocus());
  });

  it("keeps the calendar and filters available when a status has no matches", async () => {
    const user = userEvent.setup();
    render(<Harness payload={{ jobs: [task] }} />);
    const month = screen.getByRole("heading", { level: 2 });
    await user.click(screen.getByRole("button", { name: "Paused 0" }));
    expect(month).toBeVisible();
    expect(screen.queryByRole("button", { name: /PR watch.*Planned/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "All 1" }));
    expect(screen.getByRole("button", { name: /PR watch.*Planned/ })).toBeVisible();
  });

  it("keeps creation compact until focused and preserves an unfocused draft", async () => {
    const user = userEvent.setup();
    render(<Harness onStartChat={vi.fn()} settingsSnapshot={modelSettings} />);
    const input = screen.getByRole("textbox", { name: "Describe an automation" });
    const surface = input.closest(".thread-composer-surface")!;
    expect(input).not.toHaveFocus();
    expect(surface).toHaveAttribute("data-compact", "true");
    await user.click(input);
    expect(surface).not.toHaveAttribute("data-compact");
    await user.type(input, "Review this project every Monday");
    await user.click(screen.getByRole("button", { name: "Today" }));
    expect(input).toHaveValue("Review this project every Monday");
    expect(surface).not.toHaveAttribute("data-compact");
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => expect(surface).toHaveAttribute("data-compact", "true"));
    await user.click(screen.getByRole("button", { name: "fast" }));
    expect(screen.getByRole("dialog", { name: "Switch model for this chat" })).toBeVisible();
    expect(surface).toHaveAttribute("data-compact", "true");
  });

  it("starts an automation conversation from the inline composer without opening a dialog", async () => {
    const user = userEvent.setup();
    const onStartChat = vi.fn().mockResolvedValue(true);
    render(<Harness
      payload={{ jobs: [] }}
      onStartChat={onStartChat}
      settingsSnapshot={modelSettings}
    />);

    const composer = screen.getByRole("textbox", { name: "Describe an automation" });
    await user.type(composer, "Every weekday at 9, summarize my open pull requests");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(onStartChat).toHaveBeenCalledWith(
      "Create an automation for this request:\n\nEvery weekday at 9, summarize my open pull requests",
      undefined,
      undefined,
      "fast",
    );
    await waitFor(() => expect(composer).toHaveValue(""));
  });

  it("uses the shared click picker and creates the chat with the selected model preset", async () => {
    const user = userEvent.setup();
    const onStartChat = vi.fn().mockResolvedValue(true);
    render(<Harness payload={{ jobs: [] }} onStartChat={onStartChat} settingsSnapshot={modelSettings} />);

    await user.click(screen.getByRole("button", { name: "fast" }));
    const picker = screen.getByRole("dialog", { name: "Switch model for this chat" });
    await user.click(within(picker).getByRole("option", { name: "deep" }));
    expect(screen.getByRole("button", { name: "deep" })).toBeVisible();

    const composer = screen.getByRole("textbox", { name: "Describe an automation" });
    await user.type(composer, "Run a deep weekly review");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(onStartChat).toHaveBeenCalledWith(
      "Create an automation for this request:\n\nRun a deep weekly review",
      undefined,
      undefined,
      "deep",
    );
  });

  it("keeps the main chat model chip's long-press drag behavior", () => {
    vi.useFakeTimers();
    const onStartChat = vi.fn().mockResolvedValue(true);
    render(<Harness payload={{ jobs: [] }} onStartChat={onStartChat} settingsSnapshot={modelSettings} />);

    const badge = screen.getByRole("button", { name: "fast" });
    fireEvent.pointerDown(badge, { pointerId: 1, pointerType: "touch", clientY: 100 });
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByTestId("composer-model-pill-viewport")).toBeInTheDocument();
    fireEvent.pointerMove(badge, { pointerId: 1, pointerType: "touch", clientY: 56 });
    fireEvent.pointerUp(badge, { pointerId: 1, pointerType: "touch", clientY: 56 });
    expect(screen.getByRole("button", { name: "deep" })).toBeVisible();
  });

  it("uses an automation-specific placeholder", () => {
    render(<Harness payload={{ jobs: [] }} onStartChat={() => {}} settingsSnapshot={modelSettings} />);
    expect(screen.getByRole("textbox", { name: "Describe an automation" })).toHaveAttribute(
      "placeholder",
      "What would you like nanobot to schedule?",
    );
  });

  it("uses a short, conversational Chinese creation prompt", async () => {
    await act(() => i18n.changeLanguage("zh-CN"));
    render(<Harness payload={{ jobs: [] }} onStartChat={() => {}} settingsSnapshot={modelSettings} />);
    expect(screen.getByRole("textbox", { name: "描述一个自动任务" })).toHaveAttribute(
      "placeholder", "想让 nanobot 定时帮你做什么？",
    );
  });

  it("keeps the complete month grid visible when no personal automations exist", () => {
    render(<Harness payload={{ jobs: [systemTask] }} />);
    expect(screen.queryByText("No automations yet.")).not.toBeInTheDocument();
    const calendar = document.querySelector(".automation-calendar")!;
    expect(calendar.querySelector(".automation-calendar-grid")).toBeInTheDocument();
    expect(calendar.querySelectorAll(".automation-calendar-weekdays > div")).toHaveLength(7);
    expect(calendar.querySelectorAll(".automation-calendar-day").length).toBeGreaterThanOrEqual(35);
    expect(screen.queryByRole("button", { name: "Create in chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open a chat" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Automations" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /heartbeat/ }));
    const dialog = screen.getByRole("dialog", { name: "heartbeat" });
    expect(within(dialog).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Linked chat")).not.toBeInTheDocument();
  });

  it("distinguishes a finished one-time task from a task with no scheduled run", () => {
    render(<Harness payload={{ jobs: [{ ...task, delete_after_run: true,
      state: { last_status: "ok", last_run_at_ms: now - 60_000, next_run_at_ms: null } }] }} />);
    expect(screen.getByRole("button", { name: /PR watch.*Completed/ })).toBeVisible();
    expect(screen.queryByText("No next run")).not.toBeInTheDocument();
  });

  it.each(["heartbeat", "dream", "other-system-job"])("shows only actual task data for %s", (id) => {
    render(<Harness payload={{ jobs: [{ ...systemTask, id, name: id, state: {
      next_run_at_ms: now + 540_000,
    } }] }} />);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(id) }));
    const dialog = screen.getByRole("dialog", { name: id });
    expect(dialog).toHaveClass("max-w-[440px]");
    expect(dialog).not.toHaveAttribute("aria-describedby");
    expect(dialog.querySelector("p")).toBeNull();
    expect(within(dialog).queryByText("Instructions")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("System-managed automation")).not.toBeInTheDocument();
    for (const label of ["Schedule", "Next run", "Last run"]) {
      expect(within(dialog).getByText(label).tagName).toBe("DT");
    }
    expect(within(dialog).getByText("Every 30 minutes")).toBeVisible();
    expect(within(dialog).getByText("Not run yet")).toBeVisible();
    expect(within(dialog).getAllByRole("button")).toHaveLength(2);
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveClass("rounded-full", "h-7", "w-7");
    const toggle = within(dialog).getByRole("button", { name: "More details" });
    const metadata = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(metadata).toHaveAttribute("data-state", "closed");
    fireEvent.click(toggle);
    expect(metadata).toHaveAttribute("data-state", "open");
    expect(within(metadata).getByText("ID")).toBeVisible();
    fireEvent.click(toggle);
    expect(metadata).toHaveAttribute("data-state", "closed");
    expect(metadata).toHaveAttribute("inert");
    expect(metadata).toHaveClass("inline-disclosure");
    expect(within(metadata).getByText("ID")).toBeInTheDocument();
  });

  it("keeps system failures visible and does not infer purpose from a task name", () => {
    render(<Harness payload={{ jobs: [{ ...systemTask, id: "other-system-job", name: "heartbeat",
      state: { last_status: "error", last_error: "Background check failed", next_run_at_ms: null },
    }] }} />);
    fireEvent.click(screen.getByRole("button", { name: /heartbeat/ }));
    const dialog = screen.getByRole("dialog", { name: "heartbeat" });
    expect(within(dialog).queryByText("System-managed automation")).not.toBeInTheDocument();
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Background check failed");
    expect(within(dialog).getByText("Failed")).toBeVisible();
    expect(within(dialog).getByText("No next run")).toBeVisible();
    expect(dialog).not.toHaveAttribute("aria-describedby");
  });

  it.each([task, systemTask])("uses shared dialog styling and quiet detail rows for $name", (job) => {
    render(<Harness payload={{ jobs: [job] }} />);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(job.name) }));
    const dialog = screen.getByRole("dialog", { name: job.name });
    expect(dialog).toHaveClass("rounded-modal");
    expect(dialog).not.toHaveClass("rounded-[20px]");
    const title = within(dialog).getByRole("heading", { name: job.name });
    expect(title).toHaveClass("text-lg", "leading-6");
    expect(title).not.toHaveClass("text-[22px]");
    const close = within(dialog).getByRole("button", { name: "Close" });
    expect(close).toHaveClass("rounded-full", "h-7", "w-7");
    const lastRun = within(dialog).getByText("Last run");
    expect(lastRun.closest("dl")).not.toHaveClass("divide-y", "border-y");
    expect(lastRun.parentElement).toHaveClass("py-2.5");
    const details = within(dialog).getByRole("button", { name: "More details" });
    expect(details.parentElement).not.toHaveClass("border-t");
    expect(details).toHaveAttribute("aria-expanded", "false");
    if (!job.protected) {
      const taskActions = within(dialog).getByRole("button", { name: "Pause" }).parentElement;
      expect(within(dialog).getByRole("button", { name: "Run now" }).parentElement).toBe(taskActions);
      expect(within(dialog).getByRole("button", { name: "Delete" }).parentElement).toBe(taskActions);
      const edit = within(dialog).getByRole("button", { name: "Edit" });
      expect(edit.parentElement).toHaveClass("sm:ml-auto", "flex-wrap", "justify-end");
      expect(within(dialog).getByRole("link", { name: "Open a chat" }).parentElement).toBe(edit.parentElement);
    }
  });

  it("keeps the header summary concise and moves timezone into more details", async () => {
    const user = userEvent.setup();
    render(<Harness payload={{ jobs: [{
      ...task,
      schedule: { kind: "cron", expr: "15 9 * * 1-5", tz: "Asia/Shanghai" },
    }] }} />);

    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    const dialog = screen.getByRole("dialog", { name: "PR watch" });
    const description = within(dialog).getByText("Weekdays at 09:15").parentElement!;
    expect(description).toHaveTextContent("Next");
    expect(description).not.toHaveTextContent("Asia/Shanghai");

    await user.click(within(dialog).getByRole("button", { name: "More details" }));
    expect(within(dialog).getByText("Timezone")).toBeVisible();
    expect(within(dialog).getByText("Asia/Shanghai")).toBeVisible();
  });

  it("uses the existing settings surfaces for the calendar and system task group", async () => {
    const user = userEvent.setup();
    render(<Harness payload={{ jobs: [task, systemTask, {
      ...systemTask, id: "dream", name: "dream",
      state: { last_status: "error", last_error: "Memory update failed" },
    }] }} />);
    expect(screen.getByRole("heading", { name: "Automations" })).toHaveClass("font-normal", "text-[24px]");
    const taskBlock = screen.getByRole("button", { name: /PR watch.*Planned/ });
    expect(taskBlock).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.queryByRole("button", { name: "Manage PR watch" })).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: "System tasks" });
    expect(taskBlock.closest("section")).toHaveClass("rounded-panel", "bg-[hsl(var(--settings-surface))]");
    expect(list.closest(".bg-settings-surface")).not.toBe(taskBlock.closest("section"));
    const filters = screen.getByRole("group", { name: "Automations" });
    expect(filters.closest(".automation-calendar-header")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 1" }).parentElement).toHaveClass("segmented-control", "flex-wrap");
    const heartbeat = within(list).getByRole("button", { name: /heartbeat/ });
    expect(heartbeat).toHaveClass("rounded-control", "settings-hover");
    expect(within(list).queryByText("System-managed automation")).not.toBeInTheDocument();
    expect(within(list).getByText("Memory update failed")).toBeVisible();
    expect(within(list).getByText("Needs attention")).toBeVisible();
    heartbeat.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog", { name: "heartbeat" })).toBeVisible();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(heartbeat).toHaveFocus());
  });

  it("keeps separators inside the date grid and omits an outside-month task list", () => {
    const outsideTask: SessionAutomationJob = {
      ...task,
      id: "outside-month",
      name: "Paused backlog review",
      enabled: false,
      state: {},
    };
    render(<Harness payload={{ jobs: [task, outsideTask] }} />);

    const calendar = screen.getByRole("button", { name: /PR watch.*Planned/ }).closest("section")!;
    expect(calendar).not.toHaveClass("border");
    const header = calendar.querySelector(".automation-calendar-header");
    expect(header).toHaveClass("bg-foreground/[0.025]");
    expect(header).not.toHaveClass("border-b");
    expect(header?.querySelector(".automation-calendar-weekdays")).toBeInTheDocument();
    expect(calendar.querySelector(".automation-meta-row")).not.toHaveClass("border-t");
    expect(calendar.querySelector(":scope > details")).toBeNull();
    expect(screen.queryByRole("button", { name: /Paused backlog review/ })).not.toBeInTheDocument();
    expect(calendar).not.toHaveTextContent("·");
  });

  it("renders schedule metadata as separate fields without dot separators", () => {
    const cronTask: SessionAutomationJob = {
      ...task,
      schedule: { kind: "cron", expr: "0 9 * * 1-5", tz: "Asia/Shanghai" },
    };
    render(<Harness payload={{ jobs: [cronTask] }} />);
    fireEvent.click(screen.getByRole("button", { name: /PR watch/ }));
    const dialog = screen.getByRole("dialog", { name: "PR watch" });
    expect(dialog).toHaveTextContent("Weekdays at 09:00");
    expect(dialog).toHaveTextContent("Asia/Shanghai");
    expect(dialog).not.toHaveTextContent("·");
  });

  it("keeps system tasks mounted for shared expand and collapse transitions without hidden tab stops", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const toggle = screen.getByRole("button", { name: "System tasks 1" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);
    const drawer = document.getElementById(toggle.getAttribute("aria-controls")!);
    expect(drawer).toHaveClass("inline-disclosure");
    expect(drawer).toHaveAttribute("data-state", "closed");
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(drawer!.firstElementChild).toHaveClass("inline-disclosure-clip");
    expect(drawer!.firstElementChild?.firstElementChild).toHaveClass("inline-disclosure-content");
    const row = within(drawer!).getByRole("button", { hidden: true });
    expect(row).toBeDisabled();
    toggle.focus();
    await user.tab();
    expect(row).not.toHaveFocus();

    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(drawer).toHaveAttribute("data-state", "open");
    expect(drawer).not.toHaveAttribute("aria-hidden");
    expect(row).toBeEnabled();
    await user.tab();
    expect(row).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog", { name: "heartbeat" })).toBeVisible();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(row).toHaveFocus());
    await user.tab({ shift: true });
    expect(toggle).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(document.getElementById("automation-system-tasks")).toBe(drawer);
    expect(drawer).toHaveAttribute("data-state", "closed");
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(row).toBeDisabled();
    expect(screen.queryByRole("button", { name: /heartbeat/ })).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByRole("button", { name: /heartbeat/ })).toBe(row);
  });

  it("keeps status filters immediately available", async () => {
    const user = userEvent.setup();
    render(<Harness payload={{ jobs: [task, {
      ...task,
      id: "paused",
      name: "Weekly review",
      enabled: false,
      state: { last_run_at_ms: now - 60_000, last_status: "ok" },
    }, systemTask] }} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Paused 1" }));
    expect(screen.queryByRole("button", { name: /PR watch/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Weekly review/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "Paused 1" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "All 2" }));
    expect(screen.queryByRole("button", { name: "Next run", exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /PR watch.*Planned/ })).toBeVisible();
  });

  it("uses live renamed chat titles in details without changing the bound task", async () => {
    const user = userEvent.setup();
    const action = vi.fn();
    const payload = { jobs: [task] };
    const longTitle = "Daily summary with completed work, blockers, and tomorrow's plan from the current conversation";
    const { rerender } = render(<Harness payload={payload} onAction={action}
      titleOverrides={{ "websocket:demo": longTitle }} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    const dialog = screen.getByRole("dialog", { name: "PR watch" });
    const chatLabel = within(dialog).getByText(longTitle);
    expect(chatLabel.closest("a")).toBeNull();
    expect(chatLabel).toHaveClass("truncate");
    expect(chatLabel).toHaveAttribute("title", longTitle);
    expect(dialog.querySelector(".lucide-chevron-right")).toBeNull();
    rerender(<Harness payload={payload} onAction={action}
      titleOverrides={{ "websocket:demo": "新会话名称" }} />);
    expect(within(dialog).getByText("新会话名称")).toBe(chatLabel);
    await user.click(within(dialog).getByRole("button", { name: "Pause" }));
    expect(action).toHaveBeenCalledWith("disable", expect.objectContaining({
      id: task.id, payload: task.payload,
      origin: expect.objectContaining({ session_key: "websocket:demo" }),
    }));
    expect(task.origin?.title).toBe("nanobot-development");
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    rerender(<Harness payload={payload} titleOverrides={{}} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    expect(screen.getByText("nanobot-development").closest("a")).toBeNull();
    expect(screen.getByRole("link", { name: "Open a chat" })).toHaveAttribute("href", "#/chat/websocket%3Ademo");
  });

  it("retains the inspected task across refreshes and closes if it is removed", () => {
    const action = vi.fn();
    const { rerender } = render(<Harness onAction={action} />);
    fireEvent.click(screen.getByRole("button", { name: /PR watch/ }));
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(action).toHaveBeenCalledWith("disable", task);
    rerender(<Harness payload={{ jobs: [{ ...task, enabled: false }] }} onAction={action} filter="active" />);
    expect(screen.getByRole("dialog", { name: "PR watch" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(action).toHaveBeenLastCalledWith("enable", { ...task, enabled: false });
    rerender(<Harness payload={{ jobs: [] }} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("returns focus to the page heading when the inspected row is no longer present", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness filter="active" />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    rerender(<Harness payload={{ jobs: [{ ...task, enabled: false }] }} filter="active" />);
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Automations" })).toHaveFocus());

    rerender(<Harness payload={{ jobs: [task] }} filter="all" />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    rerender(<Harness payload={{ jobs: [] }} filter="all" />);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Automations" })).toHaveFocus();
    expect(document.querySelectorAll(".automation-calendar-day").length).toBeGreaterThanOrEqual(35);
    expect(screen.queryByText("No automations yet.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /PR watch/ })).not.toBeInTheDocument();
  });

  it("uses chevrons only for disclosures, while task rows open dialogs", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const toggle = screen.getByRole("button", { name: "System tasks 1" });
    const chevron = toggle.querySelector("svg");
    expect(chevron).toHaveClass("lucide-chevron-down", "rotate-180");
    await user.click(toggle);
    expect(chevron).not.toHaveClass("rotate-180");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    for (const name of [/PR watch/, /heartbeat/]) {
      const row = screen.getByRole("button", { name });
      expect(row).toHaveAttribute("aria-haspopup", "dialog");
      expect(row.querySelector(".lucide-chevron-right, .lucide-chevron-down")).toBeNull();
      await user.click(row);
      const details = screen.getByRole("button", { name: "More details" });
      expect(details.querySelector("svg")).toHaveClass("lucide-chevron-down");
      await user.click(details);
      expect(details).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByRole("dialog")).toBeVisible();
      await user.click(screen.getByRole("button", { name: "Close" }));
    }
  });

  it("hands off editing and deletion without leaving a second modal open", async () => {
    const user = userEvent.setup();
    const edit = vi.fn();
    const remove = vi.fn();
    render(<Harness onRequestEdit={edit} onRequestDelete={remove} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await waitFor(() => expect(edit).toHaveBeenCalledWith(task));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(task));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each(["Cancel", "Delete"])("unlocks navigation after the real deletion flow ends with %s", async (operation) => {
    const previousPointerEvents = document.body.style.pointerEvents;
    onTestFinished(() => {
      cleanup();
      document.body.style.pointerEvents = previousPointerEvents;
    });
    // Exercise the real animated Radix presence lifecycle. The parent dialog
    // may finish its exit before its nested menu; both must release modality.
    const getStyle = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((node) => {
      const style = getStyle(node);
      if (node.getAttribute("role") !== "dialog") return style;
      return new Proxy(style, {
        get(target, property) {
          if (property === "animationName") return node.getAttribute("data-state") === "closed" ? "exit" : "enter";
          const value = Reflect.get(target, property, target);
          return typeof value === "function" ? value.bind(target) : value;
        },
      });
    });
    const finishExit = (node: HTMLElement) => {
      const exit = new Event("animationend", { bubbles: true });
      Object.defineProperty(exit, "animationName", { value: "exit" });
      fireEvent(node, exit);
    };
    const user = userEvent.setup();
    const navigate = vi.fn();
    function DeletionHarness() {
      const [jobs, setJobs] = useState([task, systemTask]);
      const [pending, setPending] = useState<SessionAutomationJob | null>(null);
      return <>
        <button onClick={navigate}>Sidebar Apps</button>
        <AutomationDeleteDialog job={pending} deleting={false}
          onOpenChange={(open) => { if (!open) setPending(null); }}
          onConfirm={(job) => {
            setJobs((items) => items.filter((item) => item.id !== job.id));
            setPending(null);
          }} />
        <Harness payload={{ jobs }} onRequestDelete={setPending} />
      </>;
    }
    render(<DeletionHarness />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    const detail = screen.getByRole("dialog", { name: "PR watch" });
    expect(document.body.style.pointerEvents).toBe("none");
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(detail).toHaveAttribute("data-state", "closed");
    finishExit(detail);
    const confirmation = await screen.findByRole("dialog", { name: "Delete automation" });
    expect(document.body.style.pointerEvents).toBe("none");
    await user.click(within(confirmation).getByRole("button", { name: operation, exact: true }));
    finishExit(confirmation);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body.style.pointerEvents).not.toBe("none");
    await user.click(screen.getByRole("button", { name: "Sidebar Apps" }));
    expect(navigate).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /PR watch/ }) !== null).toBe(operation === "Cancel");
  });

  it("returns to the same detail after cancelling or closing the real editor", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    function EditorHarness() {
      const [editing, setEditing] = useState<SessionAutomationJob | null>(null);
      const [returning, setReturning] = useState<SessionAutomationJob | null>(null);
      return <>
        <Harness
          onRequestEdit={setEditing}
          returnToDetailJob={returning}
          onReturnToDetailHandled={() => setReturning(null)}
        />
        <AutomationEditDialog job={editing} saving={false}
          onOpenChange={(open) => { if (!open) setEditing(null); }}
          onCancel={setReturning}
          onSave={(job, values) => { save(job, values); setEditing(null); }} />
      </>;
    }
    render(<EditorHarness />);
    const row = screen.getByRole("button", { name: /PR watch/ });
    for (const operation of ["Cancel", "Close"]) {
      if (!screen.queryByRole("dialog", { name: "PR watch" })) await user.click(row);
      await user.click(screen.getByRole("button", { name: "Edit", exact: true }));
      const editor = await screen.findByRole("dialog", { name: "Edit automation" });
      expect(screen.getAllByRole("dialog")).toHaveLength(1);
      await user.click(within(editor).getByRole("button", { name: operation, exact: true }));
      await waitFor(() => expect(screen.getByRole("dialog", { name: "PR watch" })).toBeVisible());
      expect(screen.getAllByRole("dialog")).toHaveLength(1);
    }
    expect(save).not.toHaveBeenCalled();
  });

  it("localizes the legacy destination error with a recovery path", async () => {
    await act(() => i18n.changeLanguage("zh-CN"));
    render(<Harness payload={{ jobs: [{
      ...task,
      state: {
        ...task.state,
        last_status: "error",
        last_error: "legacy cron payload is missing channel/to; recreate it from a chat session",
      },
    }] }} />);

    fireEvent.click(screen.getByRole("button", { name: /PR watch/ }));
    const detail = screen.getByRole("dialog", { name: "PR watch" });
    expect(within(detail).getByRole("alert")).toHaveTextContent(
      "这个旧版自动任务缺少发送目标，无法继续运行。请从关联会话中重新创建该任务。",
    );
    expect(detail).not.toHaveTextContent("legacy cron payload");
  });

  it("runs a linked task through the existing action and prevents duplicate actions while busy", async () => {
    const user = userEvent.setup();
    const action = vi.fn();
    const { rerender } = render(<Harness onAction={action} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    await user.click(screen.getByRole("button", { name: "Run now" }));
    expect(action).toHaveBeenCalledWith("run", task);
    rerender(<Harness actionKey="run:private-job-id" />);
    for (const name of ["Edit", "Pause", "Run now", "Delete"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    rerender(<Harness error="Unable to run task" />);
    expect(within(screen.getByRole("dialog")).getByRole("alert")).toHaveTextContent("Unable to run task");
  });

  it("does not allow running a pending task or resuming an unlinked task", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness payload={{ jobs: [{
      ...task, state: { pending: true, next_run_at_ms: now + 540_000 },
    }] }} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
    rerender(<Harness payload={{ jobs: [{ ...task, enabled: false, origin: null }] }} />);
    expect(screen.getByRole("button", { name: "Resume" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "Open a chat" })).not.toBeInTheDocument();
  });

  it("keeps local trigger commands and excludes the scheduled-run action", async () => {
    const user = userEvent.setup();
    render(<Harness payload={{ jobs: [{
      ...task, kind: "local_trigger", schedule: { kind: "local" },
      trigger: { id: "trigger-1", command: "nanobot trigger run trigger-1" },
    }] }} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    expect(screen.getByText("Command")).toBeVisible();
    expect(within(screen.getByRole("dialog")).getByText("nanobot trigger run trigger-1")).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Run now" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  it("shows paused failures honestly and does not fabricate successful runs", () => {
    render(<Harness payload={{ jobs: [{
      ...task, enabled: false, state: {
        last_status: "error", last_error: "Connection interrupted", last_run_at_ms: now - 60_000,
      },
    }, { ...systemTask, state: { last_status: "error" } }] }} />);
    const row = screen.getByRole("button", { name: /PR watch.*Failed/ });
    expect(screen.getByRole("button", { name: /System tasks 1 Needs attention/ })).toBeVisible();
    fireEvent.click(row);
    expect(within(screen.getByRole("dialog")).getByText("Failed")).toBeVisible();
    expect(within(screen.getByRole("dialog")).queryByText(/Completed/)).not.toBeInTheDocument();
  });

  it("allows expanding long instructions without exposing technical metadata by default", () => {
    render(<Harness payload={{ jobs: [{
      ...task,
      payload: { message: "Long instructions. ".repeat(50) },
      state: { next_run_at_ms: now + 540_000 },
    }] }} />);
    fireEvent.click(screen.getByRole("button", { name: /PR watch/ }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Not run yet")).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Show full message" }));
    expect(within(dialog).getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    const disclosure = within(dialog).getByRole("button", { name: "More details" });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(within(dialog).getByText("More details"));
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(within(dialog).getByText(task.id)).toBeVisible();
  });

  it.each(["", "  \n  "])("omits the instructions section when a task has no real message: %j", (message) => {
    render(<Harness payload={{ jobs: [{ ...task, payload: { message } }] }} />);
    fireEvent.click(screen.getByRole("button", { name: /PR watch/ }));
    const dialog = screen.getByRole("dialog", { name: "PR watch" });
    expect(within(dialog).queryByText("Instructions")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("System-managed automation")).not.toBeInTheDocument();
    expect(within(dialog).getByText("Last run")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Edit" })).toBeEnabled();
  });
});
