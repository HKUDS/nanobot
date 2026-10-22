import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AboutSettings } from "@/components/settings/overview/OverviewSettings";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider } from "@/providers/ClientProvider";
import { useVersionCheck } from "@/providers/VersionCheckProvider";
import { jsonResponse, settingsPayload } from "@/tests/settings-test-utils";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const state = (channel = "stable", revision = 0, status = "current") => ({
  updateAvailable: null, can_change_channel: true,
  releaseStatus: { channel, revision, currentVersion: "0.3.7.dev42", state: status },
});

function Controls() {
  const channel = useVersionCheck();
  return <>
    <button onClick={() => void channel.changeChannel("preview")}>Subscribe preview</button>
    <button onClick={() => void channel.changeChannel("stable")}>Subscribe stable</button>
    <input aria-label="Draft" />
  </>;
}
function view(client: NanobotClient, token = "channel-a", native = false) {
  return <ClientProvider client={client} token={token} allowUpdateFlow={!native}
    webuiCapabilities={["webui.update-channels.v1"]}>
    <AboutSettings settings={settingsPayload()} /><Controls />
  </ClientProvider>;
}

describe("Installation-owned release channels", () => {
  it("shows saving progress, then quietly selects a channel without installation or restart consent", async () => {
    const client = new NanobotClient({ url: "ws://localhost:8765" });
    let resolve!: (value: unknown) => void;
    const mutation = vi.spyOn(client, "requestMutation").mockImplementation(() => new Promise(done => { resolve = done; }));
    const fetcher = vi.fn().mockResolvedValueOnce(jsonResponse(state()))
      .mockResolvedValueOnce(jsonResponse(state("preview", 1, "unavailable")));
    vi.stubGlobal("fetch", fetcher);
    render(view(client));
    const selector = await screen.findByRole("switch", { name: "Receive preview updates" });
    expect(selector).toBeVisible();
    expect(selector).toHaveAccessibleDescription("Try new features early.");
    expect(selector).toHaveAttribute("aria-checked", "false");
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Keep writing" } });
    fireEvent.click(selector);
    expect(selector).toBeDisabled();
    expect(screen.getByText("Saving…")).toBeVisible();
    fireEvent.click(screen.getByText("Subscribe stable"));
    expect(mutation).toHaveBeenCalledOnce();
    expect(mutation).toHaveBeenCalledWith("settings.nanobot.update.channel", { channel: "preview", revision: 0 }, expect.any(Number));
    await act(async () => resolve({ channel: "preview", revision: 1 }));
    await waitFor(() => expect(selector).toBeEnabled());
    expect(selector).toHaveAttribute("aria-checked", "true");
    expect(selector).toBeVisible();
    expect(screen.queryByText("Saving…")).toBeNull();
    expect(screen.queryByText("Update preference saved")).toBeNull();
    expect(screen.getByText("Could not check this update channel.")).toBeVisible();
    expect(screen.queryByText("You're up to date")).toBeNull();
    expect(screen.getByLabelText("Draft")).toHaveValue("Keep writing");
    expect(fetcher).toHaveBeenCalledWith("/api/settings/version-check?channel_status=1", expect.any(Object));
    expect(mutation).toHaveBeenCalledOnce();
  });

  it("reloads a quietly saved channel and uses its latest revision for the next save", async () => {
    const client = new NanobotClient({ url: "ws://localhost:8765" });
    let selection = { channel: "stable", revision: 0 };
    const mutation = vi.spyOn(client, "requestMutation").mockImplementation(async (_action, payload) => {
      selection = { channel: String(payload?.channel), revision: selection.revision + 1 };
      return selection;
    });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(state(selection.channel, selection.revision))));
    const first = render(view(client));
    fireEvent.click(await screen.findByRole("switch", { name: "Receive preview updates" }));
    await waitFor(() => expect(screen.getByRole("switch")).toBeEnabled());
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    first.unmount();

    render(view(client));
    const selector = await screen.findByRole("switch", { name: "Receive preview updates" });
    expect(selector).toHaveAttribute("aria-checked", "true");
    fireEvent.click(selector);
    await waitFor(() => expect(selector).toBeEnabled());
    expect(selector).toHaveAttribute("aria-checked", "false");
    expect(mutation).toHaveBeenNthCalledWith(1, "settings.nanobot.update.channel", { channel: "preview", revision: 0 }, expect.any(Number));
    expect(mutation).toHaveBeenNthCalledWith(2, "settings.nanobot.update.channel", { channel: "stable", revision: 1 }, expect.any(Number));
    expect(screen.queryByText("Update preference saved")).toBeNull();
  });

  it("shares the post-save check when About is reentered during a channel mutation and retries its failure", async () => {
    const client = new NanobotClient({ url: "ws://localhost:8765" });
    let resolveSave!: (value: unknown) => void;
    const mutation = vi.spyOn(client, "requestMutation").mockImplementation(() => new Promise(done => { resolveSave = done; }));
    const fetcher = vi.fn().mockResolvedValueOnce(jsonResponse(state()))
      .mockRejectedValueOnce(new Error("Channel check unavailable"))
      .mockResolvedValueOnce(jsonResponse(state("preview", 1)));
    vi.stubGlobal("fetch", fetcher);
    const surface = (about: boolean) => <ClientProvider client={client} token="save-reentry"
      webuiCapabilities={["webui.update-channels.v1"]}>
      {about && <AboutSettings settings={settingsPayload()} />}
    </ClientProvider>;
    const mounted = render(surface(true));
    fireEvent.click(await screen.findByRole("switch", { name: "Receive preview updates" }));
    mounted.rerender(surface(false));
    mounted.rerender(surface(true));
    expect(screen.getByText("Saving…")).toBeVisible();
    expect(fetcher).toHaveBeenCalledOnce();
    await act(async () => resolveSave({ channel: "preview", revision: 1 }));
    expect(await screen.findByText("Channel check unavailable")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("switch")).toBeEnabled());
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("You're up to date")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(mutation).toHaveBeenCalledOnce();
    expect(mutation).toHaveBeenCalledWith("settings.nanobot.update.channel", { channel: "preview", revision: 0 }, expect.any(Number));
  });

  it("resynchronizes a stale tab or lost response and waits for stable without downgrading", async () => {
    const client = new NanobotClient({ url: "ws://localhost:8765" });
    const mutation = vi.spyOn(client, "requestMutation").mockRejectedValue(new Error("Channel changed elsewhere; check again"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(state("preview", 1)))
      .mockResolvedValueOnce(jsonResponse(state("stable", 2, "waiting_stable"))));
    render(view(client));
    fireEvent.click(await screen.findByRole("switch", { name: "Receive preview updates" }));
    await waitFor(() => expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false"));
    expect(screen.getByText(/Channel changed elsewhere/)).toBeVisible();
    expect(screen.getByText(/newer stable release/)).toBeVisible();
    expect(screen.queryByText("You're up to date")).toBeNull();
    expect(mutation).toHaveBeenCalledOnce();
  });

  it("does not let a late old-host mutation change the new host or discard its draft", async () => {
    const client = new NanobotClient({ url: "ws://localhost:8765" });
    let resolve!: (value: unknown) => void;
    vi.spyOn(client, "requestMutation").mockImplementation(() => new Promise(done => { resolve = done; }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(state()))
      .mockResolvedValueOnce(jsonResponse(state("stable", 4)))
      .mockResolvedValueOnce(jsonResponse(state("preview", 1))));
    const { rerender } = render(view(client));
    fireEvent.click(await screen.findByRole("switch", { name: "Receive preview updates" }));
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Survives" } });
    rerender(view(client, "channel-b"));
    await screen.findByRole("switch", { name: "Receive preview updates" });
    await waitFor(() => expect(screen.getByRole("switch")).toBeEnabled());
    await act(async () => resolve({ channel: "preview", revision: 1 }));
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByLabelText("Draft")).toHaveValue("Survives");
  });

  it("does not turn a missing channel result into a green success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ updateAvailable: null })));
    render(view(new NanobotClient({ url: "ws://localhost:8765" })));
    expect(await screen.findByText(/did not return its update channel/)).toBeVisible();
    expect(screen.queryByText("You're up to date")).toBeNull();
  });

  it("shows a read-only channel for remote callers and leaves native updates to the distributor", async () => {
    const client = new NanobotClient({ url: "ws://localhost:8765" });
    const mutation = vi.spyOn(client, "requestMutation");
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...state(), can_change_channel: false })));
    const { rerender } = render(view(client));
    const selector = await screen.findByRole("switch", { name: "Receive preview updates" });
    expect(selector).toBeDisabled();
    expect(selector).toHaveAccessibleDescription(/Open this gateway on localhost or allow remote package installation/);
    fireEvent.click(screen.getByText("Subscribe preview"));
    expect(mutation).not.toHaveBeenCalled();
    rerender(view(client, "native", true));
    await waitFor(() => expect(screen.queryByRole("switch")).toBeNull());
    expect(mutation).not.toHaveBeenCalled();
  });
});
