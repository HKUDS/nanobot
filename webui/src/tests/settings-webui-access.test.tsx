import { describe, expect, it, vi } from "vitest";

import {
  fireEvent,
  installSettingsViewTestHooks,
  renderSettingsView,
  requestMutationMock,
  screen,
  settingsPayload,
  waitFor,
  within,
} from "./settings-test-utils";

const localAccess = {
  allow_other_devices: false,
  active_allow_other_devices: false,
  host: "127.0.0.1",
  active_host: "127.0.0.1",
  requires_restart: false,
  can_change: true,
};

describe("WebUI access settings", () => {
  installSettingsViewTestHooks();

  it.each([
    { capability: false, field: true },
    { capability: true, field: false },
    { capability: false, field: false },
  ])("hides the optional setting without both capability and payload: %j", ({ capability, field }) => {
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), ...(field ? { webui_access: localAccess } : {}) },
      webuiCapabilities: capability ? ["webui.access.v1"] : [],
    });
    expect(screen.queryByRole("switch", { name: "Allow access from other devices" })).not.toBeInTheDocument();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("saves the switch while preserving the active address until an explicit restart", async () => {
    const restart = vi.fn();
    requestMutationMock.mockResolvedValue({
      ...settingsPayload(),
      requires_restart: true,
      restart_required_sections: ["runtime"],
      webui_access: { ...localAccess, allow_other_devices: true, host: "0.0.0.0", requires_restart: true },
    });
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: localAccess },
      webuiCapabilities: ["webui.access.v1"],
      onRestart: restart,
    });
    const toggle = screen.getByRole("switch", { name: "Allow access from other devices" });
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    expect(requestMutationMock).toHaveBeenCalledWith("settings.webui_access.update", { allow_other_devices: true }, expect.any(Number));
    const access = screen.getByRole("region", { name: "WebUI access" });
    expect(within(access).getByText("127.0.0.1")).toBeVisible();
    expect(within(access).getByText("Currently, only this computer can connect.")).toBeVisible();
    expect(within(access).getByRole("status")).toHaveTextContent("Saved. Restart to allow other devices to connect.");
    expect(restart).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("complementary")).getByRole("button", { name: "Restart" }));
    expect(restart).toHaveBeenCalledTimes(1);
  });

  it("explains that disabling remote access disconnects other devices after restarting", async () => {
    const networkAccess = { ...localAccess, allow_other_devices: true, active_allow_other_devices: true, host: "0.0.0.0", active_host: "0.0.0.0" };
    requestMutationMock.mockResolvedValue({
      ...settingsPayload(),
      requires_restart: true,
      restart_required_sections: ["runtime"],
      webui_access: { ...networkAccess, allow_other_devices: false, host: "127.0.0.1", requires_restart: true },
    });
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: networkAccess },
      webuiCapabilities: ["webui.access.v1"],
    });
    fireEvent.click(screen.getByRole("switch", { name: "Allow access from other devices" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Allow access from other devices" })).not.toBeChecked());
    expect(requestMutationMock).toHaveBeenCalledWith("settings.webui_access.update", { allow_other_devices: false }, expect.any(Number));
    const access = screen.getByRole("region", { name: "WebUI access" });
    expect(within(access).getByRole("status")).toHaveTextContent("other devices will disconnect");
    expect(within(access).getByRole("status")).toHaveTextContent("localhost");
    expect(within(access).getByText("0.0.0.0")).toBeVisible();
  });

  it("keeps the saved value on failure and allows retry", async () => {
    requestMutationMock.mockRejectedValueOnce(new Error("save failed")).mockResolvedValueOnce({
      ...settingsPayload(),
      webui_access: { ...localAccess, allow_other_devices: true, requires_restart: true },
    });
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: localAccess },
      webuiCapabilities: ["webui.access.v1"],
    });
    const toggle = screen.getByRole("switch", { name: "Allow access from other devices" });
    fireEvent.click(toggle);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save access settings. Try again.");
    expect(toggle).not.toBeChecked();
    expect(toggle).toBeEnabled();
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the actual host-managed listener without enabling changes", () => {
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: { ...localAccess, can_change: false, active_host: "/tmp/nanobot.sock" } },
      webuiCapabilities: ["webui.access.v1"],
    });
    const toggle = screen.getByRole("switch", { name: "Allow access from other devices" });
    expect(toggle).toBeDisabled();
    expect(screen.getByText("/tmp/nanobot.sock")).toBeVisible();
    fireEvent.click(toggle);
    expect(requestMutationMock).not.toHaveBeenCalled();
  });
});
