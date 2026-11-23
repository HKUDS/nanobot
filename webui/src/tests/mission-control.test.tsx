import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

    expect(screen.getAllByText("Deploy ingress controller").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Fix arm64 cache").length).toBeGreaterThan(0);
    // Done session is isolated from the Open workspace view
    expect(screen.queryByText("Old finished task")).not.toBeInTheDocument();

    // One-click archive from smart cleanup strip archives only the stale candidate
    fireEvent.click(screen.getByRole("button", { name: /Archive all|全部结单归档/ }));
    expect(onArchiveMany).toHaveBeenCalledWith(["websocket:alpha-stale"], true);

    // Switching to Done tab reveals archived sessions with restore action
    fireEvent.click(screen.getByRole("tab", { name: /Done|已结单/ }));
    expect(screen.getByText("Old finished task")).toBeInTheDocument();
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
