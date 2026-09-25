import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LinearMemberAccess } from "../../../nanobot/channels/linear/webui/LinearMemberAccess";
import type { LinearMembersPayload } from "../../../nanobot/channels/linear/webui/types";

const { requestMutation, context } = vi.hoisted(() => {
  const requestMutation = vi.fn();
  return { requestMutation, context: { client: { requestMutation }, token: "admin-session" } };
});
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => context }));

const roster: LinearMembersPayload = {
  session_id: "", status: "members", organization_id: "org-1", legacy_allow_all: false,
  members: [
    { id: "u1", name: "Xubin", teams: ["nanobot"], allowed: true },
    { id: "u2", name: "Yongru", teams: ["nanobot"], allowed: false },
  ],
};

beforeEach(() => {
  requestMutation.mockReset().mockResolvedValue(roster);
  context.client = { requestMutation };
  context.token = "admin-session";
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const header = () => screen.getByRole("button", { name: /^Member access/ });
const xubin = () => screen.getByRole("switch", { name: "Allow Xubin to use nanobot" });
const yongru = () => screen.getByRole("switch", { name: "Allow Yongru to use nanobot" });
const refresh = () => fireEvent.click(screen.getByRole("button", { name: "Refresh members" }));

function deferNextRequest() {
  let resolve!: (value: LinearMembersPayload) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<LinearMembersPayload>((done, fail) => {
    resolve = done; reject = fail;
  });
  requestMutation.mockReturnValueOnce(promise);
  return { resolve, reject };
}

async function openMembers() {
  const view = render(<LinearMemberAccess organizationId="org-1" />);
  expect(requestMutation).not.toHaveBeenCalled();
  fireEvent.click(header());
  await screen.findByRole("switch", { name: "Allow Yongru to use nanobot" });
  return view;
}

describe("Linear member access", () => {
  it("renders Linear avatars without referrers and falls back when an image fails", async () => {
    const avatar = "https://public.linear.app/u2/avatar";
    requestMutation.mockResolvedValue({ ...roster, members: roster.members.map(member => ({
      ...member, avatar_url: member.id === "u2" ? avatar : null,
    })) });
    const view = await openMembers();
    const image = view.container.querySelector("img");
    expect(image).toHaveAttribute("src", avatar);
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("width", "32");
    fireEvent.error(image!);
    expect(view.container.querySelector("img")).toBeNull();
    expect(screen.getByText("YO")).toBeVisible();
    expect(yongru()).toBeEnabled();
    requestMutation.mockResolvedValueOnce({ ...roster, members: roster.members.map(member => ({
      ...member, avatar_url: member.id === "u2" ? "https://uploads.linear.app/u2/new-avatar" : null,
    })) });
    refresh();
    await waitFor(() => expect(view.container.querySelector("img"))
      .toHaveAttribute("src", "https://uploads.linear.app/u2/new-avatar"));
  });

  it.each([
    "javascript:alert(1)", "http://public.linear.app/u2/avatar", "https://127.0.0.1/avatar",
    "https://public.linear.app.evil.example/avatar", "https://public.linear.app@evil.example/avatar",
    "https://public.linear.app:8443/avatar", "https://user:secret@public.linear.app/avatar",
    "data:image/svg+xml,<svg/>",
  ])("uses initials for an untrusted avatar URL: %s", async (avatar_url) => {
    requestMutation.mockResolvedValue({ ...roster, members: roster.members.map(member => ({ ...member, avatar_url })) });
    const view = await openMembers();
    expect(view.container.querySelector("img")).toBeNull();
    expect(xubin()).toBeEnabled();
  });

  it("shows permissions, a summary and short guidance; details are available on demand", async () => {
    await openMembers();
    expect(yongru()).not.toBeChecked();
    expect(xubin()).toBeChecked();
    expect(header()).not.toHaveTextContent("1 enabled");
    fireEvent.click(header());
    expect(header()).toHaveTextContent("1 enabled");
    fireEvent.click(header());
    expect(requestMutation).toHaveBeenCalledWith("settings.channel.connect.start", {
      channel: "linear", operation: "members", organization_id: "org-1",
    }, 150_000);
    expect(screen.queryByText(/No pairing codes needed/)).not.toBeInTheDocument();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "About member access" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("does not grant access");
    fireEvent.change(screen.getByRole("textbox", { name: "Search members" }), { target: { value: "yong" } });
    expect(screen.queryByRole("switch", { name: "Allow Xubin to use nanobot" })).not.toBeInTheDocument();
    expect(yongru()).toBeVisible();
  });

  it.each(["hover", "focus"])("prefetches on %s, deduplicates the click, and never sends a permission write", async (intent) => {
    const request = deferNextRequest();
    render(<LinearMemberAccess organizationId="org-1" />);
    if (intent === "hover") fireEvent.mouseEnter(header());
    else fireEvent.focus(header());
    expect(requestMutation).toHaveBeenCalledTimes(1);
    fireEvent.click(header());
    expect(requestMutation).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Finding your teammates…")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Search members" })).toBeEnabled();
    expect(header()).toBeEnabled();
    expect(document.querySelector(".animate-spin")).toBeNull();
    expect(screen.queryByText(/No matching active/)).not.toBeInTheDocument();
    await act(async () => request.resolve(roster));
    expect(yongru()).toBeEnabled();
  });

  it("keeps the list and search on reopen without fetching again", async () => {
    await openMembers();
    fireEvent.change(screen.getByRole("textbox", { name: "Search members" }), { target: { value: "yong" } });
    fireEvent.click(header());
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    fireEvent.click(header());
    expect(yongru()).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Search members" })).toHaveValue("yong");
    expect(requestMutation).toHaveBeenCalledTimes(1);
  });

  it("keeps a fresh list across panel unmounts, scoped to this admin session", async () => {
    const view = await openMembers();
    view.unmount();
    render(<LinearMemberAccess organizationId="org-1" />);
    fireEvent.click(header());
    expect(yongru()).toBeVisible();
    expect(requestMutation).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Finding your teammates…")).not.toBeInTheDocument();
  });

  it("shows a stale list immediately while revalidating, without disabling the list", async () => {
    const view = await openMembers();
    view.unmount();
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 61_000);
    const request = deferNextRequest();
    render(<LinearMemberAccess organizationId="org-1" />);
    fireEvent.click(header());
    expect(yongru()).toBeVisible();
    expect(yongru()).toBeEnabled();
    expect(screen.getByText("Checking for updates…")).toBeVisible();
    await act(async () => request.resolve({ ...roster, members: [roster.members[0]] }));
    expect(screen.queryByRole("switch", { name: "Allow Yongru to use nanobot" })).not.toBeInTheDocument();
  });

  it("changes a switch only after confirmation and keeps other members editable", async () => {
    await openMembers();
    const request = deferNextRequest();
    fireEvent.click(yongru());
    expect(yongru()).toBeDisabled();
    expect(yongru()).not.toBeChecked();
    expect(xubin()).toBeEnabled();
    expect(header()).toBeEnabled();
    expect(screen.getByText("Saving…")).toBeVisible();
    expect(requestMutation).toHaveBeenLastCalledWith("settings.channel.connect.start", {
      channel: "linear", operation: "member_access", organization_id: "org-1", user_id: "u2", allowed: true,
    }, 150_000);
    await act(async () => request.resolve({ ...roster, status: "member_access_saved", members: [{ ...roster.members[1], allowed: true }] }));
    expect(yongru()).toBeChecked();
    expect(yongru()).toBeEnabled();
    expect(screen.getByText("Saved")).toBeVisible();
    expect(xubin()).toBeChecked();
  });

  it("handles concurrent member saves completing in reverse order", async () => {
    await openMembers();
    const grant = deferNextRequest();
    fireEvent.click(yongru());
    const revoke = deferNextRequest();
    fireEvent.click(xubin());
    await act(async () => revoke.resolve({ ...roster, members: [{ ...roster.members[0], allowed: false }] }));
    expect(xubin()).not.toBeChecked();
    expect(xubin()).toBeEnabled();
    expect(yongru()).toBeDisabled();
    await act(async () => grant.resolve({ ...roster, members: [{ ...roster.members[1], allowed: true }] }));
    expect(xubin()).not.toBeChecked();
    expect(yongru()).toBeChecked();
    expect(screen.getAllByText("Saved")).toHaveLength(2);
  });

  it("does not overwrite a confirmed permission with a late directory response", async () => {
    await openMembers();
    const read = deferNextRequest();
    refresh();
    const save = deferNextRequest();
    fireEvent.click(yongru());
    await act(async () => save.resolve({ ...roster, members: [{ ...roster.members[1], allowed: true }] }));
    await act(async () => read.resolve(roster));
    expect(yongru()).toBeChecked();
    expect(screen.getByText("Saved")).toBeVisible();
  });

  it("retains a pending save across closing the panel and confirms it when it finishes", async () => {
    const view = await openMembers();
    const request = deferNextRequest();
    fireEvent.click(yongru());
    view.unmount();
    render(<LinearMemberAccess organizationId="org-1" />);
    fireEvent.click(header());
    expect(yongru()).toBeDisabled();
    expect(screen.getByText("Saving…")).toBeVisible();
    expect(requestMutation).toHaveBeenCalledTimes(2);
    await act(async () => request.resolve({ ...roster, members: [{ ...roster.members[1], allowed: true }] }));
    expect(yongru()).toBeChecked();
    expect(yongru()).toBeEnabled();
  });

  it("contains an uncertain save to that member and reconciles server state on refresh", async () => {
    await openMembers();
    requestMutation.mockRejectedValueOnce(new Error("Could not confirm save"));
    fireEvent.click(yongru());
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not confirm save");
    expect(yongru()).not.toBeChecked();
    expect(yongru()).toBeDisabled();
    expect(yongru()).toHaveAccessibleDescription(/Refresh members/);
    expect(xubin()).toBeEnabled();
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
    requestMutation.mockResolvedValueOnce({
      ...roster, members: roster.members.map((member) => ({ ...member, allowed: true })),
    });
    refresh();
    await waitFor(() => expect(yongru()).toBeEnabled());
    expect(yongru()).toBeChecked();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("rejects a mismatched save confirmation", async () => {
    await openMembers();
    requestMutation.mockResolvedValueOnce(roster);
    fireEvent.click(yongru());
    expect(await screen.findByRole("alert")).toHaveTextContent("Access was not confirmed");
    expect(yongru()).not.toBeChecked();
    expect(yongru()).toBeDisabled();
  });

  it("does not turn a failed initial load into an empty successful directory", async () => {
    requestMutation.mockRejectedValueOnce(new Error("Linear unavailable"));
    render(<LinearMemberAccess organizationId="org-1" />);
    fireEvent.click(header());
    expect(await screen.findByRole("alert")).toHaveTextContent("Linear unavailable");
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByText(/No matching active/)).not.toBeInTheDocument();
  });

  it("keeps known members visible when a refresh fails", async () => {
    await openMembers();
    requestMutation.mockRejectedValueOnce(new Error("Linear unavailable"));
    refresh();
    expect(await screen.findByRole("alert")).toHaveTextContent("Linear unavailable");
    expect(xubin()).toBeChecked();
    expect(yongru()).toBeEnabled();
  });

  it.each(["workspace", "login", "gateway", "app configuration"])("isolates cached lists and late responses after changing %s", async (scope) => {
    const view = await openMembers();
    const oldSave = deferNextRequest();
    fireEvent.click(yongru());
    const nextRead = deferNextRequest();
    if (scope === "login") context.token = "another-admin-session";
    if (scope === "gateway") context.client = { requestMutation };
    const organizationId = scope === "workspace" ? "org-2" : "org-1";
    view.rerender(<LinearMemberAccess organizationId={organizationId} configScope={scope === "app configuration" ? "other-app" : ""} />);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    await act(async () => oldSave.resolve({ ...roster, members: [{ ...roster.members[1], allowed: true }] }));
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    await act(async () => nextRead.resolve({ ...roster, organization_id: organizationId, members: [roster.members[0]] }));
    expect(xubin()).toBeVisible();
    expect(screen.queryByRole("switch", { name: "Allow Yongru to use nanobot" })).not.toBeInTheDocument();
  });

  it("explains legacy wildcard access without hiding individual off switches", async () => {
    requestMutation.mockResolvedValue({ ...roster, legacy_allow_all: true });
    await openMembers();
    expect(screen.getByText(/including new members/)).toBeVisible();
    expect(yongru()).not.toBeChecked();
  });

  it("blocks prefetches and edits while parent configuration is unsaved", () => {
    render(<LinearMemberAccess organizationId="org-1" disabled />);
    fireEvent.mouseEnter(header());
    fireEvent.focus(header());
    fireEvent.click(header());
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("disambiguates duplicate names with IDs", async () => {
    requestMutation.mockResolvedValue({ ...roster, members: roster.members.map((member) => ({ ...member, name: "Alex" })) });
    render(<LinearMemberAccess organizationId="org-1" />);
    fireEvent.click(header());
    expect(await screen.findByText("u1")).toBeVisible();
    expect(screen.getByText("u2")).toBeVisible();
  });
});
