import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PairRouteSettings } from "@/components/remote/PairRouteSettings";
import i18n from "@/i18n";

const mocks = vi.hoisted(() => ({ action: vi.fn(), refresh: vi.fn(), config: "" }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client: { requestMutation: mocks.action } }) }));
vi.mock("@/components/remote/RemoteInstances", () => ({ useRemoteConnections: () => ({ refresh: mocks.refresh, directory: { profiles: [{ id: "paired", paired: true, ssh_config: mocks.config }, { id: "ssh", name: "Team SSH", paired: false }] } }) }));

beforeEach(async () => { await i18n.changeLanguage("en"); mocks.action.mockReset().mockResolvedValue({}); mocks.refresh.mockReset().mockResolvedValue(undefined); mocks.config = ""; });
afterEach(cleanup);

async function chooseSSH() {
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Team SSH" }));
}

describe("paired network route", () => {
  it("does not mislabel a saved custom route as a direct connection", () => {
    mocks.config = "/private/paired/ssh_route";
    render(<PairRouteSettings id="paired" />);
    expect(screen.getByRole("combobox")).toHaveTextContent("Saved route");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(mocks.action).not.toHaveBeenCalled();
  });
  it("shows direct only when no saved route is configured", () => {
    render(<PairRouteSettings id="paired" />);
    expect(screen.getByRole("combobox")).toHaveTextContent("Direct connection");
    expect(screen.getByText(i18n.t("remote.pair.routeHint").replace(/\s+/g, " ").trim())).toBeVisible();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });
  it("shows saving, then confirms the saved route without connecting", async () => {
    let finish!: (value: unknown) => void;
    mocks.action.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<PairRouteSettings id="paired" />);
    await chooseSSH();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(screen.getByRole("combobox")).toBeDisabled();
    await act(async () => finish({}));
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(mocks.action).toHaveBeenCalledOnce();
    expect(mocks.action).toHaveBeenCalledWith("remote.pair_route", { id: "paired", route_id: "ssh" }, 65000);
  });
  it("preserves the chosen route after a failed save and allows retry", async () => {
    mocks.action.mockRejectedValueOnce(new Error("pair_route_mismatch"));
    render(<PairRouteSettings id="paired" />);
    await chooseSSH();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("same server");
    expect(screen.getByRole("combobox")).toHaveTextContent("Team SSH");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
  });
  it("distinguishes a saved route from a subsequent failed directory refresh", async () => {
    mocks.refresh.mockRejectedValue(new Error("offline"));
    render(<PairRouteSettings id="paired" />);
    await chooseSSH();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't read your saved servers");
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(mocks.action).toHaveBeenCalledOnce();
  });
  it("does not dismiss a different screen when a closed editor finishes saving", async () => {
    let finish!: (value: unknown) => void;
    mocks.action.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const saved = vi.fn();
    const view = render(<PairRouteSettings id="paired" onSaved={saved} />);
    await chooseSSH();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    view.unmount();
    await act(async () => finish({}));
    expect(saved).not.toHaveBeenCalled();
  });
});
