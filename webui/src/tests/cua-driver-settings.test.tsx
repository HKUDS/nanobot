import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CUA_CAPABILITY, CUA_SETUP_CAPABILITY } from "@/components/settings/system/CuaDriverSetupPanel";
import type { McpPresetInfo } from "@/lib/types";
import { installSettingsViewTestHooks, jsonResponse, renderSettingsView, requestMutationMock, settingsPayload } from "@/tests/settings-test-utils";

describe("Cua Driver through Apps settings", () => {
  installSettingsViewTestHooks();

  it("routes download, observation, checking and disable through the owning gateway transport", async () => {
    let preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: false,
      configured: false, available: false, status: "not_installed", required_fields: [], connection_summary: "",
      source: "preset", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: false, managed: true, mode: "off",
      },
    };
    const payload = () => ({ presets: [preset], capabilities: [CUA_CAPABILITY], installed_count: Number(preset.configured) });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/settings") return jsonResponse(settingsPayload());
      if (path === "/api/settings/mcp-presets") return jsonResponse(payload());
      if (path === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    }));
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.install") preset = { ...preset, driver_setup: { ...preset.driver_setup!, installed: true } };
      if (action === "settings.mcp.enable") preset = { ...preset, configured: true, installed: true, runtime_status: "connected", driver_setup: { ...preset.driver_setup!, mode: "observe" } };
      if (action === "settings.mcp.disable") preset = { ...preset, configured: false, installed: false, driver_setup: { ...preset.driver_setup!, mode: "off" } };
      return { ...payload(), requires_restart: false, last_action: { ok: true, message: "Done" } };
    });
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    const row = (await screen.findByRole("heading", { name: "nanobot Computer Use" })).closest("article")!;
    fireEvent.click(within(row).getByRole("button", { name: "nanobot Computer Use" }));
    const dialog = screen.getByRole("dialog", { name: "nanobot Computer Use" });
    expect(within(dialog).getByText("Powered by Cua Driver · Integrated by nanobot")).toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: "See what’s on screen" })).toBeInTheDocument();
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: /^Install$/ }));
    expect(within(dialog).getByRole("region", { name: "Connection" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Overview" })).toHaveFocus();
    fireEvent.click(within(dialog).getByRole("button", { name: "Overview" }));
    expect(within(dialog).getByRole("heading", { name: "See what’s on screen" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /^Install$/ })).toHaveFocus();
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: /^Install$/ }));
    expect(within(dialog).getByRole("button", { name: "Download & install" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Download & install" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.mcp.install", {
      name: "cua-driver", consent: `${CUA_CAPABILITY}:install`,
    }, 660_000));
    fireEvent.click(await screen.findByRole("radio", { name: "View & control" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Overview" }));
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Connect" }));
    expect(within(dialog).getByRole("radio", { name: "View & control" })).toBeChecked();
    fireEvent.click(within(dialog).getByRole("radio", { name: "View only" }));
    fireEvent.click(screen.getByRole("button", { name: "Allow viewing & connect" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.mcp.enable", {
      name: "cua-driver", mode: "observe", consent: `${CUA_CAPABILITY}:observe`,
    }, 60_000));
    expect(within(row).getByText("Enabled")).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "Check connection" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.mcp.test", { name: "cua-driver" }, 60_000));
    await waitFor(() => expect(screen.getByRole("button", { name: "Disable" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.mcp.disable", { name: "cua-driver" }, 60_000));
    expect(requestMutationMock.mock.calls.map(call => call[0])).toEqual([
      "settings.mcp.install", "settings.mcp.enable", "settings.mcp.test", "settings.mcp.disable",
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(within(row).getByRole("button", { name: "nanobot Computer Use: Connect" })).toBeInTheDocument();
    expect(within(row).getByText("Access off")).toBeVisible();
  });

  it("keeps catalog and connection states aligned through permission recovery", async () => {
    const preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: true,
      configured: true, available: true, status: "installed", required_fields: [], connection_summary: "",
      source: "preset", runtime_status: "connected", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: true, managed: true, mode: "observe",
      },
    };
    let grantsReady = false;
    let connected = true;
    const payload = () => ({ presets: [preset], capabilities: [CUA_CAPABILITY, CUA_SETUP_CAPABILITY], installed_count: 1 });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse(payload());
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    }));
    requestMutationMock.mockImplementation(async () => ({
      ...payload(), requires_restart: false,
      last_action: { ok: true, message: "Checked", driver_check: {
        connected, accessibility: grantsReady, screen_recording: grantsReady, capture_verified: false,
      } },
    }));
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    const row = (await screen.findByRole("heading", { name: "nanobot Computer Use" })).closest("article")!;
    expect(within(row).getByText("Enabled")).toBeVisible();
    expect(within(row).queryByText("Permissions pending")).not.toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "nanobot Computer Use: Manage" }));
    const dialog = screen.getByRole("dialog", { name: "nanobot Computer Use" });
    await waitFor(() => expect(within(row).getByRole("button", { name: "nanobot Computer Use: Continue setup", hidden: true })).toBeInTheDocument());
    expect(within(dialog).getByRole("status")).toHaveTextContent("Permissions pending");
    expect(within(dialog).getByRole("button", { name: "Open Screen Recording settings" })).toBeVisible();
    grantsReady = true;
    fireEvent.click(within(dialog).getByRole("button", { name: "Check connection" }));
    await waitFor(() => expect(within(dialog).getByRole("status")).toHaveTextContent("Connected"));
    expect(within(row).getByText("Connected")).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: /Open .* settings/ })).not.toBeInTheDocument();
    connected = false;
    fireEvent.click(within(dialog).getByRole("button", { name: "Check connection" }));
    await waitFor(() => expect(within(row).getByRole("button", { name: "nanobot Computer Use: Fix connection", hidden: true })).toBeInTheDocument());
    expect(within(dialog).getByRole("status")).toHaveTextContent("Needs attention");
    expect(requestMutationMock.mock.calls.every(([action]) => action === "settings.mcp.test")).toBe(true);
  });

  it("keeps a newly saved MCP server when a closed Cua panel's check finishes", async () => {
    const preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: true,
      configured: true, available: true, status: "installed", required_fields: [], connection_summary: "",
      source: "preset", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: true, managed: true, mode: "observe",
      },
    };
    const payload = { presets: [preset], capabilities: [CUA_CAPABILITY, CUA_SETUP_CAPABILITY], installed_count: 1 };
    let finishCheck: (value: unknown) => void = () => {};
    const checking = new Promise(resolve => { finishCheck = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse(payload);
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    }));
    requestMutationMock.mockImplementation(async (action: string) => action === "settings.mcp.test" ? checking : {
      ...payload, installed_count: 2, presets: [...payload.presets, {
        ...preset, name: "notes-mcp", display_name: "Notes MCP", source: "custom", category: "custom", driver_setup: undefined,
      }], last_action: { ok: true },
    });
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "nanobot Computer Use: Manage" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.mcp.test", { name: "cua-driver", quiet: "true" }, 60_000));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Custom" }));
    fireEvent.change(screen.getByLabelText("Server name"), { target: { value: "notes-mcp" } });
    fireEvent.change(screen.getByLabelText("Command"), { target: { value: "notes-mcp" } });
    fireEvent.click(screen.getByRole("button", { name: "Save MCP server" }));
    await screen.findByRole("heading", { name: "Notes MCP" });
    await act(async () => { finishCheck(payload); });
    expect(screen.getByRole("heading", { name: "Notes MCP" })).toBeVisible();
  });

  it.each(["success", "failure"])("does not let a late check %s overwrite a newer disable", async (outcome) => {
    const preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: true,
      configured: true, available: true, status: "installed", required_fields: [], connection_summary: "",
      source: "preset", runtime_status: "connecting", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: true, managed: true, mode: "observe",
      },
    };
    const payload = { presets: [preset], capabilities: [CUA_CAPABILITY, CUA_SETUP_CAPABILITY], installed_count: 1 };
    let finishCheck: (value: unknown) => void = () => {};
    let failCheck: (error: Error) => void = () => {};
    const checking = new Promise((resolve, reject) => { finishCheck = resolve; failCheck = reject; });
    let reads = 0;
    let finishRead: (value: Response) => void = () => {};
    const delayedRead = new Promise<Response>(resolve => { finishRead = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return ++reads === 1 ? jsonResponse(payload) : delayedRead;
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    }));
    requestMutationMock.mockImplementation(async (action: string) => action === "settings.mcp.test" ? checking : {
      ...payload, installed_count: 0, presets: [{ ...preset, installed: false, configured: false,
        driver_setup: { ...preset.driver_setup!, mode: "off" } }], last_action: { ok: true },
    });
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "nanobot Computer Use: Manage" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.mcp.test", { name: "cua-driver", quiet: "true" }, 60_000));
    await waitFor(() => expect(reads).toBe(2), { timeout: 2000 });
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    await screen.findByRole("button", { name: "Allow viewing & connect" });
    await act(async () => {
      if (outcome === "success") finishCheck({ ...payload, last_action: { ok: true, driver_check: { connected: true, accessibility: true, screen_recording: true } } });
      else failCheck(new Error("Late check failed"));
      finishRead(jsonResponse(payload)); // The stale catalog read is also discarded.
    });
    expect(screen.getByRole("button", { name: "Allow viewing & connect" })).toBeEnabled();
    expect(screen.queryByText("Late check failed")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
  });
});
