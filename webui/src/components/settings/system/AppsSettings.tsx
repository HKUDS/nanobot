import {
  forwardRef,
  useId,
  useMemo,
  useState,
  type ComponentPropsWithoutRef,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Database,
  ExternalLink,
  Loader2,
  PauseCircle,
  PlayCircle,
  Plus,
  RotateCcw,
  Search,
  Server,
  SlidersHorizontal,
  TriangleAlert,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DismissibleStatusMessage,
  RestartRequiredNotice,
  SETTINGS_SEARCH_INPUT_CLASS,
  SettingsSectionTitle,
} from "@/components/settings/shared/SettingsControls";
import {
  McpManagementDialog,
  type McpManagementTab,
} from "@/components/settings/system/McpManagementDialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { isGenericRepositoryLogoUrl, logoFallbackUrls } from "@/lib/provider-brand";
import type {
  CliAppInfo,
  CliAppsPayload,
  McpOAuthFlowPayload,
  McpPresetInfo,
  McpPresetsPayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export type AppsKindFilter = "ready" | "cli" | "mcp";
type AppsCatalogItem =
  | { id: string; kind: "cli"; app: CliAppInfo }
  | { id: string; kind: "mcp"; preset: McpPresetInfo };
type CustomMcpTransport = "stdio" | "streamableHttp" | "sse";
type CustomMcpAuth = "none" | "oauth" | "headers";
export const CLI_APPS_REFRESH_RETRY_MS = 2_000;
export const CLI_APPS_REFRESH_MAX_RETRIES = 30;

export interface CustomMcpForm {
  name: string;
  transport: CustomMcpTransport;
  auth: CustomMcpAuth;
  command: string;
  args: string;
  url: string;
  env: string;
  headers: string;
  toolTimeout: string;
}

export const DEFAULT_CUSTOM_MCP_FORM: CustomMcpForm = {
  name: "",
  transport: "stdio",
  auth: "none",
  command: "",
  args: "",
  url: "",
  env: "",
  headers: "",
  toolTimeout: "30",
};

export function AppsCatalogSettings({
  cliApps,
  mcpPresets,
  cliAppsLoading,
  mcpPresetsLoading,
  query,
  filter,
  cliActionKey,
  mcpActionKey,
  mcpOAuthFlow,
  mcpOAuthPopupBlocked,
  mcpOAuthCallbackUrl,
  mcpOAuthCompleting,
  mcpOAuthCallbackError,
  cliMessage,
  cliError,
  cliFocusName,
  mcpMessage,
  mcpError,
  mcpFieldValues,
  customMcpForm,
  mcpConfigImport,
  showBrandLogos,
  requiresRestartPending,
  onQueryChange,
  onFilterChange,
  onCliAction,
  onMcpAction,
  onMcpOAuthConnect,
  onMcpOAuthCancel,
  onMcpOAuthOpen,
  onMcpOAuthCallbackUrlChange,
  onMcpOAuthComplete,
  onDismissStatus,
  onBackToChat,
  onMcpFieldChange,
  onCustomMcpFormChange,
  onMcpConfigImportChange,
  onSaveCustomMcp,
  onImportMcpConfig,
  onMcpToolsChange,
  onRestart,
  isRestarting,
}: {
  cliApps: CliAppsPayload | null;
  mcpPresets: McpPresetsPayload | null;
  cliAppsLoading: boolean;
  mcpPresetsLoading: boolean;
  query: string;
  filter: AppsKindFilter;
  cliActionKey: string | null;
  mcpActionKey: string | null;
  mcpOAuthFlow: McpOAuthFlowPayload | null;
  mcpOAuthPopupBlocked: boolean;
  mcpOAuthCallbackUrl: string;
  mcpOAuthCompleting: boolean;
  mcpOAuthCallbackError: string | null;
  cliMessage: string | null;
  cliError: string | null;
  cliFocusName: string | null;
  mcpMessage: string | null;
  mcpError: string | null;
  mcpFieldValues: Record<string, Record<string, string>>;
  customMcpForm: CustomMcpForm;
  mcpConfigImport: string;
  showBrandLogos: boolean;
  requiresRestartPending: boolean;
  onQueryChange: (value: string) => void;
  onFilterChange: (value: AppsKindFilter) => void;
  onCliAction: (action: "install" | "update" | "uninstall" | "test", name: string) => void;
  onMcpAction: (action: "enable" | "disable" | "remove" | "test" | "reconnect", name: string, values?: Record<string, string>) => void;
  onMcpOAuthConnect: (name: string, reset?: boolean) => void;
  onMcpOAuthCancel: () => void;
  onMcpOAuthOpen: () => void;
  onMcpOAuthCallbackUrlChange: (value: string) => void;
  onMcpOAuthComplete: () => void;
  onDismissStatus: () => void;
  onBackToChat: () => void;
  onMcpFieldChange: (presetName: string, fieldName: string, value: string) => void;
  onCustomMcpFormChange: Dispatch<SetStateAction<CustomMcpForm>>;
  onMcpConfigImportChange: (value: string) => void;
  onSaveCustomMcp: () => void;
  onImportMcpConfig: () => void;
  onMcpToolsChange: (name: string, enabledTools: string[]) => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const filterOptions = [
    { value: "ready", label: tx("settings.apps.filterAll", "Ready") },
    { value: "cli", label: tx("settings.apps.filterCli", "Apps") },
    { value: "mcp", label: tx("settings.apps.filterMcp", "MCP") },
  ];
  const normalizedQuery = query.trim().toLowerCase();
  const items: AppsCatalogItem[] = [
    ...(cliApps?.apps ?? []).map((app) => ({ id: `cli:${app.name}`, kind: "cli" as const, app })),
    ...(mcpPresets?.presets ?? []).map((preset) => ({
      id: `mcp:${preset.name}`,
      kind: "mcp" as const,
      preset,
    })),
  ]
    .filter((item) => {
      if (normalizedQuery) return appsSearchText(item).includes(normalizedQuery);
      if (filter === "ready") return appsReady(item);
      if (filter === "cli") {
        return item.kind === "cli" || item.preset.source === "agent-plugin";
      }
      return item.kind === "mcp" && item.preset.source !== "agent-plugin";
    })
    .sort((left, right) => {
      const rank = Number(!appsReady(left)) - Number(!appsReady(right));
      return rank || appsTitle(left).localeCompare(appsTitle(right));
    });
  const focusedApp = cliFocusName
    ? (cliApps?.apps ?? []).find((app) => app.name === cliFocusName && app.installed)
    : null;
  const loading =
    (cliAppsLoading || mcpPresetsLoading) &&
    !cliApps &&
    !mcpPresets;
  const cliAppCount = cliApps?.apps.length ?? 0;
  const emptyTitle = normalizedQuery
    ? tx("settings.apps.empty", "No tools match your search.")
    : filter === "cli"
      ? tx("settings.apps.emptyApps", "No apps available.")
      : filter === "mcp"
        ? tx("settings.apps.emptyIntegrations", "No MCP tools available.")
        : tx("settings.apps.emptyReady", "No tools are ready yet.");
  const emptyBrowseTarget: AppsKindFilter | null = normalizedQuery
    ? null
    : filter === "cli"
      ? "mcp"
      : filter === "mcp"
        ? (cliAppCount ? "cli" : null)
        : cliAppCount
          ? "cli"
          : "mcp";
  const statusMessage =
    cliError ||
    mcpError ||
    (!focusedApp ? cliMessage || mcpMessage : null);
  const statusIsError = Boolean(cliError || mcpError);
  const oauthStatusAnnouncement = mcpOAuthFlow
    ? mcpOAuthStatusText(
      mcpOAuthFlow.status,
      mcpOAuthPopupBlocked,
      tx,
      mcpOAuthFlow.completion_input,
    )
    : "";
  return (
    <div className="space-y-7">
      <div role="status" className="sr-only">{oauthStatusAnnouncement}</div>
      <section className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder={tx("settings.apps.searchPlaceholder", "Search Apps")}
              className={cn(
                "h-12 pl-11 text-[15px]",
                SETTINGS_SEARCH_INPUT_CLASS,
              )}
            />
          </div>
          <SegmentedControl
            value={filter}
            options={filterOptions}
            onChange={(value) => onFilterChange(value as AppsKindFilter)}
          />
        </div>
      </section>

      {statusMessage ? (
        <DismissibleStatusMessage
          message={statusMessage}
          isError={statusIsError}
          onDismiss={onDismissStatus}
        />
      ) : null}

      {focusedApp ? (
        <CliAppReadyPanel app={focusedApp} showBrandLogos={showBrandLogos} onBackToChat={onBackToChat} />
      ) : null}

      {requiresRestartPending ? (
        <RestartRequiredNotice
          message={tx("settings.apps.restartRequired", "Restart nanobot to apply updated apps and MCP tools.")}
          onRestart={onRestart}
          isRestarting={isRestarting}
        />
      ) : null}

      <section className="rounded-panel bg-settings-surface px-3 py-3 sm:px-4">
        <div className="flex items-center justify-between border-b border-border/45 pb-3">
          <SettingsSectionTitle>
            {filter === "mcp"
              ? tx("settings.apps.mcpTools", "MCP tools")
              : tx("settings.apps.featured", "Tools")}
          </SettingsSectionTitle>
          <span className="rounded-full bg-muted px-2.5 py-1 text-[12px] font-medium text-muted-foreground">
            {items.length}
          </span>
        </div>
        {loading ? (
          <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
            {tx("settings.apps.loading", "Loading Apps...")}
          </div>
        ) : items.length ? (
          <div className="grid grid-cols-1 gap-x-10 gap-y-1 py-3 xl:grid-cols-2">
            {items.map((item) =>
              item.kind === "cli" ? (
                <CliAppsCatalogRow
                  key={item.id}
                  app={item.app}
                  actionKey={cliActionKey}
                  showBrandLogos={showBrandLogos}
                  onAction={onCliAction}
                />
              ) : (
                <McpAppsCatalogRow
                  key={item.id}
                  preset={item.preset}
                  values={mcpFieldValues[item.preset.name] ?? {}}
                  actionKey={mcpActionKey}
                  oauthFlow={mcpOAuthFlow?.name === item.preset.name ? mcpOAuthFlow : null}
                  oauthPopupBlocked={mcpOAuthPopupBlocked}
                  oauthCallbackUrl={mcpOAuthCallbackUrl}
                  oauthCompleting={mcpOAuthCompleting}
                  oauthCallbackError={mcpOAuthCallbackError}
                  showBrandLogos={showBrandLogos}
                  showTypeBadge={filter !== "mcp"}
                  onFieldChange={onMcpFieldChange}
                  onAction={onMcpAction}
                  onOAuthConnect={onMcpOAuthConnect}
                  onOAuthCancel={onMcpOAuthCancel}
                  onOAuthOpen={onMcpOAuthOpen}
                  onOAuthCallbackUrlChange={onMcpOAuthCallbackUrlChange}
                  onOAuthComplete={onMcpOAuthComplete}
                  onToolsChange={onMcpToolsChange}
                />
              ),
            )}
          </div>
        ) : (
          <div className="px-3 py-12 text-center text-sm text-muted-foreground">
            <p>{emptyTitle}</p>
            {normalizedQuery ? (
              <Button
                type="button"
                variant="outline"
                className="mt-4 rounded-full"
                onClick={() => onQueryChange("")}
              >
                {tx("settings.apps.clearSearch", "Clear search")}
              </Button>
            ) : emptyBrowseTarget ? (
              <Button
                type="button"
                variant="outline"
                className="mt-4 rounded-full"
                onClick={() => onFilterChange(emptyBrowseTarget)}
              >
                {emptyBrowseTarget === "cli"
                  ? tx("settings.apps.browseApps", "Browse apps")
                  : tx("settings.apps.browseIntegrations", "Browse MCP tools")}
              </Button>
            ) : (
              <p className="mx-auto mt-2 max-w-[28rem] text-[12px] leading-5">
                {tx(
                  "settings.apps.emptyIntegrationsHint",
                  "Add a custom MCP server below.",
                )}
              </p>
            )}
          </div>
        )}
      </section>

      {filter === "mcp" ? (
        <McpCustomServerPanel
          form={customMcpForm}
          configImport={mcpConfigImport}
          actionKey={mcpActionKey}
          onFormChange={onCustomMcpFormChange}
          onConfigImportChange={onMcpConfigImportChange}
          onSave={onSaveCustomMcp}
          onImportConfig={onImportMcpConfig}
        />
      ) : null}
    </div>
  );
}

function CliAppsCatalogRow({
  app,
  actionKey,
  showBrandLogos,
  onAction,
}: {
  app: CliAppInfo;
  actionKey: string | null;
  showBrandLogos: boolean;
  onAction: (action: "install" | "update" | "uninstall" | "test", name: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const installBusy = actionKey === `install:${app.name}`;
  const updateBusy = actionKey === `update:${app.name}`;
  const uninstallBusy = actionKey === `uninstall:${app.name}`;
  const testBusy = actionKey === `test:${app.name}`;
  const busy = installBusy || updateBusy || uninstallBusy || testBusy;
  const description = app.description || app.requires || app.entry_point || app.name;

  return (
    <article className="apps-catalog-row group flex min-w-0 items-center gap-3 rounded-control px-3 py-3 transition-colors hover:bg-muted/45">
      <CliAppLogo app={app} showBrandLogos={showBrandLogos} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-baseline gap-2">
          <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground">{app.display_name}</h3>
          <AppsTypeBadge>{tx("settings.apps.cliLabel", "App")}</AppsTypeBadge>
        </div>
        <p className="mt-0.5 truncate text-[12.5px] leading-5 text-muted-foreground">{description}</p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {app.installed ? (
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <AppsActionButton
                  ariaLabel={tx("settings.cliApps.statusInstalled", "CLI installed")}
                  busy={testBusy || updateBusy}
                  disabled={busy}
                  tone="installed"
                >
                  <Check className="h-4 w-4" aria-hidden />
                </AppsActionButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem disabled={busy} onClick={() => onAction("test", app.name)}>
                  <PlayCircle aria-hidden />
                  {tx("settings.cliApps.test", "Test CLI")}
                </DropdownMenuItem>
                <DropdownMenuItem disabled={busy} onClick={() => onAction("update", app.name)}>
                  <RotateCcw aria-hidden />
                  {tx("settings.cliApps.update", "Update CLI")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  tone="destructive"
                  disabled={busy}
                  onClick={() => onAction("uninstall", app.name)}
                >
                  <Trash2 aria-hidden />
                  {tx("settings.cliApps.uninstall", "Uninstall CLI")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <AppsActionButton
              ariaLabel={tx("settings.cliApps.uninstall", "Uninstall CLI")}
              busy={uninstallBusy}
              disabled={busy && !uninstallBusy}
              tone="danger"
              onClick={() => onAction("uninstall", app.name)}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </AppsActionButton>
          </>
        ) : app.install_supported ? (
          <AppsActionButton
            ariaLabel={tx("settings.cliApps.install", "Install CLI")}
            busy={installBusy}
            onClick={() => onAction("install", app.name)}
          >
            <Plus className="h-4 w-4" aria-hidden />
          </AppsActionButton>
        ) : (
          <AppsActionButton ariaLabel={tx("settings.cliApps.unavailable", "Unavailable")} disabled>
            <Plus className="h-4 w-4" aria-hidden />
          </AppsActionButton>
        )}
      </div>
    </article>
  );
}

function McpAppsCatalogRow({
  preset,
  values,
  actionKey,
  oauthFlow,
  oauthPopupBlocked,
  oauthCallbackUrl,
  oauthCompleting,
  oauthCallbackError,
  showBrandLogos,
  showTypeBadge,
  onFieldChange,
  onAction,
  onOAuthConnect,
  onOAuthCancel,
  onOAuthOpen,
  onOAuthCallbackUrlChange,
  onOAuthComplete,
  onToolsChange,
}: {
  preset: McpPresetInfo;
  values: Record<string, string>;
  actionKey: string | null;
  oauthFlow: McpOAuthFlowPayload | null;
  oauthPopupBlocked: boolean;
  oauthCallbackUrl: string;
  oauthCompleting: boolean;
  oauthCallbackError: string | null;
  showBrandLogos: boolean;
  showTypeBadge: boolean;
  onFieldChange: (presetName: string, fieldName: string, value: string) => void;
  onAction: (action: "enable" | "disable" | "remove" | "test" | "reconnect", name: string, values?: Record<string, string>) => void;
  onOAuthConnect: (name: string, reset?: boolean) => void;
  onOAuthCancel: () => void;
  onOAuthOpen: () => void;
  onOAuthCallbackUrlChange: (value: string) => void;
  onOAuthComplete: () => void;
  onToolsChange: (name: string, enabledTools: string[]) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [managementOpen, setManagementOpen] = useState(false);
  const [managementTab, setManagementTab] = useState<McpManagementTab>("overview");
  const enableBusy = actionKey === `enable:${preset.name}`;
  const disableBusy = actionKey === `disable:${preset.name}`;
  const removeBusy = actionKey === `remove:${preset.name}`;
  const testBusy = actionKey === `test:${preset.name}`;
  const reconnectBusy = actionKey === `reconnect:${preset.name}`;
  const toolsBusy = actionKey === `tools:${preset.name}`;
  const oauthBusy = actionKey === `oauth:${preset.name}`;
  const anotherOAuthBusy = Boolean(actionKey?.startsWith("oauth:")) && !oauthBusy;
  const busy = enableBusy || disableBusy || removeBusy || testBusy || reconnectBusy || toolsBusy || oauthBusy;
  const agentPlugin = preset.source === "agent-plugin";
  const toggleable = preset.enabled !== undefined;
  const isOAuth = preset.auth === "oauth";
  const missingFields = preset.required_fields.filter((field) => field.required && !field.configured);
  const hasFields = preset.required_fields.length > 0;
  const needsSetupInput = missingFields.length > 0;
  const configuredInstalled = preset.installed && preset.configured;
  const readyInstalled = preset.enabled ?? configuredInstalled;
  const runtimeConnected = !toggleable && preset.runtime_status === "connected";
  const runtimeConnecting = !toggleable && preset.runtime_status === "connecting";
  const runtimeFailed = !toggleable && preset.runtime_status === "failed";
  const statusLabel = toggleable
    ? tx("settings.nanobotFeatures.enabled", "Enabled")
    : runtimeConnected
      ? tx("connection.open", "Connected")
      : mcpPresetStatusLabel(preset.status, tx);
  const failureLabel = tx("settings.mcp.connectionFailed", "Connection failed.");
  const failureStatusLabel = failureLabel.replace(/[.!。！]+$/u, "");
  const description = tx(
    `settings.mcp.presetDescriptions.${preset.name}`,
    preset.description || preset.note || preset.name,
  );
  const detail = agentPlugin && preset.requires
    ? `${description} · ${preset.requires}`
    : description || preset.requires;
  const manualCallback =
    oauthFlow?.completion_input === "callback_url" && Boolean(oauthFlow.authorization_url);
  const callbackInputId = `mcp-oauth-callback-${preset.name}`;
  const callbackHelpId = `${callbackInputId}-help`;
  const callbackErrorId = `${callbackInputId}-error`;

  const enableOrOpenSetup = () => {
    if (isOAuth) {
      onOAuthConnect(preset.name);
      return;
    }
    if (needsSetupInput || (preset.installed && !preset.configured && hasFields)) {
      setManagementTab("connection");
      setManagementOpen(true);
      return;
    }
    onAction("enable", preset.name, values);
  };
  const openManagement = (tab: McpManagementTab = "overview") => {
    setManagementTab(tab);
    setManagementOpen(true);
  };

  return (
    <article className="min-w-0 rounded-control transition-colors hover:bg-muted/45">
      <div className="group flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 px-3 py-3">
        <McpPresetLogo preset={preset} showBrandLogos={showBrandLogos} />
        <div className="min-w-[8rem] flex-[1_1_8rem]">
          <div className="flex min-w-0 items-baseline gap-2">
            <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground">{preset.display_name}</h3>
            {showTypeBadge ? (
              <AppsTypeBadge>
                {agentPlugin
                  ? tx("settings.apps.filterPlugins", "Plugins")
                  : tx("settings.apps.mcpLabel", "MCP")}
              </AppsTypeBadge>
            ) : null}
          </div>
          <p
            className={cn(
              "mt-0.5 flex min-w-0 items-center gap-1.5 text-[12.5px] leading-5 text-muted-foreground",
              runtimeFailed && configuredInstalled && "font-medium text-destructive",
            )}
          >
            {runtimeFailed && configuredInstalled ? (
              <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
            ) : null}
            <span className="truncate">
              {runtimeFailed && configuredInstalled ? failureLabel : detail}
            </span>
          </p>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {oauthFlow ? (
            <>
              <AppsActionButton
                ariaLabel={t("settings.mcp.connectingAccount", {
                  name: preset.display_name,
                  defaultValue: "Connecting {{name}}",
                })}
                visibleLabel={tx("settings.mcp.connectingLabel", "Connecting…")}
                busy
              />
              <AppsActionButton
                ariaLabel={tx("settings.actions.cancel", "Cancel")}
                visibleLabel={tx("settings.actions.cancel", "Cancel")}
                tone="danger"
                onClick={onOAuthCancel}
              />
            </>
          ) : runtimeConnecting && configuredInstalled ? (
            <>
              <AppsActionButton
                ariaLabel={`${preset.display_name}: ${tx("settings.mcp.connectingLabel", "Connecting…")}`}
                visibleLabel={tx("settings.mcp.connectingLabel", "Connecting…")}
                busy
              />
              <AppsActionButton
                ariaLabel={tx("settings.mcp.remove", "Remove")}
                busy={removeBusy}
                disabled={busy && !removeBusy}
                tone="danger"
                onClick={() => onAction("remove", preset.name)}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </AppsActionButton>
            </>
          ) : runtimeFailed && configuredInstalled ? (
            <AppsActionButton
              ariaLabel={t("settings.mcp.manageTitle", {
                name: preset.display_name,
                defaultValue: "Manage {{name}}",
              })}
              visibleLabel={tx("settings.mcp.fixConnection", "Fix connection")}
              disabled={anotherOAuthBusy}
              onClick={() => openManagement("connection")}
            >
              <SlidersHorizontal className="h-4 w-4" aria-hidden />
            </AppsActionButton>
          ) : readyInstalled ? (
            toggleable ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <AppsActionButton
                    ariaLabel={`${preset.display_name}: ${statusLabel}`}
                    visibleLabel={statusLabel}
                    busy={disableBusy}
                    disabled={busy}
                    tone="installed"
                  >
                    <Check className="h-4 w-4" aria-hidden />
                  </AppsActionButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    disabled={busy}
                    onClick={() => onAction("disable", preset.name)}
                  >
                    <PauseCircle aria-hidden />
                    {tx("settings.nanobotFeatures.disable", "Disable")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <AppsActionButton
                ariaLabel={t("settings.mcp.manageTitle", {
                  name: preset.display_name,
                  defaultValue: "Manage {{name}}",
                })}
                visibleLabel={tx("settings.mcp.manage", "Manage")}
                busy={testBusy || toolsBusy || removeBusy || reconnectBusy}
                disabled={busy}
                tone={runtimeConnected ? "installed" : "default"}
                onClick={() => openManagement("overview")}
              >
                <Check className="h-4 w-4" aria-hidden />
              </AppsActionButton>
            )
          ) : preset.enabled === false ? (
            <AppsActionButton
              ariaLabel={tx("settings.nanobotFeatures.enable", "Enable")}
              visibleLabel={tx("settings.nanobotFeatures.enable", "Enable")}
              busy={enableBusy}
              onClick={() => onAction("enable", preset.name, values)}
            />
          ) : isOAuth && preset.install_supported ? (
            <AppsActionButton
              ariaLabel={t("settings.mcp.connectTitle", {
                name: preset.display_name,
                defaultValue: "Connect {{name}}",
              })}
              visibleLabel={tx("settings.mcp.setup", "Connect")}
              busy={oauthBusy}
              disabled={anotherOAuthBusy}
              onClick={() => onOAuthConnect(preset.name)}
            />
          ) : preset.installed && !preset.configured ? (
            <AppsActionButton
              ariaLabel={hasFields ? tx("settings.mcp.configure", "Configure") : tx("settings.mcp.enable", "Enable")}
              visibleLabel={hasFields ? tx("settings.mcp.configure", "Connect") : tx("settings.mcp.enable", "Enable")}
              busy={enableBusy}
              onClick={() => {
                if (hasFields) openManagement("connection");
                else onAction("enable", preset.name, values);
              }}
            />
          ) : preset.install_supported ? (
            <AppsActionButton
              ariaLabel={t("settings.mcp.connectTitle", {
                name: preset.display_name,
                defaultValue: "Connect {{name}}",
              })}
              visibleLabel={tx("settings.mcp.setup", "Connect")}
              busy={enableBusy}
              onClick={enableOrOpenSetup}
            />
          ) : (
            <AppsActionButton
              ariaLabel={tx("settings.mcp.comingSoon", "Coming soon")}
              visibleLabel={tx("settings.mcp.comingSoon", "Coming soon")}
              disabled
            />
          )}
        </div>
      </div>

      {manualCallback ? (
        <form
          className="mx-3 mb-3 min-w-0 space-y-3 rounded-control bg-background/55 p-3"
          onSubmit={(event) => {
            event.preventDefault();
            onOAuthComplete();
          }}
        >
          <div className="flex min-w-0 items-start gap-2.5 text-[12.5px] text-muted-foreground">
            <Clipboard className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <div className="min-w-0 space-y-1">
              <p className="font-medium text-foreground">
                {t("settings.oauth.pasteCallbackToContinue")}
              </p>
              <p id={callbackHelpId} className="leading-5">
                {tx(
                  "settings.mcp.manualCallbackHelp",
                  "After approving access, the localhost page will not load. Copy its full URL from the address bar and paste it here.",
                )}
              </p>
            </div>
          </div>
          <div className="min-w-0 space-y-2">
            <label
              htmlFor={callbackInputId}
              className="block text-xs font-medium text-foreground"
            >
              {t("settings.oauth.callbackUrl")}
            </label>
            <Textarea
              id={callbackInputId}
              value={oauthCallbackUrl}
              onChange={(event) => onOAuthCallbackUrlChange(event.target.value)}
              placeholder={t("settings.oauth.callbackUrlPlaceholder")}
              autoComplete="off"
              spellCheck={false}
              required
              aria-invalid={Boolean(oauthCallbackError)}
              aria-describedby={
                oauthCallbackError
                  ? `${callbackHelpId} ${callbackErrorId}`
                  : callbackHelpId
              }
              className="min-h-[88px] w-full resize-y break-all font-mono text-[12px] leading-5"
            />
            {oauthCallbackError ? (
              <p
                id={callbackErrorId}
                role="alert"
                className="text-[12px] leading-5 text-destructive"
              >
                {oauthCallbackError}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onOAuthOpen}
              className="h-9 w-full rounded-full px-3 text-[12px] font-semibold sm:w-auto"
            >
              {tx("settings.mcp.continueSignIn", "Continue sign-in")}
              <ExternalLink className="ml-1.5 h-3.5 w-3.5" aria-hidden />
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={oauthCompleting}
              className="h-9 w-full rounded-full px-3 text-[12px] font-semibold sm:w-auto"
            >
              {oauthCompleting ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : null}
              {t("settings.oauth.finishSignIn")}
            </Button>
          </div>
        </form>
      ) : oauthFlow && oauthPopupBlocked && oauthFlow.authorization_url ? (
        <div className="mx-3 mb-3 flex flex-col gap-2.5 rounded-control bg-background/55 p-3">
          <div className="flex min-w-0 items-center gap-2.5 text-[12.5px] text-muted-foreground">
            <span>
              {mcpOAuthStatusText(
                oauthFlow.status,
                oauthPopupBlocked,
                tx,
                oauthFlow.completion_input,
              )}
            </span>
          </div>
          <div className="flex shrink-0 items-center justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onOAuthOpen}
              className="h-8 rounded-full px-3 text-[12px] font-semibold"
            >
              {tx("settings.mcp.continueSignIn", "Continue sign-in")}
              <ExternalLink className="ml-1.5 h-3.5 w-3.5" aria-hidden />
            </Button>
          </div>
        </div>
      ) : null}

      {managementOpen ? (
        <McpManagementDialog
          preset={preset}
          values={values}
          actionKey={actionKey}
          statusLabel={runtimeFailed && configuredInstalled ? failureStatusLabel : statusLabel}
          statusTone={runtimeFailed ? "warning" : configuredInstalled ? "success" : "neutral"}
          tab={managementTab}
          icon={<McpPresetLogo preset={preset} showBrandLogos={showBrandLogos} compact />}
          onTabChange={setManagementTab}
          onOpenChange={setManagementOpen}
          onFieldChange={onFieldChange}
          onAction={onAction}
          onOAuthConnect={onOAuthConnect}
          onToolsChange={onToolsChange}
        />
      ) : null}
    </article>
  );
}

function AppsTypeBadge({ children }: { children: ReactNode }) {
  return (
    <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium leading-none text-muted-foreground">
      {children}
    </span>
  );
}

type AppsActionButtonProps = Omit<
  ComponentPropsWithoutRef<typeof Button>,
  "aria-label" | "children" | "disabled" | "size" | "variant"
> & {
  ariaLabel: string;
  visibleLabel?: string;
  busy?: boolean;
  disabled?: boolean;
  tone?: "default" | "installed" | "danger";
  children?: ReactNode;
};

export const AppsActionButton = forwardRef<HTMLButtonElement, AppsActionButtonProps>(
  function AppsActionButton({
    ariaLabel,
    visibleLabel,
    busy,
    disabled,
    tone = "default",
    children,
    className,
    ...buttonProps
  }, ref) {
    return (
      <Button
        {...buttonProps}
        ref={ref}
        type="button"
        size={visibleLabel ? "sm" : "icon"}
        variant="ghost"
        aria-label={ariaLabel}
        title={ariaLabel}
        disabled={disabled || busy}
        className={cn(
          "rounded-full text-muted-foreground transition-colors",
          visibleLabel
            ? "h-8 w-auto gap-1.5 px-3 text-[12px] font-semibold"
            : "h-9 w-9",
          tone === "installed" && "bg-transparent hover:bg-muted/70 hover:text-foreground",
          tone === "danger" && "bg-transparent hover:bg-destructive/10 hover:text-destructive",
          tone === "default" && "bg-muted/70 hover:bg-muted hover:text-foreground",
          className,
        )}
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden /> : children}
        {visibleLabel ? <span>{visibleLabel}</span> : null}
      </Button>
    );
  },
);

function appsTitle(item: AppsCatalogItem): string {
  return item.kind === "cli" ? item.app.display_name : item.preset.display_name;
}

function appsReady(item: AppsCatalogItem): boolean {
  if (item.kind === "cli") return item.app.installed;
  if (item.preset.enabled !== undefined) return item.preset.enabled;
  return item.preset.installed &&
    item.preset.configured &&
    item.preset.runtime_status === "connected";
}

function appsSearchText(item: AppsCatalogItem): string {
  if (item.kind === "cli") {
    const app = item.app;
    return [
      app.display_name,
      app.name,
      app.category,
      app.description,
      app.requires,
      app.entry_point,
      app.source,
    ]
      .join(" ")
      .toLowerCase();
  }
  const preset = item.preset;
  return [
    preset.display_name,
    preset.name,
    preset.category,
    preset.description,
    preset.requires,
    preset.note,
    preset.transport,
    preset.source ?? "",
  ]
    .join(" ")
      .toLowerCase();
}

function McpCustomServerPanel({
  form,
  configImport,
  actionKey,
  onFormChange,
  onConfigImportChange,
  onSave,
  onImportConfig,
}: {
  form: CustomMcpForm;
  configImport: string;
  actionKey: string | null;
  onFormChange: Dispatch<SetStateAction<CustomMcpForm>>;
  onConfigImportChange: (value: string) => void;
  onSave: () => void;
  onImportConfig: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const oauthHelpId = useId();
  const headersInputId = useId();
  const headersHelpId = useId();
  const [activeMode, setActiveMode] = useState<"custom" | "import" | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const customBusy = actionKey?.startsWith("custom:") ?? false;
  const importBusy = actionKey === "import" || actionKey === "import-cursor";
  const remote = form.transport !== "stdio";
  const canSave = Boolean(form.name.trim()) && (remote ? Boolean(form.url.trim()) : Boolean(form.command.trim()));
  const update = <K extends keyof CustomMcpForm>(key: K, value: CustomMcpForm[K]) => {
    onFormChange((prev) => ({ ...prev, [key]: value }));
  };
  const transports: Array<{ value: CustomMcpTransport; label: string }> = [
    { value: "stdio", label: "stdio" },
    { value: "streamableHttp", label: "HTTP" },
    { value: "sse", label: "SSE" },
  ];
  const authenticationOptions: Array<{ value: CustomMcpAuth; label: string }> = [
    { value: "none", label: tx("settings.mcp.authNone", "None") },
    { value: "oauth", label: "OAuth" },
    { value: "headers", label: tx("settings.mcp.authHeaders", "Headers") },
  ];

  return (
    <section className="overflow-hidden rounded-floating bg-settings-surface">
      <div className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-control bg-muted text-muted-foreground">
            <Server className="h-4 w-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <h3 className="text-[13px] font-semibold leading-5 text-foreground">
              {tx("settings.mcp.moreOptions", "Add MCP server")}
            </h3>
            <p className="truncate text-[12px] text-muted-foreground">
              {tx(
                "settings.mcp.moreOptionsSubtitle",
                "Connect a custom MCP server or import an existing configuration.",
              )}
            </p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:flex sm:shrink-0">
          <Button
            type="button"
            size="sm"
            variant={activeMode === "custom" ? "default" : "outline"}
            onClick={() => setActiveMode((mode) => (mode === "custom" ? null : "custom"))}
            className="h-8 rounded-full px-3 text-[12px] font-semibold"
          >
            <Server className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            {tx("settings.mcp.customAction", "Custom")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={activeMode === "import" ? "default" : "outline"}
            onClick={() => setActiveMode((mode) => (mode === "import" ? null : "import"))}
            className="h-8 rounded-full px-3 text-[12px] font-semibold"
          >
            <Database className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            {tx("settings.mcp.importAction", "Import")}
          </Button>
        </div>
      </div>

      {activeMode === "custom" ? (
        <div className="border-t border-border/35 bg-muted/18 px-3 py-3">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-end">
            <label className="min-w-0 flex-1">
              <span className="mb-1.5 block text-[11.5px] font-medium text-muted-foreground">
                {tx("settings.mcp.serverName", "Server name")}
              </span>
              <Input
                value={form.name}
                onChange={(event) => update("name", event.target.value)}
                placeholder="docs"
                className="h-9 rounded-full bg-background/80 text-[12.5px]"
              />
            </label>
            <div className="min-w-[228px]">
              <span className="mb-1.5 block text-[11.5px] font-medium text-muted-foreground">
                {tx("settings.mcp.transport", "Transport")}
              </span>
              <SegmentedControl
                value={form.transport}
                options={transports}
                onChange={(value) => update("transport", value as CustomMcpTransport)}
              />
            </div>
            {remote ? (
              <label className="min-w-0 flex-[1.4]">
                <span className="mb-1.5 block text-[11.5px] font-medium text-muted-foreground">
                  {tx("settings.mcp.serverUrl", "URL")}
                </span>
                <Input
                  value={form.url}
                  onChange={(event) => update("url", event.target.value)}
                  placeholder={form.transport === "sse" ? "https://example.com/sse" : "https://example.com/mcp"}
                  className="h-9 rounded-full bg-background/80 text-[12.5px]"
                />
              </label>
            ) : (
              <label className="min-w-0 flex-[1.4]">
                <span className="mb-1.5 block text-[11.5px] font-medium text-muted-foreground">
                  {tx("settings.mcp.command", "Command")}
                </span>
                <Input
                  value={form.command}
                  onChange={(event) => update("command", event.target.value)}
                  placeholder="npx"
                  className="h-9 rounded-full bg-background/80 text-[12.5px]"
                />
              </label>
            )}
          </div>

          {remote ? (
            <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-[minmax(0,auto)_minmax(0,1fr)] sm:items-end">
              <fieldset
                className="min-w-0"
                aria-describedby={form.auth === "oauth" ? oauthHelpId : undefined}
              >
                <legend className="mb-1.5 block text-[11.5px] font-medium text-muted-foreground">
                  {tx("settings.mcp.authentication", "Authentication")}
                </legend>
                <SegmentedControl
                  value={form.auth}
                  options={authenticationOptions}
                  onChange={(value) => update("auth", value as CustomMcpAuth)}
                  className="w-full sm:w-auto"
                  itemClassName="min-w-0 flex-1 sm:flex-none"
                />
              </fieldset>
              {form.auth === "oauth" ? (
                <p
                  id={oauthHelpId}
                  className="pb-1 text-[12px] leading-5 text-muted-foreground"
                >
                  {tx(
                    "settings.mcp.oauthAfterSave",
                    "Save the server, then select Connect to sign in.",
                  )}
                </p>
              ) : null}
            </div>
          ) : null}

          {remote && form.auth === "headers" ? (
            <div className="mt-3 min-w-0">
              <label
                htmlFor={headersInputId}
                className="mb-1 block text-[11.5px] font-medium text-muted-foreground"
              >
                {tx("settings.mcp.headers", "Headers JSON")}
              </label>
              <Textarea
                id={headersInputId}
                aria-describedby={headersHelpId}
                value={form.headers}
                onChange={(event) => update("headers", event.target.value)}
                placeholder={'{"Authorization":"Bearer ..."}'}
                className="min-h-[68px] resize-y bg-background/80 font-mono text-[12px]"
              />
              <p
                id={headersHelpId}
                className="mt-1 text-[11.5px] leading-5 text-muted-foreground"
              >
                {tx(
                  "settings.mcp.headersHelp",
                  "Add the request headers used by this server.",
                )}
              </p>
            </div>
          ) : null}

          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setAdvancedOpen((open) => !open)}
            className="mt-2 h-8 rounded-full px-2 text-[12px] font-medium text-muted-foreground hover:text-foreground"
          >
            <ChevronDown
              className={cn("mr-1.5 h-3.5 w-3.5 transition-transform", advancedOpen ? "rotate-180" : "")}
              aria-hidden
            />
            {advancedOpen
              ? tx("settings.mcp.hideAdvanced", "Hide advanced")
              : tx("settings.mcp.advancedOptions", "Advanced options")}
          </Button>

          {advancedOpen ? (
            <div
              className={cn(
                "mt-2 grid gap-2",
                remote
                  ? "xl:grid-cols-[minmax(0,1fr)_180px]"
                  : "xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_180px]",
              )}
            >
              {!remote ? (
                <label className="min-w-0">
                  <span className="mb-1 block text-[11.5px] font-medium text-muted-foreground">
                    {tx("settings.mcp.args", "Args JSON")}
                  </span>
                  <Textarea
                    value={form.args}
                    onChange={(event) => update("args", event.target.value)}
                    placeholder={'["-y", "docs-mcp"]'}
                    className="min-h-[68px] resize-y bg-background/80 font-mono text-[12px]"
                  />
                </label>
              ) : null}
              <label className="min-w-0">
                <span className="mb-1 block text-[11.5px] font-medium text-muted-foreground">
                  {tx("settings.mcp.env", "Env JSON")}
                </span>
                <Textarea
                  value={form.env}
                  onChange={(event) => update("env", event.target.value)}
                  placeholder={'{"API_KEY":"..."}'}
                  className="min-h-[68px] resize-y bg-background/80 font-mono text-[12px]"
                />
              </label>
              <label className="min-w-0">
                <span className="mb-1 block text-[11.5px] font-medium text-muted-foreground">
                  {tx("settings.mcp.timeout", "Tool timeout")}
                </span>
                <Input
                  value={form.toolTimeout}
                  onChange={(event) => update("toolTimeout", event.target.value)}
                  inputMode="numeric"
                  className="h-9 rounded-full bg-background/80 text-[12.5px]"
                />
              </label>
            </div>
          ) : null}

          <div className="mt-3 flex justify-end">
            <Button
              type="button"
              size="sm"
              onClick={onSave}
              disabled={!canSave || customBusy}
              className="h-9 w-full rounded-full px-4 text-[12.5px] font-semibold sm:w-auto"
            >
              {customBusy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden />}
              {tx("settings.mcp.saveCustom", "Save MCP")}
            </Button>
          </div>
        </div>
      ) : null}

      {activeMode === "import" ? (
        <div className="border-t border-border/35 bg-muted/18 px-3 py-3">
          <div className="flex flex-col gap-2 xl:flex-row xl:items-end">
            <label className="min-w-0 flex-1">
              <span className="mb-1.5 block text-[11.5px] font-medium text-muted-foreground">
                {tx("settings.mcp.configImport", "Import mcp.json")}
              </span>
              <Textarea
                value={configImport}
                onChange={(event) => onConfigImportChange(event.target.value)}
                placeholder={'{"mcpServers":{"docs":{"command":"npx","args":["-y","docs-mcp"]}}}'}
                className="min-h-[84px] resize-y bg-background/80 font-mono text-[12px]"
              />
            </label>
            <Button
              type="button"
              size="sm"
              onClick={onImportConfig}
              disabled={!configImport.trim() || importBusy}
              className="h-9 shrink-0 rounded-full px-4 text-[12.5px] font-semibold"
            >
              {importBusy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : <Database className="mr-1.5 h-3.5 w-3.5" aria-hidden />}
              {tx("settings.mcp.importConfig", "Import")}
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function mcpOAuthStatusText(
  status: McpOAuthFlowPayload["status"],
  popupBlocked: boolean,
  tx: (key: string, fallback: string) => string,
  completionInput?: McpOAuthFlowPayload["completion_input"],
): string {
  switch (status) {
    case "starting":
      return tx("settings.mcp.preparingSignIn", "Preparing secure sign-in...");
    case "authorization_required":
      if (completionInput === "callback_url") {
        return tx(
          "settings.mcp.manualCallbackRequired",
          "Finish signing in, then paste the callback URL into nanobot.",
        );
      }
      return popupBlocked
        ? tx("settings.mcp.openSignInToContinue", "Open the sign-in page to continue.")
        : tx("settings.mcp.finishSignInInBrowser", "Finish signing in in the browser window.");
    case "connecting":
      return tx("settings.mcp.finishingConnection", "Finishing connection...");
    case "authorized":
      return tx("settings.mcp.activatingTools", "Activating tools...");
    case "connected":
      return tx("settings.mcp.connected", "Connected.");
    case "failed":
      return tx("settings.mcp.connectionFailed", "Connection failed.");
    case "cancelled":
      return tx("settings.mcp.connectionCancelled", "Connection cancelled.");
  }
}

function mcpPresetStatusLabel(
  status: string,
  tx: (key: string, fallback: string) => string,
): string {
  switch (status) {
    case "configured":
      return tx("settings.mcp.statusConfigured", "Configured");
    case "missing_credentials":
      return tx("settings.mcp.statusMissingCredentials", "Needs key");
    case "missing_dependency":
      return tx("settings.mcp.statusMissingDependency", "Needs dependency");
    case "coming_soon":
      return tx("settings.mcp.statusComingSoon", "Coming soon");
    default:
      return tx("settings.mcp.statusNotInstalled", "Not enabled");
  }
}

function McpPresetLogo({
  preset,
  showBrandLogos,
  compact = false,
}: {
  preset: McpPresetInfo;
  showBrandLogos: boolean;
  compact?: boolean;
}) {
  const bg = preset.brand_color || "hsl(var(--muted))";
  const logoUrls = useMemo(() => logoFallbackUrls(preset.logo_url), [preset.logo_url]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const packagedLogo = preset.logo_url?.startsWith("data:image/") === true;
  const initials = preset.display_name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || preset.name.slice(0, 2).toUpperCase();

  if ((showBrandLogos || packagedLogo) && logoUrl) {
    return (
      <span
        className={cn(
          "grid shrink-0 place-items-center border border-border/45 bg-background",
          compact ? "h-10 w-10 rounded-control" : "h-11 w-11 rounded-compact",
        )}
      >
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className={cn("object-contain", compact ? "h-[22px] w-[22px]" : "h-6 w-6")}
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      </span>
    );
  }
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center font-semibold text-white",
        compact
          ? "h-10 w-10 rounded-control text-[12px]"
          : "h-11 w-11 rounded-compact text-[13px]",
      )}
      style={{ backgroundColor: bg }}
    >
      {initials}
    </span>
  );
}

function CliAppReadyPanel({
  app,
  showBrandLogos,
  onBackToChat,
}: {
  app: CliAppInfo;
  showBrandLogos: boolean;
  onBackToChat: () => void;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const prompt = t("settings.cliApps.readyPrompt", {
    name: app.name,
    defaultValue: "Use @{{name}} to inspect what this CLI can do.",
  });
  const copyPrompt = () => {
    if (!navigator.clipboard) return;
    void navigator.clipboard.writeText(prompt).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    });
  };

  return (
    <section className="rounded-control bg-settings-surface px-4 py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <CliAppLogo app={app} showBrandLogos={showBrandLogos} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground">
              {app.display_name}
            </h3>
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10.5px] font-medium text-muted-foreground">
              <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-300" aria-hidden />
              {t("settings.cliApps.readyStatus", { defaultValue: "Ready" })}
            </span>
          </div>
          <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-1.5 text-[12px] text-muted-foreground">
            <span className="font-mono">@{app.name}</span>
            <span aria-hidden>·</span>
            <span className="truncate font-mono">{app.entry_point || app.name}</span>
            <span aria-hidden>·</span>
            <span>{app.category}</span>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={copyPrompt}
            className="h-8 rounded-full px-3 text-[12px] font-medium text-muted-foreground hover:bg-muted/65 hover:text-foreground"
          >
            {copied ? <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden /> : null}
            {copied
              ? t("settings.cliApps.readyCopied", { defaultValue: "Copied" })
              : t("settings.cliApps.readyTry", { name: app.name, defaultValue: "Try @{{name}}" })}
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={onBackToChat}
            className="h-8 rounded-full px-3 text-[12px] font-semibold"
          >
            {t("settings.cliApps.openChat", { defaultValue: "Open chat" })}
            <ChevronRight className="ml-1.5 h-3.5 w-3.5" aria-hidden />
          </Button>
        </div>
      </div>
    </section>
  );
}

function CliAppLogo({ app, showBrandLogos }: { app: CliAppInfo; showBrandLogos: boolean }) {
  const logoUrls = useMemo(
    () => (isGenericRepositoryLogoUrl(app.logo_url) ? [] : logoFallbackUrls(app.logo_url)),
    [app.logo_url],
  );
  const { logoUrl, logoLoaded, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const initials = app.display_name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || app.name.slice(0, 2).toUpperCase();

  const showRemoteLogo = showBrandLogos && Boolean(logoUrl);

  return (
    <span
      className="relative grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-compact border border-border/45 bg-muted text-[13px] font-semibold"
      style={{ color: app.brand_color || "hsl(var(--muted-foreground))" }}
    >
      <span
        aria-hidden
        className={cn(
          "transition-opacity duration-150 motion-reduce:transition-none",
          showRemoteLogo && logoLoaded ? "opacity-0" : "opacity-100",
        )}
      >
        {initials}
      </span>
      {showRemoteLogo ? (
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          referrerPolicy="no-referrer"
          draggable={false}
          className={cn(
            "absolute h-6 w-6 object-contain transition-opacity duration-150 motion-reduce:transition-none",
            logoLoaded ? "opacity-100" : "opacity-0",
          )}
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      ) : null}
    </span>
  );
}
