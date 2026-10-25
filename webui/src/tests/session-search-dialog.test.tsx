import { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionSearchDialog } from "@/components/SessionSearchDialog";
import { useAppViewport } from "@/hooks/useAppViewport";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { ThreadTranscript } from "@/lib/thread-transcript";
import type { ChatSummary, UIMessage } from "@/lib/types";

function session(index: number): ChatSummary {
  return {
    key: `websocket:chat-${index}`,
    channel: "websocket",
    chatId: `chat-${index}`,
    createdAt: null,
    updatedAt: null,
    title: `Chat ${index}`,
    preview: `Preview ${index}`,
  };
}

describe("SessionSearchDialog", () => {
  it("windows large result sets and selects an item reached beyond the first window", () => {
    const onSelect = vi.fn();
    render(<SessionSearchDialog open sessions={Array.from({ length: 1000 }, (_, i) => session(i))}
      activeKey={null} loading={false} onOpenChange={() => {}} onSelect={onSelect} />);
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(24);
    const input = screen.getByRole("textbox", { name: "Search" });
    for (let i = 0; i < 40; i++) fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("websocket:chat-40");
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(24);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shares keyboard rotation and dismissal with the body portal without losing a draft", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
    const viewport = Object.assign(new EventTarget(), { height: 428, offsetTop: 0, scale: 1 });
    vi.stubGlobal("visualViewport", viewport);
    const onSelect = vi.fn();
    function SearchApp() {
      useAppViewport();
      const [open, setOpen] = useState(true);
      return <>
        <textarea aria-label="Draft" defaultValue="Unsent draft" />
        <SessionSearchDialog open={open} sessions={[session(1), session(2)]}
          activeKey={null} loading={false} onOpenChange={setOpen} onSelect={onSelect} />
      </>;
    }
    const root = document.createElement("div");
    root.id = "root";
    document.body.append(root);
    const app = render(<SearchApp />, { container: root });
    try {
      const dialog = screen.getByRole("dialog");
      expect(root.contains(dialog)).toBe(false);
      act(() => {
        Object.assign(viewport, { height: 128, offsetTop: -68 });
        viewport.dispatchEvent(new Event("resize"));
      });
      expect(root).toHaveClass("short-visual-viewport");
      expect(document.documentElement.style.getPropertyValue("--app-viewport-height")).toBe("128px");
      expect(dialog).toHaveClass("session-search-dialog");
      expect(document.documentElement.style.getPropertyValue("--app-viewport-top")).toBe("0px");
      act(() => {
        Object.assign(viewport, { height: 428, offsetTop: 0 });
        viewport.dispatchEvent(new Event("resize"));
      });
      expect(root).not.toHaveClass("short-visual-viewport");
      fireEvent.change(screen.getByRole("textbox", { name: "Search" }), { target: { value: "Chat 2" } });
      expect(screen.getAllByRole("button")).toHaveLength(1);
      fireEvent.click(screen.getByRole("button", { name: /Chat 2/ }));
      expect(onSelect).toHaveBeenCalledOnce();
      expect(onSelect).toHaveBeenCalledWith("websocket:chat-2");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("Unsent draft");
    } finally {
      app.unmount();
      root.remove();
    }
  });

  it("uses a solid compact command palette surface", () => {
    render(
      <SessionSearchDialog
        open
        sessions={[{ ...session(1), title: "Model chat", preview: "/model fast" }]}
        activeKey={null}
        loading={false}
        onOpenChange={() => {}}
        onSelect={() => {}}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveClass("bg-background");
    expect(dialog.className).not.toContain("bg-popover/");
    expect(dialog.className).not.toContain("backdrop-blur");
    // The body portal must share the app's keyboard-fitted frame. Its list
    // height is bounded by that frame, not by the layout viewport's 100vh.
    expect(dialog.parentElement).toHaveStyle({
      top: "var(--app-viewport-top, 0px)",
      height: "var(--app-viewport-height, 100%)",
      bottom: "auto",
    });
    expect(dialog).toHaveClass("max-h-[min(40rem,100%)]");
    expect(screen.getByTestId("session-search-scroll")).toHaveClass("overflow-y-auto");
    expect(screen.queryByText("/model fast")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), {
      target: { value: "model fast" },
    });
    expect(screen.queryByText("Model chat")).not.toBeInTheDocument();
  });

  it("finds cached body substrings with a bounded preview and no data requests", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const cache = new ThreadMessageCache(() => false);
    const body: UIMessage = {
      id: "answer", role: "assistant", createdAt: 1,
      content: `${"Earlier content. ".repeat(1000)}权限配置 Full Access 25% session_history.py`,
    };
    cache.set("chat-1", new ThreadTranscript([body]).save());
    const onSelect = vi.fn();
    render(<SessionSearchDialog open sessions={[session(1), session(2)]}
      activeKey={null} loading={false} messageCache={cache}
      onOpenChange={() => {}} onSelect={onSelect} />);
    expect(screen.getByPlaceholderText("Search loaded content")).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "Search" });
    for (const query of ["权限", "full access", "25%", "session_history.py"]) {
      fireEvent.change(input, { target: { value: query } });
      expect(screen.getByText("Chat 1")).toBeInTheDocument();
      expect(screen.queryByText("Chat 2")).not.toBeInTheDocument();
      expect(screen.getByText(/权限配置 Full Access/).textContent!.length).toBeLessThanOrEqual(162);
    }
    fireEvent.change(input, { target: { value: "uncached server content" } });
    expect(screen.getByText("No matching topics.")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "权限" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("websocket:chat-1");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("updates an open query for streamed messages and cache eviction without duplicate sessions", () => {
    const cache = new ThreadMessageCache(() => false, 100_000, 1);
    const body = (content: string): UIMessage => ({ id: "answer", role: "assistant", content, createdAt: 1 });
    cache.set("chat-1", new ThreadTranscript([body("Cached needle")]).save());
    render(<SessionSearchDialog open sessions={[session(1), session(2)]}
      activeKey={null} loading={false} messageCache={cache}
      onOpenChange={() => {}} onSelect={() => {}} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), { target: { value: "needle" } });
    expect(screen.getByText("Chat 1")).toBeInTheDocument();
    act(() => cache.setLoadedMessages("chat-2", [[body("Streaming needle"), body("Another needle")]]));
    expect(screen.getAllByText("Chat 2")).toHaveLength(1);
    act(() => cache.set("chat-2", new ThreadTranscript([body("Streaming needle")]).save()));
    expect(screen.queryByText("Chat 1")).not.toBeInTheDocument();
    act(() => cache.setLoadedMessages("chat-2", [[body("Replacement answer")]]));
    expect(screen.queryByText("Chat 2")).not.toBeInTheDocument();
  });

  it("keeps keyboard navigation scrollable through long result lists", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    render(
      <SessionSearchDialog
        open
        sessions={Array.from({ length: 24 }, (_, index) => session(index + 1))}
        activeKey={null}
        loading={false}
        onOpenChange={() => {}}
        onSelect={() => {}}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Search" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });

    expect(scrollIntoView).toHaveBeenCalledWith({
      block: "nearest",
      inline: "nearest",
    });
  });
});
