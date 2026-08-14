import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatList } from "@/components/ChatList";
import { readDraggedSession, SESSION_DRAG_TYPE } from "@/lib/session-drag";
import type { ChatSummary } from "@/lib/types";

function session(overrides: Partial<ChatSummary>): ChatSummary {
  const chatId = overrides.chatId ?? "chat";
  return {
    key: `websocket:${chatId}`,
    channel: "websocket",
    chatId,
    createdAt: "2026-05-20T10:00:00Z",
    updatedAt: "2026-05-20T10:00:00Z",
    preview: "",
    ...overrides,
  };
}

describe("ChatList", () => {
  afterEach(() => {
    localStorage.removeItem("nanobot-webui.collapsed-pane-groups.v1");
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps tab grouping out of drag protocols while exposing inactive panes as mention sources", () => {
    render(
      <ChatList
        sessions={[session({ chatId: "root", title: "Root topic" })]}
        activeKey="websocket:root"
        paneGroups={{
          "websocket:root": {
            tabKey: "websocket:root",
            title: "Root topic",
            activePaneKey: "websocket:root",
            panes: [
              { key: "websocket:root", chatId: "root", title: "Root topic" },
              { key: "websocket:child", chatId: "child", title: "Research pane" },
            ],
          },
        }}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Tab: Root topic" }))
      .toHaveAttribute("draggable", "false");
    const pane = screen.getByRole("button", { name: "Research pane" });
    expect(pane).toHaveAttribute("draggable", "true");
    const dataTransfer = {
      effectAllowed: "none",
      setData: vi.fn(),
      getData: vi.fn(() => ""),
      types: [],
    } as unknown as DataTransfer;
    fireEvent.dragStart(pane, { dataTransfer });
    expect(dataTransfer.setData).toHaveBeenCalledWith(
      SESSION_DRAG_TYPE,
      "websocket:child",
    );
    expect(readDraggedSession(dataTransfer)).toBe("websocket:child");
    fireEvent.dragEnd(pane, { dataTransfer });
    expect(readDraggedSession(dataTransfer)).toBeNull();
    expect(document.querySelector("[data-pane-drag-overlay]")).not.toBeInTheDocument();
    expect(document.querySelector("[data-pane-snap-slot]")).not.toBeInTheDocument();
  });

  it("creates a visible tab in place and only moves panes into visible tabs", async () => {
    const onAttachPane = vi.fn();
    const onCreateTab = vi.fn();
    render(
      <ChatList
        sessions={[
          session({ chatId: "solo", title: "Solo pane" }),
          session({ chatId: "target", title: "Target pane" }),
          session({ key: "tab:existing", chatId: "group", title: "Existing group" }),
          session({ key: "tab:fine", chatId: "fine-group", title: "Fine group" }),
        ]}
        activeKey="websocket:solo"
        paneGroups={{
          "websocket:solo": {
            tabKey: "tab:solo",
            title: "Solo pane",
            activePaneKey: "websocket:solo",
            visible: false,
            panes: [{ key: "websocket:solo", chatId: "solo", title: "Solo pane" }],
          },
          "websocket:target": {
            tabKey: "tab:target",
            title: "Target pane",
            activePaneKey: "websocket:target",
            visible: false,
            panes: [{ key: "websocket:target", chatId: "target", title: "Target pane" }],
          },
          "tab:existing": {
            tabKey: "tab:existing",
            title: "Existing group",
            activePaneKey: "websocket:group-a",
            visible: true,
            panes: [
              { key: "websocket:group-a", chatId: "group-a", title: "Group A" },
              { key: "websocket:group-b", chatId: "group-b", title: "Group B" },
              { key: "websocket:group-c", chatId: "group-c", title: "Group C" },
              { key: "websocket:group-d", chatId: "group-d", title: "Group D" },
            ],
          },
          "tab:fine": {
            tabKey: "tab:fine",
            title: "Fine group",
            activePaneKey: "websocket:fine",
            visible: true,
            panes: [{ key: "websocket:fine", chatId: "fine", title: "Fine pane" }],
          },
        }}
        onCreateTab={onCreateTab}
        onAttachPane={onAttachPane}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Tab: Solo pane" }))
      .not.toBeInTheDocument();
    expect(screen.getAllByText("Solo pane")).toHaveLength(1);
    expect(screen.queryByRole("list", { name: "Panes in Solo pane" }))
      .not.toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Topic actions for Solo pane",
    }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Create group" }));
    expect(onCreateTab).toHaveBeenCalledWith("websocket:solo");

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Topic actions for Solo pane",
    }), { button: 0, ctrlKey: false });
    const moveTo = await screen.findByRole("menuitem", { name: "Move to" });
    fireEvent.pointerMove(moveTo, { pointerType: "mouse" });
    expect(screen.queryByRole("menuitem", { name: "Target pane" }))
      .not.toBeInTheDocument();
    const fullTarget = await screen.findByRole("menuitem", {
      name: "Existing group · 4/4",
    });
    expect(fullTarget).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(fullTarget);
    expect(onAttachPane).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("menuitem", { name: "Fine group · 1/4" }));
    expect(onAttachPane).toHaveBeenCalledWith("websocket:solo", "tab:fine");
  });

  it("shows every tab's pane membership in a sidebar tab group", async () => {
    const onSelect = vi.fn();
    const onSelectPane = vi.fn();
    const onDetachPane = vi.fn();
    const onDissolveTab = vi.fn();
    const onRequestRename = vi.fn();
    const onAttachPane = vi.fn();

    render(
      <ChatList
        sessions={[
          session({ chatId: "root", title: "Root topic" }),
          session({ chatId: "target", title: "Target tab" }),
        ]}
        activeKey="websocket:root"
        paneGroups={{
          "websocket:root": {
            tabKey: "websocket:root",
            title: "Root topic",
            activePaneKey: "websocket:child",
            panes: [
              { key: "websocket:root", chatId: "root", title: "Root topic" },
              { key: "websocket:child", chatId: "child", title: "Research pane" },
            ],
          },
          "websocket:target": {
            tabKey: "websocket:target",
            title: "Target tab",
            activePaneKey: "websocket:target-child",
            panes: [
              { key: "websocket:target", chatId: "target", title: "Target tab" },
              {
                key: "websocket:target-child",
                chatId: "target-child",
                title: "Target research",
              },
            ],
          },
        }}
        onSelect={onSelect}
        onSelectPane={onSelectPane}
        onDetachPane={onDetachPane}
        onDissolveTab={onDissolveTab}
        onAttachPane={onAttachPane}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={onRequestRename}
        onToggleArchive={vi.fn()}
      />,
    );

    const child = screen.getByRole("button", { name: "Research pane" });
    expect(child.closest("[data-sidebar-pane]"))
      .toHaveAttribute("data-sidebar-pane", "websocket:child");
    expect(child).toHaveAttribute("aria-current", "true");
    const targetTabRow = screen.getByRole("button", { name: "Tab: Target tab" })
      .closest("li")!;
    const targetChild = within(targetTabRow).getByRole("button", {
      name: "Target research",
    });
    expect(targetChild.closest("[data-sidebar-pane]"))
      .toHaveAttribute("data-sidebar-pane", "websocket:target-child");
    expect(targetChild).not.toHaveAttribute("aria-current");
    fireEvent.click(targetChild);
    expect(onSelectPane).toHaveBeenCalledWith(
      "websocket:target",
      "websocket:target-child",
    );
    fireEvent.click(child);
    expect(onSelectPane).toHaveBeenCalledWith("websocket:root", "websocket:child");

    fireEvent.click(screen.getByRole("button", { name: "Root topic" }));
    expect(onSelectPane).toHaveBeenCalledWith("websocket:root", "websocket:root");
    expect(onSelect).not.toHaveBeenCalled();

    onSelectPane.mockClear();
    const rootTab = screen.getByRole("button", { name: "Tab: Root topic" });
    fireEvent.click(rootTab);
    expect(onSelectPane).not.toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
    expect(rootTab).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(rootTab);
    expect(rootTab).toHaveAttribute("aria-expanded", "true");

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Topic actions for Root topic",
    }), { button: 0, ctrlKey: false });
    expect(await screen.findByRole("menuitem", { name: "Dissolve group" }))
      .toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Delete all chats" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Select" }))
      .not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "Dissolve group" }));
    expect(onDissolveTab).toHaveBeenCalledWith("websocket:root");

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Research pane pane actions",
    }), { button: 0, ctrlKey: false });
    const moveTo = await screen.findByRole("menuitem", { name: "Move to" });
    fireEvent.pointerMove(moveTo, { pointerType: "mouse" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Target tab · 2/4" }));
    expect(onAttachPane).toHaveBeenCalledWith("websocket:child", "websocket:target");

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Research pane pane actions",
    }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", {
      name: "Remove",
    }));
    expect(onDetachPane).toHaveBeenCalledWith("websocket:root", "websocket:child");

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Root topic pane actions",
    }), { button: 0, ctrlKey: false });
    expect(screen.getByRole("menuitem", { name: "Move to" }))
      .toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Remove" }))
      .toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    expect(child).toHaveAttribute("draggable", "false");
    expect(screen.getByRole("button", { name: "Tab: Target tab" }))
      .toHaveAttribute("draggable", "false");
  });

  it("collapses a multi-pane tab into one Chrome-style group header", () => {
    render(
      <ChatList
        sessions={[session({
          chatId: "root",
          title: "Root topic",
          workspaceScope: {
            project_path: "/Users/me/nanobot",
            project_name: "nanobot",
            access_mode: "restricted",
          },
        })]}
        activeKey="websocket:root"
        paneGroups={{
          "websocket:root": {
            tabKey: "websocket:root",
            title: "Root topic",
            activePaneKey: "websocket:child",
            panes: [
              { key: "websocket:root", chatId: "root", title: "Root topic" },
              { key: "websocket:child", chatId: "child", title: "Research pane" },
            ],
          },
        }}
        onSelect={vi.fn()}
        onSelectPane={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
      />,
    );

    const tabButton = screen.getByRole("button", { name: "Tab: Root topic" });
    const tabGroup = tabButton.closest("[data-sidebar-tab-group]")!;
    const tabHeader = tabButton.closest("[data-workbench-tab]")!;
    const tabSurface = tabButton.closest("[data-workbench-tab-surface]")!;
    expect(tabGroup).toHaveAttribute("data-sidebar-tab-group", "true");
    expect(tabHeader).not.toHaveAttribute("data-chat-row");
    expect(tabHeader).not.toHaveAttribute("data-sidebar-pane");
    expect(tabButton).not.toHaveAttribute("aria-current");
    expect(tabButton.querySelector("svg")).not.toBeInTheDocument();
    const paneList = within(tabGroup).getByRole("list", { name: "Panes in Root topic" });
    expect(tabSurface).toContainElement(paneList);
    const activePane = within(tabGroup).getByRole("button", { name: "Research pane" });
    expect(activePane).toHaveAttribute("aria-current", "true");
    expect(activePane.closest("[data-sidebar-pane]")).toHaveClass(
      "bg-sidebar-selected",
      "rounded-[0.65rem]",
    );
    expect(screen.getByRole("button", {
      name: "Research pane pane actions",
    })).toHaveClass("opacity-0");
    expect(within(tabGroup).getByRole("button", { name: "Root topic" }))
      .not.toHaveAttribute("aria-current");
    expect(tabGroup).not.toHaveTextContent("2/4");

    const collapse = within(tabGroup).getByRole("button", {
      name: "Collapse panes in Root topic",
    });
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(collapse);

    expect(tabGroup).toHaveAttribute("data-pane-group-collapsed", "true");
    expect(within(tabGroup).queryByRole("button", { name: "Research pane" }))
      .not.toBeInTheDocument();
    expect(within(tabGroup).getByRole("button", {
      name: "Expand panes in Root topic",
    })).toHaveAttribute("aria-expanded", "false");
    expect(within(tabGroup).getByRole("button", { name: "Tab: Root topic" }))
      .not.toHaveAttribute("aria-current");
    expect(tabSurface).toHaveClass("bg-sidebar-foreground/[0.045]");

    fireEvent.click(within(tabGroup).getByRole("button", {
      name: "Expand panes in Root topic",
    }));
    expect(within(tabGroup).getByRole("button", { name: "Research pane" }))
      .toBeInTheDocument();
    expect(within(tabGroup).getByRole("button", { name: "Root topic" }))
      .toBeInTheDocument();
  });

  it("selects a whole tab or individual panes for one bulk delete", async () => {
    const onRequestDeleteMany = vi.fn();
    render(
      <ChatList
        sessions={[
          session({ chatId: "root", title: "Root topic" }),
          session({ chatId: "target", title: "Target tab" }),
        ]}
        activeKey="websocket:root"
        paneGroups={{
          "websocket:root": {
            tabKey: "websocket:root",
            title: "Root topic",
            activePaneKey: "websocket:root",
            panes: [
              { key: "websocket:root", chatId: "root", title: "Root topic" },
              { key: "websocket:child", chatId: "child", title: "Research pane" },
            ],
          },
        }}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onRequestDeleteMany={onRequestDeleteMany}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
      />,
    );

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Root topic pane actions",
    }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Select" }));

    expect(screen.getByText("1 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tab: Root topic" }));
    expect(screen.getByRole("button", { name: "Tab: Root topic" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Root topic" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Research pane" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Target tab" }));
    expect(screen.getByText("3 selected")).toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId("delete-selection-bar")).getByRole("button", {
      name: "Delete",
    }));

    expect(onRequestDeleteMany).toHaveBeenCalledWith([
      { key: "websocket:root", label: "Root topic" },
      { key: "websocket:child", label: "Research pane" },
      { key: "websocket:target", label: "Target tab" },
    ]);
    expect(screen.queryByTestId("delete-selection-bar")).not.toBeInTheDocument();
  });

  it("shows temporary chats separately and lets the user reopen or close them", async () => {
    const temporarySession = session({
      key: "temporary:temporary-one",
      chatId: "temporary-one",
      preview: "hi",
    });
    const onSelect = vi.fn();
    const onClose = vi.fn();

    render(
      <ChatList
        sessions={[]}
        temporarySessions={[temporarySession]}
        activeKey={null}
        onSelect={onSelect}
        onCloseTemporaryChat={onClose}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
      />,
    );

    const section = screen.getByRole("region", { name: "Temporary chats" });
    fireEvent.click(within(section).getByRole("button", { name: "hi" }));
    expect(onSelect).toHaveBeenCalledWith("temporary:temporary-one");

    fireEvent.click(within(section).getByRole("button", {
      name: "Close temporary chat: hi",
    }));
    expect(onClose).toHaveBeenCalledWith("temporary:temporary-one");
  });

  it("orders chats by latest session activity by default", () => {
    const sessions = [
      session({
        chatId: "older",
        title: "Older chat",
        preview: "/model fast",
        updatedAt: "2026-05-21T10:00:00Z",
      }),
      session({
        chatId: "newest",
        title: "Newest chat",
        updatedAt: "2026-05-21T12:00:00Z",
      }),
      session({
        chatId: "middle",
        title: "Middle chat",
        updatedAt: "2026-05-21T11:00:00Z",
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey={null}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        showPreviews
      />,
    );

    const chatsSection = screen.getAllByRole("region")[0];
    const text = chatsSection.textContent ?? "";

    expect(text.indexOf("Newest chat")).toBeLessThan(text.indexOf("Middle chat"));
    expect(text.indexOf("Middle chat")).toBeLessThan(text.indexOf("Older chat"));
    expect(screen.queryByText("/model fast")).not.toBeInTheDocument();
  });

  it("shows a pin indicator for pinned chats", () => {
    const sessions = [
      session({ chatId: "pinned", title: "Pinned chat" }),
      session({ chatId: "normal", title: "Normal chat" }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey={null}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        pinnedKeys={["websocket:pinned"]}
      />,
    );

    const pinnedSection = screen.getByRole("region", { name: "Pinned" });
    expect(within(pinnedSection).getByTitle("Pinned")).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Earlier" })).queryByTitle("Pinned"),
    ).not.toBeInTheDocument();
  });

  it("groups WebUI chats by workspace project while preserving in-project sorting and activity", () => {
    const sessions = [
      session({
        chatId: "zeta",
        title: "Zeta task",
        updatedAt: "2026-05-20T12:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/nanobot",
          project_name: "nanobot",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "alpha",
        title: "Alpha task",
        updatedAt: "2026-05-20T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/nanobot",
          project_name: "nanobot",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "bench",
        title: "Bench task",
        updatedAt: "2026-05-21T09:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/nanobot-bench",
          project_name: "nanobot-bench",
          access_mode: "full",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:alpha"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        sort="title_asc"
        showTimestamps
        runningChatIds={["zeta"]}
      />,
    );

    const nanobotSection = screen.getByRole("region", { name: "nanobot" });
    const nanobotText = nanobotSection.textContent ?? "";

    expect(screen.getByRole("region", { name: "nanobot-bench" })).toBeInTheDocument();
    expect(within(nanobotSection).getByText("Alpha task")).toBeInTheDocument();
    expect(within(nanobotSection).getByText("Zeta task")).toBeInTheDocument();
    expect(nanobotText.indexOf("Alpha task")).toBeLessThan(nanobotText.indexOf("Zeta task"));
    expect(within(nanobotSection).getByLabelText("Agent running")).toBeInTheDocument();
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });

  it("keeps default workspace topics in the Topics section instead of a project folder", () => {
    const sessions = [
      session({
        chatId: "default",
        title: "Default workspace chat",
        updatedAt: "2026-05-21T10:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/.nanobot/workspace",
          project_name: "workspace",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "project",
        title: "Project chat",
        updatedAt: "2026-05-21T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/nanobot",
          project_name: "nanobot",
          access_mode: "restricted",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:default"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        defaultWorkspacePath="/Users/me/.nanobot/workspace"
        showTimestamps
      />,
    );

    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "nanobot" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "workspace" })).not.toBeInTheDocument();

    const chatsSection = screen.getByRole("region", { name: "Topics" });
    expect(within(chatsSection).getByText("Default workspace chat")).toBeInTheDocument();
    expect(within(chatsSection).queryByText("Project chat")).not.toBeInTheDocument();
  });

  it("switches row-owned tab highlights without a moving selection surface", () => {
    const props = {
      sessions: [
        session({ chatId: "active", title: "Active topic" }),
        session({ chatId: "inactive", title: "Inactive topic" }),
      ],
      onSelect: vi.fn(),
      onRequestDelete: vi.fn(),
      onTogglePin: vi.fn(),
      onRequestRename: vi.fn(),
      onToggleArchive: vi.fn(),
    };

    const { rerender } = render(
      <ChatList
        {...props}
        activeKey="websocket:active"
      />,
    );

    const activeButton = screen.getByTitle("Active topic");
    expect(activeButton).toHaveAttribute("aria-current", "page");
    expect(activeButton.closest("[data-sidebar-tab]")).toHaveClass(
      "bg-sidebar-selected",
    );
    expect(screen.queryByTestId("sessions-selection-highlight")).not.toBeInTheDocument();

    rerender(
      <ChatList
        {...props}
        activeKey="websocket:inactive"
      />,
    );

    expect(screen.getByTitle("Active topic")).not.toHaveAttribute("aria-current");
    expect(screen.getByTitle("Inactive topic")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTitle("Inactive topic").closest("[data-sidebar-tab]")).toHaveClass(
      "bg-sidebar-selected",
    );
  });

  it("restores collapsed tabs from the local UI preference", () => {
    const props = {
      sessions: [session({ chatId: "root", title: "Root topic" })],
      activeKey: "websocket:root",
      paneGroups: {
        "websocket:root": {
          tabKey: "websocket:root",
          title: "Root topic",
          activePaneKey: "websocket:root",
          panes: [
            { key: "websocket:root", chatId: "root", title: "Root topic" },
            { key: "websocket:child", chatId: "child", title: "Research pane" },
          ],
        },
      },
      onSelect: vi.fn(),
      onRequestDelete: vi.fn(),
      onTogglePin: vi.fn(),
      onRequestRename: vi.fn(),
      onToggleArchive: vi.fn(),
    };
    const firstRender = render(<ChatList {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Tab: Root topic" }));
    expect(screen.queryByRole("button", { name: "Research pane" })).not.toBeInTheDocument();
    firstRender.unmount();

    render(<ChatList {...props} />);
    expect(screen.getByRole("button", { name: "Tab: Root topic" }))
      .toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Research pane" })).not.toBeInTheDocument();
  });

  it("can collapse a project group and keeps project rename separate from chat titles", async () => {
    const onToggleGroup = vi.fn();
    const onRequestRenameProject = vi.fn();
    const onNewChatInProject = vi.fn();
    const sessions = [
      session({
        chatId: "alpha",
        title: "Alpha task",
        workspaceScope: {
          project_path: "/Users/me/nanobot",
          project_name: "nanobot",
          access_mode: "restricted",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:alpha"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        onToggleGroup={onToggleGroup}
        onRequestRenameProject={onRequestRenameProject}
        onNewChatInProject={onNewChatInProject}
        projectNameOverrides={{ "/Users/me/nanobot": "Photos" }}
        collapsedGroups={{ "project:/Users/me/nanobot": true }}
      />,
    );

    const projectSection = screen.getByRole("region", { name: "Photos" });
    fireEvent.click(within(projectSection).getByRole("button", { name: "Photos" }));

    expect(onToggleGroup).toHaveBeenCalledWith("project:/Users/me/nanobot");
    expect(within(projectSection).queryByText("Alpha task")).not.toBeInTheDocument();

    fireEvent.click(
      within(projectSection).getByRole("button", { name: "Start a new topic in Photos" }),
    );
    expect(onNewChatInProject).toHaveBeenCalledWith("/Users/me/nanobot", "Photos");
    expect(onToggleGroup).toHaveBeenCalledTimes(1);

    fireEvent.pointerDown(
      within(projectSection).getByLabelText("Topic actions for Photos"),
      { button: 0 },
    );
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));

    expect(onRequestRenameProject).toHaveBeenCalledWith("/Users/me/nanobot", "Photos");
  });

  it("hides the updated dot for the active chat", () => {
    const sessions = [
      session({
        chatId: "active",
        title: "Active task",
      }),
      session({
        chatId: "done",
        title: "Done task",
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:active"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        updatedChatIds={["active", "done"]}
      />,
    );

    const updated = screen.getAllByLabelText("New activity");
    expect(updated).toHaveLength(1);
    expect(updated[0].firstElementChild).toHaveClass("h-2", "w-2");
  });

  it("folds long default workspace chats and can show all", () => {
    const sessions = Array.from({ length: 10 }, (_, index) =>
      session({
        chatId: `chat-${index}`,
        title: `Chat ${index}`,
        updatedAt: `2026-05-21T10:${String(index).padStart(2, "0")}:00Z`,
        workspaceScope: {
          project_path: "/Users/me/.nanobot/workspace",
          project_name: "workspace",
          access_mode: "restricted",
        },
      }),
    );
    const onToggleGroup = vi.fn();
    const baseProps = {
      sessions,
      activeKey: null,
      onSelect: vi.fn(),
      onRequestDelete: vi.fn(),
      onTogglePin: vi.fn(),
      onRequestRename: vi.fn(),
      onToggleArchive: vi.fn(),
      onToggleGroup,
      defaultWorkspacePath: "/Users/me/.nanobot/workspace",
    };

    const { rerender } = render(<ChatList {...baseProps} />);
    const chatsSection = screen.getByRole("region", { name: "Topics" });

    expect(within(chatsSection).getByText("Chat 9")).toBeInTheDocument();
    expect(within(chatsSection).getByText("Chat 2")).toBeInTheDocument();
    expect(within(chatsSection).queryByText("Chat 1")).not.toBeInTheDocument();
    expect(within(chatsSection).queryByRole("button", { name: "Show all" })).not.toBeInTheDocument();
    fireEvent.click(within(chatsSection).getByRole("button", { name: "2 hidden topics" }));

    expect(onToggleGroup).toHaveBeenCalledWith("workspace:chats");

    rerender(
      <ChatList
        {...baseProps}
        collapsedGroups={{ "workspace:chats": false }}
      />,
    );

    expect(within(chatsSection).getByText("Chat 0")).toBeInTheDocument();
    expect(within(chatsSection).getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });

  it("sorts Topics section among project groups by recency, not always last", () => {
    const sessions = [
      session({
        chatId: "recent-chat",
        title: "Recent chat",
        updatedAt: "2026-05-21T12:00:00Z",
      }),
      session({
        chatId: "project-a",
        title: "Project A task",
        updatedAt: "2026-05-21T10:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-a",
          project_name: "project-a",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "project-b",
        title: "Project B task",
        updatedAt: "2026-05-21T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-b",
          project_name: "project-b",
          access_mode: "restricted",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:recent-chat"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        showTimestamps
      />,
    );

    const allRegions = screen.getAllByRole("region");
    const regionNames = allRegions.map((r) => r.getAttribute("aria-label") ?? r.textContent);

    // The most recently updated conversation ("Recent chat" at 12:00) must be
    // in the first group — Topics should come before both projects.
    const chatsIdx = regionNames.findIndex((n) => n?.includes("Topics"));
    const projAIdx = regionNames.findIndex((n) => n?.includes("project-a"));
    const projBIdx = regionNames.findIndex((n) => n?.includes("project-b"));

    expect(chatsIdx).toBeLessThan(projAIdx);
    expect(chatsIdx).toBeLessThan(projBIdx);
    expect(within(allRegions[chatsIdx]).getByText("Recent chat")).toBeInTheDocument();
  });

  it("keeps one Projects heading when Topics sorts between project groups", () => {
    const sessions = [
      session({
        chatId: "project-a",
        title: "Project A task",
        updatedAt: "2026-05-21T12:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-a",
          project_name: "project-a",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "middle-chat",
        title: "Middle chat",
        updatedAt: "2026-05-21T11:00:00Z",
      }),
      session({
        chatId: "project-b",
        title: "Project B task",
        updatedAt: "2026-05-21T10:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-b",
          project_name: "project-b",
          access_mode: "restricted",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:middle-chat"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        showTimestamps
      />,
    );

    const regionNames = screen
      .getAllByRole("region")
      .map((r) => r.getAttribute("aria-label") ?? "");

    expect(regionNames).toEqual(["project-a", "Topics", "project-b"]);
    expect(screen.getAllByText("Projects")).toHaveLength(1);
  });

  it("keeps Topics last when its latest conversation is older than all projects", () => {
    const sessions = [
      session({
        chatId: "project-a",
        title: "Project A task",
        updatedAt: "2026-05-21T12:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-a",
          project_name: "project-a",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "project-b",
        title: "Project B task",
        updatedAt: "2026-05-21T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-b",
          project_name: "project-b",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "old-chat",
        title: "Old chat",
        updatedAt: "2026-05-21T10:00:00Z",
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:old-chat"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        showTimestamps
      />,
    );

    const regionNames = screen
      .getAllByRole("region")
      .map((r) => r.getAttribute("aria-label") ?? "");

    expect(regionNames).toEqual(["project-a", "project-b", "Topics"]);
    expect(screen.getAllByText("Projects")).toHaveLength(1);
  });
});
