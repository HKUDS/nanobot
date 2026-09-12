import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionInfoPopover } from "@/components/thread/SessionInfoPopover";
import { setAppLanguage } from "@/i18n";
import type { WebUIMutationTransport } from "@/lib/api";

const requestMutation = vi.fn();
const client: WebUIMutationTransport = { requestMutation };

function automationJob(
  nextRunAt = Date.now() + 3_600_000,
  state: Record<string, unknown> = {},
) {
  return {
    id: "job-1",
    name: "Morning check",
    enabled: true,
    schedule: { kind: "every", every_ms: 3_600_000 },
    payload: { message: "Check the project status" },
    state: { next_run_at_ms: nextRunAt, ...state },
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
  beforeEach(async () => {
    await setAppLanguage("en");
    requestMutation.mockReset();
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
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/automations",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      );
    });
    const row = await screen.findByRole("button", { name: /Morning check/ });
    expect(row).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.queryByText("Check the project status")).not.toBeInTheDocument();

    await user.click(row);
    const detail = screen.getByRole("dialog", { name: "Morning check" });
    expect(detail).toHaveClass("max-w-[520px]", "rounded-modal");
    expect(within(detail).getByText("Instructions")).toBeInTheDocument();
    expect(within(detail).getByText("Check the project status")).toBeInTheDocument();
    await user.click(within(detail).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Morning check" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Session details" })).toHaveFocus();
  });

  it("manages a session task through the shared detail dialog", async () => {
    const pausedJob = { ...automationJob(), enabled: false };
    requestMutation.mockResolvedValue({ jobs: [pausedJob] });
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));
    await user.click(await screen.findByRole("button", { name: /Morning check/ }));
    const detail = screen.getByRole("dialog", { name: "Morning check" });
    await user.click(within(detail).getByRole("button", { name: "Disable" }));

    expect(requestMutation).toHaveBeenCalledWith(
      "automation.disable",
      { id: "job-1" },
      20_000,
    );
    expect(await within(detail).findByRole("button", { name: "Enable" })).toBeInTheDocument();
  });

  it("returns from the shared editor to the same task detail", async () => {
    const user = userEvent.setup();
    render(
      <SessionInfoPopover
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));
    await user.click(await screen.findByRole("button", { name: /Morning check/ }));
    await user.click(screen.getByRole("button", { name: "Edit", exact: true }));
    const editor = await screen.findByRole("dialog", { name: "Edit automation" });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await user.click(within(editor).getByRole("button", { name: "Cancel", exact: true }));

    expect(await screen.findByRole("dialog", { name: "Morning check" })).toBeVisible();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("localizes the panel chrome in Simplified Chinese", async () => {
    await setAppLanguage("zh-CN");
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        client={client}
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

  it("shows a short pending label for deferred automations", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        automationsResponse([automationJob(Date.now() - 1000, { pending: true })]),
      ),
    );
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    expect(await screen.findByText("Runs shortly")).toBeInTheDocument();
    expect(screen.queryByText(/ago/i)).not.toBeInTheDocument();
  });

  it("shows the actual message received by a local trigger", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        automationsResponse([
          {
            id: "trg_123",
            name: "PR monitor",
            enabled: true,
            kind: "local_trigger",
            schedule: { kind: "local" },
            payload: {
              kind: "local_trigger",
              message: "Review PR #4591",
              command: 'nanobot trigger trg_123 "message"',
            },
            state: { pending: false },
          },
        ]),
      ),
    );
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    const row = await screen.findByRole("button", { name: /PR monitor/ });
    expect(screen.queryByText("Review PR #4591")).not.toBeInTheDocument();
    await user.click(row);
    const detail = screen.getByRole("dialog", { name: "PR monitor" });
    expect(within(detail).getByText("Command")).toBeInTheDocument();
    expect(within(detail).getByText('nanobot trigger trg_123 "message"')).toBeInTheDocument();
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
        client={client}
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

  it("coalesces focus refreshes while a session automation request is in flight", async () => {
    let resolveRequest!: (response: Response) => void;
    const pendingRequest = new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    });
    const fetchMock = vi.fn(() => pendingRequest);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("focus"));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveRequest(automationsResponse([]));
      await pendingRequest;
    });
  });
});
