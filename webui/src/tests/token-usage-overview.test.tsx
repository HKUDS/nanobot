import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TokenUsageOverview } from "@/components/settings/TokenUsageOverview";

const client = {};
const getToken = () => "tok";
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client, getToken }) }));

const overview = { days: [], revision: "overview" };
const models = { ...overview, revision: "models", providers_30d: [], model_days_30d: [] };
const json = (value: unknown) => ({ ok: true, status: 200, json: async () => value }) as Response;

async function settle() {
  await act(async () => {});
}

describe("Token usage loading", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-09T12:00:00Z"));
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("polls conditionally and loads models only while details are open", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if ((init?.headers as Record<string, string>)["If-None-Match"]) {
        return { status: 304 } as Response;
      }
      return json(String(_input).includes("details=true") ? models : overview);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = render(<TokenUsageOverview />);
    await settle();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/settings/usage"]);
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(fetchMock).toHaveBeenLastCalledWith("/api/settings/usage", expect.objectContaining({
      headers: { Authorization: "Bearer tok", "If-None-Match": 'W/"overview"' },
    }));
    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    await settle();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/settings/usage?details=true", expect.anything());
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(fetchMock).toHaveBeenLastCalledWith("/api/settings/usage?details=true", expect.objectContaining({
      headers: { Authorization: "Bearer tok", "If-None-Match": 'W/"models"' },
    }));
    const beforeClose = fetchMock.mock.calls.length;
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    await settle();
    expect(fetchMock).toHaveBeenCalledTimes(beforeClose);
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(fetchMock).toHaveBeenLastCalledWith("/api/settings/usage", expect.anything());
    const beforeLeave = fetchMock.mock.calls.length;
    unmount();
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    fireEvent(window, new Event("focus"));
    expect(fetchMock).toHaveBeenCalledTimes(beforeLeave);
  });

  it("aborts a pending request when hidden and refreshes once when visible again", async () => {
    let visibility = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility as DocumentVisibilityState);
    const signals: AbortSignal[] = [];
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      const signal = init!.signal!;
      signals.push(signal);
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<TokenUsageOverview />);
    await settle();
    fireEvent(window, new Event("focus"));
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    visibility = "hidden";
    fireEvent(document, new Event("visibilitychange"));
    await settle();
    expect(signals[0].aborted).toBe(true);
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    visibility = "visible";
    fireEvent(document, new Event("visibilitychange"));
    await settle();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
