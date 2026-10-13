import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AutomationRunDialog } from "@/components/settings/system/AutomationRunDialog";
import { fetchAutomationRunResult } from "@/lib/api";
import i18n from "@/i18n";
import type { SessionAutomationJob } from "@/lib/types";

vi.mock("@/lib/api", () => ({ fetchAutomationRunResult: vi.fn() }));
const fetchResult = vi.mocked(fetchAutomationRunResult);
const job: SessionAutomationJob = {
  id: "reminder", name: "Water reminder", enabled: true,
  schedule: { kind: "every", every_ms: 60000 }, payload: { message: "Current instructions" },
  state: {}, origin: { channel: "websocket", session_key: "websocket:one" },
};
const run = { run_at_ms: 1000, status: "ok", duration_ms: 3000 };
const props = { token: "test-token", job, run, locale: "en", open: true,
  onOpenChange: vi.fn(), onCloseAutoFocus: vi.fn() };

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("en");
});
afterEach(cleanup);

describe("Automation run response", () => {
  it("loads only the selected run and renders its Markdown response", async () => {
    let complete!: (value: { response: string }) => void;
    fetchResult.mockReturnValue(new Promise((resolve) => { complete = resolve; }));
    render(<AutomationRunDialog {...props} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading response…");
    expect(screen.queryByText("This record doesn’t include the response text.")).not.toBeInTheDocument();
    expect(fetchResult).toHaveBeenCalledWith("test-token", "reminder", 1000, "cron", expect.any(AbortSignal));
    await act(async () => complete({ response: "**Drink water**" }));
    await act(async () => { await vi.dynamicImportSettled(); });
    expect(await screen.findByText("Drink water")).toBeVisible();
    expect(screen.getByText("Drink water").tagName).toBe("STRONG");
    expect(screen.queryByText("Current instructions")).not.toBeInTheDocument();
  });

  it("shows a retryable loading error instead of claiming no response exists", async () => {
    fetchResult.mockRejectedValueOnce(new Error("Network error"));
    fetchResult.mockResolvedValueOnce({ response: "Recovered response" });
    const user = userEvent.setup();
    render(<AutomationRunDialog {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load the response.");
    expect(screen.queryByText("This record doesn’t include the response text.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Recovered response")).toBeVisible();
    expect(fetchResult).toHaveBeenCalledTimes(2);
  });

  it("aborts stale requests and never shows an earlier run's reply", async () => {
    let first!: (value: { response: string }) => void;
    let second!: (value: { response: string }) => void;
    fetchResult.mockReturnValueOnce(new Promise((resolve) => { first = resolve; }));
    fetchResult.mockReturnValueOnce(new Promise((resolve) => { second = resolve; }));
    const { rerender, unmount } = render(<AutomationRunDialog {...props} />);
    const firstSignal = fetchResult.mock.calls[0][4]!;
    rerender(<AutomationRunDialog {...props} run={{ ...run, run_at_ms: 2000 }} />);
    expect(firstSignal.aborted).toBe(true);
    await act(async () => first({ response: "Wrong run" }));
    expect(screen.queryByText("Wrong run")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading response…");
    await act(async () => second({ response: "Selected run" }));
    expect(await screen.findByText("Selected run")).toBeVisible();
    const secondSignal = fetchResult.mock.calls[1][4]!;
    unmount();
    expect(secondSignal.aborted).toBe(true);
  });

  it.each([
    [null, "This record doesn’t include the response text."],
    ["", "No reply was generated."],
  ])("distinguishes unavailable and empty response: %s", async (response, message) => {
    fetchResult.mockResolvedValue({ response });
    render(<AutomationRunDialog {...props} job={{ ...job, kind: "local_trigger" }} />);
    expect(await screen.findByText(message)).toBeVisible();
    expect(fetchResult).toHaveBeenCalledWith("test-token", "reminder", 1000, "local_trigger", expect.any(AbortSignal));
  });

  it("does not fetch a closed result panel", async () => {
    render(<AutomationRunDialog {...props} open={false} />);
    await waitFor(() => expect(fetchResult).not.toHaveBeenCalled());
  });
});
