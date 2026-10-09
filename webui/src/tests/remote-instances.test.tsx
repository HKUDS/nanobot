import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RemoteInstances, useRemoteConnections } from "@/components/remote/RemoteInstances";
import { RemoteConnectionsPage } from "@/components/remote/RemoteConnectionsPage";
import { Sidebar } from "@/components/Sidebar";
import { HOST_BRIDGE } from "@/components/remote/host-bridge";
import { readSelectedRemote, readRecentRemotes, rememberSelectedRemote, validateRemoteConnection, type RemoteConnection } from "@/lib/remote-instances";
import i18n from "@/i18n";
import * as clipboard from "@/lib/clipboard";
import { clearPairReturn, initializePairReturn } from "@/lib/remote-pair-return";
import type { Window as HappyWindow } from "happy-dom";

(window as unknown as HappyWindow).happyDOM.settings.disableIframePageLoading = true;

const mocks = vi.hoisted(() => {
  const request = vi.fn();
  const discover = vi.fn();
  const onStatus = vi.fn();
  const inspect = vi.fn();
  return { read: vi.fn(), request, discover, inspect, onStatus, client: { status: "open", requestMutation: (action: string, payload: unknown, timeout: number) => {
    // Quick pairing prepares a local-only invitation when Add server opens;
    // these tests track SSH/config mutations separately from that lifecycle.
    if (action === "remote.pair_start") return Promise.resolve({ id: "pending-pair", command: "nanobot remote pair nbpr1.public", expires: Date.now() / 1000 + 600 });
    if (action === "remote.pair_cancel") return Promise.resolve({ cancelled: true });
    return action === "remote.discover" ? discover(payload) : action === "remote.inspect" ? inspect(payload) : request(action, payload, timeout);
  }, onStatus }, token: () => "local-token" };
});
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client: mocks.client, getToken: mocks.token }) }));
vi.mock("@/lib/remote-instances", async (original) => ({
  ...await original<typeof import("@/lib/remote-instances")>(), readRemoteInstances: mocks.read,
}));

const profile = { id: "3b968d52-081d-4898-9970-ff0a1fc93817", name: "Team server", host: "ubuntu@example.test", port: 22, config_path: "~/.nanobot/config.json", ssh_config: "", identity_file: "", runtime_user: "", connected: false };
const connection: RemoteConnection = { ...profile, hostname: "team-host", gateway_id: "gateway-1", url: "http://127.0.0.1:23456/#/?bootstrapSecret=private-secret" };
const noop = () => {};
function LocalShell({ collapsed = false, initialRemote = false }) {
  const connections = useRemoteConnections();
  const [remotePage, setRemotePage] = useState(initialRemote);
  useEffect(() => {
    const route = () => setRemotePage(window.location.hash === "#/remote");
    window.addEventListener("hashchange", route);
    return () => window.removeEventListener("hashchange", route);
  }, []);
  return <>
  <Sidebar collapsed={collapsed} sessions={[]} activeKey={null} loading={false} newChatActive={false}
    onNewChat={() => { if (connections?.managing) connections.selectLocal(); window.location.hash = "/new"; setRemotePage(false); }} onSelect={noop} onRequestDelete={noop} onTogglePin={noop}
    onRequestRename={noop} onToggleArchive={noop} onToggleGroup={noop}
    onRequestRenameProject={noop} onNewChatInProject={noop} onOpenSettings={noop}
    onOpenApps={noop} onOpenSkills={noop} onOpenAutomations={noop} onOpenChannels={noop}
    onOpenSearch={noop} onToggleArchived={noop} />
  <main><div hidden={connections?.managing} aria-hidden={connections?.managing || undefined}>
    {remotePage ? <RemoteConnectionsPage onBackToChat={() => setRemotePage(false)} /> : <><p>Local conversations</p><textarea aria-label="Local draft" /></>}
  </div>{connections?.managing && <RemoteConnectionsPage onBackToChat={connections.closeManagement} />}</main>
  </>;
}
const view = (collapsed = false, initialRemote = false) => render(<RemoteInstances><LocalShell collapsed={collapsed} initialRemote={initialRemote} /></RemoteInstances>);

beforeEach(async () => {
  await i18n.changeLanguage("en");
  window.sessionStorage.clear(); window.localStorage.clear();
  window.history.replaceState(null, "", "#/new");
  mocks.onStatus.mockReset().mockImplementation((handler) => { handler("open"); return () => {}; });
  mocks.read.mockReset().mockResolvedValue({ available: true, machine_name: "Xubin-Mac", profiles: [profile] });
  mocks.discover.mockReset().mockResolvedValue({ hosts: [], files: [], incomplete: false });
  mocks.inspect.mockReset().mockResolvedValue({ hostname: "team-host", candidates: [{ config_path: "~/.nanobot/config.json", runtime_user: "", service: "" }], incomplete: false });
  mocks.request.mockReset().mockImplementation(async (action: string) => {
    if (action === "remote.connect") return connection;
    if (action === "remote.save") return { id: profile.id };
    if (action === "remote.disconnect") return { available: true, profiles: [profile] };
    return {};
  });
});
afterEach(() => { cleanup(); clearPairReturn(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function readyRemote() {
  const frame = await screen.findByTitle("nanobot on Team server");
  await act(async () => { fireEvent.load(frame); });
  await waitFor(() => expect(readSelectedRemote()?.id).toBe(profile.id));
  return frame;
}
async function chooseHost(name: string) {
  fireEvent.pointerDown(await screen.findByRole("button", { name: i18n.t("remote.switchHost") }), { button: 0, ctrlKey: false });
  fireEvent.click(await screen.findByRole("menuitem", { name }));
}
async function openDirectory() {
  await chooseHost(i18n.t("remote.manageConnections"));
  await screen.findByRole("heading", { name: i18n.t("remote.title") });
}
function chooseExistingSSH() {
  fireEvent.pointerDown(screen.getByRole("button", { name: i18n.t("remote.pair.otherWays") }), { button: 0, ctrlKey: false });
  fireEvent.click(screen.getByRole("menuitem", { name: i18n.t("remote.pair.useSSH") }));
}

describe("remote instance UX", () => {
  it.each([
    ["webui_compatibility_unknown", "unknown"],
    ["host_update_required", "update_host"],
    ["client_update_required", "update_client"],
  ])("a restored host with %s offers version guidance, not a network diagnosis", async (code, status) => {
    rememberSelectedRemote(connection);
    mocks.read.mockResolvedValue({ available: true, client_version: "1.0.0", profiles: [{ ...profile,
      compatibility: { status, client_version: "1.0.0", host_version: "2.0.0" } }] });
    mocks.request.mockRejectedValue(new Error(code));
    view();
    await screen.findByRole("region", { name: i18n.t(`remote.compatibility.${status}`) });
    expect(screen.queryByRole("region", { name: "Server connection lost" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Version & compatibility" }));
    expect(within(await screen.findByRole("dialog")).getByRole("status")).toHaveTextContent(i18n.t(`remote.compatibility.${status}`));
    expect(screen.queryByRole("textbox", { name: "SSH address" })).not.toBeInTheDocument();
    expect(readSelectedRemote()?.id).toBe(profile.id);
  });

  it.each(["compatible", "unknown", "update_host", "update_client"] as const)("explains %s compatibility without updating either machine", async (status) => {
    mocks.read.mockResolvedValue({ available: true, client_version: "1.0.0", profiles: [{ ...profile,
      compatibility: { status, client_version: "1.0.0", host_version: "2.0.0" } }] });
    view(); await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Version & compatibility" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("1.0.0")).toBeVisible();
    expect(within(dialog).getByText("2.0.0")).toBeVisible();
    expect(within(dialog).getByRole("status")).toHaveTextContent(i18n.t(`remote.compatibility.${status}`));
    if (status === "compatible") expect(within(dialog).queryByRole("link")).not.toBeInTheDocument();
    else expect(within(dialog).getByRole("link", { name: "Update guide" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("keeps an unchecked host distinct from an incompatible host", async () => {
    view(); await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Version & compatibility" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("status")).toHaveTextContent("Not checked yet");
    expect(within(dialog).queryByRole("link")).not.toBeInTheDocument();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("opens version guidance after an incompatible connection without opening SSH configuration", async () => {
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, compatibility: {
      status: "update_client", client_version: "1.0.0", host_version: "2.0.0",
    } }] });
    mocks.request.mockRejectedValueOnce(new Error("client_update_required"));
    view(false, true);
    fireEvent.click(await screen.findByRole("button", { name: "Team server ubuntu@example.test" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("status")).toHaveTextContent("Update this computer");
    expect(within(dialog).queryByRole("textbox", { name: "SSH address" })).not.toBeInTheDocument();
    expect(readSelectedRemote()).toBeNull();
    expect(mocks.request).toHaveBeenCalledTimes(1);
  });

  it.each([false, true])("renames an open server without reloading its view (paired: %s)", async (paired) => {
    let saved = { ...profile, paired, connected: true };
    mocks.read.mockImplementation(async () => ({ available: true, profiles: [saved] }));
    mocks.request.mockImplementation(async (action, payload) => {
      if (action === "remote.connect") return connection;
      if (action === "remote.rename") { saved = { ...saved, name: payload.name }; return { available: true, profiles: [saved] }; }
      return {};
    });
    view();
    await chooseHost("Team server ubuntu@example.test");
    const frame = await readyRemote();
    const source = { postMessage: vi.fn() };
    Object.defineProperty(frame, "contentWindow", { value: source });
    act(() => window.dispatchEvent(new MessageEvent("message", { source: source as unknown as Window,
      origin: "http://127.0.0.1:23456", data: { channel: HOST_BRIDGE, type: "hello" } })));
    await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename", exact: true }));
    const input = await screen.findByRole("textbox", { name: "Name", exact: true });
    expect(input).toHaveValue("Team server");
    expect(input).toHaveAccessibleName("Name");
    expect(within(screen.getByRole("dialog")).queryByText("Name", { exact: true })).not.toBeInTheDocument();
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("maxlength", "64");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "  腾讯云 nanobot  " } });
    fireEvent.submit(input.closest("form")!);
    await screen.findByRole("button", { name: "Manage 腾讯云 nanobot" });
    expect(mocks.request).toHaveBeenCalledWith("remote.rename", { id: profile.id, name: "腾讯云 nanobot" }, 65_000);
    expect(screen.getByTitle("nanobot on 腾讯云 nanobot")).toBe(frame);
    expect(frame).toHaveAttribute("src", connection.url);
    expect(readSelectedRemote()).toMatchObject({ id: profile.id, name: "腾讯云 nanobot" });
    expect(document.title).toBe("腾讯云 nanobot");
    expect(source.postMessage).toHaveBeenLastCalledWith(expect.objectContaining({ type: "init", name: "腾讯云 nanobot" }), "http://127.0.0.1:23456");
    expect(mocks.request.mock.calls.map(([action]) => action)).toEqual(["remote.connect", "remote.rename"]);
    fireEvent.click(screen.getByRole("button", { name: "腾讯云 nanobot ubuntu@example.test" }));
    expect(screen.getByTitle("nanobot on 腾讯云 nanobot")).toBe(frame);
    expect(mocks.request).toHaveBeenCalledTimes(2);
  });

  it("explains a paired route once while preserving its credentials boundary", async () => {
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, paired: true }] });
    view(); await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: i18n.t("remote.pair.route") }));
    const dialog = await screen.findByRole("dialog", { name: i18n.t("remote.pair.route") });
    expect(within(dialog).getAllByText(i18n.t("remote.pair.routeHint"))).toHaveLength(1);
    expect(dialog).toHaveAccessibleDescription(i18n.t("remote.pair.routeHint"));
    expect(within(dialog).queryByText(i18n.t("remote.pair.routeDescription"))).not.toBeInTheDocument();
    expect(within(dialog).getByRole("combobox", { name: i18n.t("remote.pair.route") })).toBeEnabled();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("rejects a blank name, preserves input on failure and lets the user retry or cancel", async () => {
    view(); await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename", exact: true }));
    const input = await screen.findByRole("textbox", { name: "Name", exact: true });
    fireEvent.change(input, { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    fireEvent.submit(input.closest("form")!);
    expect(mocks.request).not.toHaveBeenCalled();
    mocks.request.mockRejectedValueOnce(new Error("local_io_error"));
    fireEvent.change(input, { target: { value: "Cloud" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("remote.errors.local_io_error"));
    expect(input).toHaveAccessibleDescription(i18n.t("remote.errors.local_io_error"));
    expect(input).toHaveValue("Cloud");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    expect(screen.getByRole("button", { name: "Manage Team server" })).toBeVisible();
    expect(mocks.request).toHaveBeenCalledTimes(1);
  });

  it("offers one instance-level rename for grouped authorizations", async () => {
    const siblings = [{ ...profile, paired: true, instance_id: profile.id }, { ...profile, id: "other-grant", paired: true, instance_id: profile.id }];
    mocks.read.mockResolvedValue({ available: true, profiles: siblings });
    mocks.request.mockResolvedValue({ available: true, profiles: siblings.map((item) => ({ ...item, name: "Cloud" })) });
    view(); await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename", exact: true }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Name", exact: true }), { target: { value: "Cloud" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("button", { name: "Manage Cloud" });
    expect(screen.getAllByRole("button", { name: "Cloud ubuntu@example.test" })).toHaveLength(1);
  });

  it("shows revocation as a shared copyable code block without executing it or forgetting the connection", async () => {
    const command = "nanobot remote revoke 0dec816f-55e8-47ab-a8ad-13251e2a4f30 --ssh-user ubuntu";
    const copy = vi.spyOn(clipboard, "copyTextToClipboard").mockResolvedValue(true);
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, paired: true, revoke_command: command }] });
    view(); await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Forget server" }));
    const dialog = await screen.findByRole("dialog", { name: "Forget Team server?" });
    const code = within(dialog).getByText(command);
    expect(code.closest("pre")).not.toBeNull();
    expect(code.closest(".not-prose")).toHaveClass("rounded-floating", "bg-secondary/70", "[&_pre]:[overflow-wrap:anywhere]");
    fireEvent.click(within(dialog).getByRole("button", { name: "Copy code" }));
    expect(await within(dialog).findByRole("button", { name: "Copied" })).toBeVisible();
    expect(copy).toHaveBeenCalledWith(command);
    expect(mocks.request).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel", exact: true }));
    expect(mocks.request).not.toHaveBeenCalled();
  });
  it("shows one verified instance in management and the switcher while retaining both grants in details", async () => {
    const second = { ...profile, id: "f1b18099-61d5-41d7-9c1d-6f647f7000e5", paired: true, instance_id: profile.id };
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, paired: true, instance_id: profile.id }, second] });
    view();
    await openDirectory();
    expect(screen.getAllByRole("button", { name: "Team server ubuntu@example.test" })).toHaveLength(1);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Connection details" }));
    const details = await screen.findByRole("dialog", { name: "Connection details" });
    expect(within(details).getByRole("button", { name: /^Connection 1 / })).toBeVisible();
    expect(within(details).getByRole("button", { name: /^Connection 2 / })).toBeVisible();
    fireEvent.pointerDown(within(details).getByRole("button", { name: "Manage connection 1" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Forget connection" }));
    expect(await screen.findByRole("dialog", { name: "Forget this connection?" })).toHaveTextContent(i18n.t("remote.sameInstance.forgetHint"));
    expect(screen.getByRole("button", { name: "Forget", exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: "Forget", exact: true }).firstElementChild).not.toHaveClass("truncate");
    expect(screen.queryByRole("button", { name: "Forget server", exact: true })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    expect(mocks.request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Back", exact: true }));
    fireEvent.pointerDown(screen.getByRole("button", { name: "Switch host" }), { button: 0, ctrlKey: false });
    expect(await screen.findAllByRole("menuitem", { name: "Team server ubuntu@example.test" })).toHaveLength(1);
  });

  it("keeps same-address unverified instances separate and shows their config paths", async () => {
    mocks.read.mockResolvedValue({ available: true, profiles: [profile, { ...profile, id: "another", config_path: "/srv/other/config.json" }] });
    view(); await openDirectory();
    expect(screen.getAllByRole("button", { name: "Team server ubuntu@example.test" })).toHaveLength(2);
    expect(screen.getByTitle("/srv/other/config.json")).toBeVisible();
    expect(screen.getByTitle(profile.config_path)).toBeVisible();
  });

  it("requires disconnecting before opening another authorization of an already-connected instance", async () => {
    const second = { ...profile, id: "second-grant", connected: true, paired: true, instance_id: profile.id };
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, paired: true, instance_id: profile.id }, second] });
    view(); await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "Connection details" }));
    const details = await screen.findByRole("dialog", { name: "Connection details" });
    expect(within(details).getByRole("button", { name: /^Connection 1 / })).toBeDisabled();
    expect(within(details).getByRole("button", { name: /^Connection 2 / })).toBeEnabled();
    expect(within(details).getByText(i18n.t("remote.sameInstance.switchHint"))).toBeVisible();
    expect(within(details).getByRole("button", { name: "Manage connection 1" })).toBeEnabled();
    expect(mocks.request).not.toHaveBeenCalled();
  });
  it("manages connections without changing the remote host, route, frame or authorization", async () => {
    view();
    await chooseHost("Team server ubuntu@example.test");
    const frame = await readyRemote();
    const originalTitle = document.title;
    const originalHash = window.location.hash;
    mocks.request.mockClear();
    await openDirectory();
    const panel = screen.getByRole("region", { name: "Remote connections" });
    expect(screen.getByRole("main")).toContainElement(panel);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(frame).not.toBeVisible();
    const current = within(panel).getByRole("button", { name: "Team server ubuntu@example.test" });
    expect(current).toHaveAttribute("aria-current", "true");
    expect(within(current).getByRole("status")).toHaveTextContent("Connected");
    expect(within(current).getByRole("status").querySelector(".bg-emerald-500")).not.toBeNull();
    expect(within(panel).getByRole("button", { name: "Local nanobot Xubin-Mac" })).not.toHaveAttribute("aria-current");
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(window.location.hash).toBe(originalHash);
    expect(document.title).toBe(originalTitle);
    fireEvent.click(within(panel).getByRole("button", { name: "Back", exact: true }));
    await waitFor(() => expect(panel).not.toBeInTheDocument());
    expect(screen.getByTitle("nanobot on Team server")).toBe(frame);
    expect(frame).toBeVisible();
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(screen.getByRole("button", { name: "Switch host" })).toHaveFocus();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("retains a local draft when returning from the management page", async () => {
    view();
    const draft = screen.getByRole("textbox", { name: "Local draft" });
    draft.focus();
    fireEvent.change(draft, { target: { value: "Keep this unsent draft" } });
    await openDirectory();
    expect(screen.queryByRole("textbox", { name: "Local draft" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back", exact: true }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Remote connections" })).not.toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: "Local draft" })).toBe(draft);
    expect(draft).toHaveValue("Keep this unsent draft");
    expect(draft).toHaveFocus();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("does not cancel an earlier host switch just because management was opened and closed", async () => {
    let finish!: (value: RemoteConnection) => void;
    mocks.request.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    view();
    await chooseHost("Team server ubuntu@example.test");
    await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Back", exact: true }));
    await act(async () => finish(connection));
    const frame = await readyRemote();
    expect(frame).toBeVisible();
    expect(readSelectedRemote()?.id).toBe(profile.id);
  });

  it("only returns local when the user explicitly selects it in management", async () => {
    view();
    await chooseHost("Team server ubuntu@example.test");
    const frame = await readyRemote();
    await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Local nanobot Xubin-Mac" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(readSelectedRemote()).toBeNull();
    expect(screen.getByText("Local conversations")).toBeVisible();
    expect(frame).toBeInTheDocument();
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.disconnect")).toBe(false);
  });

  it("keeps the management page open if an earlier host switch finishes behind it", async () => {
    let finish!: (value: RemoteConnection) => void;
    mocks.request.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    view();
    await chooseHost("Team server ubuntu@example.test");
    await openDirectory();
    await act(async () => finish(connection));
    const frame = await readyRemote();
    expect(frame).not.toBeVisible();
    expect(screen.getByRole("region", { name: "Remote connections" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Back", exact: true }));
    expect(frame).toBeVisible();
    expect(readSelectedRemote()?.id).toBe(profile.id);
  });

  it("does not expose local sidebar actions while managing a remote", async () => {
    view();
    await chooseHost("Team server ubuntu@example.test");
    const frame = await readyRemote();
    await openDirectory();
    expect(screen.queryByRole("button", { name: "New topic" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Remote connections" })).toBeVisible();
    expect(screen.getByText("Local conversations")).not.toBeVisible();
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(frame).toBeInTheDocument();
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.disconnect")).toBe(false);
  });

  it.each([
    { connected: false, connection_error: "disconnected", label: "Disconnected" },
    { connected: true, connection_error: "", label: "Connected" },
    { connected: false, connection_error: "ssh_auth_failed", label: "Connection error" },
  ])("shows $label independently of the current view in both management and the menu", async ({ label, ...health }) => {
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, ...health }] });
    view();
    await openDirectory();
    const row = screen.getByRole("button", { name: "Team server ubuntu@example.test" });
    expect(row).not.toHaveAttribute("aria-current");
    expect(within(row).getByRole("status")).toHaveTextContent(label);
    fireEvent.click(screen.getByRole("button", { name: "Back", exact: true }));
    fireEvent.pointerDown(screen.getByRole("button", { name: "Switch host" }), { button: 0, ctrlKey: false });
    const item = await screen.findByRole("menuitem", { name: "Team server ubuntu@example.test" });
    expect(within(item).getByRole("status")).toHaveTextContent(label);
    expect(item).toHaveAccessibleDescription(label);
  });

  it("leaves management open on a failed switch without moving off the current server", async () => {
    const other = { ...profile, id: "f1b18099-61d5-41d7-9c1d-6f647f7000e5", name: "Other server" };
    mocks.read.mockResolvedValue({ available: true, profiles: [profile, other] });
    view();
    await chooseHost("Team server ubuntu@example.test");
    await readyRemote();
    await openDirectory();
    mocks.request.mockRejectedValue(new Error("ssh_unreachable"));
    fireEvent.click(screen.getByRole("button", { name: "Other server ubuntu@example.test" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("remote.errors.ssh_unreachable"));
    expect(readSelectedRemote()?.id).toBe(profile.id);
    fireEvent.click(within(screen.getByRole("dialog", { name: "Connect to a server" })).getByRole("button", { name: "Cancel" }));
    expect(within(screen.getByRole("button", { name: "Other server ubuntu@example.test" })).getByRole("status")).toHaveTextContent("Connection error");
    expect(screen.getByRole("region", { name: "Remote connections" })).toBeVisible();
  });

  it("lets directory users cancel a cold connection before it takes over", async () => {
    let finish!: (value: RemoteConnection) => void;
    mocks.request.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    view(false, true);
    fireEvent.click(await screen.findByRole("button", { name: "Team server ubuntu@example.test" }));
    expect(await screen.findByText("Connecting to Team server…")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancel switch" }));
    expect(screen.getByRole("button", { name: "Connect to remote nanobot" })).toBeEnabled();
    await act(async () => finish(connection));
    expect(readSelectedRemote()).toBeNull();
    expect(screen.queryByTitle("nanobot on Team server")).toBeNull();
  });
  it("keeps SSH progress in the action and preserves a cancelable form", async () => {
    mocks.inspect.mockImplementation(() => new Promise(() => {}));
    await addAndInspect();
    const action = await screen.findByRole("button", { name: "Signing in and looking for nanobot…" });
    expect(action).toBeDisabled();
    expect(within(screen.getByRole("dialog")).getByRole("status").closest("button")).toBe(action);
    expect(screen.getByRole("textbox", { name: "SSH address" })).toHaveValue(profile.host);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });
  it("keeps editing compact and only suggests SSH hosts after changing the destination", async () => {
    view(false, true);
    fireEvent.pointerDown(await screen.findByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Edit connection" }));
    const address = screen.getByRole("textbox", { name: "SSH address" });
    expect(address).toHaveValue(profile.host);
    expect(mocks.discover).not.toHaveBeenCalled();
    expect(screen.queryByText("From your SSH config")).toBeNull();
    fireEvent.change(address, { target: { value: "ubuntu@other.test" } });
    await waitFor(() => expect(mocks.discover).toHaveBeenCalledOnce());
    expect(mocks.request).not.toHaveBeenCalled();
  });
  it("warns about live views before forgetting but cancellation does not disconnect", async () => {
    mocks.read.mockResolvedValue({ available: true, machine_name: "Xubin-Mac", profiles: [{ ...profile, connected: true }] });
    view(false, true);
    fireEvent.pointerDown(await screen.findByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Forget server" }));
    const dialog = await screen.findByRole("dialog", { name: "Forget Team server?" });
    expect(within(dialog).getByRole("note")).toHaveTextContent("Unsaved work may be lost");
    expect(within(dialog).getByRole("note")).toHaveTextContent("tabs using this connection");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(mocks.request).not.toHaveBeenCalled();
  });
  const pairId = "c6f4f0b0-99d2-4b90-883e-903353a4a0dc";
  const pairCode = `nbpc1.${btoa(JSON.stringify({ id: pairId, data: "encrypted" })).replace(/=+$/, "")}`;
  function prepareReturn() {
    mocks.request.mockImplementation(async (action: string) => action === "remote.pair_preview" ? {
      id: pairId, hostname: "New server", host: "ubuntu@new.example", fingerprint: "SHA256:verified",
      authorized_until: Date.now() / 1000 + 86400, revoke_command: "nanobot remote revoke device",
    } : connection);
    window.history.replaceState(null, "", `http://localhost:3000/#/remote?pairing=${pairCode}`);
    initializePairReturn();
  }
  it("opens a returned link locally instead of restoring another selected server", async () => {
    rememberSelectedRemote(connection);
    prepareReturn();
    view(false, true);
    expect(await screen.findByRole("heading", { name: "Open this nanobot?" })).toBeVisible();
    expect(screen.getByText("New server")).toBeVisible();
    expect(window.location.hash).toBe("#/remote");
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.connect" || action === "remote.pair_finish")).toBe(false);
  });
  it("brings a same-tab return link out of a remote view without closing its tunnel", async () => {
    view(false, true);
    fireEvent.click(await screen.findByRole("button", { name: "Team server ubuntu@example.test" }));
    await readyRemote();
    mocks.request.mockClear();
    await act(async () => { prepareReturn(); });
    expect(await screen.findByRole("heading", { name: "Open this nanobot?" })).toBeVisible();
    expect(readSelectedRemote()).toBeNull();
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.disconnect" || action === "remote.connect" || action === "remote.pair_finish")).toBe(false);
  });

  it("chooses a local SSH config file and discovers its hosts without uploading contents", async () => {
    mocks.request.mockResolvedValue({ path: "/local/team/ssh_config" });
    mocks.discover.mockImplementation(async ({ ssh_config }) => ({ files: [], incomplete: false,
      hosts: ssh_config ? [{ host: "cloud-team", source: ssh_config, ssh_config }] : [],
    }));
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: "ubuntu@203.0.113.1" } });
    fireEvent.click(screen.getByRole("button", { name: "Connection options" }));
    fireEvent.click(screen.getByRole("button", { name: "Choose file: SSH config file (optional)" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "SSH config file (optional)" })).toHaveValue("/local/team/ssh_config"));
    expect(mocks.request).toHaveBeenCalledWith("remote.pick_file", {}, 310_000);
    expect(await screen.findByRole("button", { name: "Use cloud-team" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "SSH address" })).toHaveValue("ubuntu@203.0.113.1");
    fireEvent.click(screen.getByRole("button", { name: "Use cloud-team" }));
    expect(screen.getByRole("textbox", { name: "SSH address" })).toHaveValue("cloud-team");
  });

  it("keeps an existing private key path when file selection is cancelled", async () => {
    mocks.request.mockResolvedValue({ path: null });
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.click(screen.getByRole("button", { name: "Connection options" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Private key path (optional)" }), { target: { value: "/local/ssh-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Choose file: Private key path (optional)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Choose file: Private key path (optional)" })).toBeEnabled());
    expect(screen.getByRole("textbox", { name: "Private key path (optional)" })).toHaveValue("/local/ssh-key");
  });

  it("does not apply a late file choice to a new editor", async () => {
    let finish!: (value: unknown) => void;
    mocks.request.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.click(screen.getByRole("button", { name: "Connection options" }));
    fireEvent.click(screen.getByRole("button", { name: "Choose file: Private key path (optional)" }));
    expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
    expect(screen.getByText("Choose a file in the system dialog…")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.click(screen.getByRole("button", { name: "Connection options" }));
    await act(async () => finish({ path: "/old/choice" }));
    expect(screen.getByRole("textbox", { name: "Private key path (optional)" })).toHaveValue("");
  });

  async function addAndInspect() {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: profile.host } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  }

  it("offers a discovered service account without connecting until confirmed", async () => {
    mocks.inspect.mockResolvedValue({ hostname: "team-host", incomplete: false, candidates: [{
      config_path: "/var/lib/nanobot/.nanobot/config.json", runtime_user: "nanobot", service: "nanobot-team.service",
    }] });
    await addAndInspect();
    expect(await screen.findByText("SSH connected")).toBeVisible();
    expect(screen.getByRole("radio")).toBeChecked();
    expect(screen.getByText(/Runs as nanobot/)).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "SSH address" })).not.toBeInTheDocument();
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.connect")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Open nanobot" }));
    await readyRemote();
    expect(mocks.request).toHaveBeenCalledWith("remote.save", { id: profile.id, profile: expect.objectContaining({
      config_path: "/var/lib/nanobot/.nanobot/config.json", runtime_user: "nanobot",
    }) }, 65_000);
    expect(mocks.inspect).toHaveBeenCalledTimes(1);
  });

  it("switches when the verified app is ready without waiting for every iframe resource", async () => {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    const frame = await screen.findByTitle("nanobot on Team server");
    const source = { postMessage: vi.fn() };
    Object.defineProperty(frame, "contentWindow", { value: source });
    const origin = new URL(connection.url).origin;
    await act(async () => window.dispatchEvent(new MessageEvent("message", {
      data: { channel: HOST_BRIDGE, type: "hello" }, source: source as unknown as Window, origin,
    })));
    const nonce = source.postMessage.mock.calls[0][0].nonce;
    await act(async () => window.dispatchEvent(new MessageEvent("message", {
      data: { channel: HOST_BRIDGE, type: "ready", nonce: "wrong" }, source: source as unknown as Window, origin,
    })));
    expect(readSelectedRemote()).toBeNull();
    await act(async () => window.dispatchEvent(new MessageEvent("message", {
      data: { channel: HOST_BRIDGE, type: "ready", nonce }, source: source as unknown as Window, origin,
    })));
    await waitFor(() => expect(readSelectedRemote()?.id).toBe(profile.id));
  });

  it("gives a cold page time to load and keeps its failed setup retryable", async () => {
    const timer = vi.spyOn(window, "setTimeout");
    await addAndInspect();
    await screen.findByTitle("nanobot on Team server");
    const deadline = timer.mock.calls.find(([, delay]) => delay === 60_000);
    expect(deadline).toBeDefined();
    await act(async () => { (deadline![0] as () => void)(); });
    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("remote.errors.view_load_failed"));
    expect(screen.queryByRole("button", { name: "SSH login settings" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open nanobot" }));
    await readyRemote();
  });

  it("requires an explicit choice between multiple discovered nanobots", async () => {
    mocks.inspect.mockResolvedValue({ hostname: "team-host", incomplete: false, candidates: [
      { config_path: "/srv/one/config.json", runtime_user: "", service: "" },
      { config_path: "/srv/two/config.json", runtime_user: "nanobot", service: "nanobot-two.service" },
    ] });
    await addAndInspect();
    await screen.findByText("SSH connected");
    expect(screen.getByRole("button", { name: "Open nanobot" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: /nanobot-two.service/ }));
    expect(screen.getByRole("button", { name: "Open nanobot" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Open nanobot" }));
    await readyRemote();
    expect(mocks.request).toHaveBeenCalledWith("remote.save", { id: profile.id, profile: expect.objectContaining({ config_path: "/srv/two/config.json" }) }, 65_000);
  });

  it("asks for the server location only after SSH succeeds but discovery finds nothing", async () => {
    mocks.inspect.mockResolvedValue({ hostname: "team-host", candidates: [], incomplete: true });
    await addAndInspect();
    expect(await screen.findByText("No nanobot configuration found")).toBeVisible();
    expect(screen.getByText("SSH connected")).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "Server's nanobot config path" }), { target: { value: "/srv/bot/config.json" } });
    fireEvent.click(screen.getByRole("button", { name: "Open nanobot" }));
    await readyRemote();
    expect(mocks.inspect).toHaveBeenCalledTimes(1);
  });

  it("recovers a handshake failure through SSH settings without blaming nanobot or a missing key", async () => {
    mocks.inspect.mockRejectedValue(new Error("ssh_connection_closed"));
    await addAndInspect();
    expect(await screen.findByRole("alert")).toHaveTextContent("does not confirm a key problem");
    expect(screen.queryByText("SSH connected")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "SSH login settings" }));
    expect(screen.getByRole("textbox", { name: "Private key path (optional)" })).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Server's nanobot config path" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "SSH address" })).toHaveValue(profile.host);
  });

  it("does not resume inspection or auto-connect after cancelling the dialog", async () => {
    let resolve!: (value: unknown) => void;
    mocks.inspect.mockReturnValue(new Promise((done) => { resolve = done; }));
    await addAndInspect();
    await waitFor(() => expect(mocks.inspect).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => resolve({ hostname: "server", candidates: [{ config_path: "/srv/bot/config.json", runtime_user: "", service: "" }], incomplete: false }));
    expect(screen.queryByRole("dialog", { name: "Connect to a server" })).not.toBeInTheDocument();
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.connect")).toBe(false);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.save")).toHaveLength(1);
  });

  it("verifies a first-contact host before resuming discovery instead of connecting blindly", async () => {
    mocks.inspect.mockRejectedValueOnce(new Error("host_key_unknown")).mockResolvedValue({
      hostname: "team-host", candidates: [], incomplete: false,
    });
    mocks.request.mockImplementation(async (action: string) => action === "remote.save" ? { id: profile.id }
      : action === "remote.fingerprint" ? { fingerprint: "SHA256:verified-test", challenge: "nonce" } : {});
    await addAndInspect();
    await screen.findByText("SHA256:verified-test");
    fireEvent.click(screen.getByRole("button", { name: "Connect to verified host" }));
    expect(await screen.findByText("No nanobot configuration found")).toBeVisible();
    expect(mocks.inspect).toHaveBeenCalledTimes(2);
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.connect")).toBe(false);
  });

  it("changing the server requires discovery again and preserves typed SSH settings", async () => {
    mocks.inspect.mockResolvedValue({ hostname: "team-host", candidates: [], incomplete: false });
    await addAndInspect();
    await screen.findByText("SSH connected");
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(screen.getByRole("textbox", { name: "SSH address" })).toHaveValue(profile.host);
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: "ubuntu@second.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("SSH connected");
    expect(mocks.inspect).toHaveBeenCalledTimes(2);
  });

  it("uses only the footer host menu to reach connection management", async () => {
    view();
    await screen.findByRole("button", { name: "Switch host" });
    expect(screen.queryByRole("button", { name: "Remote connections" })).not.toBeInTheDocument();
    expect(screen.queryByText("This machine")).not.toBeInTheDocument();
    await openDirectory();
    expect(screen.getByRole("main")).toContainElement(screen.getByText("Team server"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.querySelector('nav')).toBeVisible();
    expect(window.location.hash).toBe("#/new");
    expect(screen.getByText("Local nanobot")).toBeInTheDocument();
    expect(screen.getByText("Currently using")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect to remote nanobot" })).toBeInTheDocument();
  });

  it("keeps the connection action accessible when the sidebar is collapsed", async () => {
    view(true);
    const switcher = await screen.findByRole("button", { name: "Switch host" });
    expect(screen.queryByRole("button", { name: "Remote connections" })).not.toBeInTheDocument();
    expect(switcher).toHaveClass("w-8", "h-8");
    expect(within(switcher).getByRole("status")).toHaveTextContent("Xubin-Mac");
    await openDirectory();
  });

  it("moves the remote picker into a verified sidebar and can return local through its parent-owned menu", async () => {
    view();
    await screen.findByText("Local");
    await chooseHost("Team server ubuntu@example.test");
    const frame = await screen.findByTitle("nanobot on Team server");
    const source = { postMessage: vi.fn() };
    Object.defineProperty(frame, "contentWindow", { value: source });
    await act(async () => { fireEvent.load(frame); });
    await waitFor(() => expect(readSelectedRemote()?.id).toBe(profile.id));
    expect(screen.getByTestId("legacy-host-footer")).toBeVisible();
    const nonce = source.postMessage.mock.calls[0][0].nonce;
    const message = (data: Record<string, unknown>) => act(() => {
      window.dispatchEvent(new MessageEvent("message", { source: source as unknown as Window,
        origin: "http://127.0.0.1:23456", data: { channel: HOST_BRIDGE, nonce, ...data } }));
    });
    message({ type: "ready" });
    expect(screen.queryByTestId("legacy-host-footer")).not.toBeInTheDocument();
    message({ type: "open", anchor: { left: 40, top: 500, width: 150, height: 32 } });
    expect(await screen.findByRole("menu")).toHaveAttribute("data-side", "top");
    fireEvent.click(screen.getByRole("menuitem", { name: "Local nanobot Xubin-Mac" }));
    await waitFor(() => expect(screen.getByText("Local conversations")).toBeVisible());
    expect(frame).toBeInTheDocument();
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.disconnect")).toBe(false);
  });

  it("keeps the remote sidebar and scopes management layout messages to its verified frame", async () => {
    view();
    await chooseHost("Team server ubuntu@example.test");
    const frame = await readyRemote();
    const source = { postMessage: vi.fn() };
    Object.defineProperty(frame, "contentWindow", { value: source });
    act(() => fireEvent.load(frame));
    const nonce = source.postMessage.mock.calls[0][0].nonce;
    const message = (data: Record<string, unknown>, origin = "http://127.0.0.1:23456") => act(() => {
      window.dispatchEvent(new MessageEvent("message", { source: source as unknown as Window,
        origin, data: { channel: HOST_BRIDGE, nonce, ...data } }));
    });
    message({ type: "ready" });
    document.documentElement.classList.remove("dark");
    message({ type: "surface", theme: "dark", rect: { left: 272, top: 0, width: 900, height: 800 } });
    expect(document.documentElement).not.toHaveClass("dark");
    message({ type: "open", anchor: { left: 40, top: 500, width: 150, height: 32 } });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Manage connections…" }));
    const panel = screen.getByTestId("remote-management-surface");
    expect(panel).toHaveStyle({ left: "272px" });
    expect(document.documentElement).toHaveClass("dark");
    expect(frame).toBeVisible();
    expect(screen.getByText("Local conversations")).not.toBeVisible();
    expect(source.postMessage).toHaveBeenLastCalledWith(expect.objectContaining({ managing: true }), "http://127.0.0.1:23456");
    message({ type: "surface", rect: { left: 500, top: 0, width: 900, height: 800 } }, "https://untrusted.example");
    message({ type: "surface", nonce: "wrong", rect: { left: 500, top: 0, width: 900, height: 800 } });
    message({ type: "surface", rect: { left: -20, top: 0, width: 900, height: 800 } });
    expect(panel).toHaveStyle({ left: "272px" });
    message({ type: "surface", theme: "dark", rect: { left: 64, top: 0, width: 1100, height: 800 } });
    expect(panel).toHaveStyle({ left: "64px" });
    message({ type: "leave-management", nonce: "wrong" });
    expect(panel).toBeInTheDocument();
    message({ type: "leave-management" });
    expect(panel).not.toBeInTheDocument();
    expect(document.documentElement).not.toHaveClass("dark");
    expect(frame).toBeVisible();
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(mocks.request.mock.calls.map(([action]) => action)).toEqual(["remote.connect"]);
  });

  it("uses clear Chinese navigation and returns from the connection form without saving", async () => {
    await i18n.changeLanguage("zh-CN");
    view();
    await openDirectory();
    expect(screen.getByText("本地 nanobot")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "连接远程 nanobot" }));
    chooseExistingSSH();
    expect(screen.getByRole("heading", { name: "添加连接" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "添加连接" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.getByRole("heading", { name: "远程连接" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "SSH 地址" })).not.toBeInTheDocument();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("opens a saved server without asking for keys or configuration again", async () => {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    const frame = await readyRemote();
    expect(frame).toHaveAttribute("src", connection.url);
    expect(frame).toHaveAttribute("sandbox", expect.not.stringContaining("allow-top-navigation"));
    expect(document.querySelector('[data-host-view="local"]')).toHaveAttribute("inert");
    expect(within(screen.getByRole("button", { name: "Switch host" })).getByRole("status")).toHaveTextContent("Team server, team-host");
    expect(mocks.request).toHaveBeenCalledWith("remote.connect", { id: profile.id }, 65_000);
    expect(window.sessionStorage.getItem("nanobot.remote-instance")).not.toContain("secret");
    expect(readRecentRemotes()).toEqual([profile.id]);
    const storedValues = Array.from({ length: window.localStorage.length }, (_, index) =>
      window.localStorage.getItem(window.localStorage.key(index) || ""));
    expect(JSON.stringify(storedValues)).not.toContain("private-secret");
    expect(JSON.stringify(storedValues)).not.toContain(connection.url);
  });

  it("returning local keeps the saved server view and SSH warm", async () => {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    await readyRemote();
    await chooseHost("Local nanobot Xubin-Mac");
    expect(screen.getByText("Local conversations")).toBeVisible();
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.disconnect")).toBe(false);
    expect(readSelectedRemote()).toBeNull();
    expect(readRecentRemotes()).toEqual([profile.id]);
    expect(mocks.request.mock.calls.some(([action]) => String(action).includes("stop"))).toBe(false);
  });

  it("keeps local drafts, view identity and keyboard focus across warm round trips", async () => {
    view();
    const draft = screen.getByRole("textbox", { name: "Local draft" });
    draft.focus();
    fireEvent.change(draft, { target: { value: "Unsent local draft" } });
    await screen.findByText("Local");
    await chooseHost("Team server ubuntu@example.test");
    const frame = await readyRemote();
    expect(draft).not.toBeVisible();
    const shortcut = vi.fn();
    window.addEventListener("keydown", shortcut);
    fireEvent.keyDown(screen.getByRole("button", { name: "Switch host" }), { key: "b", metaKey: true });
    expect(shortcut).not.toHaveBeenCalled();
    window.removeEventListener("keydown", shortcut);
    await chooseHost("Local nanobot Xubin-Mac");
    await waitFor(() => expect(draft).toHaveFocus());
    expect(screen.getByRole("textbox", { name: "Local draft" })).toBe(draft);
    expect(draft).toHaveValue("Unsent local draft");
    await chooseHost("Team server ubuntu@example.test");
    expect(screen.getByTitle("nanobot on Team server")).toBe(frame);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.connect")).toHaveLength(1);
  });

  it("can close an offline cached view, but confirms before discarding its state", async () => {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    await readyRemote();
    await chooseHost("Local nanobot Xubin-Mac");
    await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Disconnect" }));
    const dialog = await screen.findByRole("dialog", { name: "Disconnect from Team server?" });
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.disconnect")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(screen.queryByTitle("nanobot on Team server")).not.toBeInTheDocument());
    expect(mocks.request).toHaveBeenCalledWith("remote.disconnect", { id: profile.id }, 65_000);
  });

  it("keeps the current view when forgetting fails and closes it only after a successful retry", async () => {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    const frame = await readyRemote();
    await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Forget server" }));
    const dialog = await screen.findByRole("dialog", { name: "Forget Team server?" });
    mocks.request.mockImplementation(async (action: string) => {
      if (action === "remote.remove") throw new Error("local_io_error");
      return {};
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Forget server" }));
    await within(dialog).findByRole("alert");
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(frame).toBeInTheDocument();
    expect(mocks.request.mock.calls.map(([action]) => action)).toEqual(["remote.connect", "remote.remove"]);

    mocks.request.mockResolvedValue({ available: true, profiles: [] });
    mocks.read.mockRejectedValue(new Error("directory_unavailable"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Forget server" }));
    await waitFor(() => expect(frame).not.toBeInTheDocument());
    expect(readSelectedRemote()).toBeNull();
    expect(screen.queryByRole("button", { name: "Manage Team server" })).not.toBeInTheDocument();
    expect(mocks.request.mock.calls.map(([action]) => action)).toEqual(["remote.connect", "remote.remove", "remote.remove"]);
  });

  it("refresh restores the selected remote, keeping the local shell hidden", async () => {
    rememberSelectedRemote(connection);
    view();
    expect(screen.queryByText("Local conversations")).not.toBeVisible();
    await readyRemote();
    expect(mocks.request).toHaveBeenCalledWith("remote.connect", { id: profile.id }, 65_000);
  });

  it("failed restore stays remote and offers reconnect and an explicit return", async () => {
    rememberSelectedRemote(connection);
    mocks.request.mockRejectedValue(new Error("ssh_unreachable"));
    view();
    await screen.findByRole("region", { name: "Server connection lost" });
    expect(screen.queryByText("Local conversations")).not.toBeVisible();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to local nanobot" }));
    await screen.findByText("Local conversations");
  });

  it("waits for the local socket before restoring and restores only once", async () => {
    let status: ((value: string) => void) | undefined;
    const unsubscribe = vi.fn();
    mocks.onStatus.mockImplementation((handler) => { status = handler; handler("connecting"); return unsubscribe; });
    rememberSelectedRemote(connection);
    const rendered = view();
    expect(mocks.request).not.toHaveBeenCalled();
    expect(screen.queryByText("Local conversations")).not.toBeVisible();
    await act(async () => { status?.("open"); });
    await readyRemote();
    await act(async () => { status?.("reconnecting"); status?.("open"); });
    expect(mocks.request).toHaveBeenCalledTimes(1);
    rendered.unmount();
    expect(unsubscribe).toHaveBeenCalled();
  });

  it("clears errors from an earlier connection when opening a server from the page", async () => {
    rememberSelectedRemote(connection);
    mocks.request.mockRejectedValue(new Error("ssh_unreachable"));
    view();
    await screen.findByRole("region", { name: "Server connection lost" });
    fireEvent.click(screen.getByRole("button", { name: "Back to local nanobot" }));
    await screen.findByText("Local conversations");
    mocks.request.mockResolvedValue(connection);
    await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    await readyRemote();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("saves once and preserves entered fields when SSH authentication fails", async () => {
    mocks.inspect.mockRejectedValue(new Error("ssh_auth_failed"));
    mocks.request.mockImplementation(async (action: string) => {
      if (action === "remote.save") return { id: profile.id };
      throw new Error("ssh_auth_failed");
    });
    view(); await openDirectory(); fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: "ubuntu@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("textbox", { name: "SSH address" })).toHaveValue("ubuntu@example.test");
    expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.save")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(mocks.request.mock.calls.filter(([action]) => action === "remote.save")).toHaveLength(2));
    expect(mocks.inspect).toHaveBeenCalledWith({ id: profile.id });
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.connect")).toBe(false);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.save")[1][1]).toMatchObject({ id: profile.id });
  });

  it("edits in the same dialog but only saves, without connecting or switching", async () => {
    view(); await openDirectory();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Manage Team server" }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Edit connection" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit connection" });
    expect(within(dialog).getByRole("textbox", { name: "SSH address" })).toHaveValue(profile.host);
    fireEvent.click(within(dialog).getByRole("button", { name: "Connection options" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Name (optional)" }), { target: { value: "Renamed server" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit connection" })).not.toBeInTheDocument());
    expect(mocks.request).toHaveBeenCalledTimes(1);
    expect(mocks.request).toHaveBeenCalledWith("remote.save", {
      id: profile.id, profile: expect.objectContaining({ host: profile.host, name: "Renamed server" }),
    }, 65_000);
    expect(readSelectedRemote()).toBeNull();
    expect(screen.getByRole("heading", { name: "Remote connections" })).toBeVisible();
  });

  it.each(["en", "zh-CN"])("keeps server login separate from nanobot location (%s)", async (language) => {
    await i18n.changeLanguage(language);
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("remote.add") }));
    chooseExistingSSH();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("remote.connectionOptions") }));
    const port = screen.getByRole("spinbutton", { name: i18n.t("remote.sshPort") });
    const key = screen.getByRole("textbox", { name: i18n.t("remote.identity_file") });
    expect(screen.queryByRole("textbox", { name: i18n.t("remote.runtime_user") })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: i18n.t("remote.config_path") })).not.toBeInTheDocument();
    expect(port).toHaveClass("h-10");
    expect(key).toHaveClass("h-10");
  });

  it("imports a pasted SSH command into the existing connection options", async () => {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    const address = screen.getByRole("textbox", { name: "SSH address" });
    fireEvent.change(address, { target: { value: 'ssh -p2222 -i "~/.ssh/team key" -l ubuntu example.test' } });
    fireEvent.blur(address);
    expect(address).toHaveValue("ubuntu@example.test");
    expect(screen.getByRole("status")).toHaveTextContent(i18n.t("remote.commandImported"));
    expect(mocks.request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Connection options" }));
    expect(screen.getByRole("spinbutton", { name: "SSH port" })).toHaveValue(2222);
    expect(screen.getByRole("textbox", { name: "Private key path (optional)" })).toHaveValue("~/.ssh/team key");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await readyRemote();
    expect(mocks.request).toHaveBeenCalledWith("remote.save", {
      id: "", profile: expect.objectContaining({ host: "ubuntu@example.test", name: "ubuntu@example.test", port: 2222, identity_file: "~/.ssh/team key" }),
    }, 65_000);
  });

  it("parses Enter submission without requiring a blur and preserves fields after failure", async () => {
    mocks.request.mockImplementation(async (action: string) => {
      if (action === "remote.save") return { id: profile.id };
      throw new Error("ssh_agent_refused");
    });
    view(); await openDirectory(); fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    const address = screen.getByRole("textbox", { name: "SSH address" });
    fireEvent.change(address, { target: { value: "ssh -p 2222 ubuntu@example.test" } });
    fireEvent.submit(address.closest("form")!);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("remote.errors.ssh_agent_refused"));
    // Errors stay outside the form's field scroller. The outer dialog frame
    // may itself scroll when a mobile keyboard leaves less room than the form.
    expect(address.closest("form")!.querySelector(".overflow-y-auto")).not.toContainElement(alert);
    expect(address).toHaveValue("ubuntu@example.test");
    fireEvent.click(screen.getByRole("button", { name: "Connection options" }));
    expect(screen.getByRole("spinbutton", { name: "SSH port" })).toHaveValue(2222);
    expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
  });

  it("doesn't save or execute a command with unsupported flags", async () => {
    view(); await openDirectory(); fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    const address = screen.getByRole("textbox", { name: "SSH address" });
    fireEvent.change(address, { target: { value: "ssh -o ProxyCommand=unsafe team" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("remote.errors.invalid_ssh_command"));
    expect(address).toHaveValue("ssh -o ProxyCommand=unsafe team");
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("closes successful setup and restores the original local view on return", async () => {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: profile.host } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await readyRemote();
    await chooseHost("Local nanobot Xubin-Mac");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Local conversations")).toBeVisible();
  });

  it("cancels a dialog's pending connection without a late jump or error", async () => {
    let finish: ((result: RemoteConnection) => void) | undefined;
    mocks.request.mockImplementation(async (action: string) => action === "remote.save" ? { id: profile.id }
      : new Promise<RemoteConnection>((resolve) => { finish = resolve; }));
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: profile.host } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(finish).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => { finish?.(connection); });
    expect(screen.queryByRole("dialog", { name: "Connect to a server" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("nanobot on Team server")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(readSelectedRemote()).toBeNull();
  });

  it("keeps verification in one dialog and Back preserves setup without trusting", async () => {
    mocks.request.mockImplementation(async (action: string) => {
      if (action === "remote.save") return { id: profile.id };
      if (action === "remote.connect") throw new Error("host_key_unknown");
      if (action === "remote.fingerprint") return { fingerprint: "SHA256:example", challenge: "one-use" };
      return {};
    });
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: profile.host } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("SHA256:example");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("textbox", { name: "SSH address" })).toHaveValue(profile.host);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.trust")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  });

  it("does not reopen verification after cancelling a pending fingerprint read", async () => {
    let finish: ((value: { fingerprint: string; challenge: string }) => void) | undefined;
    mocks.request.mockImplementation(async (action: string) => {
      if (action === "remote.save") return { id: profile.id };
      if (action === "remote.connect") throw new Error("host_key_unknown");
      return new Promise<{ fingerprint: string; challenge: string }>((resolve) => { finish = resolve; });
    });
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: profile.host } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(finish).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => { finish?.({ fingerprint: "SHA256:example", challenge: "one-use" }); });
    expect(screen.queryByRole("dialog", { name: "Connect to a server" })).not.toBeInTheDocument();
    expect(screen.queryByText("SHA256:example")).not.toBeInTheDocument();
  });

  it("doesn't create privileged controls on an unsupported remote gateway", async () => {
    mocks.read.mockResolvedValue({ available: false, profiles: [] });
    view(); await waitFor(() => expect(mocks.read).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Remote connections" })).not.toBeInTheDocument();
  });

  it("does not discover SSH hosts or expose nested connections inside a remote frame", async () => {
    vi.stubGlobal("top", {});
    view(false, true);
    await screen.findByText(i18n.t("remote.unavailable"));
    expect(mocks.read).not.toHaveBeenCalled();
    expect(mocks.discover).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Remote connections" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect to remote nanobot" })).not.toBeInTheDocument();
  });

  it("keeps the directory quiet and offers one focused add-server dialog", async () => {
    mocks.read.mockResolvedValue({ available: true, profiles: [] });
    view(); await openDirectory();
    expect(mocks.discover).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    const host = screen.getByRole("textbox", { name: "SSH address" });
    const dialog = screen.getByRole("dialog", { name: "Connect to a server" });
    expect(dialog).toContainElement(host);
    expect(host).toHaveFocus();
    expect(within(dialog).getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Connect to remote nanobot", hidden: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Connect to a server" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Connect to remote nanobot" })).toHaveFocus();
    expect(screen.getByRole("heading", { name: "Remote connections" })).toBeVisible();
  });

  it("does not navigate to a remote instance after leaving a pending connection", async () => {
    let finish: ((result: RemoteConnection) => void) | undefined;
    mocks.request.mockImplementation(() => new Promise<RemoteConnection>((resolve) => { finish = resolve; }));
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    fireEvent.click(screen.getByRole("button", { name: "Back", exact: true }));
    await act(async () => { finish?.(connection); });
    expect(screen.getByText("Local conversations")).toBeVisible();
    expect(screen.queryByTitle("nanobot on Team server")).not.toBeInTheDocument();
    expect(readSelectedRemote()).toBeNull();
  });

  it("does not start SSH if the user leaves while a profile is saving", async () => {
    let finish: ((result: { id: string }) => void) | undefined;
    mocks.read.mockResolvedValue({ available: true, profiles: [] });
    mocks.request.mockImplementation(() => new Promise<{ id: string }>((resolve) => { finish = resolve; }));
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: "ubuntu@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Back", exact: true }));
    await act(async () => { finish?.({ id: profile.id }); });
    expect(mocks.request).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Local conversations")).toBeVisible();
  });

  it("keeps cached servers visible during refresh and lets users retry failed reads", async () => {
    view();
    await screen.findByRole("button", { name: "Switch host" });
    mocks.read.mockRejectedValue(new Error("directory_unavailable"));
    await openDirectory();
    await screen.findByRole("alert");
    expect(screen.getByText("Team server")).toBeVisible();
    mocks.read.mockResolvedValue({ available: true, profiles: [profile] });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByText("Team server")).toBeVisible();
  });

  it("explains unavailable direct routes without displaying SSH controls", async () => {
    mocks.read.mockResolvedValue({ available: false, profiles: [] });
    view(false, true);
    await screen.findByText("Open this page from a locally running nanobot to connect to servers over SSH.");
    expect(screen.queryByRole("textbox", { name: "SSH address" })).not.toBeInTheDocument();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("identifies the host in the existing sidebar footer without a top bar", async () => {
    view();
    const identity = await screen.findByRole("button", { name: "Switch host" });
    expect(identity).toHaveTextContent("Local");
    expect(within(identity).getByRole("status")).toHaveTextContent("Xubin-Mac");
    expect(screen.getByRole("navigation", { name: "Sidebar navigation" })).toContainElement(identity);
    expect(document.querySelector("header")).toBeNull();
    fireEvent.pointerDown(identity, { button: 0, ctrlKey: false });
    expect(await screen.findByRole("menuitem", { name: "Local nanobot Xubin-Mac" })).toBeVisible();
    expect(screen.getByRole("menuitem", { name: "Manage connections…" })).toBeVisible();
  });

  it("discovers and filters SSH aliases without connecting, then inherits the selected config", async () => {
    mocks.discover.mockResolvedValue({ hosts: [
      { host: "team-sg", source: "/home/test/.ssh/config", ssh_config: "" },
      { host: "staging", source: "/home/test/.ssh/hosts", ssh_config: "" },
    ], files: ["/home/test/.ssh/config"], incomplete: false });
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    await screen.findByRole("button", { name: "Use team-sg" });
    expect(mocks.request).not.toHaveBeenCalled();
    const address = screen.getByRole("textbox", { name: "SSH address" });
    fireEvent.keyDown(address, { key: "ArrowDown" });
    expect(screen.getByRole("button", { name: "Use team-sg" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(screen.getByRole("button", { name: "Use staging" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(address).toHaveFocus();
    fireEvent.change(screen.getByRole("textbox", { name: "SSH address" }), { target: { value: "team" } });
    expect(screen.queryByRole("button", { name: "Use staging" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use team-sg" }));
    expect(screen.getByRole("textbox", { name: "SSH address" })).toHaveValue("team-sg");
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await readyRemote();
    expect(mocks.request).toHaveBeenCalledWith("remote.save", expect.objectContaining({ profile: expect.objectContaining({ host: "team-sg", ssh_config: "", port: null }) }), 65_000);
  });

  it("reads a custom SSH config and carries that path to the selected profile", async () => {
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    fireEvent.click(screen.getByRole("button", { name: "Connection options" }));
    mocks.discover.mockResolvedValue({ hosts: [{ host: "team", source: "/team/ssh_config", ssh_config: "/team/ssh_config" }], files: ["/team/ssh_config"], incomplete: false });
    fireEvent.change(screen.getByRole("textbox", { name: "SSH config file (optional)" }), { target: { value: "/team/ssh_config" } });
    fireEvent.click(await screen.findByRole("button", { name: "Use team" }));
    expect(screen.getByRole("textbox", { name: "SSH config file (optional)" })).toHaveValue("/team/ssh_config");
    expect(screen.getByRole("spinbutton", { name: "SSH port" })).toHaveValue(null);
    expect(mocks.discover).toHaveBeenCalledWith({ ssh_config: "/team/ssh_config" });
    expect(screen.queryByRole("button", { name: "Read hosts" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await readyRemote();
    expect(mocks.request).toHaveBeenCalledWith("remote.save", expect.objectContaining({ profile: expect.objectContaining({ host: "team", ssh_config: "/team/ssh_config" }) }), 65_000);
  });

  it("keeps manual entry available for an invalid discovery response", async () => {
    mocks.discover.mockResolvedValue({ hosts: [{}], files: [], incomplete: false });
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    await screen.findByRole("alert");
    expect(screen.getByRole("textbox", { name: "SSH address" })).toBeVisible();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("ignores late SSH suggestions after changing the config file", async () => {
    let finishOld: ((value: unknown) => void) | undefined;
    mocks.discover.mockImplementation(({ ssh_config }: { ssh_config: string }) => ssh_config
      ? Promise.resolve({ hosts: [{ host: "custom-team", source: ssh_config, ssh_config }], files: [ssh_config], incomplete: false })
      : new Promise((resolve) => { finishOld = resolve; }));
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    await waitFor(() => expect(finishOld).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "Connection options" }));
    fireEvent.change(screen.getByRole("textbox", { name: "SSH config file (optional)" }), { target: { value: "/team/config" } });
    await screen.findByRole("button", { name: "Use custom-team" });
    await act(async () => { finishOld?.({ hosts: [{ host: "stale-host", source: "/default", ssh_config: "" }], files: ["/default"], incomplete: false }); });
    expect(screen.queryByRole("button", { name: "Use stale-host" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use custom-team" })).toBeVisible();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("keeps manual setup available when discovery fails and does not clear cached hosts", async () => {
    mocks.discover.mockResolvedValue({ hosts: [{ host: "team", source: "/config", ssh_config: "/config" }], files: ["/config"], incomplete: false });
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    chooseExistingSSH();
    await screen.findByRole("button", { name: "Use team" });
    mocks.discover.mockRejectedValue(new Error("ssh_config_unreadable"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh SSH hosts" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Use team" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "SSH address" })).toBeVisible();
  });

  it("requires an explicit fingerprint confirmation and never trusts a changed host", async () => {
    mocks.request.mockImplementation(async (action: string) => {
      if (action === "remote.connect") throw new Error("host_key_unknown");
      if (action === "remote.fingerprint") return { fingerprint: "SHA256:example", challenge: "one-use" };
      return {};
    });
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    await screen.findByText("SHA256:example");
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.trust")).toBe(false);
    mocks.request.mockImplementation(async (action: string) => action === "remote.connect" ? connection : {});
    fireEvent.click(screen.getByRole("button", { name: "Connect to verified host" }));
    await readyRemote();
    expect(mocks.request).toHaveBeenCalledWith("remote.trust", { id: profile.id, challenge: "one-use" }, 65_000);
  });

  it("tolerates transient health failures and covers, rather than reloads, the remote frame", async () => {
    let tick: (() => void) | undefined;
    vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => { if (delay === 5_000) tick = callback as () => void; return 1; });
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    const frame = await readyRemote();
    fireEvent.load(frame);
    await act(async () => { tick?.(); });
    expect(screen.queryByRole("region", { name: "Server connection lost" })).not.toBeInTheDocument();
    await act(async () => { tick?.(); });
    await screen.findByRole("region", { name: "Server connection lost" });
    expect(screen.getByTitle("nanobot on Team server")).toBeInTheDocument();
    expect(frame.parentElement).toHaveAttribute("inert");
    expect(document.querySelector('[data-host-view="local"]')).toHaveAttribute("inert");
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Server connection lost" })).not.toBeInTheDocument());
    expect(screen.queryByText("Opening your server…")).not.toBeInTheDocument();
    expect(screen.getByTitle("nanobot on Team server")).toBe(frame);
    expect(frame.parentElement).not.toHaveAttribute("inert");
  });

  it("rechecks on wake and network recovery without reloading or switching hosts", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    const rendered = view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    const frame = await readyRemote();
    mocks.read.mockClear();
    await act(async () => { window.dispatchEvent(new Event("online")); });
    expect(mocks.read).toHaveBeenCalledTimes(1);
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(mocks.read).toHaveBeenCalledTimes(2);
    await screen.findByRole("region", { name: "Server connection lost" });
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, connected: true }] });
    await act(async () => { window.dispatchEvent(new Event("pageshow")); });
    expect(mocks.read).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("region", { name: "Server connection lost" })).not.toBeInTheDocument();
    expect(screen.getByTitle("nanobot on Team server")).toBe(frame);
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.connect")).toHaveLength(1);
    rendered.unmount();
    mocks.read.mockClear();
    window.dispatchEvent(new Event("online"));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(mocks.read).not.toHaveBeenCalled();
  });

  it("coalesces wake signals while a health check is in flight", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    await readyRemote();
    let finish: ((result: unknown) => void) | undefined;
    mocks.read.mockClear().mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    await act(async () => {
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("pageshow"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(mocks.read).toHaveBeenCalledTimes(1);
    await act(async () => { finish?.({ available: true, profiles: [{ ...profile, connected: true }] }); });
    expect(readSelectedRemote()?.id).toBe(profile.id);
  });

  it.each(["pair_authorization_rejected", "remote_auth_failed", "host_key_changed", "incompatible_gateway"])("offers setup rather than endless reconnect for %s", async (code) => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    view(); await openDirectory();
    fireEvent.click(screen.getByRole("button", { name: "Team server ubuntu@example.test" }));
    await readyRemote();
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, connected: false, connection_error: code }] });
    await act(async () => { window.dispatchEvent(new Event("online")); });
    await act(async () => { window.dispatchEvent(new Event("pageshow")); });
    expect(screen.getByText(i18n.t(`remote.errors.${code}`))).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reconnect" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Manage connections…" }));
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(screen.getByRole("region", { name: "Remote connections" })).toBeVisible();
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.disconnect")).toHaveLength(0);
  });

  it("dismissing a restore error does not leave an endless opening screen", async () => {
    rememberSelectedRemote(connection);
    mocks.request.mockRejectedValue(new Error("ssh_unreachable"));
    view();
    await screen.findByRole("region", { name: "Server connection lost" });
    fireEvent.pointerDown(screen.getByRole("button", { name: "Switch host" }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("button", { name: "Close" }));
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.getByRole("region", { name: "Server connection lost" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeVisible();
    expect(screen.queryByText("Opening your server…")).not.toBeInTheDocument();
  });

  it.each([[-1, true], [3, true], [30, false]])("shows only relevant device expiry hints at %i days", async (days, visible) => {
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, paired: true,
      authorized_until: Math.floor(Date.now() / 1000) + days * 86400 }] });
    view(false, true);
    await screen.findByRole("button", { name: /Team server ubuntu@example.test/ });
    expect(!!screen.queryByText(days < 0 ? /Authorization expired/ : /Authorization expires/)).toBe(visible);
  });
});

it.each(["https://evil.example/", "http://user@127.0.0.1:23456/", "javascript:alert(1)", "http://127.0.0.1:23456/wrong"])("rejects unsafe navigation %s", (url) => {
  expect(() => validateRemoteConnection({ ...connection, url })).toThrow();
});
