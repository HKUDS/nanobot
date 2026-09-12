import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DevelopmentSettings } from "@/components/settings/DevelopmentSettings";
import { CodexLimits } from "@/components/CodexLimits";
import { controlDevelopment, fetchCodexLimits, fetchDevelopment, type DevelopmentPayload } from "@/lib/operations";

vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client: {}, getToken: token }) }));
const token = () => "test-token";
vi.mock("@/lib/operations", async (original) => ({
  ...await original<typeof import("@/lib/operations")>(),
  fetchCodexLimits: vi.fn(), fetchDevelopment: vi.fn(), controlDevelopment: vi.fn(),
}));

const project: DevelopmentPayload = { enabled: true, project: {
  objective: "Full agreed scope", paused: false, requirements: [{ id: "one", description: "Required behavior" }],
  jobs: [{ id: "dev-one", title: "First change", objective: "Implement behavior", stage: "ready",
    acceptance: ["Acceptance criterion"], notes: ["Builder says done"], blocked_reason: null,
    review: null, review_accepted: false, verification: [] }],
} };

beforeEach(() => { vi.clearAllMocks(); vi.mocked(fetchCodexLimits).mockResolvedValue({ enabled: false, state: "disabled", observed_at: null, gateway_account_matches: null, buckets: [], error: null }); });
afterEach(() => vi.useRealTimers());

describe("development control", () => {
  it("shows full scope and keeps a ready artifact separate from deployed", async () => {
    vi.mocked(fetchDevelopment).mockResolvedValue(project);
    render(<DevelopmentSettings />);
    expect(await screen.findByText("Full agreed scope")).toBeInTheDocument();
    expect(screen.getByText("Sprawdzona zmiana, oczekuje na wdrożenie")).toBeInTheDocument();
    expect(screen.queryByText("Wdrożone")).not.toBeInTheDocument();
    expect(screen.getByText("Required behavior")).toBeInTheDocument();
  });

  it("applies owner pause to the server and displays the returned state", async () => {
    vi.mocked(fetchDevelopment).mockResolvedValue(project);
    vi.mocked(controlDevelopment).mockResolvedValue({ ...project, project: { ...project.project!, paused: true } });
    render(<DevelopmentSettings />);
    fireEvent.click(await screen.findByRole("button", { name: "Wstrzymaj" }));
    await waitFor(() => expect(controlDevelopment).toHaveBeenCalledWith({}, "pause", undefined));
    expect(await screen.findByText("Rozwój wstrzymany")).toBeInTheDocument();
  });

  it("refreshes real quota windows and marks stale observations", async () => {
    const quota = { enabled: true, state: "available" as const, observed_at: 1000, gateway_account_matches: true,
      buckets: [{ limit_id: "codex", limit_name: null, primary: { used_percent: 34, window_duration_mins: 10080, resets_at: null }, secondary: null }], error: null };
    vi.mocked(fetchCodexLimits).mockResolvedValue(quota);
    render(<CodexLimits compact />);
    expect(await screen.findByText("Codex: 7d 34%")).toBeInTheDocument();
    vi.mocked(fetchCodexLimits).mockResolvedValue({ ...quota, state: "stale", buckets: [{ ...quota.buckets[0], primary: { ...quota.buckets[0].primary, used_percent: 38 } }] });
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(await screen.findByText("Codex: 7d 38% · nieaktualne")).toBeInTheDocument();
  });
});
