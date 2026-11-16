import { useState } from "react";

import { AppsCatalogSettings, DEFAULT_CUSTOM_MCP_FORM } from "@/components/settings/system/AppsSettings";
import type { McpPresetInfo } from "@/lib/types";

const parameters = new URLSearchParams(location.search);
const unbrandedPlugin: McpPresetInfo = {
  name: "plugin-nanobot-workflows", display_name: "Nanobot Workflows", category: "Workflow",
  description: "Engineering workflows", docs_url: "", requires: "Project files", note: "", connection_summary: "",
  transport: "stdio", install_supported: false, installed: true, configured: true,
  enabled: true, available: true, status: "enabled", required_fields: [], source: "agent-plugin",
};

export function AppsFixture() {
  const noop = () => {};
  const managing = parameters.has("manage");
  const connectionLayout = parameters.has("connection-layout");
  const [connecting, setConnecting] = useState(false);
  const [actions, setActions] = useState<unknown[]>([]);
  const presets: McpPresetInfo[] = connectionLayout ? [
    {
      name: "linear", display_name: "Linear", category: "productivity", description: "Manage issues and projects",
      docs_url: "", transport: "streamableHttp", auth: "oauth", requires: "Linear account", note: "",
      install_supported: true, installed: parameters.has("runtime"), configured: parameters.has("runtime"),
      available: true, status: parameters.has("runtime") ? "configured" : "not_installed",
      required_fields: [], connection_summary: "", source: "preset",
      brand_color: "#5E6AD2", runtime_status: parameters.has("runtime") ? "connecting" : undefined,
    },
    ...["Notion", "GitHub", "Xmind"].map((name): McpPresetInfo => ({
      name: name.toLowerCase(), display_name: name, category: "productivity", description: `Connect your ${name} workspace`,
      docs_url: "", transport: "streamableHttp", auth: "oauth", requires: "", note: "",
      install_supported: true, installed: false, configured: false, available: true,
      status: "not_installed", required_fields: [], connection_summary: "", source: "preset",
    })),
  ] : managing ? [{
    name: "design", display_name: "Design MCP", category: "design", description: "Read design context",
    docs_url: "", transport: "streamableHttp", auth: "oauth", requires: "", note: "",
    install_supported: true, installed: false, configured: false, available: true,
    status: "not_installed", required_fields: [], connection_summary: "https://design.example/mcp", source: "preset",
  }] : [
    unbrandedPlugin,
    { ...unbrandedPlugin, name: "test-mcp", display_name: "Test MCP", source: "builtin", logo_url: "/missing-app-icon.svg" },
    { ...unbrandedPlugin, name: "brand-example", display_name: "Brand Example", source: "builtin", brand_color: "#5E6AD2" },
  ];
  return <main className="mx-auto max-w-4xl p-6" style={connectionLayout ? { maxWidth: 800 } : undefined}><AppsCatalogSettings
    cliApps={{ apps: [], installed_count: 0 }}
    mcpPresets={{ presets, installed_count: connectionLayout ? Number(parameters.has("runtime")) : managing ? 0 : 3 }}
    cliAppsLoading={false} mcpPresetsLoading={false} query="" filter={managing || connectionLayout ? "mcp" : "ready"}
    cliActionKey={null} mcpActionKey={null}
    mcpOAuthFlow={connecting ? { flow_id: "fixture", name: "linear", status: "authorization_required", expires_in: 300 } : null}
    mcpOAuthPopupBlocked={false}
    mcpOAuthCallbackUrl="" mcpOAuthCompleting={false} mcpOAuthCallbackError={null}
    cliMessage={null} cliError={null} cliFocusName={null} mcpMessage={null} mcpError={null}
    mcpFieldValues={{}} customMcpForm={DEFAULT_CUSTOM_MCP_FORM} mcpConfigImport=""
    showBrandLogos={parameters.get("logos") !== "hidden"} requiresRestartPending={false}
    onQueryChange={noop} onFilterChange={noop} onCliAction={noop}
    onMcpAction={(action, name, values) => setActions((prev) => [...prev, { action, name, values }])}
    onMcpOAuthConnect={(name, reset, values) => {
      setActions((prev) => [...prev, { action: "oauth", name, reset, values }]);
      if (connectionLayout) setConnecting(true);
    }}
    onMcpOAuthCancel={() => setConnecting(false)} onMcpOAuthOpen={noop}
    onMcpOAuthCallbackUrlChange={noop} onMcpOAuthComplete={noop} onDismissStatus={noop}
    onBackToChat={noop} onMcpFieldChange={noop} onCustomMcpFormChange={noop}
    onMcpConfigImportChange={noop} onSaveCustomMcp={noop} onImportMcpConfig={noop}
    onMcpToolsChange={noop}
  />{managing && <output data-testid="mcp-actions">{JSON.stringify(actions)}</output>}</main>;
}
