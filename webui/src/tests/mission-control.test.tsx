import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActiveSessionDrawer } from "@/components/session/ActiveSessionDrawer";
import { MissionControlView } from "@/components/session/MissionControlView";
import { buildSessionIntelligence } from "@/lib/session-intelligence";
import type { ChatSummary } from "@/lib/types";

const NOW = Date.parse("2026-11-23T12:00:00Z");
const minsAgo = (mins: number) => new Date(NOW - mins * 60_000).toISOString();

function buildFixture() {
  const sessions: ChatSummary[] = [
    {
      key: "websocket:alpha-run",
      channel: "websocket",
      chatId: "alpha-run",
      createdAt: minsAgo(60),
      updatedAt: minsAgo(2),
      title: "Deploy ingress controller",
      preview: "Running helm upgrade",
      runStartedAt: (NOW - 90_000) / 1000,
      workspaceScope: { project_path: "/code/infra", project_name: "infra", access_mode: "restricted" },
      projectLocked: true,
    },
    {
      key: "websocket:alpha-ready",
      channel: "websocket",
      chatId: "alpha-ready",
      createdAt: minsAgo(120),
      updatedAt: minsAgo(15),
      title: "Fix arm64 cache",
      preview: "Workflow updated",
      workspaceScope: { project_path: "/code/infra", project_name: "infra", access_mode: "restricted" },
      projectLocked: true,
    },
    {
      key: "websocket:alpha-stale",
      channel: "websocket",
      chatId: "alpha-stale",
      createdAt: minsAgo(14_000),
      updatedAt: minsAgo(13_998),
      title: "One-off DNS lookup",
      preview: "TXT record format",
      workspaceScope: { project_path: "/code/infra", project_name: "infra", access_mode: "restricted" },
      projectLocked: true,
    },
    {
      key: "websocket:done-chat",
      channel: "websocket",
      chatId: "done-chat",
      createdAt: minsAgo(20_000),
      updatedAt: minsAgo(19_000),
      title: "Old finished task",
      preview: "Completed",
      workspaceScope: { project_path: "/code/infra", project_name: "infra", access_mode: "restricted" },
      projectLocked: true,
    },
  ];
  return buildSessionIntelligence(sessions, {
    pinnedKeys: [],
    archivedKeys: ["websocket:done-chat"],
    runningChatIds: ["alpha-run"],
    updatedChatIds: ["alpha-ready"],
    recoveryChatIds: [],
    titleOverrides: {},
    projectNameOverrides: {},
    automationCountsByKey: new Map(),
    paneGroups: {},
    activeKey: null,
    defaultWorkspacePath: "/workspace",
    generalLabel: "General",
    fallbackTitle: "New chat",
    nowMs: NOW,
  });
}

describe("MissionControlView & ActiveSessionDrawer", () => {
  afterEach(() => {
    cleanup();
  });

  it("surfaces running & ready-to-review attention cards, smart cleanup archive, and separate Done tab", () => {
    const intelligence = buildFixture();
    const onArchiveMany = vi.fn();
    const onSelectSession = vi.fn();

    render(
      <MissionControlView
        intelligence={intelligence}
        activeKey={null}
        onSelectSession={onSelectSession}
        onSelectWorkbenchGroup={() => {}}
        onNewChat={() => {}}
        onNewChatInProject={() => {}}
        onTogglePin={() => {}}
        onArchiveMany={onArchiveMany}
        onRequestDeleteMany={() => {}}
        onRequestRename={async () => {}}
        onRequestRenameProject={() => {}}
      />,
    );

    expect(screen.getAllByText("Deploy ingress controller")).toHaveLength(1);
    expect(screen.getAllByText("Fix arm64 cache")).toHaveLength(1);
    // Done session is isolated from the Open workspace view
    expect(screen.queryByText("Old finished task")).not.toBeInTheDocument();

    // Open Tidy tab and archive the stale candidate
    fireEvent.click(screen.getByRole("tab", { name: /Tidy|整理/ }));
    fireEvent.click(screen.getByRole("button", { name: /Archive \(1\)|结单所选 \(1\)/ }));
    expect(onArchiveMany).toHaveBeenCalledWith(["websocket:alpha-stale"], true);

    // Switching to Done tab reveals archived sessions with restore action
    fireEvent.click(screen.getByRole("tab", { name: /Done|已结单/ }));
    expect(screen.getByText("Old finished task")).toBeInTheDocument();
  });

  it("scopes Done counts to the selected project and keeps the selected project tab visible across Open and Done", () => {
    const sessions: ChatSummary[] = [
      {
        key: "websocket:alpha-open",
        channel: "websocket",
        chatId: "alpha-open",
        createdAt: minsAgo(60),
        updatedAt: minsAgo(10),
        title: "Alpha active thread",
        preview: "",
        workspaceScope: { project_path: "/code/alpha", project_name: "alpha", access_mode: "restricted" },
        projectLocked: true,
      },
      {
        key: "websocket:beta-done",
        channel: "websocket",
        chatId: "beta-done",
        createdAt: minsAgo(20_000),
        updatedAt: minsAgo(19_000),
        title: "Beta archived thread",
        preview: "",
        workspaceScope: { project_path: "/code/beta", project_name: "beta", access_mode: "restricted" },
        projectLocked: true,
      },
    ];
    const intelligence = buildSessionIntelligence(sessions, {
      pinnedKeys: [],
      archivedKeys: ["websocket:beta-done"],
      runningChatIds: [],
      updatedChatIds: [],
      recoveryChatIds: [],
      titleOverrides: {},
      projectNameOverrides: {},
      automationCountsByKey: new Map(),
      paneGroups: {},
      activeKey: null,
      defaultWorkspacePath: "/workspace",
      generalLabel: "General",
      fallbackTitle: "New chat",
      nowMs: NOW,
    });

    render(
      <MissionControlView
        intelligence={intelligence}
        activeKey={null}
        onSelectSession={() => {}}
        onSelectWorkbenchGroup={() => {}}
        onNewChat={() => {}}
        onNewChatInProject={() => {}}
        onTogglePin={() => {}}
        onArchiveMany={() => {}}
        onRequestDeleteMany={() => {}}
        onRequestRename={async () => {}}
        onRequestRenameProject={() => {}}
      />,
    );

    // Globally Done shows count 1
    expect(screen.getByRole("tab", { name: /Done|已结单/ })).toHaveTextContent("1");

    // Filtering to alpha (0 archived) removes the stale global count from Done tab
    fireEvent.click(screen.getByRole("tab", { name: "alpha" }));
    expect(screen.getByRole("tab", { name: /Done|已结单/ })).not.toHaveTextContent("1");

    // Switching to Done keeps the selected alpha tab visible and active
    fireEvent.click(screen.getByRole("tab", { name: /Done|已结单/ }));
    expect(screen.getByRole("tab", { name: "alpha" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Beta archived thread")).not.toBeInTheDocument();
  });

  it("supports keyboard focus navigation with scrollIntoView, Escape reset, and safe archiving on non-live rows", () => {
    vi.useFakeTimers();
    try {
      const intelligence = buildFixture();
      const onArchiveMany = vi.fn();
      const onSelectSession = vi.fn();
      const scrollSpy = vi.fn();

      const { container } = render(
        <MissionControlView
          intelligence={intelligence}
          activeKey={null}
          onSelectSession={onSelectSession}
          onSelectWorkbenchGroup={() => {}}
          onNewChat={() => {}}
          onNewChatInProject={() => {}}
          onTogglePin={() => {}}
          onArchiveMany={onArchiveMany}
          onRequestDeleteMany={() => {}}
          onRequestRename={async () => {}}
          onRequestRenameProject={() => {}}
        />,
      );

      for (const row of container.querySelectorAll("[data-mission-session-row]")) {
        row.scrollIntoView = scrollSpy;
      }

      // First j focuses the live running tile; pressing e must NOT archive a live running session
      fireEvent.keyDown(window, { key: "j" });
      expect(scrollSpy).toHaveBeenCalledTimes(1);
      fireEvent.keyDown(window, { key: "e" });
      act(() => {
        vi.advanceTimersByTime(250);
      });
      expect(onArchiveMany).not.toHaveBeenCalled();

      // Next j focuses the non-live row; Enter opens it and e archives it
      fireEvent.keyDown(window, { key: "j" });
      fireEvent.keyDown(window, { key: "Enter" });
      expect(onSelectSession).toHaveBeenCalledWith("websocket:alpha-ready");

      fireEvent.keyDown(window, { key: "e" });
      act(() => {
        vi.advanceTimersByTime(250);
      });
      expect(onArchiveMany).toHaveBeenCalledWith(["websocket:alpha-ready"], true);

      // Escape clears keyboard focus cleanly
      fireEvent.keyDown(window, { key: "Escape" });
      fireEvent.keyDown(window, { key: "Enter" });
      expect(onSelectSession).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens project-scoped Tidy review instead of archiving immediately when clicking project header Tidy", () => {
    const intelligence = buildFixture();
    const onArchiveMany = vi.fn();

    render(
      <MissionControlView
        intelligence={intelligence}
        activeKey={null}
        onSelectSession={() => {}}
        onSelectWorkbenchGroup={() => {}}
        onNewChat={() => {}}
        onNewChatInProject={() => {}}
        onTogglePin={() => {}}
        onArchiveMany={onArchiveMany}
        onRequestDeleteMany={() => {}}
        onRequestRename={async () => {}}
        onRequestRenameProject={() => {}}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Tidy \(1\)|整理 \(1\)/ }));
    expect(onArchiveMany).not.toHaveBeenCalled();
    expect(screen.getByRole("tab", { name: /Tidy|整理/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "infra" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps live running and unread rollup badges visible on collapsed project headers in ActiveSessionDrawer", () => {
    const intelligence = buildFixture();
    const infraId = intelligence.projects[0].project.id;

    render(
      <ActiveSessionDrawer
        open
        pinned={false}
        intelligence={intelligence}
        temporarySessions={[]}
        activeKey={null}
        collapsedGroups={{ [infraId]: true }}
        onClose={() => {}}
        onTogglePinDrawer={() => {}}
        onSelectSession={() => {}}
        onToggleGroup={() => {}}
        onNewChat={() => {}}
        onNewChatInProject={() => {}}
        onTogglePinSession={() => {}}
        onArchiveSession={() => {}}
        onRequestRename={async () => {}}
        onRequestDeleteMany={() => {}}
        onOpenOverviewDone={() => {}}
      />,
    );

    expect(screen.getByTestId(`drawer-project-running-${infraId}`)).toHaveTextContent("1");
    expect(screen.getByTestId(`drawer-project-updated-${infraId}`)).toHaveTextContent("1");
  });
});
