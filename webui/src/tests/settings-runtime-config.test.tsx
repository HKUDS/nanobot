import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RuntimeSettings } from "@/components/settings/system/RuntimeSettings";
import { DEFAULT_AGENT_SETTINGS_DRAFT } from "@/components/settings/models/ModelsSettings";
import { installSettingsViewTestHooks, jsonResponse, renderSettingsView, requestMutationMock, settingsPayload } from "@/tests/settings-test-utils";

function runtimeSettings() {
  return { ...settingsPayload(), runtime_config: {
    "agents.defaults.bot_name": "nanobot",
    "agents.defaults.bot_icon": "🐈",
    "agents.defaults.timezone_mode": "auto",
    "agents.defaults.timezone": "UTC",
    "agents.defaults.dream.enabled": true,
    "gateway.heartbeat.enabled": true,
    "tools.exec.timeout": 60,
    "tools.exec.allowed_env_keys": ["TERM"],
    "tools.exec.allow_patterns": [],
    "tools.exec.deny_patterns": [],
    "tools.exec.sandbox_ro_binds": [],
    "tools.exec.sandbox_rw_binds": [],
    "agents.defaults.max_tool_iterations": 200,
    "tools.web.proxy": "http://localhost:8080",
  } };
}

describe("Runtime configuration settings", () => {
  installSettingsViewTestHooks();

  it("hides advanced options for disabled tool families", () => {
    const payload = runtimeSettings();
    renderSettingsView({ initialSection: "advanced", initialSettings: {
      ...payload, runtime_config: {
        ...payload.runtime_config, "tools.exec.enable": false,
        "tools.web.enable": false, "tools.cli_apps.enable": false,
      },
    } });
    expect(screen.queryByRole("region", { name: "Shell and sandbox" })).not.toBeInTheDocument();
    expect(document.getElementById("runtime-tools.web.proxy")).not.toBeInTheDocument();
    expect(document.getElementById("runtime-tools.cli_apps.run_timeout")).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Local services" })).toBeVisible();
  });

  it("keeps chat permission settings discoverable within the advanced page", () => {
    renderSettingsView({ initialSection: "advanced", initialSettings: runtimeSettings() });
    expect(screen.getByRole("switch", { name: "Local services" })).toBeInTheDocument();
  });

  it("places common settings in their feature pages and reserves advanced for low-frequency controls", () => {
    renderSettingsView({ initialSection: "runtime", initialSettings: runtimeSettings() });
    expect(document.getElementById("runtime-tools.exec.enable")).toBeInTheDocument();
    expect(document.getElementById("runtime-agents.defaults.workspace")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(document.getElementById("runtime-tools.exec.enable")).not.toBeInTheDocument();
    expect(document.getElementById("runtime-tools.image_generation.save_dir")).not.toBeInTheDocument();
    expect(document.getElementById("runtime-tools.exec.sandbox")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Capabilities" }));
    expect(document.getElementById("runtime-tools.image_generation.save_dir")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    expect(document.getElementById("runtime-tools.image_generation.save_dir")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    expect(screen.getByRole("switch", { name: "Web access" })).toBeInTheDocument();
  });

  it("exposes the CLI switch on the apps page", () => {
    renderSettingsView({ initialSection: "apps", initialSettings: runtimeSettings() });
    expect(document.getElementById("runtime-tools.cli_apps.enable")).toBeInTheDocument();
  });

  it("keeps runtime configuration out of the automations page", () => {
    renderSettingsView({ initialSection: "automations", initialSettings: runtimeSettings() });
    expect(document.getElementById("runtime-agents.defaults.dream.enabled")).not.toBeInTheDocument();
    expect(document.getElementById("runtime-gateway.heartbeat.enabled")).not.toBeInTheDocument();
    expect(screen.queryByText("Heartbeat schedule")).not.toBeInTheDocument();
  });



  it("offers only the memory consolidation switch and saves only dream.enabled", async () => {
    const payload = runtimeSettings();
    requestMutationMock.mockResolvedValue({ ...payload, runtime_config: { ...payload.runtime_config, "agents.defaults.dream.enabled": false } });
    renderSettingsView({ initialSection: "memory", initialSettings: payload });
    const memory = within(screen.getByRole("region", { name: "Memory consolidation" }));
    expect(memory.getAllByRole("switch")).toHaveLength(1);
    expect(memory.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(memory.queryByRole("textbox")).not.toBeInTheDocument();
    expect(memory.queryByText("Advanced options")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Memory consolidation" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.runtime_config.update", { values: { "agents.defaults.dream.enabled": false } }, 20_000));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Memory consolidation" })).not.toBeChecked());
  });

  it("explains unavailable memory settings instead of rendering a blank page", () => {
    renderSettingsView({ initialSection: "memory", initialSettings: settingsPayload() });
    expect(screen.getByText("Update the gateway to edit these settings.")).toBeVisible();
  });







  it("uses switches for binary modes and reveals sandbox fields only when enabled", async () => {
    const payload = runtimeSettings();
    requestMutationMock.mockResolvedValue(payload);
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });
    expect(document.getElementById("runtime-tools.exec.sandbox_ro_binds")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Enable Bubblewrap sandbox" }));
    expect(document.getElementById("runtime-tools.exec.sandbox_ro_binds")).toBeVisible();
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.runtime_config.update", { values: { "tools.exec.sandbox": "bwrap" } }, 20_000));
  });



  it("starts the API with newly saved advanced settings", async () => {
    const payload = runtimeSettings();
    payload.api = { ...payload.api, host: "192.168.1.7", timeout: 77.5, api_key_hint: "set" };
    const action = vi.fn();
    render(<RuntimeSettings form={DEFAULT_AGENT_SETTINGS_DRAFT} settings={payload}
      requiresRestartPending={false} apiService={{
        installed: true, running: false, managed: false, host: "127.0.0.1", port: 8900,
        timeout: 120, endpoint: "http://127.0.0.1:8900/v1", command: "nanobot serve",
        api_key_hint: "set",
      }} apiServiceLoading={false} apiServiceAction={null} apiServiceError={null}
      capabilitiesLoading={false} capabilityAction={null} capabilityError={null}
      onApiServiceAction={action} onInstallCapability={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Start API server" }));
    expect(action).toHaveBeenCalledWith("start", {
      host: "192.168.1.7", port: 8900, timeout: 77.5, apiKey: undefined,
    });
  });

  it("saves only edited fields using the existing settings footer", async () => {
    const payload = runtimeSettings();
    requestMutationMock.mockResolvedValue({ ...payload, requires_restart: true,
      runtime_config: { ...payload.runtime_config, "tools.exec.timeout": 90 } });
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Command timeout (seconds)" }), { target: { value: "90" } });
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.exec.timeout": 90 } }, 20_000,
    ));
    expect(await screen.findByText("Saved. Restart when ready.")).toBeInTheDocument();
    expect(screen.queryByText("Saved and applied.")).not.toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Shell and sandbox" })).queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("validates numbers and keeps a failed draft editable", async () => {
    requestMutationMock.mockRejectedValue(new Error("Could not save settings"));
    renderSettingsView({ initialSection: "advanced", initialSettings: runtimeSettings() });
    const field = screen.getByRole("spinbutton", { name: "Command timeout (seconds)" });
    fireEvent.change(field, { target: { value: "-1" } });
    await waitFor(() => expect(field).toHaveFocus());
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "17" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save settings");
    expect(field).toHaveValue(17);
    expect(within(screen.getByRole("group", { name: "Shell and sandbox" })).queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("preserves drafts when navigating away and supports explicit clearing", async () => {
    renderSettingsView({ initialSection: "advanced", initialSettings: runtimeSettings() });
    const proxy = screen.getByRole("textbox", { name: "Web proxy" });
    fireEvent.change(proxy, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "System" }));
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByRole("textbox", { name: "Web proxy" })).toHaveValue("");
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.web.proxy": null } }, 20_000,
    ));
  });

  it("enables manual timezone entry and persists both fields together", async () => {
    const payload = runtimeSettings();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) =>
      jsonResponse(String(input) === "/api/settings" ? payload : {})));
    requestMutationMock.mockResolvedValue(payload);
    renderSettingsView({ initialSection: "runtime", initialSettings: payload });
    expect(screen.queryByRole("textbox", { name: "Timezone" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Use system timezone" }));
    const field = screen.getByRole("textbox", { name: "Timezone" });
    expect(field).toBeEnabled();
    fireEvent.change(field, { target: { value: "Asia/Shanghai" } });
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: {
        "agents.defaults.timezone_mode": "manual", "agents.defaults.timezone": "Asia/Shanghai",
      } }, 20_000,
    ));
  });
});
