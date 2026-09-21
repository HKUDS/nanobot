import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { UsageDashboard } from "@/components/settings/UsageDashboard";
import { TokenUsageDetails } from "@/components/settings/TokenUsageDetails";
import { fetchUsageDetails } from "@/lib/api";
import type { UsageDetails, UsageRange } from "@/lib/types";
import { usageCalendar, usageModelLabel } from "@/lib/usage-dashboard";
import { usageDetails } from "@/tests/fixtures/usage-details";

describe("Usage dashboard", () => {
  it("loads only when opened and shows a single window, actual models and unknown measurements", async () => {
    const load = vi.fn(async (range: UsageRange) => usageDetails(range));
    render(<TokenUsageDetails days={[]} loadDetails={load} />);
    expect(load).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    expect(await screen.findByRole("table", { name: "Model breakdown" })).toBeInTheDocument();
    expect(load).toHaveBeenCalledWith("30");
    const close = screen.getByRole("button", { name: "Close" });
    expect(close.closest("[data-usage-details-scroll]")).toBeNull();
    expect(screen.getByRole("dialog")).toContainElement(close);
    expect(screen.getByText("2026-08-24 – 2026-09-22 · Asia/Shanghai")).toBeInTheDocument();
    const primary = screen.getByRole("row", { name: /demo\/primary/ });
    expect(primary).toHaveTextContent("—");
    expect(screen.getByRole("row", { name: /demo\/backup/ })).toHaveTextContent("50%");
    expect(screen.getByText(/1 requests without token usage/)).toBeInTheDocument();
    expect(screen.getByText(/not a provider bill/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "7 days" }));
    expect(await screen.findByText("2026-09-16 – 2026-09-22 · Asia/Shanghai")).toBeInTheDocument();
    const heatmap = screen.getByRole("group", { name: "Daily activity" });
    expect(within(heatmap).getAllByRole("button")).toHaveLength(7);
    const trend = screen.getByRole("group", { name: "Model usage over time" });
    fireEvent.click(within(trend).getByRole("button", { name: /2026-09-22/ }));
    expect(screen.getAllByRole("status").some(node => node.textContent?.includes("demo/backup"))).toBe(true);
  });

  it("ignores stale range results and never paints an old window as the new one", async () => {
    let resolveOld!: (data: UsageDetails) => void;
    const load = vi.fn((range: UsageRange) => range === "30"
      ? new Promise<UsageDetails>(resolve => { resolveOld = resolve; })
      : Promise.resolve(usageDetails(range)));
    render(<UsageDashboard load={load} />);
    fireEvent.click(screen.getByRole("button", { name: "7 days" }));
    await screen.findByText("2026-09-16 – 2026-09-22 · Asia/Shanghai");
    await act(async () => resolveOld(usageDetails("30")));
    expect(screen.queryByText(/2026-08-24 –/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
  });

  it("offers an explicit retry instead of showing failed loads as zero", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("Unavailable")).mockResolvedValue(usageDetails());
    render(<UsageDashboard load={load} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load usage details");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("table", { name: "Model breakdown" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("allows keyboard and tap inspection of zero-token failed request days", async () => {
    render(<UsageDashboard load={async () => usageDetails("7")} />);
    const group = await screen.findByRole("group", { name: "Daily activity" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.filter(button => button.tabIndex === 0)).toEqual([buttons[6]]);
    act(() => buttons[6].focus());
    fireEvent.keyDown(buttons[6], { key: "ArrowUp" });
    expect(buttons[5]).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("2026-09-21: 0 tokens, 1 requests");
    fireEvent.keyDown(buttons[5], { key: "Home" });
    expect(buttons[0]).toHaveFocus();
    fireEvent.click(buttons[6]);
    expect(screen.getByRole("status")).toHaveTextContent("2026-09-22: 100 tokens, 1 requests");
    expect(screen.getByRole("table", { name: "Daily data", hidden: true })).toBeInTheDocument();
  });

  it("keeps calendar labels stable over DST and bounds retained ranges", () => {
    const data = usageDetails();
    data.start_date = "2026-03-07";
    data.end_date = "2026-03-10";
    data.timezone = "America/New_York";
    expect(usageCalendar(data).map(day => day.date)).toEqual(["2026-03-07", "2026-03-08", "2026-03-09", "2026-03-10"]);
    expect(usageCalendar(usageDetails("retained"))).toHaveLength(400);
    expect(usageCalendar(usageDetails("365"))).toHaveLength(365);
    expect(usageModelLabel("codex", "codex/demo")).toBe("codex/demo");
    expect(usageModelLabel("other", "demo")).toBe("other/demo");
  });

  it("requests authenticated noncached details and rejects legacy gateway payloads", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ details: usageDetails("7") }), { headers: { "Content-Type": "application/json" } }));
    try {
      expect(await fetchUsageDetails("test-token", "7")).toEqual(usageDetails("7"));
      expect(fetch).toHaveBeenCalledWith("/api/settings/usage?range=7", expect.objectContaining({
        cache: "no-store", headers: { Authorization: "Bearer test-token" }, credentials: "same-origin",
      }));
      fetch.mockResolvedValue(new Response(JSON.stringify({ days: [] }), { headers: { "Content-Type": "application/json" } }));
      await expect(fetchUsageDetails("test-token", "7")).rejects.toThrow();
    } finally { fetch.mockRestore(); }
  });
});
