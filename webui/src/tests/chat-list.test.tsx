import { createEvent, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatList } from "@/components/ChatList";
import { PANE_DRAG_TYPE, SESSION_DRAG_TYPE } from "@/lib/session-drag";
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

function rect({
  left,
  top,
  width,
  height,
}: {
  left: number;
  top: number;
  width: number;
  height: number;
}): DOMRect {
  return {
    x: left,
    y: top,
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    toJSON: () => ({}),
  } as DOMRect;
}

function dragOverAt(
  element: Element,
  clientY: number,
  dataTransfer: Record<string, unknown>,
): void {
  const event = createEvent.dragOver(element, { dataTransfer });
  Object.defineProperty(event, "clientY", { value: clientY });
  fireEvent(element, event);
}

function dropAt(
  element: Element,
  clientY: number,
  dataTransfer: Record<string, unknown>,
): void {
  const event = createEvent.drop(element, { dataTransfer });
  Object.defineProperty(event, "clientY", { value: clientY });
  fireEvent(element, event);
}

describe("ChatList", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("exposes chats as drag sources", () => {
    const dataTransfer = {
      effectAllowed: "",
      setData: vi.fn(),
      setDragImage: vi.fn(),
    };
    render(
      <ChatList
        sessions={[
          session({ chatId: "active", title: "Active chat" }),
          session({ chatId: "reference", title: "Reference chat" }),
        ]}
        activeKey="websocket:active"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Active chat" }))
      .toHaveAttribute("draggable", "true");
    const reference = screen.getByRole("button", { name: "Reference chat" });
    expect(reference).toHaveAttribute("draggable", "true");

    fireEvent.dragStart(reference, { dataTransfer });

    expect(dataTransfer.setData).toHaveBeenCalledWith(
      SESSION_DRAG_TYPE,
      "websocket:reference",
    );
    expect(dataTransfer.setDragImage).toHaveBeenCalled();
    expect(document.querySelector("[data-pane-drag-overlay]"))
      .toHaveTextContent("Reference chat");
    expect(reference.closest("li")).not.toHaveClass("opacity-0");
    expect(document.querySelector("[data-tab-drag-placeholder]"))
      .not.toBeInTheDocument();
    fireEvent.dragEnd(reference, { dataTransfer });
    expect(document.querySelector("[data-pane-drag-overlay]")).not.toBeInTheDocument();
  });

  it("reorders topics with a displaced-neighbor preview instead of an insertion line", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(rect({
      left: 0,
      top: 0,
      width: 284,
      height: 32,
    }));
    const onReorderSessions = vi.fn();
    const sessions = [
      session({ chatId: "alpha", title: "Alpha" }),
      session({ chatId: "bravo", title: "Bravo" }),
      session({ chatId: "charlie", title: "Charlie" }),
      session({ chatId: "old-a", title: "Old A" }),
      session({ chatId: "old-b", title: "Old B" }),
    ];
    const { rerender } = render(
      <ChatList
        sessions={sessions}
        activeKey={null}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        onReorderSessions={onReorderSessions}
        archivedKeys={["websocket:old-a", "websocket:old-b"]}
        sessionOrder={sessions.map((item) => item.key)}
      />,
    );
    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      setData: vi.fn(),
    };
    fireEvent.dragStart(screen.getByRole("button", { name: "Alpha" }), { dataTransfer });
    const charlieRow = screen.getByRole("button", { name: "Charlie" }).closest("li")!;
    dragOverAt(charlieRow, 24, dataTransfer);
    expect(document.querySelector("[data-session-drop-edge]")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bravo" }).closest("li"))
      .toHaveAttribute("data-session-displaced", "true");
    expect(charlieRow).toHaveStyle({ transform: "translateY(-32px)" });
    expect(screen.getByRole("button", { name: "Alpha" }).closest("li"))
      .toHaveAttribute("data-session-dragging", "true");
    dropAt(charlieRow, 24, dataTransfer);

    expect(onReorderSessions).toHaveBeenCalledWith([
      "websocket:bravo",
      "websocket:charlie",
      "websocket:alpha",
      "websocket:old-a",
      "websocket:old-b",
    ]);

    rerender(
      <ChatList
        sessions={sessions}
        activeKey={null}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        onReorderSessions={onReorderSessions}
        archivedKeys={["websocket:old-a", "websocket:old-b"]}
        sessionOrder={[
          "websocket:bravo",
          "websocket:charlie",
          "websocket:alpha",
          "websocket:old-a",
          "websocket:old-b",
        ]}
        sort="manual"
      />,
    );
    const section = screen.getByRole("region", { name: "Topics" });
    const text = section.textContent ?? "";
    expect(text.indexOf("Bravo")).toBeLessThan(text.indexOf("Charlie"));
    expect(text.indexOf("Charlie")).toBeLessThan(text.indexOf("Alpha"));
  });

  it("shows every tab's pane membership in a sidebar tab group", async () => {
    const onSelect = vi.fn();
    const onSelectPane = vi.fn();
    const onDetachPane = vi.fn();
    const onPromotePane = vi.fn();
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
            topicKey: "websocket:root",
            activePaneKey: "websocket:child",
            panes: [
              { key: "websocket:root", chatId: "root", title: "Root topic" },
              { key: "websocket:child", chatId: "child", title: "Research pane" },
            ],
          },
          "websocket:target": {
            topicKey: "websocket:target",
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
        onPromotePane={onPromotePane}
        paneAcceptingTabKeys={["websocket:target"]}
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
    fireEvent.click(screen.getByRole("button", { name: "Tab: Root topic" }));
    expect(onSelectPane).not.toHaveBeenCalled();

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Research pane pane actions",
    }), { button: 0, ctrlKey: false });
    const moveToTab = await screen.findByRole("menuitem", { name: "Move to tab" });
    fireEvent.pointerMove(moveToTab, { pointerType: "mouse" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Target tab" }));
    expect(onAttachPane).toHaveBeenCalledWith("websocket:child", "websocket:target");

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Research pane pane actions",
    }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", {
      name: "Move Research pane to a new tab",
    }));
    expect(onDetachPane).toHaveBeenCalledWith("websocket:root", "websocket:child");

    fireEvent.pointerDown(screen.getByRole("button", {
      name: "Root topic pane actions",
    }), { button: 0, ctrlKey: false });
    expect(screen.queryByRole("menuitem", { name: "Move to tab" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Move Root topic to a new tab" }))
      .not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      setData: vi.fn(),
    };
    onAttachPane.mockClear();
    fireEvent.dragStart(child, { dataTransfer });
    expect(child.closest("li")).toHaveAttribute("data-pane-dragging", "true");
    expect(child.closest("li")).not.toHaveClass("opacity-0");
    const targetTab = screen.getByRole("button", { name: "Tab: Target tab" });
    dragOverAt(targetTab.closest("li")!, 0, dataTransfer);
    expect(targetTab.closest("li"))
      .not.toHaveAttribute("data-tab-attach-target");
    expect(targetTab.closest("li")!.querySelector("[data-pane-snap-slot]"))
      .not.toBeInTheDocument();
    dropAt(targetTab.closest("li")!, 0, dataTransfer);
    expect(dataTransfer.setData).toHaveBeenCalledWith(
      PANE_DRAG_TYPE,
      JSON.stringify({
        paneKey: "websocket:child",
        sourceTabKey: "websocket:root",
      }),
    );
    expect(onAttachPane).not.toHaveBeenCalled();
    fireEvent.dragEnd(child, { dataTransfer });
  });

  it("collapses a multi-pane tab into one Chrome-style group header", () => {
    render(
      <ChatList
        sessions={[session({ chatId: "root", title: "Root topic" })]}
        activeKey="websocket:root"
        paneGroups={{
          "websocket:root": {
            topicKey: "websocket:root",
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

    const tabGroup = screen.getByRole("button", { name: "Tab: Root topic" })
      .closest("[data-sidebar-tab-group]")!;
    expect(tabGroup).toHaveAttribute("data-sidebar-tab-group", "true");
    expect(within(tabGroup).getByRole("list", { name: "Panes in Root topic" }))
      .toBeInTheDocument();
    expect(within(tabGroup).getByRole("button", { name: "Research pane" }))
      .toHaveAttribute("aria-current", "true");
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
    expect(within(tabGroup).getByRole("button", { name: "Tab: Root topic" })
      .closest("[data-sidebar-tab]"))
      .toHaveClass("bg-sidebar-selected");

    fireEvent.click(within(tabGroup).getByRole("button", {
      name: "Expand panes in Root topic",
    }));
    expect(within(tabGroup).getByRole("button", { name: "Research pane" }))
      .toBeInTheDocument();
    expect(within(tabGroup).getByRole("button", { name: "Root topic" }))
      .toBeInTheDocument();
  });

  it("keeps the Pane opaque without exposing a slot in another tab", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(rect({
      left: 0,
      top: 0,
      width: 240,
      height: 28,
    }));
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      setData: vi.fn(),
      setDragImage: vi.fn(),
    };
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
            topicKey: "websocket:root",
            activePaneKey: "websocket:child",
            panes: [
              { key: "websocket:root", chatId: "root", title: "Root topic" },
              { key: "websocket:child", chatId: "child", title: "Research pane" },
            ],
          },
        }}
        paneAcceptingTabKeys={["websocket:target"]}
        onAttachPane={onAttachPane}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
      />,
    );

    const pane = screen.getByRole("button", { name: "Research pane" });
    fireEvent.dragStart(pane, { clientX: 40, clientY: 40, dataTransfer });
    expect(dataTransfer.setDragImage).toHaveBeenCalled();

    const dragOver = createEvent.dragOver(
      screen.getByRole("button", { name: "Target tab" }).closest("li")!,
      { dataTransfer },
    );
    Object.defineProperties(dragOver, {
      clientX: { value: 160 },
      clientY: { value: 120 },
    });
    fireEvent(screen.getByRole("button", { name: "Target tab" }).closest("li")!, dragOver);

    const paneRow = pane.closest("li")!;
    const overlay = document.querySelector<HTMLElement>("[data-pane-drag-overlay]")!;
    expect(overlay).toHaveStyle({
      opacity: "1",
      height: "28px",
      transform: "translate3d(40px, 106px, 0)",
      visibility: "visible",
      width: "240px",
    });
    expect(overlay).toHaveTextContent("Research pane");
    expect(overlay).toHaveClass(
      "!bg-sidebar-selected",
      "!shadow-none",
    );
    expect(overlay).toHaveStyle({ boxShadow: "none" });
    expect(document.querySelector("[data-pane-snap-slot]")).not.toBeInTheDocument();
    expect(paneRow.querySelector("[data-sidebar-pane]"))
      .toHaveClass("!bg-transparent", "!text-transparent", "!shadow-none");
    expect(paneRow.style.transform).toBe("");
    expect(paneRow).not.toHaveClass("opacity-0");

    dataTransfer.dropEffect = "none";
    fireEvent.dragEnd(pane, { clientX: 160, clientY: 120, dataTransfer });
    expect(onAttachPane).not.toHaveBeenCalled();
    expect(document.querySelector("[data-pane-drag-overlay]")).not.toBeInTheDocument();
  });

  it("repels sibling Panes and snaps the dragged Pane into the selected slot", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(rect({
      left: 0,
      top: 0,
      width: 240,
      height: 28,
    }));
    const onAttachPane = vi.fn();
    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      setData: vi.fn(),
      setDragImage: vi.fn(),
    };

    render(
      <ChatList
        sessions={[session({ chatId: "root", title: "Root topic" })]}
        activeKey="websocket:root"
        paneGroups={{
          "websocket:root": {
            topicKey: "websocket:root",
            activePaneKey: "websocket:first",
            panes: [
              { key: "websocket:root", chatId: "root", title: "Root topic" },
              { key: "websocket:first", chatId: "first", title: "First pane" },
              { key: "websocket:second", chatId: "second", title: "Second pane" },
              { key: "websocket:third", chatId: "third", title: "Third pane" },
            ],
          },
        }}
        onAttachPane={onAttachPane}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
      />,
    );

    const first = screen.getByRole("button", { name: "First pane" });
    const secondRow = screen.getByRole("button", { name: "Second pane" }).closest("li")!;
    fireEvent.dragStart(first, { clientX: 40, clientY: 14, dataTransfer });
    dragOverAt(secondRow, 20, dataTransfer);

    expect(secondRow).toHaveAttribute("data-pane-displaced", "true");
    expect(secondRow).toHaveStyle("transform: translateY(-30px)");
    expect((first.closest("li") as HTMLElement).style.transform).toBe("");
    const snapSlot = screen.getByRole("list", { name: "Panes in Root topic" })
      .querySelector("[data-pane-snap-slot]")!;
    expect(snapSlot).toHaveStyle("height: 28px; transform: translateY(60px)");
    expect(snapSlot).toHaveClass("absolute", "bg-transparent");
    expect(first.closest("li")).not.toHaveClass("opacity-0");

    dropAt(snapSlot, 20, dataTransfer);
    expect(onAttachPane).toHaveBeenCalledWith(
      "websocket:first",
      "websocket:root",
      "websocket:third",
    );
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
            topicKey: "websocket:root",
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
      name: "Topic actions for Root topic",
    }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Select" }));

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

  it("reorders one-pane tabs instead of attaching them through drag", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(rect({
      left: 0,
      top: 0,
      width: 284,
      height: 32,
    }));
    const onAttachPane = vi.fn();
    const onReorderSessions = vi.fn();
    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      setData: vi.fn(),
    };

    render(
      <ChatList
        sessions={[
          session({ chatId: "detached", title: "Detached pane" }),
          session({ chatId: "target", title: "Target tab" }),
        ]}
        activeKey={null}
        attachableTabKeys={["websocket:detached", "websocket:target"]}
        paneAcceptingTabKeys={["websocket:detached", "websocket:target"]}
        onAttachPane={onAttachPane}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        onReorderSessions={onReorderSessions}
      />,
    );

    const detached = screen.getByRole("button", { name: "Detached pane" });
    fireEvent.dragStart(detached, {
      dataTransfer,
    });
    expect(detached.closest("li"))
      .toHaveAttribute("data-session-dragging", "true");
    const target = screen.getByRole("button", { name: "Target tab" }).closest("li")!;
    dragOverAt(target, 16, dataTransfer);
    expect(target).not.toHaveAttribute("data-tab-attach-target");
    expect(target).toHaveAttribute("data-session-displaced", "true");
    expect(document.querySelector("[data-pane-snap-slot]")).not.toBeInTheDocument();
    dropAt(target, 16, dataTransfer);

    expect(onAttachPane).not.toHaveBeenCalled();
    expect(onReorderSessions).toHaveBeenCalledWith([
      "websocket:target",
      "websocket:detached",
    ]);
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
    const inactiveButton = screen.getByTitle("Inactive topic");
    expect(activeButton).toHaveAttribute("aria-current", "page");
    expect(activeButton.closest("[data-sidebar-tab]")).toHaveClass(
      "bg-sidebar-selected",
    );
    expect(inactiveButton.closest("[data-sidebar-tab]")).not.toHaveClass(
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
    expect(screen.getByTitle("Active topic").closest("[data-sidebar-tab]")).not.toHaveClass(
      "bg-sidebar-selected",
    );
    expect(screen.getByTitle("Inactive topic").closest("[data-sidebar-tab]")).toHaveClass(
      "bg-sidebar-selected",
    );

    rerender(<ChatList {...props} activeKey={null} />);
    expect(screen.getByTitle("Inactive topic").closest("[data-sidebar-tab]")).not.toHaveClass(
      "bg-sidebar-selected",
    );
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
