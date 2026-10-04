import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QuickPairSetup } from "@/components/remote/QuickPairSetup";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import type { ConnectionStatus } from "@/lib/types";
import { NanobotClient } from "@/lib/nanobot-client";
import i18n from "@/i18n";

const mocks = vi.hoisted(() => {
  const action = vi.fn();
  const listeners = new Set<(status: ConnectionStatus) => void>();
  const client = {
    status: "open" as ConnectionStatus,
    requestMutation: action,
    onStatus: (listener: (status: ConnectionStatus) => void) => {
      listeners.add(listener);
      listener(client.status);
      return () => { listeners.delete(listener); };
    },
  };
  return { action, client, listeners, transportClient: null as NanobotClient | null, connect: vi.fn(), refresh: vi.fn(), cancel: vi.fn(), copy: vi.fn() };
});
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client: mocks.transportClient ?? mocks.client }) }));
vi.mock("@/components/remote/RemoteInstances", () => ({ useRemoteConnections: () => ({ connect: mocks.connect, refresh: mocks.refresh, cancel: mocks.cancel, directory: { profiles: [] } }) }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copy }));
const request = () => ({ id: "request-1", command: "nanobot remote pair nbpr1.public", expires: Date.now() / 1000 + 600 });
const preview = { id: "request-1", host: "ubuntu@server", hostname: "team", fingerprint: "SHA256:trusted-server", authorized_until: Date.now() / 1000 + 86400, revoke_command: "nanobot remote revoke request-1" };

beforeEach(async () => {
  await i18n.changeLanguage("en");
  mocks.client.status = "open";
  mocks.listeners.clear();
  mocks.action.mockReset().mockImplementation(async (action: string) => {
    if (action === "remote.pair_start") return request();
    if (action === "remote.pair_preview") return preview;
    if (action === "remote.pair_finish") return { id: "paired-server" };
    return {};
  });
  mocks.copy.mockReset().mockResolvedValue(true);
  mocks.connect.mockReset().mockResolvedValue(undefined);
  mocks.refresh.mockReset().mockResolvedValue(undefined);
});
afterEach(() => { cleanup(); mocks.transportClient?.close(); mocks.transportClient = null; vi.useRealTimers(); vi.restoreAllMocks(); });
const view = (onSSH = vi.fn(), onClose = vi.fn()) => render(<Dialog open><DialogContent><QuickPairSetup onSSH={onSSH} onClose={onClose} /></DialogContent></Dialog>);
function chooseOtherWay(name: string) {
  fireEvent.pointerDown(screen.getByRole("button", { name: "Other ways" }), { button: 0, ctrlKey: false });
  fireEvent.click(screen.getByRole("menuitem", { name }));
}
function setStatus(status: ConnectionStatus) {
  act(() => {
    mocks.client.status = status;
    mocks.listeners.forEach((listener) => listener(status));
  });
}
function returnedView() {
  return render(<Dialog open><DialogContent><QuickPairSetup returned={{ id: "request-1", code: "nbpc1.encrypted" }} onSSH={vi.fn()} onClose={vi.fn()} /></DialogContent></Dialog>);
}

async function reviewed() {
  await screen.findByRole("button", { name: "Copy command" });
  chooseOtherWay("Use a connection code instead");
  fireEvent.change(await screen.findByRole("textbox", { name: "Connection code" }), { target: { value: "nbpc1.encrypted" } });
  fireEvent.click(screen.getByRole("button", { name: "Review connection" }));
  await screen.findByRole("heading", { name: "Open this nanobot?" });
}

describe("quick pairing", () => {
  it("keeps retry available if saving finishes as the invitation expires", async () => {
    const timer = vi.spyOn(window, "setTimeout");
    view(); await reviewed();
    const expiry = timer.mock.calls.find(([, delay]) => typeof delay === "number" && delay > 599_000)?.[0];
    expect(typeof expiry).toBe("function");
    let finish!: (value: { id: string }) => void;
    mocks.action.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    mocks.connect.mockRejectedValueOnce(new Error("ssh_connection_closed"));
    fireEvent.click(screen.getByRole("button", { name: "Connect", exact: true }));
    act(() => { if (typeof expiry === "function") expiry(); });
    await act(async () => finish({ id: "paired-server" }));
    expect(await screen.findByRole("button", { name: "Retry", exact: true })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Open this nanobot?" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Get a new command" })).not.toBeInTheDocument();
  });
  it("replaces an expired confirmation with a new-command action", async () => {
    const timer = vi.spyOn(window, "setTimeout");
    view(); await reviewed();
    const expiry = timer.mock.calls.find(([, delay]) => typeof delay === "number" && delay > 599_000)?.[0];
    expect(typeof expiry).toBe("function");
    act(() => { if (typeof expiry === "function") expiry(); });
    expect(screen.getByRole("button", { name: "Get a new command" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: "Open this nanobot?" })).not.toBeInTheDocument();
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it.each(["pair_expired", "pair_used"])("offers a new command when manual review reports %s", async (code) => {
    mocks.action.mockImplementation(async (action: string) => {
      if (action === "remote.pair_start") return request();
      if (action === "remote.pair_preview") throw new Error(code);
      return {};
    });
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    chooseOtherWay("Use a connection code instead");
    fireEvent.change(screen.getByRole("textbox", { name: "Connection code" }), { target: { value: "nbpc1.expired" } });
    fireEvent.click(screen.getByRole("button", { name: "Review connection" }));
    const restart = await screen.findByRole("button", { name: "Get a new command" });
    expect(screen.queryByRole("textbox", { name: "Connection code" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
    fireEvent.click(restart);
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.action.mock.calls.filter(([action]) => action === "remote.pair_start")).toHaveLength(2);
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("does not start work when mounted only for the closing animation", () => {
    render(<Dialog open><DialogContent><QuickPairSetup active={false} onSSH={vi.fn()} onClose={vi.fn()} /></DialogContent></Dialog>);
    expect(mocks.action).not.toHaveBeenCalled();
  });
  it("ignores a preview arriving during the closing animation", async () => {
    let resolve!: (value: typeof preview) => void;
    mocks.action.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const returned = { id: "request-1", code: "nbpc1.encrypted" };
    const content = (active: boolean) => <Dialog open><DialogContent><QuickPairSetup active={active} returned={returned} onSSH={vi.fn()} onClose={vi.fn()} /></DialogContent></Dialog>;
    const result = render(content(true));
    result.rerender(content(false));
    await act(async () => resolve(preview));
    expect(screen.queryByRole("heading", { name: "Open this nanobot?" })).not.toBeInTheDocument();
    expect(mocks.connect).not.toHaveBeenCalled();
    expect(mocks.action).toHaveBeenCalledTimes(1);
  });
  it("cleans up an invitation arriving during the closing animation", async () => {
    let resolve!: (value: ReturnType<typeof request>) => void;
    mocks.action.mockImplementation((action: string) => action === "remote.pair_start" ? new Promise((done) => { resolve = done; }) : Promise.resolve({}));
    const content = (active: boolean) => <Dialog open><DialogContent><QuickPairSetup active={active} onSSH={vi.fn()} onClose={vi.fn()} /></DialogContent></Dialog>;
    const result = render(content(true));
    result.rerender(content(false));
    await act(async () => resolve(request()));
    expect(mocks.action).toHaveBeenCalledWith("remote.pair_cancel", { id: "request-1" }, 65000);
  });
  it("uses the same copyable revocation code block in pairing details", async () => {
    returnedView();
    await screen.findByRole("heading", { name: "Open this nanobot?" });
    fireEvent.click(screen.getByRole("button", { name: "Connection details & revocation" }));
    expect(screen.getByText(preview.revoke_command).closest("pre")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeVisible();
    expect(mocks.copy).toHaveBeenCalledWith(preview.revoke_command);
    expect(mocks.connect).not.toHaveBeenCalled();
    expect(mocks.action.mock.calls.some(([action]) => action === "remote.pair_finish")).toBe(false);
  });
  it("explains an existing instance and saves its additional authorization only on confirmation", async () => {
    mocks.action.mockImplementation(async (action: string) => {
      if (action === "remote.pair_preview") return { ...preview, existing_connection: { id: "saved-server", name: "My team", connected: true } };
      if (action === "remote.pair_finish") return { id: "saved-server" };
      return {};
    });
    returnedView();
    await screen.findByRole("heading", { name: "This nanobot is already saved" });
    expect(screen.getByText("My team")).toBeVisible();
    expect(screen.getByText(i18n.t("remote.sameInstance.pairHint"))).toBeVisible();
    expect(mocks.action.mock.calls.some(([action]) => action === "remote.pair_finish")).toBe(false);
    expect(mocks.connect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save and open" }));
    await waitFor(() => expect(mocks.connect).toHaveBeenCalledWith("saved-server", expect.any(Function)));
    expect(mocks.action).toHaveBeenCalledWith("remote.pair_finish", { id: "request-1", code: "nbpc1.encrypted" }, 65000);
  });
  it("introduces remote access with the original logo and no duplicate instruction spacer", async () => {
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAccessibleName("Connect to remote nanobot");
    expect(dialog).toHaveAccessibleDescription(i18n.t("remote.pair.introHint"));
    const illustration = dialog.querySelector('image[href="/brand/nanobot_mark.svg"]')?.closest("svg");
    expect(illustration).toHaveAttribute("aria-hidden", "true");
    expect(illustration).toHaveAttribute("focusable", "false");
    expect(dialog.querySelector(".invisible")).toBeNull();
    expect(screen.queryByText(i18n.t("remote.pair.afterCopyHint"))).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    await screen.findByRole("heading", { name: "Command copied" });
    expect(dialog.querySelector('image[href="/brand/nanobot_mark.svg"]')?.closest("svg")).toBe(illustration);
    expect(screen.queryByText(i18n.t("remote.pair.introHint"))).toBeNull();
  });
  it("keeps the illustration out of code entry and authorization review", async () => {
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    chooseOtherWay("Use a connection code instead");
    const dialog = screen.getByRole("dialog");
    expect(dialog.querySelector('image[href="/brand/nanobot_mark.svg"]')).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Connection code" }), { target: { value: "nbpc1.encrypted" } });
    fireEvent.click(screen.getByRole("button", { name: "Review connection" }));
    await screen.findByRole("heading", { name: "Open this nanobot?" });
    expect(dialog.querySelector('image[href="/brand/nanobot_mark.svg"]')).toBeNull();
    expect(screen.getByText(i18n.t("remote.pair.access"))).toBeVisible();
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("reviews through the real NanobotClient after its socket opens", async () => {
    const socket = {
      readyState: 0,
      onopen: null as (() => void) | null,
      onmessage: null as ((event: MessageEvent) => void) | null,
      onerror: null as (() => void) | null,
      onclose: null as (() => void) | null,
      send: vi.fn(), close: vi.fn(),
    };
    mocks.transportClient = new NanobotClient({
      url: "ws://local-test", reconnect: false,
      socketFactory: () => socket as unknown as WebSocket,
    });
    mocks.transportClient.connect();
    returnedView();
    expect(socket.send).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    act(() => { socket.readyState = 1; socket.onopen?.(); });
    const frame = JSON.parse(socket.send.mock.calls[0][0]);
    expect(frame).toMatchObject({ type: "webui_request", action: "remote.pair_preview", payload: { id: "request-1", code: "nbpc1.encrypted" } });
    await act(async () => {
      socket.onmessage?.({ data: JSON.stringify({ event: "webui_response", request_id: frame.request_id, ok: true, result: preview }) } as MessageEvent);
    });
    expect(screen.getByRole("heading", { name: "Open this nanobot?" })).toBeVisible();
    expect(socket.send).toHaveBeenCalledTimes(1);
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("waits for the local socket on a cold return-link page and reviews only once", async () => {
    mocks.client.status = "connecting";
    returnedView();
    expect(mocks.action).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "Get a new command" })).toBeNull();
    setStatus("open");
    await screen.findByRole("heading", { name: "Open this nanobot?" });
    setStatus("reconnecting"); setStatus("open");
    expect(mocks.action).toHaveBeenCalledTimes(1);
    expect(mocks.action).toHaveBeenCalledWith("remote.pair_preview", { id: "request-1", code: "nbpc1.encrypted" }, 65000);
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("waits before preparing an invitation and stops waiting when the dialog closes", () => {
    mocks.client.status = "connecting";
    const result = view();
    expect(mocks.action).not.toHaveBeenCalled();
    result.unmount();
    setStatus("open");
    expect(mocks.action).not.toHaveBeenCalled();
    expect(mocks.listeners.size).toBe(0);
  });
  it("explains a slow local connection and recovers without discarding the receipt", async () => {
    vi.useFakeTimers();
    mocks.client.status = "connecting";
    returnedView();
    await act(async () => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByRole("alert")).toHaveTextContent(/local nanobot/);
    expect(screen.queryByRole("button", { name: "Get a new command" })).toBeNull();
    expect(mocks.action).not.toHaveBeenCalled();
    setStatus("open");
    await act(async () => {});
    expect(screen.getByRole("heading", { name: "Open this nanobot?" })).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it.each([["WebUI connection is not open", 503], ["WebUI request timed out after 65000ms", 504]])("retries the same returned receipt after %s", async (message, status) => {
    mocks.action.mockRejectedValueOnce(Object.assign(new Error(String(message)), { status }));
    returnedView();
    expect(await screen.findByRole("alert")).toHaveTextContent(/local nanobot/);
    expect(screen.queryByRole("button", { name: "Get a new command" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("heading", { name: "Open this nanobot?" });
    expect(mocks.action.mock.calls.map(([action]) => action)).toEqual(["remote.pair_preview", "remote.pair_preview"]);
    expect(mocks.action.mock.calls[0]).toEqual(mocks.action.mock.calls[1]);
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("never asks a returning user to copy another command while validating their link", async () => {
    mocks.action.mockImplementation(() => new Promise(() => {}));
    render(<Dialog open><DialogContent><QuickPairSetup returned={{ id: "request-1", code: "nbpc1.encrypted" }} onSSH={vi.fn()} onClose={vi.fn()} /></DialogContent></Dialog>);
    expect(screen.getByRole("heading", { name: "Review connection" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Copy command" })).toBeNull();
    expect(screen.queryByText(i18n.t("remote.pair.introHint"))).toBeNull();
    expect(screen.getByRole("button", { name: "Review connection" })).toBeDisabled();
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("shows only the next action and reveals requirements on demand", async () => {
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    expect(screen.getByText(/For Linux servers/).closest(".inline-disclosure")).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("menuitem")).toBeNull();
    expect(screen.queryByText(i18n.t("remote.pair.afterCopyHint"))).toBeNull();
    chooseOtherWay("Requirements & help");
    expect(screen.getByText(/For Linux servers/)).toBeVisible();
    expect(screen.getByText(/Commands expire after 10 minutes/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "View command" }));
    expect(screen.getByText(request().command)).toBeVisible();
    expect(screen.getByText(/For Linux servers/).closest(".inline-disclosure")).toHaveAttribute("aria-hidden", "true");
  });
  it("keeps closed command details mounted but inert for reversible transitions", async () => {
    view();
    const toggle = await screen.findByRole("button", { name: "View command" });
    const panel = document.getElementById(toggle.getAttribute("aria-controls")!);
    expect(panel).toHaveAttribute("data-state", "closed");
    expect(panel).toHaveAttribute("inert");
    fireEvent.click(toggle);
    expect(panel).toHaveAttribute("data-state", "open");
    expect(panel).not.toHaveAttribute("inert");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).toBe(panel);
    expect(panel).toHaveAttribute("aria-hidden", "true");
    expect(panel).toHaveAttribute("inert");
  });
  it("keeps preparation in the button, and delays its indicator without delaying readiness", async () => {
    vi.useFakeTimers();
    let finish!: (value: ReturnType<typeof request>) => void;
    mocks.action.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    view();
    const button = screen.getByRole("button", { name: "Copy command" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("Preparing your connection…")).toBeNull();
    act(() => { vi.advanceTimersByTime(199); });
    expect(button).toHaveTextContent("Copy command");
    act(() => { vi.advanceTimersByTime(1); });
    expect(button).toHaveTextContent("Preparing your connection…");
    expect(screen.getByRole("status").closest("button")).toBe(button);
    await act(async () => finish(request()));
    expect(button).toHaveTextContent("Copy command");
    expect(button).toBeEnabled();
    expect(button).toHaveAttribute("aria-busy", "false");
  });
  it("does not flash a delayed status after fast preparation finishes", async () => {
    vi.useFakeTimers();
    view();
    await act(async () => {});
    act(() => { vi.advanceTimersByTime(250); });
    expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled();
    expect(screen.queryByText("Preparing your connection…")).toBeNull();
  });
  it("preserves the pasted code and SSH fallback during a slow review", async () => {
    const ssh = vi.fn();
    view(ssh);
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    chooseOtherWay("Use a connection code instead");
    fireEvent.change(screen.getByRole("textbox", { name: "Connection code" }), { target: { value: "nbpc1.unfinished" } });
    mocks.action.mockImplementation(() => new Promise(() => {}));
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Review connection" }));
    act(() => { vi.advanceTimersByTime(200); });
    expect(screen.getByRole("textbox", { name: "Connection code" })).toHaveValue("nbpc1.unfinished");
    expect(screen.getByRole("button", { name: "Checking the connection link…" })).toBeDisabled();
    chooseOtherWay("Use existing SSH settings");
    expect(ssh).toHaveBeenCalledOnce();
  });
  it("advances only after copying succeeds and never implies a server connection", async () => {
    let finish!: (success: boolean) => void;
    mocks.copy.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    expect(screen.getByRole("heading", { name: "Connect to remote nanobot" })).toBeVisible();
    await act(async () => finish(true));
    expect(screen.getByRole("heading", { name: "Command copied" })).toBeVisible();
    expect(screen.getByText(/Paste it into your server terminal/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy again" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Copy again" })).toHaveClass("border", "border-input");
    expect(screen.getByRole("dialog")).toHaveAccessibleDescription(i18n.t("remote.pair.afterCopyHint"));
    expect(mocks.connect).not.toHaveBeenCalled();
    expect(mocks.action.mock.calls.map(([action]) => action)).toEqual(["remote.pair_start"]);
  });
  it("exposes the command when the clipboard fails without claiming it was copied", async () => {
    mocks.copy.mockResolvedValue(false);
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    await screen.findByRole("alert");
    expect(screen.getByText(request().command)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Connect to remote nanobot" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Copy again" })).toBeNull();
  });
  it("keeps a manual code when returning to the simpler command screen", async () => {
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    chooseOtherWay("Use a connection code instead");
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Connection code" })).toHaveFocus());
    fireEvent.change(screen.getByRole("textbox", { name: "Connection code" }), { target: { value: "nbpc1.unfinished" } });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    chooseOtherWay("Use a connection code instead");
    expect(screen.getByRole("textbox", { name: "Connection code" })).toHaveValue("nbpc1.unfinished");
  });
  it("replaces copied guidance with recovery when the invitation expires", async () => {
    const timer = vi.spyOn(window, "setTimeout");
    view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    await screen.findByRole("heading", { name: "Command copied" });
    const expiry = timer.mock.calls.find(([, delay]) => typeof delay === "number" && delay > 599_000)?.[0];
    expect(typeof expiry).toBe("function");
    act(() => { if (typeof expiry === "function") expiry(); });
    expect(screen.queryByRole("heading", { name: "Command copied" })).toBeNull();
    expect(screen.getByText(/This request has expired/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Get a new command" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    expect(screen.queryByText(/This request has expired/)).toBeNull();
  });
  it("can revisit the receipt from return-link confirmation without a disabled copy dead end", async () => {
    render(<Dialog open><DialogContent><QuickPairSetup returned={{ id: "request-1", code: "nbpc1.encrypted" }} onSSH={vi.fn()} onClose={vi.fn()} /></DialogContent></Dialog>);
    await screen.findByRole("heading", { name: "Open this nanobot?" });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("textbox", { name: "Connection code" })).toHaveValue("nbpc1.encrypted");
    expect(screen.getByRole("button", { name: "Review connection" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Copy command" })).toBeNull();
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("prepares one command when Add server opens and keeps the SSH entry", async () => {
    const ssh = vi.fn(); view(ssh);
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    expect(mocks.action.mock.calls.filter(([action]) => action === "remote.pair_start")).toHaveLength(1);
    expect(screen.queryByRole("textbox", { name: /Private key/ })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Connection code" })).toBeNull();
    chooseOtherWay("Use existing SSH settings");
    expect(ssh).toHaveBeenCalledOnce();
  });
  it("reviews public details before storing and opening the connection", async () => {
    const close = vi.fn(); view(vi.fn(), close); await reviewed();
    expect(mocks.action).not.toHaveBeenCalledWith("remote.pair_finish", expect.anything(), expect.anything());
    expect(screen.getByText(/full access/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(mocks.connect).toHaveBeenCalledWith("paired-server", expect.any(Function));
  });
  it("keeps the receipt and saved profile after a network failure, retries without re-authorizing", async () => {
    mocks.connect.mockRejectedValueOnce(new Error("ssh_connection_closed"));
    view(); await reviewed(); fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByRole("alert");
    expect(screen.getByText(/Pairing is saved/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mocks.connect).toHaveBeenCalledTimes(2));
    expect(mocks.action.mock.calls.filter(([action]) => action === "remote.pair_finish")).toHaveLength(1);
  });
  it("shows an actionable invalid-code error without losing the pasted value", async () => {
    mocks.action.mockImplementation(async (action: string) => {
      if (action === "remote.pair_start") return request();
      if (action === "remote.pair_preview") throw new Error("pair_invalid");
      return {};
    });
    view(); await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    chooseOtherWay("Use a connection code instead");
    fireEvent.change(await screen.findByRole("textbox", { name: "Connection code" }), { target: { value: "bad-code" } });
    fireEvent.click(screen.getByRole("button", { name: "Review connection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid/);
    expect(screen.getByRole("textbox", { name: "Connection code" })).toHaveValue("bad-code");
  });
  it("cleans up an invitation returned after closing the dialog", async () => {
    let resolve!: (value: ReturnType<typeof request>) => void;
    mocks.action.mockImplementation((action: string) => action === "remote.pair_start" ? new Promise((done) => { resolve = done; }) : Promise.resolve({}));
    const result = view();
    result.unmount(); await act(async () => resolve(request()));
    expect(mocks.action).toHaveBeenCalledWith("remote.pair_cancel", { id: "request-1" }, 65000);
  });
  it("keeps a displayed invitation when navigating away so the return link survives", async () => {
    const result = view();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    result.unmount();
    expect(mocks.action.mock.calls.some(([action]) => action === "remote.pair_cancel")).toBe(false);
  });
  it("reviews a returned receipt without generating another key or connecting automatically", async () => {
    render(<Dialog open><DialogContent><QuickPairSetup returned={{ id: "request-1", code: "nbpc1.encrypted" }} onSSH={vi.fn()} onClose={vi.fn()} /></DialogContent></Dialog>);
    await screen.findByRole("heading", { name: "Open this nanobot?" });
    expect(mocks.action).toHaveBeenCalledWith("remote.pair_preview", { id: "request-1", code: "nbpc1.encrypted" }, 65000);
    expect(mocks.action.mock.calls.some(([action]) => action === "remote.pair_start" || action === "remote.pair_finish")).toBe(false);
    expect(mocks.connect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(mocks.connect).toHaveBeenCalledOnce());
  });
  it("offers a fresh command when a returned link is invalid", async () => {
    mocks.action.mockRejectedValue(new Error("pair_invalid"));
    render(<Dialog open><DialogContent><QuickPairSetup returned={{ id: "", code: "" }} onSSH={vi.fn()} onClose={vi.fn()} /></DialogContent></Dialog>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid/);
    expect(screen.getByRole("button", { name: "Get a new command" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Copy command" })).toBeNull();
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("recovers from preparation failure without showing a stuck preparing state", async () => {
    mocks.action.mockRejectedValueOnce(new Error("local_io_error"));
    view();
    await screen.findByRole("alert");
    expect(screen.queryByText("Preparing your connection…")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Get a new command" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy command" })).toBeEnabled());
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
