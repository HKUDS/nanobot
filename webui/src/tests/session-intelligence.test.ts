import { describe, expect, it } from "vitest";

import {
  buildSessionIntelligence,
  classifyCleanupReason,
  formatCompactRelativeTime,
  formatElapsedDuration,
} from "@/lib/session-intelligence";
import type { ChatSummary } from "@/lib/types";

const NOW = Date.parse("2026-11-23T12:00:00Z");
const minsAgo = (mins: number) => new Date(NOW - mins * 60_000).toISOString();

function makeSession(overrides: Partial<ChatSummary> & { key: string }): ChatSummary {
  const chatId = overrides.key.split(":")[1] ?? overrides.key;
  return {
    channel: "websocket",
    chatId,
    createdAt: minsAgo(60),
    updatedAt: minsAgo(10),
    title: chatId,
    preview: "",
    projectLocked: true,
    ...overrides,
  };
}

describe("session-intelligence", () => {
  it("classifies stale and quick one-off sessions while protecting running, pinned, and automated sessions", () => {
    const stale = classifyCleanupReason({
      archived: false,
      pinned: false,
      attention: "idle",
      automationCount: 0,
      projectLocked: true,
      createdMs: NOW - 10 * 86_400_000,
      updatedMs: NOW - 8 * 86_400_000,
      nowMs: NOW,
    });
    expect(stale).toBe("stale");

    const quick = classifyCleanupReason({
      archived: false,
      pinned: false,
      attention: "idle",
      automationCount: 0,
      projectLocked: true,
      createdMs: NOW - 30 * 3_600_000,
      updatedMs: NOW - 30 * 3_600_000 + 2 * 60_000,
      nowMs: NOW,
    });
    expect(quick).toBe("quick_chat");

    const protectedByAutomation = classifyCleanupReason({
      archived: false,
      pinned: false,
      attention: "idle",
      automationCount: 1,
      projectLocked: true,
      createdMs: NOW - 15 * 86_400_000,
      updatedMs: NOW - 12 * 86_400_000,
      nowMs: NOW,
    });
    expect(protectedByAutomation).toBeNull();

    const protectedByPin = classifyCleanupReason({
      archived: false,
      pinned: true,
      attention: "idle",
      automationCount: 0,
      projectLocked: true,
      createdMs: NOW - 15 * 86_400_000,
      updatedMs: NOW - 12 * 86_400_000,
      nowMs: NOW,
    });
    expect(protectedByPin).toBeNull();
  });

  it("rolls up cross-project live status and keeps workbench panes in their native projects", () => {
    const sessions: ChatSummary[] = [
      makeSession({
        key: "websocket:alpha-run",
        title: "Alpha running task",
        runStartedAt: (NOW - 125_000) / 1000,
        workspaceScope: { project_path: "/code/alpha", project_name: "alpha", access_mode: "restricted" },
      }),
      makeSession({
        key: "websocket:beta-wait",
        title: "Beta waiting approval",
        workspaceScope: { project_path: "/code/beta", project_name: "beta", access_mode: "restricted" },
      }),
      makeSession({
        key: "websocket:beta-stale",
        title: "Old Beta lookup",
        createdAt: minsAgo(15_000),
        updatedAt: minsAgo(14_998),
        workspaceScope: { project_path: "/code/beta", project_name: "beta", access_mode: "restricted" },
      }),
      makeSession({
        key: "websocket:beta-auto",
        title: "Nightly Beta cron",
        createdAt: minsAgo(20_000),
        updatedAt: minsAgo(16_000),
        workspaceScope: { project_path: "/code/beta", project_name: "beta", access_mode: "restricted" },
      }),
      makeSession({
        key: "websocket:done-item",
        title: "Wrapped up task",
        workspaceScope: { project_path: "/code/alpha", project_name: "alpha", access_mode: "restricted" },
      }),
    ];

    const snapshot = buildSessionIntelligence(sessions, {
      pinnedKeys: [],
      archivedKeys: ["websocket:done-item"],
      runningChatIds: ["alpha-run"],
      updatedChatIds: [],
      recoveryChatIds: ["beta-wait"],
      titleOverrides: {},
      projectNameOverrides: {},
      automationCountsByKey: new Map([["websocket:beta-auto", 1]]),
      paneGroups: {
        "tab:cross": {
          tabKey: "tab:cross",
          title: "Cross-project debug",
          activePaneKey: "websocket:alpha-run",
          visible: true,
          panes: [{ key: "websocket:alpha-run" }, { key: "websocket:beta-wait" }],
        },
      },
      activeKey: null,
      defaultWorkspacePath: "/workspace",
      generalLabel: "General",
      fallbackTitle: "New chat",
      nowMs: NOW,
    });

    // Attention orders recovery ahead of running
    expect(snapshot.attention.map((item) => item.session.key)).toEqual([
      "websocket:beta-wait",
      "websocket:alpha-run",
    ]);

    // Both projects still contain their native sessions despite sharing a split workbench
    const alpha = snapshot.projects.find((p) => p.project.name === "alpha")!;
    const beta = snapshot.projects.find((p) => p.project.name === "beta")!;
    expect(alpha.openSessions.map((s) => s.session.key)).toEqual(["websocket:alpha-run"]);
    expect(alpha.runningCount).toBe(1);
    expect(alpha.archivedSessions.map((s) => s.session.key)).toEqual(["websocket:done-item"]);
    expect(beta.openSessions.map((s) => s.session.key)).toContain("websocket:beta-wait");
    expect(beta.recoveryCount).toBe(1);

    // Cleanup suggests only beta-stale (beta-auto is protected by automation!)
    expect(snapshot.cleanupCandidates.map((s) => s.session.key)).toEqual(["websocket:beta-stale"]);

    // Workbench split group is surfaced separately with both native projects intact
    expect(snapshot.workbenchGroups).toHaveLength(1);
    expect(snapshot.workbenchGroups[0].panes.map((p) => p.project.name)).toEqual(["alpha", "beta"]);
  });

  it("formats elapsed durations and compact relative timestamps cleanly", () => {
    expect(formatElapsedDuration((NOW - 45_000) / 1000, NOW)).toBe("45s");
    expect(formatElapsedDuration((NOW - 185_000) / 1000, NOW)).toBe("3m 05s");
    expect(formatElapsedDuration((NOW - 5_400_000) / 1000, NOW)).toBe("1h 30m");
    expect(formatCompactRelativeTime(NOW - 30_000, "zh-CN", NOW)).toBe("刚刚");
    expect(formatCompactRelativeTime(NOW - 12 * 60_000, "en", NOW)).toBe("12m");
    expect(formatCompactRelativeTime(NOW - 3 * 86_400_000, "zh-CN", NOW)).toBe("3天前");
  });
});
