import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ client: { status: "idle", onStatus: () => () => {} } }),
}));

function noop() {}

// Reproduces the #5770 chain: the mobile drawer autofocuses the search button
// (Radix focus-scope default), and focusing a tooltip trigger with no preceding
// pointerdown opens its tooltip.
function DrawerWithSearchTooltip(props: {
  onOpenAutoFocus?: (event: Event) => void;
}) {
  return (
    <TooltipProvider>
      <Sheet open onOpenChange={noop}>
        <SheetContent
          side="left"
          showCloseButton={false}
          aria-describedby={undefined}
          onOpenAutoFocus={props.onOpenAutoFocus}
        >
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button">search</button>
            </TooltipTrigger>
            <TooltipContent side="bottom">Search tip</TooltipContent>
          </Tooltip>
        </SheetContent>
      </Sheet>
    </TooltipProvider>
  );
}

describe("SheetContent autofocus", () => {
  // happy-dom reports tabIndex -1 for natively focusable elements without an
  // explicit tabindex attribute (browsers report 0), which makes Radix
  // getTabbableCandidates() find nothing. Stub browser behavior so the
  // autofocus path under test actually runs.
  const tabIndexDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "tabIndex");
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "tabIndex", {
      configurable: true,
      get(this: HTMLElement): number {
        const attr = this.getAttribute("tabindex");
        if (attr !== null) return Number(attr);
        if (/^(BUTTON|A|INPUT|SELECT|TEXTAREA)$/.test(this.tagName)) return 0;
        return -1;
      },
    });
  });
  afterEach(() => {
    if (tabIndexDesc) Object.defineProperty(HTMLElement.prototype, "tabIndex", tabIndexDesc);
  });

  it("does not steal focus into the search button or pop its tooltip on open (#5770)", async () => {
    render(<DrawerWithSearchTooltip />);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveFocus());
    const searchButton = within(dialog).getByRole("button", { name: "search" });
    expect(searchButton).not.toHaveFocus();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("honors a caller-supplied onOpenAutoFocus handler", async () => {
    const onOpenAutoFocus = vi.fn((event: Event) => event.preventDefault());
    render(<DrawerWithSearchTooltip onOpenAutoFocus={onOpenAutoFocus} />);
    await screen.findByRole("dialog");
    await waitFor(() => expect(onOpenAutoFocus).toHaveBeenCalled());
  });
});
