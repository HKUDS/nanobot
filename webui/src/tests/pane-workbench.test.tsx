import { createPortal } from "react-dom";
import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PaneWorkbench } from "@/components/workbench/PaneWorkbench";
import {
  EMPTY_WORKBENCH_STATE,
  addWorkbenchPane,
  focusWorkbenchPane,
  setWorkbenchLayout,
  workbenchTab,
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

function WorkbenchHarness() {
  const [state, setState] = useState(() => (
    addWorkbenchPane(EMPTY_WORKBENCH_STATE, "alpha", "beta")
  ));
  const tab = workbenchTab(state, "alpha");
  const titles: Record<string, string> = { alpha: "Alpha", beta: "Beta" };

  return (
    <PaneWorkbench
      panes={tab.paneKeys.map((key) => ({ key, title: titles[key] }))}
      activePaneKey={tab.activePaneKey}
      layout={tab.layout}
      onActivatePane={(key) => setState((current) => (
        focusWorkbenchPane(current, "alpha", key)
      ))}
      onAddPane={vi.fn()}
      onLayoutChange={(layout) => setState((current) => (
        setWorkbenchLayout(current, "alpha", layout)
      ))}
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
  });
});
