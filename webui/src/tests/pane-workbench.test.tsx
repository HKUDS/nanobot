import { createPortal } from "react-dom";
import { type ReactNode, useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PaneWorkbench } from "@/components/workbench/PaneWorkbench";
import {
  EMPTY_WORKBENCH_STATE,
  addWorkbenchPane,
  setWorkbenchLayout,
  setWorkbenchPaneLayoutOrder,
  workbenchTab,
  workbenchTabForPane,
} from "@/components/workbench/workbench-model";

function rect(left: number, top: number, width: number, height: number): DOMRect {
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
  };
}

function WorkbenchHarness({
  initialLayout = "columns",
  onPaneOrderChange = () => {},
  onSplitRatiosChange = () => {},
}: {
  initialLayout?: "columns" | "rows";
  onPaneOrderChange?: (paneKeys: string[]) => void;
  onSplitRatiosChange?: (splitRatios: number[]) => void;
} = {}) {
  const [activePaneKey, setActivePaneKey] = useState("beta");
  const [state, setState] = useState(() => {
    const initial = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "alpha", "beta");
    const tabKey = workbenchTabForPane(initial, "alpha").tabKey;
    return setWorkbenchLayout(initial, tabKey, initialLayout);
  });
  const tabKey = workbenchTabForPane(state, "alpha").tabKey;
  const tab = workbenchTab(state, tabKey);
  if (!tab) return null;
  const titles: Record<string, string> = { alpha: "Alpha", beta: "Beta" };

  return (
    <PaneWorkbench
      panes={tab.layoutPaneKeys.map((key) => ({ key, title: titles[key] }))}
      activePaneKey={activePaneKey}
      layout={tab.layout}
      splitRatios={tab.splitRatios}
      showLayoutControl
      onActivatePane={setActivePaneKey}
      onAddPane={vi.fn()}
      onLayoutChange={(layout) => setState((current) => (
        setWorkbenchLayout(current, tabKey, layout)
      ))}
      onPaneOrderChange={(paneKeys) => {
        onPaneOrderChange(paneKeys);
        setState((current) => (
          setWorkbenchPaneLayoutOrder(current, tabKey, paneKeys)
        ));
      }}
      onSplitRatiosChange={onSplitRatiosChange}
      renderPane={(pane, context) => (
        <>
          <button type="button">Focus {pane.title}</button>
          {context.headerPortalTarget && context.active ? createPortal(
            context.headerActions,
            context.headerPortalTarget,
          ) : null}
          {context.composerPortalTarget ? createPortal(
            <div hidden={!context.active}>
              <textarea aria-label={`Composer ${pane.title}`} />
            </div>,
            context.composerPortalTarget,
          ) : null}
        </>
      )}
    />
  );
}

function BspWorkbenchHarness() {
  const panes = ["alpha", "beta", "gamma", "delta"].map((key) => ({
    key,
    title: key,
  }));
  return (
    <PaneWorkbench
      panes={panes}
      activePaneKey="delta"
      layout="bsp"
      splitRatios={[]}
      showLayoutControl
      onActivatePane={vi.fn()}
      onAddPane={vi.fn()}
      onLayoutChange={vi.fn()}
      onPaneOrderChange={vi.fn()}
      onSplitRatiosChange={vi.fn()}
      renderPane={(pane) => <span>{pane.title}</span>}
    />
  );
}

describe("PaneWorkbench", () => {
  const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
  const originalAnimate = HTMLElement.prototype.animate;
  const animate = vi.fn(() => ({
    addEventListener: vi.fn(),
    cancel: vi.fn(),
  }) as unknown as Animation);

  beforeEach(() => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    HTMLElement.prototype.animate = animate;
    HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRect() {
      if (this.dataset.testid === "pane-grid") return rect(0, 0, 1000, 1000);
      if (!this.classList.contains("workbench-pane")) {
        return originalGetBoundingClientRect.call(this);
      }
      const layout = this.parentElement?.dataset.layout;
      const index = Array.from(this.parentElement?.children ?? []).indexOf(this);
      return layout === "rows"
        ? rect(0, index * 500, 1000, 500)
        : rect(index * 500, 0, 500, 1000);
    };
  });

  afterEach(() => {
    HTMLElement.prototype.animate = originalAnimate;
    HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect;
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("focuses without reordering and keeps only the focused composer visible", () => {
    render(<WorkbenchHarness />);

    const grid = screen.getByTestId("pane-grid");
    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Alpha", "Beta"]);
    expect(screen.getByLabelText("Composer Beta")).toBeVisible();
    expect(screen.getByLabelText("Composer Alpha")).not.toBeVisible();

    fireEvent.pointerDown(
      within(screen.getByRole("region", { name: "Alpha" }))
        .getByRole("button", { name: "Focus Alpha" }),
    );

    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Alpha", "Beta"]);
    expect(screen.getByLabelText("Composer Alpha")).toBeVisible();
    expect(screen.getByLabelText("Composer Beta")).not.toBeVisible();
  });

  it("moves the focused pane between workspace slots from its bottom handle", () => {
    const onPaneOrderChange = vi.fn();
    render(<WorkbenchHarness onPaneOrderChange={onPaneOrderChange} />);

    const grid = screen.getByTestId("pane-grid");
    const handle = screen.getByRole("button", { name: "Move Beta pane" });
    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Alpha", "Beta"]);

    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 750, clientY: 990 });
    fireEvent.pointerMove(window, {
      buttons: 1,
      pointerId: 1,
      clientX: 250,
      clientY: 500,
    });
    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Beta", "Alpha"]);
    expect(onPaneOrderChange).toHaveBeenCalledOnce();
    expect(onPaneOrderChange).toHaveBeenCalledWith(["beta", "alpha"]);

    fireEvent.pointerMove(window, {
      buttons: 1,
      pointerId: 1,
      clientX: 750,
      clientY: 500,
    });
    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Alpha", "Beta"]);
    expect(onPaneOrderChange).toHaveBeenLastCalledWith(["alpha", "beta"]);
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 750, clientY: 500 });

    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Alpha", "Beta"]);
    expect(onPaneOrderChange).toHaveBeenCalledTimes(2);
  });

  it("moves panes up and down through stable workspace slots", () => {
    const onPaneOrderChange = vi.fn();
    render(
      <WorkbenchHarness initialLayout="rows" onPaneOrderChange={onPaneOrderChange} />,
    );

    const grid = screen.getByTestId("pane-grid");
    const handle = screen.getByRole("button", { name: "Move Beta pane" });
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500, clientY: 990 });
    fireEvent.pointerMove(window, {
      buttons: 1,
      pointerId: 1,
      clientX: 500,
      clientY: 250,
    });
    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Beta", "Alpha"]);

    fireEvent.pointerMove(window, {
      buttons: 1,
      pointerId: 1,
      clientX: 500,
      clientY: 750,
    });
    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Alpha", "Beta"]);
    expect(onPaneOrderChange.mock.calls).toEqual([
      [["beta", "alpha"]],
      [["alpha", "beta"]],
    ]);
    fireEvent.pointerUp(window, { pointerId: 1, clientX: 500, clientY: 750 });
  });

  it("moves the focused pane between workspace slots with arrow keys", () => {
    render(<WorkbenchHarness />);

    const handle = screen.getByRole("button", { name: "Move Beta pane" });
    act(() => handle.focus());
    expect(handle).toHaveFocus();
    fireEvent.keyDown(handle, { key: "ArrowLeft" });

    expect(Array.from(screen.getByTestId("pane-grid").children)
      .map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Beta", "Alpha"]);
  });

  it("previews edge resizing locally and commits one ratio when dragging ends", () => {
    const onSplitRatiosChange = vi.fn();
    render(<WorkbenchHarness onSplitRatiosChange={onSplitRatiosChange} />);

    const grid = screen.getByTestId("pane-grid");
    const separator = screen.getByRole("separator", {
      name: "Resize pane boundary 1",
    });
    fireEvent.pointerDown(separator, {
      button: 0,
      pointerId: 7,
      clientX: 500,
      clientY: 400,
    });
    fireEvent.pointerMove(window, {
      buttons: 1,
      pointerId: 7,
      clientX: 700,
      clientY: 400,
    });

    expect(grid.style.gridTemplateColumns)
      .toBe("minmax(0, 700fr) minmax(0, 300fr)");
    expect(onSplitRatiosChange).not.toHaveBeenCalled();

    fireEvent.pointerUp(window, { pointerId: 7, clientX: 700, clientY: 400 });
    expect(onSplitRatiosChange).toHaveBeenCalledOnce();
    expect(onSplitRatiosChange).toHaveBeenCalledWith([0.7]);
  });

  it("resizes a pane boundary with the matching arrow keys", () => {
    const onSplitRatiosChange = vi.fn();
    render(<WorkbenchHarness onSplitRatiosChange={onSplitRatiosChange} />);

    const separator = screen.getByRole("separator", {
      name: "Resize pane boundary 1",
    });
    fireEvent.keyDown(separator, { key: "ArrowLeft" });

    expect(onSplitRatiosChange).toHaveBeenCalledWith([0.47]);
  });

  it("keeps one shared layout control and animates geometry changes", async () => {
    render(<WorkbenchHarness />);

    const header = screen.getByTestId("workbench-header-host");
    expect(within(header).getAllByRole("button", { name: "Pane layout" })).toHaveLength(1);
    fireEvent.pointerDown(within(header).getByRole("button", { name: "Pane layout" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Rows" }));
    expect(screen.getByTestId("pane-grid")).toHaveAttribute("data-layout", "rows");
    await waitFor(() => expect(animate).toHaveBeenCalledTimes(2));

    fireEvent.pointerDown(within(header).getByRole("button", { name: "Pane layout" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole("menuitemradio", { name: "BSP" }));
    expect(screen.getByTestId("pane-grid")).toHaveAttribute("data-layout", "bsp");
    await waitFor(() => expect(animate).toHaveBeenCalledTimes(4));
  });

  it("keeps a retargeted pane surface in the same physical motion", async () => {
    const common = {
      layout: "columns" as const,
      showLayoutControl: false,
      onActivatePane: vi.fn(),
      onAddPane: vi.fn(),
      onLayoutChange: vi.fn(),
      onPaneOrderChange: vi.fn(),
      renderPane: (pane: { title: string }) => <span>{pane.title}</span>,
    };
    const { rerender } = render(
      <PaneWorkbench
        {...common}
        panes={[
          { key: "alpha", reactKey: "tab-root", title: "Alpha" },
          { key: "beta", reactKey: "pane:beta", title: "Beta" },
        ]}
        activePaneKey="alpha"
      />,
    );
    animate.mockClear();

    rerender(
      <PaneWorkbench
        {...common}
        panes={[
          { key: "beta", reactKey: "pane:beta", title: "Beta" },
          { key: "gamma", reactKey: "tab-root", title: "Gamma" },
        ]}
        activePaneKey="gamma"
      />,
    );

    await waitFor(() => expect(animate).toHaveBeenCalledWith(
      [
        { transform: "translate(-500px, 0px) scale(1, 1)" },
        { transform: "translate(0, 0) scale(1, 1)" },
      ],
      {
        duration: 260,
        easing: "cubic-bezier(0.2, 0, 0, 1)",
      },
    ));
  });

  it("renders only the active pane and hides workbench controls on mobile", () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: query.includes("max-width: 767px"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    const panes = ["alpha", "beta", "gamma", "delta"].map((key) => ({
      key,
      title: key,
    }));
    const props = {
      panes,
      layout: "bsp" as const,
      showLayoutControl: true,
      onActivatePane: vi.fn(),
      onAddPane: vi.fn(),
      onLayoutChange: vi.fn(),
      onPaneOrderChange: vi.fn(),
      renderPane: (pane: { key: string; title: string }, context: {
        headerActions: ReactNode;
      }) => <>{context.headerActions}<span>{pane.title}</span></>,
    };

    const { rerender } = render(<PaneWorkbench {...props} activePaneKey="gamma" />);

    expect(screen.getByTestId("pane-grid").children).toHaveLength(1);
    expect(screen.getByTestId("workbench-pane-gamma")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pane layout" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add pane" })).not.toBeInTheDocument();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();

    rerender(<PaneWorkbench {...props} activePaneKey="delta" />);
    expect(screen.getByTestId("pane-grid").children).toHaveLength(1);
    expect(screen.getByTestId("workbench-pane-delta")).toBeInTheDocument();
    expect(screen.queryByTestId("workbench-pane-gamma")).not.toBeInTheDocument();
  });

  it("explains why the desktop add-pane control is disabled", () => {
    render(
      <PaneWorkbench
        panes={[{ key: "alpha", title: "Alpha" }]}
        activePaneKey="alpha"
        layout="columns"
        showLayoutControl={false}
        addPaneDisabled
        addPaneDisabledLabel="Maximum 4 panes"
        onActivatePane={vi.fn()}
        onAddPane={vi.fn()}
        onLayoutChange={vi.fn()}
        onPaneOrderChange={vi.fn()}
        renderPane={(_pane, context) => context.headerActions}
      />,
    );

    expect(screen.getByRole("button", { name: "Add pane" }))
      .toHaveAttribute("title", "Maximum 4 panes");
  });

  it("fills the workbench through alternating binary splits", () => {
    render(<BspWorkbenchHarness />);

    const alpha = screen.getByTestId("workbench-pane-alpha");
    const beta = screen.getByTestId("workbench-pane-beta");
    const gamma = screen.getByTestId("workbench-pane-gamma");
    const delta = screen.getByTestId("workbench-pane-delta");
    expect([alpha.style.gridColumn, alpha.style.gridRow]).toEqual(["1 / 2", "1 / 3"]);
    expect([beta.style.gridColumn, beta.style.gridRow]).toEqual(["2 / 4", "1 / 2"]);
    expect([gamma.style.gridColumn, gamma.style.gridRow]).toEqual(["2 / 3", "2 / 3"]);
    expect([delta.style.gridColumn, delta.style.gridRow]).toEqual(["3 / 4", "2 / 3"]);
  });
});
