import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CUA_CAPABILITY, CUA_SETUP_CAPABILITY } from "@/components/settings/system/CuaDriverSetupPanel";
import { setAppLanguage } from "@/i18n";
import type { McpPresetInfo } from "@/lib/types";
import { installSettingsViewTestHooks, jsonResponse, renderSettingsView, requestMutationMock, settingsPayload } from "@/tests/settings-test-utils";

describe("Cua Driver through Apps settings", () => {
  installSettingsViewTestHooks();

  it.each([
    { failed: ["linear"], message: "MCP config reloaded, but some servers did not connect: linear", localError: null },
    { failed: ["linear", "cua-driver"], message: "MCP config reloaded, but some servers did not connect: linear, cua-driver", localError: "Computer Use: Connection failed." },
    { failed: undefined, message: "Could not reload MCP config.", localError: "Could not reload MCP config." },
  ])("scopes enable feedback to Computer Use while preserving reload diagnostics ($message)", async ({ failed, message, localError }) => {
    let preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: false,
      configured: false, available: false, status: "not_installed", required_fields: [], connection_summary: "",
      source: "preset", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: true, managed: true, mode: "off",
      },
    };
    const payload = () => ({ presets: [preset], capabilities: [CUA_CAPABILITY], installed_count: Number(preset.configured) });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse(payload());
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return jsonResponse({});
    }));
    requestMutationMock.mockImplementation(async () => {
      preset = { ...preset, configured: true, installed: true, runtime_status: localError ? "failed" : "connected",
        driver_setup: { ...preset.driver_setup!, mode: "observe" } };
      return { ...payload(), last_action: { ok: true, message: `Computer Use enabled. ${message}` },
        hot_reload: { ok: false, failed, message, requires_restart: !failed } };
    });
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP", exact: true }));
    fireEvent.click(await screen.findByRole("button", { name: "Computer Use", exact: true }));
    const dialog = screen.getByRole("dialog", { name: "Computer Use" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Allow viewing & connect" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Disable" })).toBeEnabled());
    if (localError) expect(within(dialog).getByRole("alert")).toHaveTextContent(localError);
    else expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/linear/)).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.getByText(message)).toBeVisible();
  });

  it("does not carry another MCP's failed action into Computer Use setup", async () => {
    const preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: false,
      configured: false, available: false, status: "not_installed", required_fields: [], connection_summary: "",
      source: "preset", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: true, managed: true, mode: "off",
      },
    };
    const linear: McpPresetInfo = { ...preset, name: "linear", display_name: "Linear", source: "custom",
      driver_setup: undefined, installed: true, configured: true, available: true, runtime_status: "failed" };
    const payload = { presets: [preset, linear], capabilities: [CUA_CAPABILITY], installed_count: 1 };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse(payload);
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return jsonResponse({});
    }));
    requestMutationMock.mockRejectedValueOnce(new Error("Linear could not connect"));
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP", exact: true }));
    fireEvent.click(await screen.findByRole("button", { name: "Manage Linear" }));
    const linearDialog = screen.getByRole("dialog", { name: "Linear" });
    fireEvent.click(within(linearDialog).getByRole("tab", { name: "Connection" }));
    fireEvent.click(within(linearDialog).getByRole("button", { name: "Reconnect" }));
    await screen.findByText("Linear could not connect");
    fireEvent.click(screen.getByRole("button", { name: "Computer Use", exact: true }));
    const dialog = screen.getByRole("dialog", { name: "Computer Use" });
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Allow viewing & connect" })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.getByText("Linear could not connect")).toBeVisible();
  });

  it("keeps app names and descriptions in English while localizing interface actions", async () => {
    const preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "Computer use", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: false,
      configured: false, available: false, status: "not_installed", required_fields: [], connection_summary: "",
      source: "preset", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: false, managed: true, mode: "off", permission_app: "CuaDriver",
      },
    };
    const apps = [
      { name: "comfyui", display_name: "ComfyUI", description: "AI image generation workflow management via ComfyUI REST API" },
      { name: "dify-workflow", display_name: "Dify Workflow", description: "CLI-Anything wrapper for the Dify workflow DSL editor" },
      { name: "external-app", display_name: "External app", description: "Description supplied by the external catalog" },
    ].map(app => ({ ...app, category: "workflow", source: "harness", requires: "", entry_point: app.name,
      install_supported: true, installed: false, available: false, status: "not_installed", skill_installed: false }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse({ presets: [preset], capabilities: [CUA_CAPABILITY], installed_count: 0 });
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps, installed_count: 0 });
      return jsonResponse({});
    }));
    await setAppLanguage("zh-CN");
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "应用", exact: true }));
    expect(await screen.findByText(apps[0].description)).toBeVisible();
    expect(screen.getByText(apps[1].description)).toBeVisible();
    expect(screen.getByText("Description supplied by the external catalog")).toBeVisible();
    expect(screen.getAllByRole("heading", { level: 3 }).map(heading => heading.textContent)).toEqual([
      "ComfyUI", "Computer Use", "Dify Workflow", "External app",
    ]);

    const search = screen.getByPlaceholderText("搜索工具");
    fireEvent.change(search, { target: { value: "image generation" } });
    expect(screen.getByRole("heading", { name: "ComfyUI" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Dify Workflow" })).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "Computer Use" } });
    expect(screen.getByRole("heading", { name: "Computer Use" })).toBeVisible();
    expect(screen.getByText("Let nanobot observe and operate your computer.")).toBeVisible();
    const install = screen.getByRole("button", { name: "Computer Use: 安装" });
    expect(install).toBeVisible();
    expect(install).toHaveTextContent(/^$/);
    expect(install).toHaveAttribute("title", "Computer Use: 安装");
    expect(install).toHaveAttribute("aria-haspopup", "dialog");
    install.focus();
    fireEvent.click(install);
    const setup = screen.getByRole("dialog", { name: "Computer Use" });
    expect(within(setup).getByRole("button", { name: "下载并安装" })).toBeEnabled();
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(within(setup).getByRole("button", { name: "关闭" }));
    await waitFor(() => expect(install).toHaveFocus());
    fireEvent.change(search, { target: { value: "computer" } });
    fireEvent.click(screen.getByRole("button", { name: "Computer Use", exact: true }));
    const dialog = screen.getByRole("dialog", { name: "Computer Use" });
    expect(within(dialog).getByText("Let nanobot observe and operate your computer.")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "下载并安装" })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "总览" }));
    expect(within(dialog).getByText("由 Cua Driver 驱动 · nanobot 集成")).toBeVisible();
    await act(() => setAppLanguage("en"));
    expect(screen.getByRole("dialog", { name: "Computer Use" })).toBeVisible();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

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
    let finishInstall!: () => void;
    const download = new Promise<void>(resolve => { finishInstall = resolve; });
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.install") {
        await download;
        preset = { ...preset, driver_setup: { ...preset.driver_setup!, installed: true } };
      }
      if (action === "settings.mcp.enable") preset = { ...preset, configured: true, installed: true, runtime_status: "connected", driver_setup: { ...preset.driver_setup!, mode: "observe" } };
      if (action === "settings.mcp.disable") preset = { ...preset, configured: false, installed: false, driver_setup: { ...preset.driver_setup!, mode: "off" } };
      return { ...payload(), requires_restart: false, last_action: { ok: true, message: "Done" } };
    });
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    const row = (await screen.findByRole("heading", { name: "Computer Use" })).closest("article")!;
    fireEvent.click(within(row).getByRole("button", { name: "Computer Use" }));
    let dialog = screen.getByRole("dialog", { name: "Computer Use" });
    expect(within(dialog).getByRole("heading", { name: "See what’s on screen" })).toBeInTheDocument();
    expect(requestMutationMock).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("region", { name: "Connection" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Overview" }));
    const info = within(dialog).getByRole("dialog", { name: "Overview" });
    expect(within(info).getByText("Powered by Cua Driver · Integrated by nanobot")).toBeVisible();
    expect(info.contains(document.activeElement)).toBe(true);
    expect(within(info).getByText(/Downloads the official pinned release/).closest("[inert]")).not.toBeNull();
    fireEvent.click(within(info).getByRole("button", { name: "Installation details" }));
    expect(within(info).getByText(/Downloads the official pinned release/)).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "Download & install" })).not.toBeInTheDocument();
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(within(info).getByRole("button", { name: "Close", exact: true }));
    expect(within(dialog).getByRole("button", { name: "Download & install" })).toBeEnabled();
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Overview" })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "Download & install" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith("settings.mcp.install", {
      name: "cua-driver", consent: `${CUA_CAPABILITY}:install`,
    }, 660_000));
    expect(within(dialog).getByRole("button", { name: "Installing…" })).toBeDisabled();
    expect(within(dialog).getByText(/Downloading and verifying/)).toBeVisible();
    expect(screen.getByRole("dialog", { name: "Computer Use" })).toBe(dialog);
    expect(within(dialog).queryByRole("radio")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    const reopen = within(row).getByRole("button", { name: "Computer Use: Installing…" });
    expect(reopen).toBeEnabled();
    expect(reopen).toHaveAttribute("aria-busy", "true");
    fireEvent.click(reopen);
    dialog = screen.getByRole("dialog", { name: "Computer Use" });
    expect(within(dialog).getByRole("button", { name: "Installing…" })).toBeDisabled();
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    await act(async () => finishInstall());
    fireEvent.click(await screen.findByRole("radio", { name: "View & control" }));
    expect(screen.getByRole("dialog", { name: "Computer Use" })).toBe(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Overview" }));
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(within(dialog).queryByRole("radio")).not.toBeInTheDocument();
    fireEvent.keyDown(within(dialog).getByRole("dialog", { name: "Overview" }), { key: "Escape" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Overview" })).toHaveFocus());
    expect(screen.getByRole("dialog", { name: "Computer Use" })).toBe(dialog);
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
    expect(within(row).getByRole("button", { name: "Computer Use: Connect" })).toBeInTheDocument();
    expect(within(row).getByText("Access off")).toBeVisible();
  });

  it("keeps setup open when disabling from Ready, then returns focus to the catalog", async () => {
    let preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: true,
      configured: true, available: true, status: "installed", required_fields: [], connection_summary: "",
      source: "preset", runtime_status: "connected", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: true, managed: true, mode: "observe",
      },
    };
    const payload = () => ({ presets: [preset], capabilities: [CUA_CAPABILITY], installed_count: Number(preset.configured) });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse(payload());
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return jsonResponse({});
    }));
    requestMutationMock.mockImplementation(async () => {
      preset = { ...preset, configured: false, installed: false, runtime_status: "disconnected", driver_setup: { ...preset.driver_setup!, mode: "off" } };
      return { ...payload(), last_action: { ok: true } };
    });
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "Ready", exact: true }));
    const opener = await screen.findByRole("button", { name: "Computer Use", exact: true });
    opener.focus();
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Computer Use" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Disable" }));
    await within(dialog).findByText("Installed · access off");
    expect(screen.getByRole("dialog", { name: "Computer Use" })).toBe(dialog);
    expect(within(dialog).getByRole("button", { name: "Allow viewing & connect" })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.getByPlaceholderText("Search tools")).toHaveFocus());
    expect(screen.queryByRole("heading", { name: "Computer Use" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "MCP", exact: true }));
    expect(screen.getByRole("button", { name: "Computer Use: Connect" })).toBeEnabled();
  });

  it.each(["enable", "disable"])("refreshes persisted access after a native %s failure", async (action) => {
    let configured = action === "disable";
    const payload = () => ({ presets: [{
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: configured,
      configured, available: false, status: "installed", required_fields: [], connection_summary: "",
      source: "preset", runtime_status: "failed", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: true, managed: true, mode: configured ? "observe" : "off",
      },
    }], capabilities: [CUA_CAPABILITY], installed_count: Number(configured) });
    const reads = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse(payload());
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", reads);
    requestMutationMock.mockImplementation(async () => {
      configured = action === "enable"; // Configuration persisted before the native operation.
      throw new Error("Native driver could not finish. Check the gateway computer.");
    });
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "Computer Use", exact: true }));
    const dialog = screen.getByRole("dialog", { name: "Computer Use" });
    fireEvent.click(within(dialog).getByRole("button", { name: action === "enable" ? "Allow viewing & connect" : "Disable" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: action === "enable" ? "Disable" : "Allow viewing & connect" })).toBeEnabled());
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Native driver could not finish");
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(reads.mock.calls.filter(([path]) => path === "/api/settings/mcp-presets")).toHaveLength(2);
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
    const row = (await screen.findByRole("heading", { name: "Computer Use" })).closest("article")!;
    expect(within(row).getByText("Enabled")).toBeVisible();
    expect(within(row).queryByText("Permissions pending")).not.toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "Computer Use: Manage" }));
    const dialog = screen.getByRole("dialog", { name: "Computer Use" });
    await waitFor(() => expect(within(row).getByRole("button", { name: "Computer Use: Continue setup", hidden: true })).toBeInTheDocument());
    expect(within(row).getByRole("button", { name: "Computer Use: Continue setup", hidden: true })).toHaveTextContent("Continue setup");
    expect(within(dialog).getByRole("status")).toHaveTextContent("Permissions pending");
    expect(within(dialog).getByRole("button", { name: "Open Accessibility settings" })).toBeVisible();
    grantsReady = true;
    fireEvent.click(within(dialog).getByRole("button", { name: "Check connection" }));
    await waitFor(() => expect(within(dialog).getByRole("region", { name: "Gateway computer" })).toHaveTextContent("Connected"));
    expect(within(row).getByText("Connected")).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: /Open .* settings/ })).not.toBeInTheDocument();
    connected = false;
    fireEvent.click(within(dialog).getByRole("button", { name: "Connection details" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Check connection" }));
    await waitFor(() => expect(within(row).getByRole("button", { name: "Computer Use: Fix connection", hidden: true })).toBeInTheDocument());
    expect(within(row).getByRole("button", { name: "Computer Use: Fix connection", hidden: true })).toHaveTextContent("Fix connection");
    expect(within(dialog).getByRole("region", { name: "Gateway computer" })).toHaveTextContent("Needs attention");
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
    fireEvent.click(await screen.findByRole("button", { name: "Computer Use: Manage" }));
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

  it("keeps manual check outcomes inside setup across silent polls, failure and retry", async () => {
    const preset: McpPresetInfo = {
      name: "cua-driver", display_name: "Cua Driver", category: "computer", description: "", docs_url: "",
      transport: "stdio", requires: "", note: "", install_supported: true, installed: true,
      configured: true, available: true, status: "installed", required_fields: [], connection_summary: "",
      source: "preset", runtime_status: "connected", driver_setup: {
        schema: 1, version: "0.33.4", platform: "Darwin", machine: "remote-mac",
        supported: true, installed: true, managed: true, mode: "observe",
      },
    };
    const payload = { presets: [preset], capabilities: [CUA_CAPABILITY, CUA_SETUP_CAPABILITY], installed_count: 1 };
    const result = (granted: boolean | null) => ({ ...payload, last_action: {
      ok: true, message: "Connection checked", driver_check: {
        connected: granted === true, accessibility: granted, screen_recording: granted, capture_verified: false,
      },
    } });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/mcp-presets") return jsonResponse(payload);
      if (String(input) === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      return jsonResponse({});
    }));
    requestMutationMock.mockResolvedValue(result(null));
    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Computer Use: Manage" }));
    const dialog = screen.getByRole("dialog", { name: "Computer Use" });
    await within(dialog).findByRole("button", { name: "Open Accessibility settings" });
    expect(within(dialog).queryByRole("status", { name: "Manual check result" })).not.toBeInTheDocument();

    let finish!: (payload: unknown) => void;
    requestMutationMock.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Check connection" }));
    expect(within(dialog).getByRole("button", { name: "Checking…" })).toBeDisabled();
    await act(async () => finish(result(null)));
    const receipt = within(dialog).getByRole("status", { name: "Manual check result" });
    expect(receipt).toBeVisible();
    expect(receipt).toHaveTextContent("System permissions could not be confirmed.");
    expect(receipt).toHaveTextContent("This check does not verify screen capture or model vision.");
    expect(screen.queryByText("Connection checked")).not.toBeInTheDocument();

    requestMutationMock.mockResolvedValue(result(true));
    const beforePoll = requestMutationMock.mock.calls.length;
    fireEvent.focus(window);
    await waitFor(() => expect(requestMutationMock.mock.calls.length).toBeGreaterThan(beforePoll));
    await waitFor(() => expect(within(dialog).getByRole("region", { name: "Gateway computer" })).toHaveTextContent("Connected"));
    expect(receipt).toHaveTextContent("System permissions could not be confirmed.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Connection details" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Check connection" }));
    await waitFor(() => expect(within(dialog).getByRole("status", { name: "Manual check result" })).toHaveTextContent("Connected. Return to chat"));

    requestMutationMock.mockRejectedValueOnce(new Error("Gateway timed out"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Check connection" }));
    const failure = await within(dialog).findByRole("alert", { name: "Manual check result" });
    expect(failure).toHaveTextContent("The check could not finish. Please retry.");
    expect(failure).toHaveTextContent("Gateway timed out");
    expect(within(dialog).getAllByRole("alert")).toHaveLength(1);
    const beforeRecovery = requestMutationMock.mock.calls.length;
    fireEvent.focus(window);
    await waitFor(() => expect(requestMutationMock.mock.calls.length).toBeGreaterThan(beforeRecovery));
    expect(failure).toBeVisible(); // Background success cannot erase the user's failed receipt.
    fireEvent.click(await within(dialog).findByRole("button", { name: "Check connection" }));
    await waitFor(() => expect(within(dialog).getByRole("status", { name: "Manual check result" })).toHaveTextContent("Connected. Return to chat"));
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
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
    fireEvent.click(await screen.findByRole("button", { name: "Computer Use: Manage" }));
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
