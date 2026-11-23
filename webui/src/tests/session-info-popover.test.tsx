import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

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
  beforeAll(async () => { await import("@/components/settings/system/AutomationsSettings"); });

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
    await screen.findByText("Check the project status");
    const detail = screen.getByRole("dialog", { name: "Morning check" });
    expect(detail).toHaveClass("max-w-[520px]", "rounded-modal");
    expect(within(detail).queryByText("Task instructions")).not.toBeInTheDocument();
    expect(within(detail).getByText("Check the project status")).toBeInTheDocument();
    await user.click(within(detail).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Morning check" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Session details" })).toHaveFocus();
  });

  it("uses a skeleton for the initial request and keeps jobs while reopening and refreshing", async () => {
    let finish!: (response: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const user = userEvent.setup();
    const view = render(<SessionInfoPopover client={client} sessionKey="websocket:chat-1" token="tok" />);
    await user.click(screen.getByRole("button", { name: "Session details" }));
    expect(screen.getByRole("status", { name: "Loading automations..." })).toHaveAttribute("aria-busy", "true");
    await act(async () => finish(automationsResponse([automationJob()])));
    expect(await screen.findByRole("button", { name: /Morning check/ })).toBeVisible();
    await user.keyboard("{Escape}");
    let fail!: (error: Error) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((_, reject) => { fail = reject; }));
    await user.click(screen.getByRole("button", { name: "Session details" }));
    expect(screen.getByRole("button", { name: /Morning check/ })).toBeVisible();
    expect(screen.queryByRole("status", { name: "Loading automations..." })).not.toBeInTheDocument();
    await act(async () => fail(new Error("Refresh failed")));
    expect(screen.getByRole("button", { name: /Morning check/ })).toBeVisible();
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    view.rerender(<SessionInfoPopover client={client} sessionKey="websocket:chat-2" token="tok" />);
    expect(screen.queryByRole("button", { name: /Morning check/ })).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading automations..." })).toBeVisible();
    await act(async () => finish(automationsResponse([])));
    expect(await screen.findByText("No automations in this session yet.")).toBeVisible();
  });

  it("manages a session task through the shared detail dialog", async () => {
    const boundJob = { ...automationJob(), origin: {
      session_key: "websocket:chat-1", channel: "websocket", chat_id: "chat-1",
    } };
    vi.mocked(fetch).mockResolvedValue(automationsResponse([boundJob]));
    const pausedJob = { ...boundJob, enabled: false };
    requestMutation.mockResolvedValue({ jobs: [pausedJob] });
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));
    await user.click(await screen.findByRole("button", { name: /Morning check/ }));
    await screen.findByText("Check the project status");
    const detail = screen.getByRole("dialog", { name: "Morning check" });
    await user.click(within(detail).getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Disable" }));

    expect(requestMutation).toHaveBeenCalledWith(
      "automation.disable",
      { id: "job-1" },
      20_000,
    );
    await waitFor(() => expect(within(detail).getByRole("button", { name: "More actions" })).toBeEnabled());
    await user.click(within(detail).getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("menuitem", { name: "Enable" })).toBeVisible();
    requestMutation.mockResolvedValue({ jobs: [boundJob] });
    await user.click(screen.getByRole("menuitem", { name: "Enable" }));
    expect(requestMutation).toHaveBeenLastCalledWith(
      "automation.enable", { id: "job-1" }, 20_000,
    );
    await user.click(within(detail).getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("menuitem", { name: "Disable" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(within(detail).getByRole("button", { name: "More actions" })).toHaveFocus();
  });

  it("blocks Escape and outside clicks while saving, then keeps the error and draft in the editor", async () => {
    let failSave!: (error: Error) => void;
    requestMutation.mockImplementationOnce(() => new Promise((_, reject) => { failSave = reject; }));
    const user = userEvent.setup();
    render(
      <SessionInfoPopover
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));
    await user.click(await screen.findByRole("button", { name: /Morning check/ }));
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const editor = await screen.findByRole("dialog", { name: "Edit task" });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    const name = within(editor).getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Edited task name");
    const save = within(editor).getByRole("button", { name: "Save" });
    await user.click(save);
    expect(save).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(editor).toBeVisible();
    fireEvent.pointerDown(editor.closest("[data-dialog-backdrop]")!);
    expect(editor).toBeVisible();

    await act(async () => failSave(new Error("Could not save schedule")));
    expect(await within(editor).findByRole("alert")).toHaveTextContent("Could not save schedule");
    expect(save).toBeEnabled();
    expect(name).toHaveValue("Edited task name");
    await user.click(within(editor).getByRole("button", { name: "Cancel" }));

    expect(await screen.findByRole("dialog", { name: "Morning check" })).toBeVisible();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("keeps the delete confirmation open until the request settles so failures can be retried", async () => {
    let failDelete!: (error: Error) => void;
    requestMutation.mockImplementationOnce(() => new Promise((_, reject) => { failDelete = reject; }));
    const user = userEvent.setup();
    render(<SessionInfoPopover client={client} sessionKey="websocket:chat-1" token="tok" />);
    await user.click(screen.getByRole("button", { name: "Session details" }));
    await user.click(await screen.findByRole("button", { name: /Morning check/ }));
    const detail = await screen.findByRole("dialog", { name: "Morning check" });
    await user.click(within(detail).getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    const confirmation = await screen.findByRole("dialog", { name: "Delete automation" });
    const remove = within(confirmation).getByRole("button", { name: "Delete" });
    await user.click(remove);
    expect(remove).toBeDisabled();
    fireEvent.pointerDown(confirmation.closest("[data-dialog-backdrop]")!);
    expect(confirmation).toBeVisible();
    await user.keyboard("{Escape}");
    expect(confirmation).toBeVisible();

    await act(async () => failDelete(new Error("Could not delete schedule")));
    expect(within(confirmation).getByRole("alert")).toHaveTextContent("Could not delete schedule");
    expect(remove).toBeEnabled();
    requestMutation.mockResolvedValueOnce({ jobs: [] });
    await user.click(remove);
    await waitFor(() => expect(confirmation).not.toBeInTheDocument());
  });

  it("localizes the panel chrome in Simplified Chinese", async () => {
    await setAppLanguage("zh-CN");
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        client={client}
        sessionKey="websocket:chat-1"
        token="tok"
      />,
    );

    await user.click(screen.getByRole("button", { name: "会话详情" }));

    expect(await screen.findByText("自动任务")).toBeInTheDocument();
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
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    const row = await screen.findByRole("button", { name: /PR monitor/ });
    expect(screen.queryByText("Review PR #4591")).not.toBeInTheDocument();
    await user.click(row);
    await screen.findByText("Command");
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
