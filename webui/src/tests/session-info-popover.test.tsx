import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionInfoPopover } from "@/components/thread/SessionInfoPopover";
import { setAppLanguage } from "@/i18n";

function automationJob(nextRunAt = Date.now() + 3_600_000) {
  return {
    id: "job-1",
    name: "Morning check",
    enabled: true,
    schedule: { kind: "every", every_ms: 3_600_000 },
    payload: { message: "Check the project status" },
    state: { next_run_at_ms: nextRunAt },
  };
}

function automationsResponse(jobs: unknown[]) {
  return {
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({
      jobs,
    }),
  } as Response;
}

describe("SessionInfoPopover", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(automationsResponse([automationJob()])),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("loads and displays session automations when opened", async () => {
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/automations",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      );
    });
    expect(await screen.findByText("Morning check")).toBeInTheDocument();
    expect(screen.getByText("Check the project status")).toBeInTheDocument();
  });

  it("localizes the panel chrome in Simplified Chinese", async () => {
    await setAppLanguage("zh-CN");
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="@hyperframes 使用指南"
      />,
    );

    await user.click(screen.getByRole("button", { name: "会话详情" }));

    expect(await screen.findByText("会话")).toBeInTheDocument();
    expect(screen.getByText("自动任务")).toBeInTheDocument();
    expect(screen.getByText("Morning check")).toBeInTheDocument();
    expect(screen.getByText(/下次/)).toBeInTheDocument();
    expect(screen.queryByText("Session")).not.toBeInTheDocument();
    expect(screen.queryByText("Automations")).not.toBeInTheDocument();
  });

  it("refreshes while open so completed one-shot automations disappear", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockResolvedValueOnce(automationsResponse([automationJob(Date.now() + 1000)]))
        .mockResolvedValue(automationsResponse([])),
    );
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));
    expect(await screen.findByText("Morning check")).toBeInTheDocument();

    await waitFor(
      () => {
        expect(screen.queryByText("Morning check")).not.toBeInTheDocument();
      },
      { timeout: 4500 },
    );
    expect(screen.getByText("No automations in this session yet.")).toBeInTheDocument();
  }, 8000);
});
