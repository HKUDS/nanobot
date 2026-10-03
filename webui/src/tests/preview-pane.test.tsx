import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PreviewPane } from "@/components/PreviewPane";
import { FilePreviewStore, useFilePreviewState } from "@/hooks/useFilePreviewState";

describe("preview tabs", () => {
  it("deduplicates targets, keeps selection and width per session, and closes neighboring tabs", () => {
    const store = new FilePreviewStore();
    const storage = vi.spyOn(Storage.prototype, "setItem");
    store.open("a", "file", "chart.png");
    store.open("a", "file", "index.html");
    store.open("a", "file", "data.json");
    store.update("a", { width: 620 });
    store.open("a", "file", "index.html");
    expect(store.get("a").tabs).toHaveLength(3);
    expect(store.get("a").activeId).toBe("file:index.html");
    store.closeTab("a", "file:chart.png");
    expect(store.get("a").activeId).toBe("file:index.html");
    store.closeTab("a", "file:index.html");
    expect(store.get("a").activeId).toBe("file:data.json");
    store.select("a", "missing");
    store.closeTab("a", "missing");
    expect(store.get("a").activeId).toBe("file:data.json");
    store.open("b", "web", "https://example.com");
    expect(store.get("a").width).toBe(620);
    store.closeTab("a", "file:data.json");
    expect(store.get("a")).toMatchObject({ tabs: [], activeId: null, width: 620 });
    expect(store.get("b").tabs).toHaveLength(1);
    store.open("a", "file", "chart.png");
    store.close("a");
    expect(store.get("a")).toMatchObject({ tabs: [], activeId: null, width: 620 });
    store.delete("b");
    store.clear();
    expect(store.get("a").tabs).toEqual([]);
    expect(store.get("b").tabs).toEqual([]);
    expect(storage).not.toHaveBeenCalled();
    storage.mockRestore();
  });

  it("keeps one shell, supports keyboard tabs and close buttons, and never reloads the same tab", async () => {
    const store = new FilePreviewStore();
    store.open("a", "file", "chart.png");
    store.open("a", "file", "index.html");
    store.open("a", "file", "data.json");
    function View() {
      const { state, selectTab, closeTab, close } = useFilePreviewState("a", store);
      return state.activeId ? <PreviewPane tabs={state.tabs} activeId={state.activeId} width={544}
        isClosing={false} onSelect={selectTab} onCloseTab={closeTab} onClose={close} onResizeStart={() => {}}>
        <p>{state.activeId}</p>
      </PreviewPane> : null;
    }
    render(<View />);
    const shell = screen.getByTestId("preview-pane");
    const highlight = screen.getByTestId("preview-tabs-selection-highlight");
    expect(highlight).toHaveAttribute("data-active-id", "file:data.json");
    expect(highlight.className).toContain("bg-sidebar-foreground/[0.055]");
    expect(highlight.className).toContain("motion-reduce:transition-none");
    await waitFor(() => expect(shell.style.getPropertyValue("--file-preview-slot-width")).toBe("544px"));
    fireEvent.click(screen.getByRole("tab", { name: "chart.png" }));
    expect(screen.getByTestId("preview-pane")).toBe(shell);
    expect(screen.getByTestId("preview-tabs-selection-highlight")).toBe(highlight);
    expect(highlight).toHaveAttribute("data-active-id", "file:chart.png");
    expect(shell.style.getPropertyValue("--file-preview-slot-width")).toBe("544px");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("file:chart.png");
    fireEvent.keyDown(screen.getByRole("tab", { name: "chart.png" }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "index.html" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "index.html" })).toHaveAttribute("aria-selected", "true");
    act(() => store.open("a", "file", "index.html"));
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    fireEvent.keyDown(screen.getByRole("tab", { name: "index.html" }), { key: "Delete" });
    expect(screen.queryByRole("tab", { name: "index.html" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "data.json" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Close chart.png" }));
    expect(screen.getByRole("tab", { name: "data.json" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("button", { name: "Close preview pane" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close data.json" }));
    expect(screen.queryByTestId("preview-pane")).not.toBeInTheDocument();
  });

  it("reveals the whole active tab including its close button after the tab strip resizes", () => {
    let resize: (() => void) | undefined;
    const observe = vi.fn();
    const disconnect = vi.fn();
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: () => void) { resize = callback; }
      observe = observe;
      disconnect = disconnect;
    });
    try {
      const tab = { id: "file:chart.png", kind: "file" as const, value: "chart.png" };
      const view = render(<PreviewPane tabs={[tab]} activeId={tab.id} width={544} isClosing={false}
        onSelect={() => {}} onCloseTab={() => {}} onClose={() => {}} onResizeStart={() => {}}>
        <p>Preview</p>
      </PreviewPane>);
      const wholeTab = screen.getByRole("tab", { name: "chart.png" }).parentElement!;
      const reveal = vi.fn();
      wholeTab.scrollIntoView = reveal;
      expect(wholeTab).toContainElement(screen.getByRole("button", { name: "Close chart.png" }));
      expect(observe).toHaveBeenCalledWith(screen.getByRole("tablist"));
      act(() => resize?.());
      expect(reveal).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
      view.unmount();
      expect(disconnect).toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
