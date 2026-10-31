import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatList } from "@/components/ChatList";
import type { ChatSummary } from "@/lib/types";
import { mockBrowserFocus } from "./browser-focus";

const topic: ChatSummary = {
  key: "websocket:review", chatId: "review", channel: "websocket",
  title: "Review", preview: "", createdAt: null, updatedAt: null,
};

function RenameCase({
  save,
  grouped = false,
  onSelect = vi.fn(),
}: {
  save: (key: string, title: string) => Promise<void>;
  grouped?: boolean;
  onSelect?: ReturnType<typeof vi.fn>;
}) {
  const [titles, setTitles] = useState<Record<string, string>>({});
  const title = titles[topic.key] ?? topic.title!;
  return <ChatList
    sessions={grouped ? [{ ...topic, key: "tab:group", title: "Group" }] : [
      topic, { ...topic, key: "websocket:other", chatId: "other", title: "Other" },
    ]}
    activeKey={null}
    titleOverrides={titles}
    paneGroups={grouped ? {
      "tab:group": {
        tabKey: "tab:group", title: "Group", activePaneKey: "websocket:other", visible: true,
        panes: [{ key: topic.key, chatId: topic.chatId, title }],
      },
    } : {}}
    onSelect={onSelect}
    onSelectPane={onSelect}
    onRequestDelete={vi.fn()}
    onTogglePin={vi.fn()}
    onToggleArchive={vi.fn()}
    onRequestRename={async (key, nextTitle) => {
      await save(key, nextTitle);
      setTitles((current) => ({ ...current, [key]: nextTitle }));
    }}
  />;
}

async function startRename(contextMenu = false, title = "Review") {
  if (contextMenu) {
    fireEvent.contextMenu(screen.getByRole("button", { name: title }));
  } else {
    fireEvent.pointerDown(screen.getByRole("button", { name: `Topic actions for ${title}` }), {
      button: 0, ctrlKey: false,
    });
  }
  fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
  return screen.getByRole("textbox", { name: "Topic name" });
}

describe("inline sidebar topic rename", () => {
  let restoreFocus: () => void;
  beforeEach(() => { restoreFocus = mockBrowserFocus(); });
  afterEach(() => {
    restoreFocus();
    localStorage.removeItem("nanobot-webui.collapsed-pane-groups.v1");
  });

  it.each([false, true])("saves an inactive topic only after acknowledgement, grouped=%s", async (grouped) => {
    let confirm!: () => void;
    const save = vi.fn(() => new Promise<void>((resolve) => { confirm = resolve; }));
    const onSelect = vi.fn();
    render(<RenameCase save={save} grouped={grouped} onSelect={onSelect} />);
    const input = await startRename(grouped);
    expect(input).toHaveValue("Review");
    await waitFor(() => expect(input).toHaveFocus());
    expect(input.closest("button")).toBeNull();
    expect(input).toHaveAttribute("maxlength", "160");
    fireEvent.change(input, { target: { value: "  Updated name  " } });
    fireEvent.click(input);
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith(topic.key, "Updated name");
    expect(input).toHaveAttribute("readonly");
    expect(input.closest("form")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("button", { name: "Updated name" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
    await act(async () => { confirm(); });
    expect(await screen.findByRole("button", { name: "Updated name" })).toHaveFocus();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("does not let an older save close a newer edit of the same topic", async () => {
    let confirm!: () => void;
    const save = vi.fn(() => new Promise<void>((resolve) => { confirm = resolve; }));
    render(<RenameCase save={save} />);
    const first = await startRename();
    fireEvent.change(first, { target: { value: "First saved title" } });
    fireEvent.keyDown(first, { key: "Enter" });
    await startRename(false, "Other");
    const current = await startRename();
    fireEvent.change(current, { target: { value: "Newer draft" } });
    await act(async () => { confirm(); });
    expect(current).toBeInTheDocument();
    expect(current).toHaveValue("Newer draft");
    fireEvent.keyDown(current, { key: "Escape" });
    expect(screen.getByRole("button", { name: "First saved title" })).toBeInTheDocument();
  });

  it("retains a failed draft and allows retrying the same name", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("write failed")).mockResolvedValue(undefined);
    render(<RenameCase save={save} />);
    const input = await startRename();
    fireEvent.change(input, { target: { value: "  Keep this draft  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save the name. Try again.");
    expect(input).toHaveValue("  Keep this draft  ");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("button", { name: "Keep this draft" })).toBeInTheDocument();
    expect(save).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("cancels a failed edit with Escape without saving or switching topics", async () => {
    const save = vi.fn().mockRejectedValue(new Error("write failed"));
    const onSelect = vi.fn();
    render(<RenameCase save={save} onSelect={onSelect} />);
    const input = await startRename();
    fireEvent.change(input, { target: { value: "Unconfirmed" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByRole("alert");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Review" })).toHaveFocus();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(save).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("ignores blank names and IME confirmation keys, then saves once composition finishes", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<RenameCase save={save} />);
    const input = await startRename();
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "新的话题" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(save).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByRole("button", { name: "新的话题" })).toBeInTheDocument();
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("keeps keyboard activation of Cancel distinct from submitting the form", async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    render(<RenameCase save={save} />);
    await startRename();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    cancel.focus();
    await user.keyboard("{Enter}");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });
});
