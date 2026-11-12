import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Window as HappyWindow } from "happy-dom";
import type { InboundEvent, Outbound } from "@/lib/types";

(window as unknown as HappyWindow).happyDOM.settings.disableIframePageLoading = true;

vi.mock("@/lib/bootstrap", async (original) => ({
  ...await original<typeof import("@/lib/bootstrap")>(),
  fetchBootstrap: vi.fn(async () => ({ token: "test", api_token: "test", ws_path: "/" })),
  deriveWsUrl: () => "ws://test",
}));
// Keep this suite focused on App's remote boundary rather than the chat implementation.
vi.mock("@/components/thread/ThreadShell", () => ({
  ThreadShell: () => <textarea aria-label="Local draft" />,
}));

const profile = {
  id: "3b968d52-081d-4898-9970-ff0a1fc93817", name: "Team server", host: "ubuntu@example.test",
  port: 22, config_path: "~/.nanobot/config.json", ssh_config: "", identity_file: "", runtime_user: "", connected: false,
};
const connection = {
  ...profile, hostname: "team-host", gateway_id: "gateway-1",
  url: "http://127.0.0.1:23456/#/?bootstrapSecret=test-only",
};

class TestSocket {
  static current: TestSocket;
  readyState = 0;
  sent: Outbound[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor() { TestSocket.current = this; }
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.readyState = 3; this.onclose?.(); }
  receive(event: InboundEvent) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event) }));
  }
  send(data: string) {
    const frame = JSON.parse(data) as Outbound;
    this.sent.push(frame);
    if (frame.type !== "webui_request") return;
    const result = frame.action === "remote.connect" ? connection
      : frame.action === "remote.pair_start" ? { id: "test-pair", command: "nanobot remote pair nbpr1.test", expires: Date.now() / 1000 + 600 }
      : frame.action === "remote.discover" ? { hosts: [], files: [], incomplete: false } : {};
    queueMicrotask(() => this.receive({
      event: "webui_response", request_id: frame.request_id, ok: true, result,
    }));
  }
}

let releaseManagement: (() => void) | undefined;
let managementImport: Promise<typeof import("@/components/remote/RemoteConnectionsPage")> | undefined;

async function finishManagementImport() {
  await act(async () => { releaseManagement?.(); await managementImport; });
}

async function loadApp(deferManagement = false, importError?: Error) {
  const loaded = vi.fn();
  const gate = new Promise<void>((resolve) => { releaseManagement = resolve; });
  vi.doMock("@/components/remote/RemoteConnectionsPage", (original) => {
    loaded();
    if (importError) return Promise.reject(importError);
    managementImport = (async () => {
      if (deferManagement) await gate;
      return original<typeof import("@/components/remote/RemoteConnectionsPage")>();
    })();
    return managementImport;
  });
  const { initializeI18n, loadAllLocaleResources } = await import("@/i18n");
  await initializeI18n();
  await loadAllLocaleResources();
  const { default: App } = await import("@/App");
  return { App, loaded };
}

async function readyShell() {
  await screen.findByRole("button", { name: "Switch host" });
  await act(async () => { TestSocket.current.open(); });
}

async function manageConnections() {
  fireEvent.pointerDown(screen.getByRole("button", { name: "Switch host" }), { button: 0, ctrlKey: false });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Manage connections" }));
}

function managementSkeleton() {
  const status = screen.getByText("Loading nanobot…", { selector: "[role=status]" });
  const skeleton = status.closest("section");
  expect(skeleton).toBeVisible();
  expect(skeleton).toHaveAttribute("aria-busy", "true");
  expect(skeleton).toHaveAttribute("data-startup-surface", "remote");
  expect(skeleton).toHaveAttribute("data-embedded", "true");
  return skeleton;
}

beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/#/new");
  vi.stubGlobal("WebSocket", TestSocket);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/remote-instances") return Response.json({ available: true, machine_name: "Local machine", profiles: [profile] });
    if (path === "/api/sessions") return Response.json({ sessions: [] });
    if (path === "/api/webui/sidebar-state") return Response.json({});
    return new Response(null, { status: 404 });
  }));
});

afterEach(async () => {
  cleanup();
  await finishManagementImport();
  releaseManagement = undefined;
  managementImport = undefined;
  if (TestSocket.current) {
    TestSocket.current.onclose = null;
    TestSocket.current.close();
  }
  vi.doUnmock("@/components/remote/RemoteConnectionsPage");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("lazy remote management", () => {
  it("keeps chat and the host picker ready before loading management from the local menu", async () => {
    const { App, loaded } = await loadApp();
    expect(loaded).not.toHaveBeenCalled();
    render(<App />);
    await readyShell();
    const draft = await screen.findByRole("textbox", { name: "Local draft" });
    fireEvent.change(draft, { target: { value: "Keep my local draft" } });
    fireEvent.pointerDown(screen.getByRole("button", { name: "Switch host" }), { button: 0, ctrlKey: false });
    const host = await screen.findByRole("menuitem", { name: "Team server ubuntu@example.test" });
    expect(within(host).getByRole("status")).toHaveTextContent("Disconnected");
    expect(loaded).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("menuitem", { name: "Manage connections" }));
    await screen.findByRole("heading", { name: "Remote connections" });
    expect(loaded).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("textbox", { name: "Local draft" })).toBe(draft);
    expect(draft).toHaveValue("Keep my local draft");
    await manageConnections();
    await screen.findByRole("heading", { name: "Remote connections" });
    expect(loaded).toHaveBeenCalledTimes(1);
    expect(TestSocket.current.sent.filter((frame) => frame.type === "webui_request" && frame.action.startsWith("remote."))).toEqual([]);
  });

  it("keeps the shell and local draft when the management import rejects, and can go back", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { App, loaded } = await loadApp(false, new Error("Failed to fetch dynamically imported module"));
    render(<App />);
    await readyShell();
    const draft = await screen.findByRole("textbox", { name: "Local draft" });
    fireEvent.change(draft, { target: { value: "Keep my draft after a chunk failure" } });
    const hostPicker = screen.getByRole("button", { name: "Switch host" });
    await manageConnections();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load this view. Go back, or reload the page to try again.");
    expect(screen.getByRole("button", { name: "Switch host" })).toBe(hostPicker);
    expect(hostPicker).toBeVisible();
    expect(draft).toBeInTheDocument();
    expect(draft).toHaveValue("Keep my draft after a chunk failure");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Local draft" })).toBe(draft);
    expect(draft).toBeVisible();
    expect(draft).toHaveValue("Keep my draft after a chunk failure");
    expect(loaded).toHaveBeenCalledTimes(1);
    expect(TestSocket.current.sent.filter((frame) => frame.type === "webui_request" && frame.action.startsWith("remote."))).toEqual([]);
  });

  it("shows the existing skeleton on a cold remote route, then opens pairing and SSH controls", async () => {
    window.history.replaceState(null, "", "/#/remote");
    const { App, loaded } = await loadApp(true);
    render(<App />);
    await readyShell();
    await waitFor(() => expect(loaded).toHaveBeenCalledTimes(1));
    managementSkeleton();
    await finishManagementImport();
    await screen.findByRole("heading", { name: "Remote connections" });
    fireEvent.click(screen.getByRole("button", { name: "Connect to remote nanobot" }));
    await screen.findByText("nanobot remote pair nbpr1.test");
    fireEvent.pointerDown(screen.getByRole("button", { name: "Other ways" }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", { name: "SSH connection" }));
    expect(await screen.findByRole("textbox", { name: "SSH address" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(await screen.findByRole("button", { name: "Back to chat" }));
    expect(await screen.findByRole("textbox", { name: "Local draft" })).toBeVisible();
    expect(loaded).toHaveBeenCalledTimes(1);
  });

  it("can leave local management while its chunk is pending without reopening it on completion", async () => {
    const { App, loaded } = await loadApp(true);
    render(<App />);
    await readyShell();
    const draft = await screen.findByRole("textbox", { name: "Local draft" });
    fireEvent.change(draft, { target: { value: "Unsent local draft" } });
    await manageConnections();
    await waitFor(() => expect(loaded).toHaveBeenCalledTimes(1));
    managementSkeleton();
    fireEvent.click(screen.getByRole("button", { name: "New topic" }));
    expect(screen.getByRole("textbox", { name: "Local draft" })).toBe(draft);
    expect(draft).toHaveValue("Unsent local draft");
    await finishManagementImport();
    expect(screen.queryByRole("region", { name: "Remote connections" })).not.toBeInTheDocument();
    expect(screen.queryByText("Loading nanobot…")).not.toBeInTheDocument();
    expect(TestSocket.current.sent.filter((frame) => frame.type === "webui_request" && frame.action.startsWith("remote."))).toEqual([]);
  });

  it("restores the host before loading management and preserves its frame, selection and route", async () => {
    const { rememberSelectedRemote, readSelectedRemote } = await import("@/lib/remote-instances");
    rememberSelectedRemote(connection);
    const { App, loaded } = await loadApp(true);
    render(<App />);
    await readyShell();
    const frame = await screen.findByTitle("nanobot on Team server");
    await act(async () => { fireEvent.load(frame); });
    await waitFor(() => expect(readSelectedRemote()?.id).toBe(profile.id));
    expect(loaded).not.toHaveBeenCalled();
    const hash = window.location.hash;
    const title = document.title;
    const requests = TestSocket.current.sent.filter((frame) => frame.type === "webui_request");
    await manageConnections();
    await waitFor(() => expect(loaded).toHaveBeenCalledTimes(1));
    managementSkeleton();
    expect(screen.getByTestId("remote-management-surface")).toBeVisible();
    expect(screen.getByTitle("nanobot on Team server")).toBe(frame);
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(window.location.hash).toBe(hash);
    expect(document.title).toBe(title);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(frame).toBeVisible();
    expect(readSelectedRemote()?.id).toBe(profile.id);
    await manageConnections();
    managementSkeleton();
    await finishManagementImport();
    const page = await screen.findByRole("region", { name: "Remote connections" });
    const host = within(page).getByRole("button", { name: "Team server ubuntu@example.test" });
    expect(host).toHaveAttribute("aria-current", "true");
    expect(within(host).getByRole("status")).toHaveTextContent("Connected");
    fireEvent.click(within(page).getByRole("button", { name: "Back" }));
    expect(screen.getByTitle("nanobot on Team server")).toBe(frame);
    expect(frame).toBeVisible();
    expect(frame).toHaveAttribute("src", connection.url);
    expect(readSelectedRemote()?.id).toBe(profile.id);
    expect(window.location.hash).toBe(hash);
    expect(document.title).toBe(title);
    expect(TestSocket.current.sent.filter((frame) => frame.type === "webui_request")).toEqual(requests);
  });
});
