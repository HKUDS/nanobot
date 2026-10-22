import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/Sidebar";
import { AboutSettings } from "@/components/settings/overview/OverviewSettings";
import { UpdateNotice } from "@/components/UpdateNotice";
import { ClientProvider } from "@/providers/ClientProvider";
import { useVersionCheck } from "@/providers/VersionCheckProvider";
import { NanobotClient } from "@/lib/nanobot-client";
import { jsonResponse, settingsPayload } from "@/tests/settings-test-utils";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });
const client = new NanobotClient({ url: "ws://localhost:8765" });
const available = (version = "0.3.6") => ({ updateAvailable: { currentVersion: "0.3.5", latestVersion: version } });

it.each([
  ["uv", "Update via uv"], ["pipx", "Update via pipx"], ["pip", "Update via pip"],
  ["source", "Update via source checkout"], ["container", "Update via container deployment"],
  ["managed", "Update"], ["future-owner", "Update"],
])("labels the update entry with the detected owner (%s)", async (method, label) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ...available(), installation_method: method })));
  const request = vi.fn();
  render(<ClientProvider token="test" client={client}><AboutSettings settings={settingsPayload()} onRequestUpdate={request} /></ClientProvider>);
  const entry = await screen.findByRole("button", { name: label });
  fireEvent.click(entry);
  expect(request).toHaveBeenCalledOnce();
});

function Surface() {
  const update = useVersionCheck();
  const [about, setAbout] = useState(false);
  return <>
    <input aria-label="Draft" />
    {update.result?.type === "update" && update.dismissedVersion !== update.result.latestVersion && (
      <UpdateNotice version={update.result.latestVersion} onOpen={() => setAbout(true)} onDismiss={update.dismiss} />
    )}
    <button onClick={() => void update.check()}>Refresh version</button>
    {about && <AboutSettings settings={{ ...settingsPayload(), version: { current: "0.3.5" } }} />}
  </>;
}

const view = (token = "host-a") => <ClientProvider client={client} token={token}><Surface /></ClientProvider>;

describe("Sidebar update entry", () => {
  it("keeps About update actions available after dismissing the sidebar notice", async () => {
    const fetcher = vi.fn(async () => jsonResponse(available()));
    vi.stubGlobal("fetch", fetcher);
    const { rerender } = render(view("dismiss-sidebar"));
    fireEvent.click(screen.getByText("Refresh version"));
    fireEvent.click(await screen.findByRole("button", { name: "Update available v0.3.6" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss update notice" }));
    rerender(<ClientProvider client={client} token="dismiss-sidebar">
      <Surface />
      <AboutSettings settings={settingsPayload()} onRequestUpdate={vi.fn()} />
    </ClientProvider>);
    expect(await screen.findByRole("button", { name: /^Update$/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Update available v0.3.6" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss update notice" })).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("automatically checks each About entry, shares an in-flight check and retries failures without a loading delay", async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn().mockImplementation(() => new Promise<Response>(done => { resolve = done; }));
    vi.stubGlobal("fetch", fetcher);
    const surface = (about: boolean) => <ClientProvider client={client} token="about-entry">
      {about && <AboutSettings settings={settingsPayload()} />}
    </ClientProvider>;
    const mounted = render(surface(false));
    expect(fetcher).not.toHaveBeenCalled();
    mounted.rerender(surface(true));
    expect(screen.getByRole("status")).toHaveTextContent("Checking...");
    expect(fetcher).toHaveBeenCalledOnce();
    mounted.rerender(surface(false));
    mounted.rerender(surface(true));
    expect(fetcher).toHaveBeenCalledOnce();
    await act(async () => resolve(jsonResponse({ updateAvailable: null })));
    expect(screen.getByText("You're up to date")).toBeVisible();

    mounted.rerender(surface(false));
    mounted.rerender(surface(true));
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toHaveTextContent("Checking...");
    await act(async () => resolve(jsonResponse({ updateAvailable: null })));
    fetcher.mockRejectedValueOnce(new Error("Connection unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("Connection unavailable")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(screen.getByRole("status")).toHaveTextContent("Checking...");
    expect(fetcher).toHaveBeenCalledTimes(4);
    await act(async () => resolve(jsonResponse(available())));
    expect(screen.getByRole("link", { name: "Installation guide" })).toBeVisible();
  });
  it("opens the provided update confirmation directly without navigating through details", () => {
    const openDetails = vi.fn();
    const requestUpdate = vi.fn();
    render(<UpdateNotice version="0.3.6" onOpen={openDetails} onDismiss={vi.fn()} onRequestUpdate={requestUpdate} />);
    expect(requestUpdate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Update available v0.3.6" }));
    expect(requestUpdate).toHaveBeenCalledOnce();
    expect(openDetails).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "View details" })).toBeNull();
  });

  it("uses the same direct confirmation in About when an update action is available", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(available())));
    const requestUpdate = vi.fn();
    render(<ClientProvider client={client} token="about-update">
      <AboutSettings settings={{ ...settingsPayload(), version: { current: "0.3.5" } }} onRequestUpdate={requestUpdate} />
    </ClientProvider>);
    const button = await screen.findByRole("button", { name: /^Update$/ });
    expect(screen.queryByRole("link", { name: "Installation guide" })).toBeNull();
    expect(requestUpdate).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(requestUpdate).toHaveBeenCalledOnce();
  });

  it("opens in place, preserves the draft, and navigates only from View details", async () => {
    const fetcher = vi.fn(async () => jsonResponse(available()));
    vi.stubGlobal("fetch", fetcher);
    render(view());
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Keep writing" } });
    fireEvent.click(screen.getByText("Refresh version"));
    fireEvent.click(await screen.findByRole("button", { name: "Update available v0.3.6" }));
    expect(screen.getByRole("dialog", { name: "Update available v0.3.6" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Installation guide" })).toBeNull();
    expect(screen.getByLabelText("Draft")).toHaveValue("Keep writing");
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Update available v0.3.6" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Update available v0.3.6" }));
    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    expect(await screen.findByRole("link", { name: "Installation guide" })).toHaveAttribute("href", "https://github.com/HKUDS/nanobot#-install");
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenCalledWith("/api/settings/version-check", expect.any(Object));
  });

  it("deduplicates checks, dismisses one version, and shows a later version", async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }))
      .mockResolvedValueOnce(jsonResponse(available())).mockResolvedValueOnce(jsonResponse(available("0.3.7")));
    vi.stubGlobal("fetch", fetcher);
    render(view());
    fireEvent.click(screen.getByText("Refresh version"));
    fireEvent.click(screen.getByText("Refresh version"));
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => resolve(jsonResponse(available())));
    fireEvent.click(screen.getByRole("button", { name: "Update available v0.3.6" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss update notice" }));
    expect(screen.queryByRole("button", { name: "Update available v0.3.6" })).toBeNull();
    fireEvent.click(screen.getByText("Refresh version"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "Update available v0.3.6" })).toBeNull();
    fireEvent.click(screen.getByText("Refresh version"));
    expect(await screen.findByRole("button", { name: "Update available v0.3.7" })).toBeVisible();
  });

  it("ignores late host results without remounting the client or losing its draft", async () => {
    let resolveOld!: (response: Response) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((done) => { resolveOld = done; }))
      .mockResolvedValueOnce(jsonResponse({ updateAvailable: null }));
    vi.stubGlobal("fetch", fetcher);
    const { rerender } = render(view());
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByText("Refresh version"));
    rerender(view("host-b"));
    expect(fetcher).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Refresh version"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    await act(async () => resolveOld(jsonResponse(available())));
    expect(screen.queryByRole("button", { name: /Update available/ })).toBeNull();
    expect(screen.getByLabelText("Draft")).toHaveValue("Keep this draft");
  });

  it.each([null, new Error("offline")])("keeps an unavailable check quiet (%s)", async (failure) => {
    const fetcher = vi.fn().mockImplementation(() => failure ? Promise.reject(failure) : Promise.resolve(jsonResponse({ updateAvailable: null })));
    vi.stubGlobal("fetch", fetcher);
    render(view());
    fireEvent.click(screen.getByText("Refresh version"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: /Update available/ })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders the same entry in expanded and collapsed navigation", () => {
    const noop = vi.fn();
    const props = { sessions: [], activeKey: null, loading: false, newChatActive: false,
      onNewChat: noop, onSelect: noop, onRequestDelete: noop, onTogglePin: noop, onRequestRename: noop,
      onToggleArchive: noop, onToggleGroup: noop, onRequestRenameProject: noop, onNewChatInProject: noop,
      onOpenSettings: noop, onOpenApps: noop, onOpenSkills: noop, onOpenAutomations: noop, onOpenChannels: noop,
      onOpenSearch: noop, onToggleArchived: noop, onOpenUpdates: noop,
      availableUpdate: { version: "0.3.6", onDismiss: noop } };
    const { rerender } = render(<ClientProvider client={client} token="test"><Sidebar {...props} /></ClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Update available v0.3.6" }));
    expect(noop).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    expect(noop).toHaveBeenCalledOnce();
    rerender(<ClientProvider client={client} token="test"><Sidebar {...props} collapsed /></ClientProvider>);
    expect(screen.getByRole("button", { name: "Update available v0.3.6" })).toBeVisible();
    expect(screen.queryByText("Update available")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Update available v0.3.6" }));
    expect(screen.getByRole("dialog", { name: "Update available v0.3.6" })).toBeVisible();
  });
});
