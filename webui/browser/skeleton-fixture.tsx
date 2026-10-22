import { useState } from "react";

import { FilePreviewPanelView } from "@/components/FilePreviewPanelView";
import { SkillsCatalogSettings } from "@/components/settings/SkillsCatalogSettings";
import { SkillsMarketplace } from "@/components/settings/SkillsMarketplace";
import { ModelIdPicker } from "@/components/settings/shared/ModelControls";
import { AppsCatalogSettings, DEFAULT_CUSTOM_MCP_FORM } from "@/components/settings/system/AppsSettings";
import { ChannelsSettings } from "@/components/settings/system/ChannelsSettings";
import { McpManagementDialog } from "@/components/settings/system/McpManagementDialog";
import { WorkspaceProjectPicker } from "@/components/thread/WorkspaceControls";
import { settings } from "@/dev/gallery/settings";
import { useReadingTypography } from "@/hooks/useReadingTypography";
import { fetchWorkspaceDirectories } from "@/lib/api";
import type { McpPresetInfo, NanobotFeatureInfo } from "@/lib/types";

const noop = () => {};
const names = ["Search documentation", "Read repository", "List projects", "Inspect changes", "Review results", "Write notes"];
const preset: McpPresetInfo = {
  name: "docs", display_name: "Docs MCP", category: "Workflow", description: "Search the team knowledge base.",
  docs_url: "", requires: "", note: "", connection_summary: "https://example.com/mcp",
  transport: "streamableHttp", install_supported: true, installed: true, configured: true,
  available: true, status: "configured", required_fields: [], source: "custom",
};

export function SkeletonFixture({ surface, loading }: { surface: string; loading: boolean }) {
  useReadingTypography();
  const [model, setModel] = useState("");
  const [previewLoading, setPreviewLoading] = useState(loading);
  const feature: NanobotFeatureInfo = {
    name: "telegram", display_name: "Telegram", type: "channel", enabled: true, installed: true,
    configured: true, ready: true, install_supported: true, status: "enabled", requires_restart: false,
  };
  return <main className="settings-grid mx-auto w-full max-w-4xl p-4" data-testid="skeleton-fixture">
    {surface === "workspace" ? <WorkspaceProjectPicker isHero scope={{ project_path: "/srv/workspace", access_mode: "restricted" }}
      defaultScope={{ project_path: "/srv/workspace", access_mode: "restricted" }}
      controls={{ can_change_project: true, can_browse_directories: true }}
      onBrowseDirectories={(path, query, showHidden, allowPartial) => fetchWorkspaceDirectories("fixture", path, query, showHidden, allowPartial)}
      onChange={noop} /> : surface === "apps" || surface === "cli" ? <AppsCatalogSettings
      cliApps={{ apps: surface === "cli" && !loading ? names.map((name, index) => ({
        name: `app-${index}`, display_name: name, category: "Tools", description: "Search and inspect the project.",
        requires: "", source: "builtin", entry_point: `app-${index}`, install_supported: true, installed: false,
        available: false, status: "not_installed", skill_installed: false,
      })) : [], installed_count: 0 }}
      mcpPresets={loading ? null : { presets: names.map((name, index) => ({ ...preset, name: `docs-${index}`, display_name: name })), installed_count: 6 }}
      cliAppsLoading={loading} mcpPresetsLoading={loading} query="" filter={surface === "cli" ? "cli" : "mcp"}
      cliActionKey={null} mcpActionKey={null} mcpOAuthFlow={null} mcpOAuthPopupBlocked={false}
      mcpOAuthCallbackUrl="" mcpOAuthCompleting={false} mcpOAuthCallbackError={null}
      cliMessage={null} cliError={null} cliFocusName={null} mcpMessage={null} mcpError={null}
      mcpFieldValues={{}} customMcpForm={DEFAULT_CUSTOM_MCP_FORM} mcpConfigImport=""
      showBrandLogos={false} requiresRestartPending={false}
      onQueryChange={noop} onFilterChange={noop} onCliAction={noop} onMcpAction={noop}
      onMcpOAuthConnect={noop} onMcpOAuthCancel={noop} onMcpOAuthOpen={noop}
      onMcpOAuthCallbackUrlChange={noop} onMcpOAuthComplete={noop} onDismissStatus={noop}
      onBackToChat={noop} onMcpFieldChange={noop} onCustomMcpFormChange={noop}
      onMcpConfigImportChange={noop} onSaveCustomMcp={noop} onImportMcpConfig={noop} onMcpToolsChange={noop}
    /> : surface === "channels" ? <ChannelsSettings
      token="fixture" nanobotFeatures={loading ? null : { features: names.map((name, index) => ({ ...feature, name: `channel-${index}`, display_name: name })), enabled_count: 6, requires_restart: false }}
      loading={loading} actionKey={null} showBrandLogos={false} error={null} requiresRestartPending={false}
      onAction={noop} onFeaturesUpdate={noop} onDismissStatus={noop}
    /> : surface === "skills" ? <SkillsCatalogSettings loading={loading} skills={loading ? [] : names.map((name) => ({
      name, description: "Search, inspect and maintain the project.", source: "builtin", available: true, enabled: true,
    }))} /> : surface === "marketplace" ? <SkillsMarketplace installedSkills={[]} installing="" onInstallingChange={noop} />
      : surface === "models" || surface === "models-compact" ? <ModelIdPicker token="fixture"
        settings={{ ...settings, providers: settings.providers.map((provider) => provider.name === "openai" ? { ...provider, model_catalog: "official" } : provider) }}
        provider={surface === "models-compact" ? "openai" : "anthropic"}
        value={model} showProviderLogos={false} onChange={setModel} />
      : surface === "tools" ? <McpManagementDialog
        preset={{ ...preset, tool_names: loading ? [] : names.map((_, index) => `read_project_${index}`), tool_count: loading ? 0 : 6 }}
        values={{}} actionKey={loading ? "test:docs" : null} statusLabel="Connected" statusTone="success" tab="tools"
        icon={<span aria-hidden>DM</span>} onTabChange={noop} onOpenChange={noop} onFieldChange={noop}
        onAction={noop} onOAuthConnect={noop} onToolsChange={noop}
      /> : surface === "file" || surface === "markdown" ? <div className="flex flex-col" style={{ height: 560 }}><FilePreviewPanelView path={surface === "markdown" ? "/project/README.md" : "/project/main.py"}
        state={previewLoading ? { status: "loading" } : { status: "ready", payload: {
          kind: "text", path: surface === "markdown" ? "/project/README.md" : "/project/main.py", display_path: "project file", project_path: "/project", size: 400,
          language: surface === "markdown" ? "markdown" : "python", truncated: false,
          content: surface === "markdown" ? "# Project overview\n\nSearch, inspect and maintain the project.\n\nReview the results before making changes." : names.map((name, index) => `value_${index} = ${JSON.stringify(name)}`).join("\n"),
        } }} imageOpen={false} onImageOpenChange={noop} onImageError={noop} /></div> : null}
    {surface === "file" || surface === "markdown" ? <button data-testid="reload-preview" style={{ position: "fixed", bottom: 8, left: 8 }} onClick={() => setPreviewLoading(true)}>Reload preview</button> : null}
  </main>;
}
