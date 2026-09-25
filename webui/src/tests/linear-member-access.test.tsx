import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LinearMemberAccess } from "../../../nanobot/channels/linear/webui/LinearMemberAccess";
import type { LinearMembersPayload } from "../../../nanobot/channels/linear/webui/types";

const { requestMutation } = vi.hoisted(() => ({ requestMutation: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => {
  const client = { requestMutation };
  return { useClient: () => ({ client }) };
});

const roster: LinearMembersPayload = {
  session_id: "", status: "members", organization_id: "org-1", legacy_allow_all: false,
  members: [
    { id: "u1", name: "Xubin", teams: ["nanobot"], allowed: true },
    { id: "u2", name: "Yongru", teams: ["nanobot"], allowed: false },
  ],
};

beforeEach(() => requestMutation.mockReset().mockResolvedValue(roster));
afterEach(cleanup);

async function openMembers() {
  render(<LinearMemberAccess organizationId="org-1" />);
  expect(requestMutation).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Member access" }));
  return screen.findByRole("switch", { name: "Allow Yongru to use nanobot" });
}

describe("Linear member access", () => {
  it("loads the selected workspace, shows effective permissions and searches by name", async () => {
    const toggle = await openMembers();
    expect(toggle).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Allow Xubin to use nanobot" })).toBeChecked();
    expect(requestMutation).toHaveBeenCalledWith("settings.channel.connect.start", {
      channel: "linear", operation: "members", organization_id: "org-1",
    }, 150_000);
    expect(screen.getByText(/does not grant access/)).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "Search members" }), { target: { value: "yong" } });
    expect(screen.queryByRole("switch", { name: "Allow Xubin to use nanobot" })).not.toBeInTheDocument();
    expect(toggle).toBeVisible();
  });

  it("changes the switch only after the server confirms and sends stable IDs", async () => {
    const toggle = await openMembers();
    let resolve!: (value: LinearMembersPayload) => void;
    requestMutation.mockImplementationOnce(() => new Promise<LinearMembersPayload>((done) => { resolve = done; }));
    fireEvent.click(toggle);
    expect(toggle).toBeDisabled();
    expect(toggle).not.toBeChecked();
    expect(requestMutation).toHaveBeenLastCalledWith("settings.channel.connect.start", {
      channel: "linear", operation: "member_access", organization_id: "org-1", user_id: "u2", allowed: true,
    }, 150_000);
    await act(async () => resolve({ ...roster, status: "member_access_saved", members: [{ ...roster.members[1], allowed: true }] }));
    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
    expect(screen.getByText("Member access saved.")).toBeVisible();
    expect(screen.getByRole("switch", { name: "Allow Xubin to use nanobot" })).toBeChecked();
  });

  it("does not fake success on save failure and requires refresh before retrying", async () => {
    const toggle = await openMembers();
    requestMutation.mockRejectedValueOnce(new Error("Could not save"));
    fireEvent.click(toggle);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
    expect(toggle).not.toBeChecked();
    expect(toggle).toBeDisabled();
    expect(screen.queryByText("Member access saved.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh members" }));
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not turn a failed roster load into an empty successful directory", async () => {
    requestMutation.mockRejectedValueOnce(new Error("Linear unavailable"));
    render(<LinearMemberAccess organizationId="org-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Member access" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Linear unavailable");
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByText(/No matching active/)).not.toBeInTheDocument();
  });

  it("explains legacy wildcard access without hiding individual off switches", async () => {
    requestMutation.mockResolvedValue({ ...roster, legacy_allow_all: true });
    const toggle = await openMembers();
    expect(screen.getByText(/including new members/)).toBeVisible();
    expect(toggle).not.toBeChecked();
  });

  it("blocks edits while parent configuration is unsaved", () => {
    render(<LinearMemberAccess organizationId="org-1" disabled />);
    fireEvent.click(screen.getByRole("button", { name: "Member access" }));
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("disambiguates duplicate names with IDs", async () => {
    requestMutation.mockResolvedValue({ ...roster, members: roster.members.map((member) => ({ ...member, name: "Alex" })) });
    render(<LinearMemberAccess organizationId="org-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Member access" }));
    expect(await screen.findByText("u1")).toBeVisible();
    expect(screen.getByText("u2")).toBeVisible();
  });
});
