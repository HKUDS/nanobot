import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LinearResetConnection } from "../../../nanobot/channels/linear/webui/LinearResetConnection";
import type { ChannelConfigField } from "@/components/settings/channels/catalog";

const { requestMutation } = vi.hoisted(() => ({ requestMutation: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ client: { requestMutation }, token: "preview-only" }),
}));

const fields: ChannelConfigField[] = [
  { key: "channels.linear.clientId", label: "Client ID" },
  { key: "channels.linear.publicBaseUrl", label: "URL" },
  { key: "channels.linear.clientSecret", label: "Secret", secret: true },
  { key: "channels.linear.webhookSigningSecret", label: "Webhook secret", secret: true },
  { key: "channels.linear.port", label: "Port", defaultValue: "3979" },
];
const orgs = [
  { organization_id: "one", organization_name: "One" },
  { organization_id: "two", organization_name: "Two" },
];
let remaining = [...orgs];
let failWorkspace: string | null = null;
let failStop = false;
let failSave = false;

beforeEach(() => {
  remaining = [...orgs];
  failWorkspace = null;
  failStop = false;
  failSave = false;
  requestMutation.mockReset().mockImplementation(async (method, params) => {
    if (params.operation === "inspect") return { installations: [...remaining] };
    if (params.operation === "disconnect") {
      if (params.organization_id === failWorkspace) throw new Error("Linear unavailable");
      remaining = remaining.filter(item => item.organization_id !== params.organization_id);
      return { installations: [...remaining] };
    }
    if (method === "settings.feature.disable") return {
      features: [{ name: "linear", enabled: false, runtime_status: failStop ? "running" : "stopped" }],
      enabled_count: 0,
    };
    if (method === "settings.channel.configure") {
      if (failSave) throw new Error("Save failed");
      return { saved: true };
    }
    throw new Error(`Unexpected mutation: ${method}`);
  });
});
afterEach(cleanup);

async function openReset() {
  const onWorkspaceRemoved = vi.fn();
  const onWorkspacesChange = vi.fn();
  render(<LinearResetConnection fields={fields} disabled={false} onBusyChange={vi.fn()}
    onFeaturesUpdate={vi.fn()} onWorkspaceRemoved={onWorkspaceRemoved}
    onWorkspacesChange={onWorkspacesChange} />);
  fireEvent.click(screen.getByRole("button", { name: "Reset Linear connection" }));
  const dialog = await screen.findByRole("alertdialog");
  return { dialog, onWorkspaceRemoved, onWorkspacesChange,
    confirm: () => fireEvent.click(within(dialog).getByRole("button", { name: "Reset", exact: true })) };
}

describe("reset Linear connection", () => {
  it("does nothing before confirmation, and cancellation preserves everything", async () => {
    const { dialog } = await openReset();
    expect(requestMutation).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent("Linear app, issues, comments, chat history and pairing approvals.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("separates what is cleared from what is kept and focuses the safe action", async () => {
    const { dialog } = await openReset();
    expect(dialog).toHaveAccessibleName("Reset Linear?");
    expect(dialog).toHaveAccessibleDescription(/Disconnect all workspaces linked through this app and stop the channel/);
    expect(within(dialog).getByText("Clears").tagName).toBe("DT");
    expect(within(dialog).getByText("Keeps").tagName).toBe("DT");
    expect(within(dialog).getByText("Member access settings and this instance’s app configuration, including saved credentials.").tagName).toBe("DD");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(within(dialog).getByRole("button", { name: "Reset", exact: true })).toBeEnabled();
  });

  it("inspects fresh installations, revokes each, stops the channel, then clears settings", async () => {
    const { confirm, onWorkspaceRemoved } = await openReset();
    confirm();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(onWorkspaceRemoved.mock.calls).toEqual([["one"], ["two"]]);
    expect(requestMutation.mock.calls.map(([method, params]) => params.operation ?? method)).toEqual([
      "inspect", "disconnect", "disconnect", "inspect", "settings.feature.disable", "settings.channel.configure",
    ]);
    expect(requestMutation).toHaveBeenLastCalledWith("settings.channel.configure", {
      name: "linear", values: {
        "channels.linear.clientId": "", "channels.linear.publicBaseUrl": "",
        "channels.linear.clientSecret": null, "channels.linear.webhookSigningSecret": null,
        "channels.linear.port": "3979",
      },
    }, 150_000);
  });

  it("preserves credentials and the remaining workspace on partial failure, then resumes", async () => {
    failWorkspace = "two";
    const { confirm, dialog, onWorkspacesChange } = await openReset();
    confirm();
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Reset is incomplete");
    expect(remaining).toEqual([orgs[1]]);
    expect(onWorkspacesChange).toHaveBeenLastCalledWith([orgs[1]]);
    expect(requestMutation.mock.calls.some(([method]) => method === "settings.channel.configure")).toBe(false);
    failWorkspace = null;
    confirm();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(requestMutation.mock.calls.filter(([, params]) => params.operation === "disconnect" && params.organization_id === "one")).toHaveLength(1);
  });

  it("does not interpret a missing installation list as an empty one", async () => {
    requestMutation.mockResolvedValueOnce({});
    const { confirm, dialog } = await openReset();
    confirm();
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Could not verify");
    expect(requestMutation).toHaveBeenCalledTimes(1);
  });

  it("does not clear settings while the channel is still running", async () => {
    failStop = true;
    const { confirm, dialog } = await openReset();
    confirm();
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("could not be stopped");
    expect(requestMutation.mock.calls.some(([method]) => method === "settings.channel.configure")).toBe(false);
  });

  it("keeps settings when a new workspace appears during reset", async () => {
    requestMutation.mockImplementationOnce(async () => {
      remaining = [orgs[1]];
      return { installations: [] };
    });
    const { confirm, dialog } = await openReset();
    confirm();
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Another workspace was connected");
    expect(requestMutation.mock.calls.some(([method]) => method === "settings.channel.configure")).toBe(false);
    expect(remaining).toEqual([orgs[1]]);
  });

  it("can retry a failed config save without revoking removed workspaces again", async () => {
    failSave = true;
    const { confirm, dialog } = await openReset();
    confirm();
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Save failed");
    failSave = false;
    confirm();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(requestMutation.mock.calls.filter(([, params]) => params.operation === "disconnect")).toHaveLength(2);
  });

  it("prevents repeat submissions or dismissal while resetting", async () => {
    let finish!: (value: unknown) => void;
    requestMutation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { confirm, dialog } = await openReset();
    confirm();
    expect(within(dialog).getByRole("button", { name: "Resetting…" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(dialog).toBeVisible();
    finish({});
    await within(dialog).findByRole("alert");
  });
});
