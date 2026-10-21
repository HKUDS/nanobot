import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RuntimeSettings } from "@/components/settings/system/RuntimeSettings";
import { RUNTIME_CONFIG_FIELDS, RUNTIME_CONFIG_GROUPS } from "@/components/settings/system/runtime-config-fields";
import runtimeConfigKeys from "../../../tests/webui/fixtures/runtime-config-keys.json";
import { TimezonePicker } from "@/components/settings/shared/TimezonePicker";
import { DEFAULT_AGENT_SETTINGS_DRAFT } from "@/components/settings/models/ModelsSettings";
import type { SettingsPayload } from "@/lib/types";
import { installSettingsViewTestHooks, jsonResponse, renderSettingsView, requestMutationMock, settingsPayload } from "@/tests/settings-test-utils";

function runtimeSettings() {
  const payload = settingsPayload();
  const runtimeConfig: NonNullable<SettingsPayload["runtime_config"]> = {
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
  };
  return { ...payload, advanced: { ...payload.advanced, exec_max_runtime_limit: 86400 }, runtime_config: runtimeConfig };
}

describe("Runtime configuration settings", () => {
  installSettingsViewTestHooks();

  it("covers the shared runtime wire-key catalogue without duplicate editors", () => {
    const paths = RUNTIME_CONFIG_FIELDS.map((field) => field.path);
    expect(new Set(paths).size).toBe(paths.length);
    // This key gates the CLI group rather than having a separate editor.
    const visibilityOnly = "tools.cli_apps.enable";
    expect(RUNTIME_CONFIG_GROUPS.find((group) => group.id === "cli")?.enabledBy).toBe(visibilityOnly);
    expect([...paths, visibilityOnly].sort()).toEqual([...runtimeConfigKeys].sort());
  });

  it("keeps local service controls available when tool families are disabled", () => {
    const payload = runtimeSettings();
    renderSettingsView({ initialSection: "advanced", initialSettings: {
      ...payload, runtime_config: {
        ...payload.runtime_config, "tools.exec.enable": false,
        "tools.web.enable": false, "tools.cli_apps.enable": false,
      },
    } });
    expect(screen.getByRole("switch", { name: "Local services" })).toBeVisible();
  });

  it("keeps chat permission settings discoverable within the advanced page", () => {
    renderSettingsView({ initialSection: "advanced", initialSettings: runtimeSettings() });
    expect(screen.getByRole("switch", { name: "Local services" })).toBeInTheDocument();
  });

  it("places common settings in their feature pages and reserves advanced for low-frequency controls", () => {
    renderSettingsView({ initialSection: "runtime", initialSettings: runtimeSettings() });
    expect(document.getElementById("runtime-tools.exec.enable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(document.getElementById("runtime-tools.exec.sandbox")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Capabilities" }));
    fireEvent.click(screen.getByRole("switch", { name: "Image generation" }));
    expect(document.getElementById("runtime-tools.image_generation.save_dir")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("switch", { name: "Web access" })).toBeInTheDocument();
  });

  it("offers only the memory consolidation switch and saves only dream.enabled", async () => {
    const payload = runtimeSettings();
    requestMutationMock.mockResolvedValue({ ...payload, runtime_config: { ...payload.runtime_config, "agents.defaults.dream.enabled": false } });
    renderSettingsView({ initialSection: "memory", initialSettings: payload });
    const memory = within(screen.getByRole("region", { name: "Memory consolidation" }));
    expect(memory.getAllByRole("switch")).toHaveLength(1);
    fireEvent.click(screen.getByRole("switch", { name: "Memory consolidation" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.runtime_config.update", { values: { "agents.defaults.dream.enabled": false } }, 20_000));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Memory consolidation" })).not.toBeChecked());
  });

  it("explains unavailable memory settings instead of rendering a blank page", () => {
    renderSettingsView({ initialSection: "memory", initialSettings: settingsPayload() });
    expect(screen.getByText("Update the gateway to edit these settings.")).toBeVisible();
  });

  it.each(["bwrap", "seatbelt", ""])("saves the %s sandbox and reveals its path settings", async (backend) => {
    const payload = runtimeSettings();
    payload.runtime_config!["tools.exec.sandbox"] = backend ? "" : "seatbelt";
    requestMutationMock.mockResolvedValue({ ...payload, runtime_config: { ...payload.runtime_config, "tools.exec.sandbox": backend } });
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });
    fireEvent.click(screen.getByRole("combobox", { name: "Command sandbox" }));
    fireEvent.click(screen.getByRole("option", { name: backend || "None" }));
    if (backend) expect(document.getElementById("runtime-tools.exec.sandbox_ro_binds")).toBeVisible();
    else expect(document.getElementById("runtime-tools.exec.sandbox_ro_binds")).not.toBeInTheDocument();
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.runtime_config.update", { values: { "tools.exec.sandbox": backend } }, 20_000));
  });

  it("edits lists in a dialog, cancels drafts, and retains failed saves for retry", async () => {
    const payload = runtimeSettings();
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });
    const trigger = screen.getByRole("button", { name: "Environment variables", expanded: false });
    expect(screen.queryByRole("textbox", { name: "Environment variables" })).not.toBeInTheDocument();
    fireEvent.click(trigger);
    let dialog = screen.getByRole("dialog", { name: "Environment variables" });
    let editor = within(dialog).getByRole("textbox");
    expect(editor).toHaveValue("TERM");
    await waitFor(() => expect(editor).toHaveFocus());
    fireEvent.change(editor, { target: { value: "discarded" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(requestMutationMock).not.toHaveBeenCalled();

    fireEvent.click(trigger);
    dialog = screen.getByRole("dialog", { name: "Environment variables" });
    editor = within(dialog).getByRole("textbox");
    expect(editor).toHaveValue("TERM");
    fireEvent.change(editor, { target: { value: " TERM \n\n COLORTERM " } });
    requestMutationMock.mockRejectedValueOnce(new Error("Could not save list"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Could not save list");
    expect(editor).toHaveValue(" TERM \n\n COLORTERM ");
    expect(requestMutationMock).toHaveBeenLastCalledWith("settings.runtime_config.update", {
      values: { "tools.exec.allowed_env_keys": ["TERM", "COLORTERM"] },
    }, 20_000);
    requestMutationMock.mockResolvedValueOnce({ ...payload, requires_restart: true,
      runtime_config: { ...payload.runtime_config, "tools.exec.allowed_env_keys": ["TERM", "COLORTERM"] } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText("Saved. Restart to apply changes.")).toBeVisible();
    fireEvent.click(trigger);
    expect(within(screen.getByRole("dialog")).getByRole("textbox")).toHaveValue("TERM\nCOLORTERM");
  });

  it("starts the API with newly saved advanced settings", async () => {
    const payload = runtimeSettings();
    payload.api = { ...payload.api, host: "192.168.1.7", port: 8900, timeout: 77.5, api_key_hint: "set" };
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
    fireEvent.change(screen.getByRole("spinbutton", { name: "Custom runtime (seconds)" }), { target: { value: "90" } });
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.exec.timeout": 90 } }, 20_000,
    ));
    expect(await screen.findByText("Saved. Restart to apply changes.")).toBeInTheDocument();
  });

  it("keeps a loaded custom runtime editable when typing through a preset", async () => {
    const payload = runtimeSettings();
    requestMutationMock.mockResolvedValue({ ...payload, runtime_config: {
      ...payload.runtime_config, "tools.exec.timeout": 9000,
    } });
    const user = userEvent.setup();
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });
    const field = screen.getByRole("spinbutton", { name: "Custom runtime (seconds)" });

    await user.clear(field);
    await user.type(field, "900");
    expect(field).toHaveFocus();
    expect(field).toHaveValue(900);
    await user.type(field, "0");
    expect(field).toHaveFocus();
    expect(field).toHaveValue(9000);

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.exec.timeout": 9000 } }, 20_000,
    ));
  });

  it("validates numbers and keeps a failed draft editable", async () => {
    requestMutationMock.mockRejectedValue(new Error("Could not save settings"));
    renderSettingsView({ initialSection: "advanced", initialSettings: runtimeSettings() });
    const field = screen.getByRole("spinbutton", { name: "Custom runtime (seconds)" });
    fireEvent.change(field, { target: { value: "-1" } });
    await waitFor(() => expect(field).toHaveFocus());
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "17" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save settings");
    expect(field).toHaveValue(17);
  });

  it.each([
    ["24 hours", 86400],
    ["No time limit", 0],
  ])("saves the %s command runtime preset in seconds", async (label, seconds) => {
    const payload = runtimeSettings();
    payload.runtime_config["tools.exec.timeout"] = 3600;
    requestMutationMock.mockResolvedValue({ ...payload, runtime_config: {
      ...payload.runtime_config, "tools.exec.timeout": seconds,
    } });
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });

    const control = screen.getByRole("combobox", { name: "Command runtime" });
    expect(control).toHaveTextContent("1 hour");
    expect(screen.getByText("Timed runs: up to 24 hours")).toBeVisible();
    fireEvent.click(control);
    fireEvent.click(screen.getByRole("option", { name: label }));

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.exec.timeout": seconds } }, 20_000,
    ));
  });

  it("rejects over-limit custom input without clamping or saving it", async () => {
    const payload = runtimeSettings();
    payload.runtime_config["tools.exec.timeout"] = 3600;
    requestMutationMock.mockResolvedValue({ ...payload, runtime_config: {
      ...payload.runtime_config, "tools.exec.timeout": 86400,
    } });
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });
    fireEvent.click(screen.getByRole("combobox", { name: "Command runtime" }));
    fireEvent.click(screen.getByRole("option", { name: "Custom (seconds)" }));
    const field = screen.getByRole("spinbutton", { name: "Custom runtime (seconds)" });
    expect(field).toHaveAttribute("max", "86400");
    fireEvent.change(field, { target: { value: "86401" } });

    expect(field).toHaveValue(3600);
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("1 to 86,400");
    expect(requestMutationMock).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: "86400" } });
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.exec.timeout": 86400 } }, 20_000,
    ));
    await screen.findByText("Saved.", { exact: true });
    fireEvent.change(field, { target: { value: "86401" } });
    expect(field).toHaveValue(86400);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText("Saved.", { exact: true })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "System" }));
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByRole("spinbutton", { name: "Custom runtime (seconds)" })).toHaveValue(86400);
    expect(screen.getByRole("alert")).toHaveTextContent("1 to 86,400");
  });

  it("starts a custom duration from No time limit without saving an empty value", async () => {
    const payload = runtimeSettings();
    payload.runtime_config["tools.exec.timeout"] = 0;
    requestMutationMock.mockResolvedValue({ ...payload, runtime_config: {
      ...payload.runtime_config, "tools.exec.timeout": 120,
    } });
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });
    fireEvent.click(screen.getByRole("combobox", { name: "Command runtime" }));
    fireEvent.click(screen.getByRole("option", { name: "Custom (seconds)" }));
    const field = screen.getByRole("spinbutton", { name: "Custom runtime (seconds)" });
    expect(field).toHaveValue(null);
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "120" } });
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.exec.timeout": 120 } }, 20_000,
    ));
  });

  it("uses the gateway's configured runtime limit for presets and custom input", () => {
    const payload = runtimeSettings();
    payload.advanced.exec_max_runtime_limit = 7200;
    renderSettingsView({ initialSection: "advanced", initialSettings: payload });
    expect(screen.getByText("Timed runs: up to 2 hours")).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "Custom runtime (seconds)" })).toHaveAttribute("max", "7200");
    fireEvent.click(screen.getByRole("combobox", { name: "Command runtime" }));
    expect(screen.getByRole("option", { name: "2 hours" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "24 hours" })).not.toBeInTheDocument();
  });

  it("keeps runtime editing available on a host without limit metadata", async () => {
    const payload = runtimeSettings();
    requestMutationMock.mockResolvedValue({ ...payload, runtime_config: {
      ...payload.runtime_config, "tools.exec.timeout": 90,
    } });
    renderSettingsView({ initialSection: "advanced", initialSettings: {
      ...payload, advanced: settingsPayload().advanced,
    } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Custom runtime (seconds)" }), { target: { value: "90" } });
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.exec.timeout": 90 } }, 20_000,
    ));
  });

  it("preserves drafts when navigating away and supports explicit clearing", async () => {
    renderSettingsView({ initialSection: "capabilities", initialSettings: runtimeSettings() });
    const openWebSettings = () => {
      fireEvent.click(within(screen.getByRole("region", { name: "Web access" })).getByRole("button", { name: "Configure" }));
      fireEvent.click(screen.getByRole("button", { name: "Advanced options" }));
    };
    openWebSettings();
    const proxy = screen.getByRole("textbox", { name: "Web proxy" });
    fireEvent.change(proxy, { target: { value: "" } });
    fireEvent.click(within(screen.getByRole("dialog", { name: "Web access" })).getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "System" }));
    fireEvent.click(screen.getByRole("button", { name: "Capabilities" }));
    openWebSettings();
    expect(screen.getByRole("textbox", { name: "Web proxy" })).toHaveValue("");
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: { "tools.web.proxy": null } }, 20_000,
    ));
  });

  it("keeps an existing timezone alias selectable and accepts only listed search results", () => {
    const onChange = vi.fn();
    render(<TimezonePicker value="Asia/Calcutta" aria-label="Timezone" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Timezone" }));
    const search = screen.getByRole("combobox", { name: "Search" });
    fireEvent.change(search, { target: { value: "invalid timezone" } });
    expect(screen.getByRole("status")).toHaveTextContent("No matching timezones.");
    fireEvent.keyDown(search, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(search, { target: { value: "Asia/Calcutta" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("Asia/Calcutta");
  });

  it("selects a manual timezone from search results and persists both fields", async () => {
    const payload = runtimeSettings();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) =>
      jsonResponse(String(input) === "/api/settings" ? payload : {})));
    requestMutationMock.mockResolvedValue(payload);
    renderSettingsView({ initialSection: "runtime", initialSettings: payload });
    fireEvent.click(screen.getByRole("switch", { name: "System timezone" }));
    const field = screen.getByRole("button", { name: "Timezone", expanded: false });
    expect(field).toBeEnabled();
    fireEvent.click(field);
    fireEvent.change(screen.getByRole("combobox", { name: "Search" }), { target: { value: "Shanghai" } });
    fireEvent.click(screen.getByRole("option", { name: /Asia\/Shanghai/ }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.runtime_config.update", { values: {
        "agents.defaults.timezone_mode": "manual", "agents.defaults.timezone": "Asia/Shanghai",
      } }, 20_000,
    ));
  });
});
