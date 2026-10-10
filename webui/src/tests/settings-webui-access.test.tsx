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
  password_required: false,
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
    fireEvent.click(within(access).getByRole("button", { name: "Current listening address" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Currently, only this computer can connect.");
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

  it("asks for a password when enabling a new installation and lets the user cancel", async () => {
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: { ...localAccess, password_required: true } },
      webuiCapabilities: ["webui.access.v1"],
      onAccessPasswordChange: vi.fn(),
    });
    const toggle = screen.getByRole("switch", { name: "Allow access from other devices" });
    fireEvent.click(toggle);
    const dialog = screen.getByRole("dialog", { name: "Set an access password" });
    expect(toggle).not.toBeChecked();
    fireEvent.change(within(dialog).getByLabelText("WebUI password"), { target: { value: "draft-password" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(toggle).not.toBeChecked();
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(toggle);
    expect(screen.getByLabelText("WebUI password")).toHaveValue("");
  });

  it("validates password length, allowed characters and confirmation before sending", () => {
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: { ...localAccess, password_required: true } },
      webuiCapabilities: ["webui.access.v1"],
      onAccessPasswordChange: vi.fn(),
    });
    fireEvent.click(screen.getByRole("switch", { name: "Allow access from other devices" }));
    const password = screen.getByLabelText("WebUI password");
    const confirmation = screen.getByLabelText("Confirm password");
    const submit = screen.getByRole("button", { name: "Set password and allow access" });
    for (const invalid of [
      "Aa1!bcd", "Aa1!".repeat(256) + "x", "Valid42!中文", "Valid42!😀", "Valid42!$",
      " Valid42!", "Valid42! ", "Valid 42!", "Valid42!${PASSWORD}",
    ]) {
      fireEvent.change(password, { target: { value: invalid } });
      fireEvent.click(submit);
      expect(screen.getByRole("alert")).toHaveTextContent("8–1024 visible ASCII characters");
      expect(password).toHaveFocus();
      expect(requestMutationMock).not.toHaveBeenCalled();
    }
    fireEvent.change(password, { target: { value: "Aa1!bcde" } });
    fireEvent.change(confirmation, { target: { value: "different" } });
    fireEvent.click(submit);
    expect(screen.getByRole("alert")).toHaveTextContent("The passwords do not match");
    expect(confirmation).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    expect(confirmation).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
    expect(confirmation).toHaveAttribute("type", "password");
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("keeps the switch off and the draft on save failure, then updates credentials on retry", async () => {
    const credentialsChanged = vi.fn();
    requestMutationMock.mockRejectedValueOnce(new Error("save_failed")).mockResolvedValueOnce({
      ...settingsPayload(),
      requires_restart: true,
      restart_required_sections: ["runtime"],
      webui_access: { ...localAccess, allow_other_devices: true, host: "0.0.0.0", requires_restart: true },
    });
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: { ...localAccess, password_required: true } },
      webuiCapabilities: ["webui.access.v1"],
      onAccessPasswordChange: credentialsChanged,
    });
    const toggle = screen.getByRole("switch", { name: "Allow access from other devices" });
    fireEvent.click(toggle);
    const secret = "a".repeat(1024);
    fireEvent.change(screen.getByLabelText("WebUI password"), { target: { value: secret } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: secret } });
    fireEvent.click(screen.getByRole("button", { name: "Set password and allow access" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save access settings. Try again.");
    expect(toggle).not.toBeChecked();
    expect(credentialsChanged).not.toHaveBeenCalled();
    expect(screen.getByLabelText("WebUI password")).toHaveValue(secret);
    fireEvent.click(screen.getByRole("button", { name: "Set password and allow access" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(toggle).toBeChecked();
    expect(requestMutationMock).toHaveBeenLastCalledWith("settings.webui_access.update", {
      allow_other_devices: true, password: secret,
    }, expect.any(Number));
    expect(credentialsChanged).toHaveBeenCalledTimes(1);
    expect(credentialsChanged).toHaveBeenCalledWith(secret);
    const access = screen.getByRole("region", { name: "WebUI access" });
    expect(within(access).getByText("127.0.0.1")).toBeVisible();
    expect(within(access).getByRole("status")).toHaveTextContent("Saved. Restart to allow other devices to connect.");
  });

  it.each(["ABCDEFGH", "12345678", "!@#%^&*?"])("accepts %s without requiring character combinations", async (secret) => {
    const credentialsChanged = vi.fn();
    requestMutationMock.mockResolvedValueOnce({
      ...settingsPayload(),
      requires_restart: true,
      restart_required_sections: ["runtime"],
      webui_access: { ...localAccess, allow_other_devices: true, host: "0.0.0.0", requires_restart: true },
    });
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: { ...localAccess, password_required: true } },
      webuiCapabilities: ["webui.access.v1"],
      onAccessPasswordChange: credentialsChanged,
    });
    fireEvent.click(screen.getByRole("switch", { name: "Allow access from other devices" }));
    fireEvent.change(screen.getByLabelText("WebUI password"), { target: { value: secret } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: secret } });
    fireEvent.click(screen.getByRole("button", { name: "Set password and allow access" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(requestMutationMock).toHaveBeenCalledWith("settings.webui_access.update", {
      allow_other_devices: true, password: secret,
    }, expect.any(Number));
    expect(credentialsChanged).toHaveBeenCalledWith(secret);
    expect(screen.getByRole("switch", { name: "Allow access from other devices" })).toBeChecked();
  });

  it.each([
    ["password_already_set", "Another page has already set the password. Refresh this page before changing access."],
    ["access_local_only", "Set the password on the computer running nanobot."],
  ])("shows %s without changing access or credentials", async (code, message) => {
    const credentialsChanged = vi.fn();
    requestMutationMock.mockRejectedValueOnce(new Error(code));
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: { ...settingsPayload(), webui_access: { ...localAccess, password_required: true } },
      webuiCapabilities: ["webui.access.v1"],
      onAccessPasswordChange: credentialsChanged,
    });
    const toggle = screen.getByRole("switch", { name: "Allow access from other devices" });
    fireEvent.click(toggle);
    fireEvent.change(screen.getByLabelText("WebUI password"), { target: { value: "Second-Tab42!" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "Second-Tab42!" } });
    fireEvent.click(screen.getByRole("button", { name: "Set password and allow access" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(toggle).not.toBeChecked();
    expect(credentialsChanged).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });
});
