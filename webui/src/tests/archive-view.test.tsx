import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArchiveView, type ArchiveViewProps } from "@/components/ArchiveView";
import type { ChatSummary } from "@/lib/types";

function session(chatId: string, title: string, handle: string): ChatSummary {
  return {
    key: `websocket:${chatId}`,
    channel: "websocket",
    chatId,
    createdAt: null,
    updatedAt: null,
    title,
    preview: "",
    handle: { id: `handle_${chatId}`, name: handle },
  };
}

function renderArchive() {
  const onOpen = vi.fn<ArchiveViewProps["onOpen"]>();
  const onUnarchive = vi.fn<ArchiveViewProps["onUnarchive"]>();
  const onRequestDeleteMany = vi.fn<ArchiveViewProps["onRequestDeleteMany"]>();
  render(<ArchiveView
    sessions={[
      session("plan", "Planning draft", "mira"),
      session("design", "Design spec", "taro"),
      session("notes", "Operations notes", "nora"),
      session("review", "Operations review", "nola"),
    ]}
    titleOverrides={{ "websocket:plan": "Release roadmap" }}
    loading={false}
    loadError={false}
    onRetry={vi.fn()}
    onOpen={onOpen}
    onUnarchive={onUnarchive}
    onRequestDeleteMany={onRequestDeleteMany}
    onBack={vi.fn()}
  />);
  return { onOpen, onUnarchive, onRequestDeleteMany };
}

describe("ArchiveView", () => {
  it("reports an incomplete list and retries instead of showing an empty archive", () => {
    const onRetry = vi.fn();
    const props: ArchiveViewProps = {
      sessions: [], titleOverrides: {}, loading: false, loadError: true, onRetry,
      onOpen: vi.fn(), onUnarchive: vi.fn(), onRequestDeleteMany: vi.fn(), onBack: vi.fn(),
    };
    const { rerender } = render(<ArchiveView {...props} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load all topics.");
    expect(screen.queryByText("No archived topics.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
    rerender(<ArchiveView {...props} loadError={false} sessions={[session("plan", "Planning", "mira")]} />);
    expect(screen.getByRole("button", { name: "@mira Planning" })).toBeInTheDocument();
  });

  it("searches displayed titles and handles case-insensitively", () => {
    renderArchive();
    const search = screen.getByRole("searchbox", { name: "Search archived topics" });

    fireEvent.change(search, { target: { value: "  ROADMAP  " } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "@mira Release roadmap" })).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "@TARO" } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "@taro Design spec" })).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "  OPERATIONS   nora  " } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "@nora Operations notes" })).toBeInTheDocument();
  });

  it("preserves a bulk selection on unarchive cancellation and confirms only those selected", () => {
    const { onOpen, onUnarchive } = renderArchive();
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByText("4 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "@nora Operations notes" }));
    fireEvent.click(screen.getByRole("button", { name: "@nola Operations review" }));
    expect(screen.getByRole("checkbox", { name: "Select all" })).toHaveAttribute("aria-checked", "mixed");
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    expect(onOpen).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Unarchive" }));
    const dialog = screen.getByRole("alertdialog", { name: "Unarchive 2 topics?" });
    expect(onUnarchive).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "@mira Release roadmap" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "@taro Design spec" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "@nora Operations notes" })).toHaveAttribute("aria-pressed", "false");
    expect(onUnarchive).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Unarchive" }));
    fireEvent.click(within(screen.getByRole("alertdialog", { name: "Unarchive 2 topics?" }))
      .getByRole("button", { name: "Unarchive" }));
    expect(onUnarchive).toHaveBeenCalledOnce();
    expect(onUnarchive).toHaveBeenCalledWith(["websocket:plan", "websocket:design"]);
    expect(screen.getByRole("button", { name: "Select" })).toBeInTheDocument();
  });

  it("delegates bulk deletion and keeps the selection when the decision is cancelled", () => {
    const { onOpen, onRequestDeleteMany } = renderArchive();
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "@mira Release roadmap" }));
    fireEvent.click(screen.getByRole("button", { name: "@nora Operations notes" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    const items = [
      { key: "websocket:plan", label: "Release roadmap" },
      { key: "websocket:notes", label: "Operations notes" },
    ];
    expect(onRequestDeleteMany).toHaveBeenCalledOnce();
    expect(onRequestDeleteMany).toHaveBeenCalledWith(items, expect.any(Function));
    expect(onOpen).not.toHaveBeenCalled();
    act(() => onRequestDeleteMany.mock.calls[0][1]?.(false));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "@mira Release roadmap" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "@nora Operations notes" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onRequestDeleteMany).toHaveBeenCalledTimes(2);
    expect(onRequestDeleteMany).toHaveBeenLastCalledWith(items, expect.any(Function));
    act(() => onRequestDeleteMany.mock.calls[1][1]?.(true));
    expect(screen.getByRole("button", { name: "Select" })).toBeInTheDocument();
  });

  it("removes a selection when an updated title no longer matches the search", () => {
    const onRequestDeleteMany = vi.fn<ArchiveViewProps["onRequestDeleteMany"]>();
    const first = session("first", "Archive notes", "mira");
    const second = session("second", "Archive plan", "taro");
    const props: ArchiveViewProps = {
      sessions: [first, second], titleOverrides: {}, loading: false, loadError: false,
      onRetry: vi.fn(), onOpen: vi.fn(), onUnarchive: vi.fn(), onRequestDeleteMany, onBack: vi.fn(),
    };
    const { rerender } = render(<ArchiveView {...props} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search archived topics" }), { target: { value: "archive" } });
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    fireEvent.click(screen.getByRole("button", { name: "Unarchive" }));
    expect(screen.getByRole("alertdialog", { name: "Unarchive 2 topics?" })).toBeInTheDocument();

    rerender(<ArchiveView {...props} sessions={[first, { ...second, title: "Final plan" }]} />);
    const dialog = screen.getByRole("alertdialog", { name: "Unarchive this topic?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onRequestDeleteMany).toHaveBeenCalledWith([
      { key: "websocket:first", label: "Archive notes" },
    ], expect.any(Function));

    act(() => onRequestDeleteMany.mock.calls[0][1]?.(false));
    rerender(<ArchiveView {...props} />);
    expect(screen.getByRole("button", { name: "@taro Archive plan" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });

  it("clears selections when search changes so hidden topics cannot be deleted", () => {
    const { onRequestDeleteMany } = renderArchive();
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "@mira Release roadmap" }));
    fireEvent.click(screen.getByRole("button", { name: "@taro Design spec" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    const search = screen.getByRole("searchbox", { name: "Search archived topics" });
    fireEvent.change(search, { target: { value: "operations" } });
    expect(screen.queryByRole("button", { name: "@mira Release roadmap" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "@taro Design spec" })).not.toBeInTheDocument();
    expect(screen.getByText("0 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Unarchive" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Select all" })).toHaveAttribute("aria-checked", "false");

    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onRequestDeleteMany).toHaveBeenCalledOnce();
    expect(onRequestDeleteMany).toHaveBeenCalledWith([
      { key: "websocket:notes", label: "Operations notes" },
      { key: "websocket:review", label: "Operations review" },
    ], expect.any(Function));

    act(() => onRequestDeleteMany.mock.calls[0][1]?.(false));
    fireEvent.change(search, { target: { value: "" } });
    expect(screen.getByText("0 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "@mira Release roadmap" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "@nora Operations notes" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });
});
