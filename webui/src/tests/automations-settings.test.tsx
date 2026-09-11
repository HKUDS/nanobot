import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { AutomationDeleteDialog, AutomationEditDialog, AutomationsSettings } from "@/components/settings/system/AutomationsSettings";
import type { AutomationFilter, AutomationSort } from "@/components/settings/system/AutomationsSettings";
import type { SessionAutomationJob } from "@/lib/types";

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
type Props = Partial<React.ComponentProps<typeof AutomationsSettings>>;
const SYSTEM_TASKS_OPEN_STORAGE_KEY = "nanobot-webui.automation-system-tasks-open";

function Harness({ payload = { jobs: [task, systemTask] }, ...props }: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<AutomationFilter>("all");
  const [sort, setSort] = useState<AutomationSort>("next");
  return <AutomationsSettings
    payload={payload} loading={false} query={query} filter={filter} sort={sort}
    actionKey={null} error={null} onQueryChange={setQuery} onFilterChange={setFilter}
    onSortChange={setSort} onAction={() => {}} onRequestEdit={() => {}}
    onRequestDelete={() => {}} {...props}
  />;
}

beforeEach(() => {
  window.localStorage.removeItem(SYSTEM_TASKS_OPEN_STORAGE_KEY);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.removeItem(SYSTEM_TASKS_OPEN_STORAGE_KEY);
});

describe("Automation task list and detail sheet", () => {
  it("avoids redundant headings and decorative uppercase group labels", () => {
    render(<Harness />);
    expect(screen.queryByRole("heading", { name: "Your automations" })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Your automations" })).toBeVisible();
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

  it("does not replace a remembered collapse when search reveals system tasks", () => {
    window.localStorage.setItem(SYSTEM_TASKS_OPEN_STORAGE_KEY, "false");
    const view = render(<Harness query="heartbeat" />);
    expect(screen.getByRole("button", { name: /heartbeat/ })).toBeVisible();
    expect(window.localStorage.getItem(SYSTEM_TASKS_OPEN_STORAGE_KEY)).toBe("false");
    view.unmount();
    render(<Harness />);
    expect(screen.getByRole("button", { name: "System tasks 1" })).toHaveAttribute("aria-expanded", "false");
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

  it.each(["Done", "Escape", "removed", "Edit", "Edit removed"])("finishes the detail exit before cleanup and handoff: %s", async (action) => {
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
    expect(screen.getByRole("textbox")).toBeVisible();
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
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(row).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog", { name: "PR watch" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(row).toHaveFocus();
  });

  it("keeps a text-only empty state when only system tasks exist", () => {
    render(<Harness payload={{ jobs: [systemTask] }} />);
    expect(screen.getByText("No automations yet.")).toBeVisible();
    expect(screen.getByText("Tell nanobot in a chat what you'd like it to do on a schedule.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Create in chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open a chat" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Search and filter" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /heartbeat/ }));
    const dialog = screen.getByRole("dialog", { name: "heartbeat" });
    expect(within(dialog).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Linked chat")).not.toBeInTheDocument();
  });

  it("distinguishes a finished one-time task from a task with no scheduled run", () => {
    render(<Harness payload={{ jobs: [{ ...task, delete_after_run: true,
      state: { last_status: "ok", next_run_at_ms: null } }] }} />);
    expect(screen.getByRole("button", { name: /PR watch/ })).toHaveTextContent("Completed");
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
    expect(within(dialog).getByRole("button", { name: "Done" })).toHaveClass("text-foreground");
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

  it("uses channel search controls and the skills catalog surface for both task groups", async () => {
    const user = userEvent.setup();
    render(<Harness payload={{ jobs: [task, systemTask, {
      ...systemTask, id: "dream", name: "dream",
      state: { last_status: "error", last_error: "Memory update failed" },
    }] }} />);
    expect(screen.getByRole("heading", { name: "Automations" })).toHaveClass("font-normal", "text-[24px]");
    const personalRow = screen.getByRole("button", { name: /PR watch/ });
    expect(personalRow).toHaveClass("rounded-control", "px-2", "py-3", "settings-hover");
    const list = screen.getByRole("list", { name: "System tasks" });
    const surface = personalRow.closest(".bg-settings-surface");
    expect(surface).toHaveClass("rounded-panel");
    expect(list.closest(".bg-settings-surface")).toBe(surface);
    const search = screen.getByRole("textbox");
    expect(search.closest(".rounded-panel")).toBeNull();
    expect(search).toHaveClass("h-12", "bg-settings-surface", "focus-visible:bg-background");
    expect(screen.getByRole("button", { name: "All 1" }).parentElement).toHaveClass("segmented-control", "flex-wrap");
    const heartbeat = within(list).getByRole("button", { name: /heartbeat/ });
    expect(heartbeat.className).toBe(personalRow.className);
    expect(within(list).queryByText("System-managed automation")).not.toBeInTheDocument();
    expect(within(list).getByText("Memory update failed")).toBeVisible();
    expect(within(list).getByText("Needs attention")).toBeVisible();
    heartbeat.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog", { name: "heartbeat" })).toBeVisible();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(heartbeat).toHaveFocus());
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

  it("keeps search, status filters and sorting immediately available", async () => {
    const user = userEvent.setup();
    render(<Harness payload={{ jobs: [task, { ...task, id: "paused", name: "Weekly review", enabled: false }, systemTask] }} />);
    const search = screen.getByRole("textbox");
    expect(search).toBeVisible();
    expect(search).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Search and filter" })).not.toBeInTheDocument();
    await user.type(search, "chat:nanobot");
    expect(screen.getByRole("button", { name: /PR watch/ })).toBeVisible();
    await user.clear(search);
    await user.type(search, "heartbeat");
    expect(screen.getByRole("button", { name: /heartbeat/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "System tasks 1" })).toHaveAttribute("aria-expanded", "true");
    await user.clear(search);
    await user.click(screen.getByRole("button", { name: "Paused 1" }));
    expect(screen.queryByRole("button", { name: /PR watch/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Weekly review/ })).toBeVisible();
    expect(search).toBeVisible();
    expect(screen.getByRole("button", { name: "Paused 1" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "All 2" }));
    await user.click(screen.getByRole("button", { name: "Next run" }));
    await user.click(screen.getByRole("menuitem", { name: "Name" }));
    const rows = within(screen.getByRole("list", { name: "Your automations" })).getAllByRole("button");
    expect(rows[0]).toHaveTextContent("PR watch");
  });

  it("uses live renamed chat titles in details and search without changing the bound task", async () => {
    const user = userEvent.setup();
    const action = vi.fn();
    const payload = { jobs: [task] };
    const { rerender } = render(<Harness payload={payload} onAction={action}
      titleOverrides={{ "websocket:demo": "推特大战场" }} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    const dialog = screen.getByRole("dialog", { name: "PR watch" });
    const chatLink = within(dialog).getByRole("link", { name: "推特大战场" });
    expect(chatLink).toHaveAttribute("href", "#/chat/websocket%3Ademo");
    rerender(<Harness payload={payload} onAction={action}
      titleOverrides={{ "websocket:demo": "新会话名称" }} />);
    expect(within(dialog).getByRole("link", { name: "新会话名称" })).toBe(chatLink);
    await user.click(within(dialog).getByRole("button", { name: "Pause" }));
    expect(action).toHaveBeenCalledWith("disable", expect.objectContaining({
      id: task.id, payload: task.payload,
      origin: expect.objectContaining({ session_key: "websocket:demo" }),
    }));
    expect(task.origin?.title).toBe("nanobot-development");
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await user.type(screen.getByRole("textbox"), "chat:新会话名称");
    expect(screen.getByRole("button", { name: /PR watch/ })).toBeVisible();
    rerender(<Harness payload={payload} titleOverrides={{}} />);
    expect(screen.queryByRole("button", { name: /PR watch/ })).not.toBeInTheDocument();
    await user.clear(screen.getByRole("textbox"));
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    expect(screen.getByRole("link", { name: "nanobot-development" })).toHaveAttribute("href", "#/chat/websocket%3Ademo");
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

  it("keeps controls visible and preserves search when Escape dismisses sorting", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const search = screen.getByRole("textbox");
    expect(search).not.toHaveFocus();
    await user.tab();
    expect(search).toHaveFocus();
    await user.type(search, "PR");
    await user.keyboard("{Escape}");
    expect(search).toHaveValue("PR");
    expect(search).toHaveFocus();
    expect(search).toBeEnabled();
    fireEvent.keyDown(search, { key: "Escape", isComposing: true });
    expect(search).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Next run", exact: true }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next run", exact: true })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("region", { name: "Search and filter" })).toBeVisible();
    expect(search).toHaveValue("PR");
  });

  it("returns focus to search or the page heading when the inspected row is no longer present", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness filter="active" />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    rerender(<Harness payload={{ jobs: [{ ...task, enabled: false }] }} filter="active" />);
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveFocus());

    rerender(<Harness payload={{ jobs: [task] }} filter="all" />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    rerender(<Harness payload={{ jobs: [] }} filter="all" />);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Automations" })).toHaveFocus();
    expect(screen.getByText("No automations yet.")).toBeVisible();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
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
      await user.click(screen.getByRole("button", { name: "Done" }));
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
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
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
      if (!["menu", "dialog"].includes(node.getAttribute("role") ?? "")) return style;
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
    await user.click(screen.getByRole("button", { name: "More actions" }));
    expect(document.body.style.pointerEvents).toBe("none");
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
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

  it("returns keyboard focus to the task after cancelling or saving the real editor", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    function EditorHarness() {
      const [editing, setEditing] = useState<SessionAutomationJob | null>(null);
      return <>
        <Harness onRequestEdit={setEditing} />
        <AutomationEditDialog job={editing} saving={false}
          onOpenChange={(open) => { if (!open) setEditing(null); }}
          onSave={(job, values) => { save(job, values); setEditing(null); }} />
      </>;
    }
    render(<EditorHarness />);
    const row = screen.getByRole("button", { name: /PR watch/ });
    for (const operation of ["Cancel", "Save"]) {
      await user.click(row);
      await user.click(screen.getByRole("button", { name: "Edit", exact: true }));
      const editor = await screen.findByRole("dialog", { name: "Edit automation" });
      expect(screen.getAllByRole("dialog")).toHaveLength(1);
      if (operation === "Save") {
        await user.clear(within(editor).getByRole("textbox", { name: "Name", exact: true }));
        await user.type(within(editor).getByRole("textbox", { name: "Name", exact: true }), "Updated watch");
      }
      await user.click(within(editor).getByRole("button", { name: operation, exact: true }));
      await waitFor(() => expect(row).toHaveFocus());
    }
    expect(save).toHaveBeenCalledWith(task, expect.objectContaining({ name: "Updated watch" }));
  });

  it("runs a linked task through the existing action and prevents duplicate actions while busy", async () => {
    const user = userEvent.setup();
    const action = vi.fn();
    const { rerender } = render(<Harness onAction={action} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Run now" }));
    expect(action).toHaveBeenCalledWith("run", task);
    rerender(<Harness actionKey="run:private-job-id" />);
    for (const name of ["Edit", "Pause", "More actions"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    rerender(<Harness error="Unable to run task" />);
    expect(within(screen.getByRole("dialog")).getByRole("alert")).toHaveTextContent("Unable to run task");
  });

  it("does not allow running a pending task or resuming an unlinked task", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness payload={{ jobs: [{ ...task, state: { pending: true } }] }} />);
    await user.click(screen.getByRole("button", { name: /PR watch/ }));
    await user.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("menuitem", { name: "Run now" })).toHaveAttribute("aria-disabled", "true");
    await user.keyboard("{Escape}");
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
    await user.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.queryByRole("menuitem", { name: "Run now" })).not.toBeInTheDocument();
  });

  it("shows paused failures honestly and does not fabricate successful runs", () => {
    render(<Harness payload={{ jobs: [{
      ...task, enabled: false, state: { last_status: "error", last_error: "Connection interrupted" },
    }, { ...systemTask, state: { last_status: "error" } }] }} />);
    const row = screen.getByRole("button", { name: /PR watch/ });
    expect(row).toHaveTextContent("Needs attention");
    expect(row).toHaveTextContent("Paused");
    expect(screen.getByRole("button", { name: /System tasks 1 Needs attention/ })).toBeVisible();
    fireEvent.click(row);
    expect(within(screen.getByRole("dialog")).getByText("Failed")).toBeVisible();
    expect(within(screen.getByRole("dialog")).queryByText(/Completed/)).not.toBeInTheDocument();
  });

  it("allows expanding long instructions without exposing technical metadata by default", () => {
    render(<Harness payload={{ jobs: [{ ...task, payload: { message: "Long instructions. ".repeat(50) }, state: {} }] }} />);
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
});
