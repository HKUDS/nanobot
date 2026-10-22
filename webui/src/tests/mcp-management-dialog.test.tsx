import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  McpManagementDialog,
  type McpManagementTab,
} from "@/components/settings/system/McpManagementDialog";
import { createSystemSettingsActions } from "@/components/settings/system/createSystemSettingsActions";
import { useSystemSettingsState } from "@/components/settings/system/useSystemSettingsState";
import i18n from "@/i18n";
import { NanobotClient } from "@/lib/nanobot-client";
import type { McpPresetInfo, McpPresetsPayload } from "@/lib/types";
import {
  installSettingsViewTestHooks,
  jsonResponse,
  renderSettingsView,
  requestMutationMock,
  settingsPayload,
} from "@/tests/settings-test-utils";

const connectedPreset: McpPresetInfo = {
  name: "docs",
  display_name: "Docs MCP",
  category: "productivity",
  description: "Search and maintain the team knowledge base.",
  docs_url: "https://example.com/docs-mcp",
  transport: "streamableHttp",
  auth: null,
  requires: "",
  note: "",
  install_supported: true,
  installed: true,
  configured: true,
  available: true,
  status: "configured",
  runtime_status: "connected",
  required_fields: [],
  connection_summary: "https://mcp.example.com/mcp",
  tool_count: 3,
  tool_names: ["search_docs", "write_note", "list_sources"],
  enabled_tools: ["*"],
  checked_at: "2026-08-12T08:00:00Z",
  source: "custom",
};

describe("McpManagementDialog", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("keeps tool scope changes as a draft until Save changes", () => {
    const onToolsChange = vi.fn();
    renderDialog({ initialTab: "tools", onToolsChange });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    expect(dialog).toHaveClass("h-[min(34rem,calc(100dvh-2rem))]");
    expect(within(dialog).getByRole("tab", { name: /Tools/ })).toHaveAttribute("aria-selected", "true");
    expect(within(dialog).getByText("3 enabled")).toBeInTheDocument();
    expect(within(dialog).queryByText("Close")).not.toBeInTheDocument();

    const searchDocs = within(dialog).getByRole("checkbox", { name: /search_docs/ });
    expect(searchDocs).toBeChecked();
    fireEvent.click(searchDocs);

    expect(searchDocs).not.toBeChecked();
    expect(within(dialog).getByText("2 enabled")).toBeInTheDocument();
    expect(onToolsChange).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(onToolsChange).toHaveBeenCalledWith("docs", ["write_note", "list_sources"]);
  });

  it("searches the inventory and exposes connection management in the same modal", () => {
    const onAction = vi.fn();
    renderDialog({ initialTab: "tools", onAction });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search tools" }), {
      target: { value: "write" },
    });
    expect(within(dialog).getByRole("checkbox", { name: /write_note/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole("checkbox", { name: /search_docs/ })).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("tab", { name: "Connection" }));
    expect(within(dialog).getByText("https://mcp.example.com/mcp")).toBeInTheDocument();
    expect(within(dialog).getByText("Streamable HTTP")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Open docs" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Remove connection" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Reconnect" }));
    expect(onAction).toHaveBeenCalledWith("reconnect", "docs", {});
  });

  it.each(["streamableHttp", "sse"])("edits an existing %s proxy flag without restarting OAuth", (transport) => {
    const onAction = vi.fn();
    const { updateDialog } = renderDialog({
      initialTab: "connection", onAction,
      preset: { ...connectedPreset, transport, use_proxy: true },
    });
    const useProxy = screen.getByRole("switch", { name: "Use proxy" });
    expect(useProxy).toBeChecked();
    expect(screen.queryByRole("textbox", { name: /proxy/i })).not.toBeInTheDocument();
    fireEvent.click(useProxy);
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(onAction).toHaveBeenCalledWith("proxy", "docs", { use_proxy: "false" });
    updateDialog({ ...connectedPreset, transport, use_proxy: false });
    expect(useProxy).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });

  it("shows proxy guidance on demand without changing the connection draft", async () => {
    const onAction = vi.fn();
    renderDialog({ initialTab: "connection", onAction });
    expect(screen.queryByText("Uses the shared proxy in Advanced.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use proxy" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Uses the shared proxy in Advanced.");
    expect(onAction).not.toHaveBeenCalled();
    expect(screen.getByRole("switch", { name: "Use proxy" })).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });

  it("preserves the configured proxy flag when reconnecting OAuth", () => {
    const onOAuthConnect = vi.fn();
    renderDialog({
      initialTab: "connection", onOAuthConnect,
      preset: { ...connectedPreset, auth: "oauth", use_proxy: true },
    });
    expect(screen.getByRole("switch", { name: "Use proxy" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(onOAuthConnect).toHaveBeenCalledWith("docs", true, { use_proxy: "true" });
  });

  it("does not offer a proxy switch for stdio servers", () => {
    renderDialog({ initialTab: "connection", preset: { ...connectedPreset, transport: "stdio" } });
    expect(screen.queryByRole("switch", { name: "Use proxy" })).not.toBeInTheDocument();
  });

  it("loads tools on entry and supports refreshing the empty inventory", async () => {
    const onAction = vi.fn();
    renderDialog({
      initialTab: "tools",
      onAction,
      preset: { ...connectedPreset, tool_count: 0, tool_names: [], enabled_tools: ["*"] },
    });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    await waitFor(() => expect(onAction).toHaveBeenCalledWith("test", "docs"));
    expect(within(dialog).getByText("No tools available")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Refresh tools" }));
    expect(onAction).toHaveBeenCalledTimes(2);
  });

  it("shows a skeleton for the first inspection and keeps tools and draft selections during reinspection", () => {
    const emptyPreset = { ...connectedPreset, tool_count: 0, tool_names: [] };
    const { updateDialog } = renderDialog({
      initialTab: "tools",
      preset: emptyPreset,
      actionKey: "test:docs",
    });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    expect(within(dialog).getByRole("status", { name: "Loading tools…" })).toHaveAttribute("aria-busy", "true");
    expect(within(dialog).queryByRole("textbox", { name: "Search tools" })).not.toBeInTheDocument();
    expect(within(dialog).queryByText("No tools available")).not.toBeInTheDocument();

    updateDialog(connectedPreset);
    expect(within(dialog).queryByRole("status", { name: "Loading tools…" })).not.toBeInTheDocument();
    const searchDocs = within(dialog).getByRole("checkbox", { name: /search_docs/ });
    fireEvent.click(searchDocs);
    expect(searchDocs).not.toBeChecked();

    updateDialog({ ...connectedPreset, tool_names: [] }, "test:docs");
    expect(within(dialog).queryByRole("status", { name: "Loading tools…" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("checkbox", { name: /search_docs/ })).not.toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: /write_note/ })).toBeChecked();
    expect(within(dialog).getByText("2 enabled")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it.each([
    { error: undefined, message: "No tools available" },
    { error: "Inspection failed", message: "Inspection failed" },
  ])("offers recovery when inspection finishes with $message", ({ error, message }) => {
    const onAction = vi.fn();
    const emptyPreset = { ...connectedPreset, tool_count: 0, tool_names: [], error };
    const { updateDialog } = renderDialog({
      initialTab: "tools",
      preset: emptyPreset,
      actionKey: "test:docs",
      onAction,
    });

    const dialog = screen.getByRole("dialog", { name: "Docs MCP" });
    expect(within(dialog).getByRole("status", { name: "Loading tools…" })).toBeInTheDocument();
    updateDialog(emptyPreset);
    expect(within(dialog).queryByRole("status", { name: "Loading tools…" })).not.toBeInTheDocument();
    expect(within(dialog).getByText(message)).toBeInTheDocument();
    if (error) expect(within(dialog).getByRole("alert")).toHaveTextContent(error);
    fireEvent.click(within(dialog).getByRole("button", { name: "Refresh tools" }));
    expect(onAction).toHaveBeenLastCalledWith("test", "docs");
  });
});

function renderDialog({
  initialTab,
  onAction = vi.fn(),
  onToolsChange = vi.fn(),
  onOAuthConnect = vi.fn(),
  preset = connectedPreset,
  actionKey = null,
}: {
  initialTab: McpManagementTab;
  onAction?: ReturnType<typeof vi.fn>;
  onToolsChange?: ReturnType<typeof vi.fn>;
  onOAuthConnect?: ReturnType<typeof vi.fn>;
  preset?: McpPresetInfo;
  actionKey?: string | null;
}) {
  function Harness({ preset, actionKey }: { preset: McpPresetInfo; actionKey: string | null }) {
    const [tab, setTab] = useState(initialTab);
    const [values, setValues] = useState<Record<string, string>>({});
    return (
      <McpManagementDialog
        preset={preset}
        values={values}
        actionKey={actionKey}
        statusLabel="Connected"
        statusTone="success"
        tab={tab}
        icon={<span aria-hidden>DM</span>}
        onTabChange={setTab}
        onOpenChange={vi.fn()}
        onFieldChange={(_name, field, value) => setValues((prev) => ({ ...prev, [field]: value }))}
        onAction={onAction}
        onOAuthConnect={onOAuthConnect}
        onToolsChange={onToolsChange}
      />
    );
  }
  const view = render(<Harness preset={preset} actionKey={actionKey} />);
  return {
    ...view,
    updateDialog: (nextPreset: McpPresetInfo, nextActionKey: string | null = null) => {
      view.rerender(<Harness preset={nextPreset} actionKey={nextActionKey} />);
    },
  };
}

describe("MCP connection draft lifecycle", () => {
  installSettingsViewTestHooks();

  const metabasePreset: McpPresetInfo = {
    ...connectedPreset,
    name: "metabase",
    display_name: "Metabase",
    auth: "oauth",
    source: "preset",
    required_fields: [{
      name: "mcp_url", label: "MCP server URL", secret: false, required: true, configured: true,
    }],
  };

  it("reopens and reconnects without proxy after OAuth with proxy and a same-endpoint import", async () => {
    const endpoint = "https://app.xmind.com/api/mcp";
    let preset: McpPresetInfo = {
      ...connectedPreset,
      name: "xmind",
      display_name: "Xmind",
      auth: "oauth",
      source: "preset",
      installed: false,
      configured: false,
      available: false,
      status: "not_installed",
      runtime_status: undefined,
      connection_summary: "",
      use_proxy: false,
    };
    const importedConfig = JSON.stringify({
      mcpServers: { Xmind: { url: endpoint, auth: "oauth", useProxy: false } },
    });
    vi.stubGlobal("open", vi.fn(() => null));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [preset], installed_count: Number(preset.installed) });
      }
      if (url === "/api/settings/mcp-oauth/status?flow_id=flow-proxy") {
        preset = {
          ...preset,
          installed: true,
          configured: true,
          available: true,
          status: "configured",
          runtime_status: "connected",
          connection_summary: endpoint,
          use_proxy: true,
        };
        return jsonResponse({
          flow_id: "flow-proxy", name: "xmind", status: "connected", expires_in: 299,
        });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    }));
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.oauth_start") {
        return {
          flow_id: "flow-proxy", name: "xmind", status: "authorization_required", expires_in: 300,
          authorization_url: "https://accounts.xmind.test/authorize?state=proxy",
        };
      }
      if (action === "settings.mcp.import") {
        preset = { ...preset, use_proxy: false };
        return {
          presets: [preset], installed_count: 1,
          last_action: { ok: true, message: "Imported 1 MCP server(s)." },
        };
      }
      if (action === "settings.mcp.oauth_cancel") {
        return { flow_id: "flow-proxy", name: "xmind", status: "cancelled", expires_in: 299 };
      }
      throw new Error(`Unexpected mutation: ${action}`);
    });

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect Xmind" }));
    fireEvent.click(screen.getByRole("switch", { name: "Use proxy" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.oauth_start", { name: "xmind", use_proxy: "true" }, 30_000,
    ));
    await screen.findByRole("button", { name: "Manage Xmind" });

    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    fireEvent.click(screen.getByRole("button", { name: "Import mcp.json" }));
    const editor = screen.getByRole("dialog", { name: "Import mcp.json" });
    fireEvent.change(within(editor).getByRole("textbox", { name: "Import mcp.json" }), {
      target: { value: importedConfig },
    });
    await act(async () => fireEvent.click(within(editor).getByRole("button", { name: "Save" })));
    await act(async () => fireEvent.click(screen.getAllByRole("button", { name: "Import" })[1]));
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.import", { config: importedConfig }, 20_000,
    );

    fireEvent.click(screen.getByRole("button", { name: "Manage Xmind" }));
    fireEvent.click(screen.getByRole("tab", { name: "Connection" }));
    expect(screen.getByRole("switch", { name: "Use proxy" })).not.toBeChecked();
    expect(screen.getByText(endpoint)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.mcp.oauth_start", { name: "xmind", reset: true, use_proxy: "false" }, 30_000,
    ));
    const cancel = await screen.findByRole("button", { name: "Cancel" });
    await act(async () => fireEvent.click(cancel));
  });

  it("retires the consumed OAuth proxy draft only after success, preserving a failed attempt", async () => {
    const { result } = renderMcpActions();
    const drafts = { docs: { use_proxy: "true" }, metabase: { mcp_url: "https://analytics.example.com/mcp", use_proxy: "true" } };
    await act(async () => result.current.state.setMcpFieldValues(drafts));
    vi.stubGlobal("open", vi.fn(() => null));
    requestMutationMock.mockResolvedValueOnce({
      flow_id: "flow-failed", name: "docs", status: "failed", error: "Proxy connection failed", expires_in: 300,
    });

    await act(async () => result.current.actions.handleMcpOAuthConnect("docs", false, drafts.docs));
    expect(result.current.state.mcpError).toBe("Proxy connection failed");
    expect(result.current.state.mcpFieldValues).toEqual(drafts);

    requestMutationMock.mockResolvedValueOnce({
      flow_id: "flow-connected", name: "docs", status: "connected", expires_in: 300,
    });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      presets: [{ ...connectedPreset, auth: "oauth", use_proxy: true }], installed_count: 1,
    })));
    await act(async () => result.current.actions.handleMcpOAuthConnect("docs", false, drafts.docs));
    expect(result.current.state.mcpPresets?.presets[0].use_proxy).toBe(true);
    expect(result.current.state.mcpFieldValues).toEqual({ docs: {}, metabase: drafts.metabase });
  });

  it.each([true, false])("reconciles only accepted import names (mcpServers wrapper: %s)", async (wrapped) => {
    const { result } = renderMcpActions();
    const drafts = {
      metabase: { use_proxy: "true", mcp_url: "https://analytics.example.com/mcp" },
      docs: { use_proxy: "true" },
    };
    const servers = { Metabase: { url: metabasePreset.connection_summary, auth: "oauth", useProxy: false } };
    const config = JSON.stringify(wrapped ? { mcpServers: servers } : servers);
    await act(async () => {
      result.current.state.setMcpFieldValues(drafts);
      result.current.state.setMcpConfigImport(config);
    });
    requestMutationMock.mockRejectedValueOnce(new Error("Import could not be saved"));
    await act(async () => result.current.actions.handleImportMcpConfig());
    expect(result.current.state.mcpFieldValues).toEqual(drafts);
    expect(result.current.state.mcpConfigImport).toBe(config);

    requestMutationMock.mockResolvedValueOnce({
      presets: [{ ...metabasePreset, use_proxy: false }, connectedPreset],
      installed_count: 2,
      last_action: { ok: true, message: "Imported 1 MCP server(s)." },
    });
    await act(async () => result.current.actions.handleImportMcpConfig());
    expect(result.current.state.mcpFieldValues).toEqual({
      metabase: { mcp_url: drafts.metabase.mcp_url }, docs: drafts.docs,
    });
    expect(result.current.state.mcpConfigImport).toBe("");
  });

  it("reconciles a saved custom replacement even while its OAuth authorization is pending", async () => {
    const { result } = renderMcpActions();
    await act(async () => {
      result.current.state.setMcpFieldValues({
        metabase: { use_proxy: "true", mcp_url: "https://analytics.example.com/mcp" }, docs: { use_proxy: "true" },
      });
      result.current.state.setCustomMcpForm((prev) => ({
        ...prev, name: "Metabase", transport: "streamableHttp", auth: "oauth",
        url: metabasePreset.connection_summary, useProxy: false,
      }));
    });
    requestMutationMock.mockResolvedValueOnce({
      presets: [{ ...metabasePreset, configured: false, use_proxy: false, status: "authorization_required" }],
      installed_count: 1,
      last_action: { ok: true, message: "Saved MCP server metabase." },
      hot_reload: { ok: false, message: "Authorization required", failed: ["metabase"] },
    });
    await act(async () => result.current.actions.handleSaveCustomMcp());
    expect(result.current.state.mcpError).toBeNull();
    expect(result.current.state.mcpFieldValues).toEqual({
      metabase: { mcp_url: "https://analytics.example.com/mcp" }, docs: { use_proxy: "true" },
    });
  });

  it("retains failed proxy drafts, then retires applied or removed flags without discarding other edits", async () => {
    const { result } = renderMcpActions();
    const drafts = {
      metabase: { use_proxy: "true", mcp_url: "https://analytics.example.com/mcp" }, docs: { use_proxy: "true" },
    };
    await act(async () => result.current.state.setMcpFieldValues(drafts));
    const payload: McpPresetsPayload = { presets: [{ ...metabasePreset, use_proxy: true }], installed_count: 1 };
    requestMutationMock.mockRejectedValueOnce(new Error("Proxy could not be saved"));
    await act(async () => result.current.actions.handleMcpPresetAction("proxy", "metabase", { use_proxy: "true" }));
    expect(result.current.state.mcpFieldValues).toEqual(drafts);

    requestMutationMock.mockResolvedValueOnce(payload);
    await act(async () => result.current.actions.handleMcpPresetAction("proxy", "metabase", { use_proxy: "true" }));
    expect(result.current.state.mcpFieldValues).toEqual({
      metabase: { mcp_url: drafts.metabase.mcp_url }, docs: drafts.docs,
    });

    await act(async () => result.current.state.setMcpFieldValues(drafts));
    requestMutationMock.mockResolvedValueOnce({
      presets: [], installed_count: 0, last_action: { ok: true, removed: true, message: "Removed MCP server metabase." },
    });
    await act(async () => result.current.actions.handleMcpPresetAction("remove", "metabase"));
    expect(result.current.state.mcpFieldValues).toEqual({
      metabase: { mcp_url: drafts.metabase.mcp_url }, docs: drafts.docs,
    });
  });
});

function renderMcpActions() {
  const client = new NanobotClient({ url: "ws://example.test" });
  client.requestMutation = requestMutationMock;
  return renderHook(() => {
    const state = useSystemSettingsState();
    const actions = createSystemSettingsActions({
      state,
      featureCatalog: [],
      client,
      token: "tok",
      getToken: () => "tok",
      t: i18n.t,
      applyPayload: vi.fn(),
      maybeRestartHostEngine: vi.fn(),
      setPendingRestartSections: vi.fn(),
      refreshAutomations: vi.fn(),
    });
    return { state, actions };
  });
}
