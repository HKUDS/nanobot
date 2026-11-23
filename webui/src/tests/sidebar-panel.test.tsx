import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SidebarPanel } from "@/components/ui/sidebar-panel";

describe("sidebar presence", () => {
  it("retains the same surface until both slot and content finish closing", async () => {
    const view = (open: boolean) => <SidebarPanel open={open} width={420} aria-label="Details"><input aria-label="Draft" /></SidebarPanel>;
    const { rerender } = render(view(true));
    const panel = screen.getByRole("complementary", { name: "Details" });
    let finishSlot!: () => void;
    let finishSurface!: () => void;
    const slot = new Promise<void>((resolve) => { finishSlot = resolve; });
    const surface = new Promise<void>((resolve) => { finishSurface = resolve; });
    Object.defineProperty(panel, "getAnimations", { value: () => [{ finished: slot }] });
    Object.defineProperty(panel.firstElementChild, "getAnimations", { value: () => [{ finished: surface }] });
    rerender(view(false));
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveAttribute("inert");
    expect(panel).toHaveAttribute("aria-hidden", "true");
    await act(async () => { finishSurface(); });
    expect(panel).toBeInTheDocument();
    await act(async () => { finishSlot(); });
    expect(panel).not.toBeInTheDocument();
  });

  it("does not let an interrupted exit discard the reopened editor", async () => {
    const view = (open: boolean) => <SidebarPanel open={open} width={420} aria-label="Details"><input aria-label="Draft" defaultValue="Unsaved" /></SidebarPanel>;
    const { rerender } = render(view(true));
    const panel = screen.getByRole("complementary", { name: "Details" });
    const input = screen.getByRole("textbox", { name: "Draft" });
    let finish!: () => void;
    const finished = new Promise<void>((resolve) => { finish = resolve; });
    Object.defineProperty(panel, "getAnimations", { value: () => [{ finished }] });
    rerender(view(false));
    rerender(view(true));
    await act(async () => { finish(); });
    expect(screen.getByRole("complementary", { name: "Details" })).toBe(panel);
    expect(screen.getByRole("textbox", { name: "Draft" })).toBe(input);
    expect(input).toHaveValue("Unsaved");
    expect(panel).not.toHaveAttribute("inert");
  });

  it("releases immediately without surface motion, ignoring activity inside it", () => {
    const ref = vi.fn();
    const view = (open: boolean) => <SidebarPanel ref={ref} open={open} width={420} aria-label="Details"><span data-testid="activity" /></SidebarPanel>;
    const { rerender } = render(view(true));
    const panel = screen.getByRole("complementary", { name: "Details" });
    const getActivityAnimations = vi.fn();
    Object.defineProperty(screen.getByTestId("activity"), "getAnimations", { value: getActivityAnimations });
    rerender(view(false));
    expect(panel).not.toBeInTheDocument();
    expect(ref).toHaveBeenLastCalledWith(null);
    expect(getActivityAnimations).not.toHaveBeenCalled();
  });
});
