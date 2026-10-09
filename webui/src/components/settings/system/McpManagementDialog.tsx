import {
  AppActionsIcon,
} from "@/components/icons/product-icons";
import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import {
  Check,
  ExternalLink,
  Info,
  Loader2,
  RotateCcw,
  Search,
  Server,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { SkeletonStatus } from "@/components/settings/shared/SkeletonStatus";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { McpPresetInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export type McpManagementTab = "overview" | "tools" | "connection";

type McpAction = "enable" | "disable" | "remove" | "test" | "reconnect";

interface McpManagementDialogProps {
  fallbackFocusRef?: RefObject<HTMLElement>;
  preset: McpPresetInfo;
  values: Record<string, string>;
  actionKey: string | null;
  statusLabel: string;
  statusTone: "success" | "warning" | "neutral";
  tab: McpManagementTab;
  icon: ReactNode;
  overviewContent?: ReactNode;
  /** Managed connections own their permission flow instead of raw MCP/tool editing. */
  connectionPanel?: ReactNode;
  onTabChange: (tab: McpManagementTab) => void;
  onOpenChange: (open: boolean) => void;
  onFieldChange: (presetName: string, fieldName: string, value: string) => void;
  onAction: (action: McpAction, name: string, values?: Record<string, string>) => void;
  onOAuthConnect: (name: string, reset?: boolean) => void;
  onToolsChange: (name: string, enabledTools: string[]) => void;
}

export function McpManagementDialog({
  fallbackFocusRef,
  preset,
  values,
  actionKey,
  statusLabel,
  statusTone,
  tab,
  icon,
  overviewContent,
  connectionPanel,
  onTabChange,
  onOpenChange,
  onFieldChange,
  onAction,
  onOAuthConnect,
  onToolsChange,
}: McpManagementDialogProps) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const inventoryRef = useRef(preset.tool_names ?? []);
  if (preset.tool_names?.length) inventoryRef.current = preset.tool_names;
  const toolNames = inventoryRef.current;
  const [toolQuery, setToolQuery] = useState("");
  const [draftEnabledTools, setDraftEnabledTools] = useState<string[]>(
    preset.enabled_tools ?? ["*"],
  );
  const testBusy = actionKey === `test:${preset.name}`;
  const reconnectBusy = actionKey === `reconnect:${preset.name}`;
  const removeBusy = actionKey === `remove:${preset.name}`;
  const enableBusy = actionKey === `enable:${preset.name}`;
  const toolsBusy = actionKey === `tools:${preset.name}`;
  const oauthBusy = actionKey === `oauth:${preset.name}`;
  const busy = testBusy || reconnectBusy || removeBusy || enableBusy || toolsBusy || oauthBusy;
  const configuredInstalled = preset.installed && preset.configured;
  const isOAuth = preset.auth === "oauth";
  const inspectionRequestedRef = useRef(false);
  const allowAllTools = draftEnabledTools.includes("*");
  const selectedTools = new Set(allowAllTools ? toolNames : draftEnabledTools);
  const normalizedQuery = toolQuery.trim().toLowerCase();
  const filteredTools = useMemo(
    () => toolNames.filter((name) => name.toLowerCase().includes(normalizedQuery)),
    [normalizedQuery, toolNames],
  );
  const knownToolCount = preset.tool_count ?? toolNames.length;
  const selectedToolCount = allowAllTools ? knownToolCount : selectedTools.size;
  const requiredFieldsComplete = preset.required_fields
    .filter((field) => field.required && !field.configured)
    .every((field) => Boolean(values[field.name]?.trim()));
  const initialTools = normalizeTools(preset.enabled_tools ?? ["*"]);
  const draftTools = normalizeTools(draftEnabledTools);
  const description = tx(
    `settings.mcp.presetDescriptions.${preset.name}`,
    preset.description || preset.note || preset.name,
  );
  const toolsDirty = initialTools.join("\n") !== draftTools.join("\n");
  const tabs: Array<{ value: McpManagementTab; label: ReactNode }> = [
    { value: "overview", label: tx("settings.mcp.overviewTab", "Overview") },
    ...(!connectionPanel ? [{
      value: "tools" as const,
      label: tx("settings.mcp.toolScope", "Tools"),
    }] : []),
    { value: "connection", label: tx("settings.mcp.connectionTab", "Connection") },
  ];
  const activePanelLabel = connectionPanel
    ? tx("settings.mcp.connectionTab", "Connection")
    : tab === "overview"
      ? tx("settings.mcp.overviewTab", "Overview")
      : tab === "tools"
        ? tx("settings.mcp.toolScope", "Tools")
        : tx("settings.mcp.connectionTab", "Connection");
  const managedOverview = Boolean(connectionPanel) && tab === "overview";
  const contentRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const toggleTool = (toolName: string) => {
    const next = new Set(allowAllTools ? toolNames : draftEnabledTools);
    if (next.has(toolName)) next.delete(toolName);
    else next.add(toolName);
    setDraftEnabledTools(next.size === toolNames.length ? ["*"] : Array.from(next));
  };

  const connect = () => {
    onOpenChange(false);
    if (isOAuth) {
      onOAuthConnect(preset.name, configuredInstalled);
      return;
    }
    onAction(configuredInstalled ? "reconnect" : "enable", preset.name, values);
  };

  const inspectTools = () => {
    inspectionRequestedRef.current = true;
    onAction("test", preset.name);
  };

  useEffect(() => {
    if (
      connectionPanel || tab !== "tools" ||
      !configuredInstalled ||
      toolNames.length ||
      busy ||
      preset.error ||
      inspectionRequestedRef.current
    ) {
      return;
    }
    inspectionRequestedRef.current = true;
    onAction("test", preset.name);
  }, [busy, configuredInstalled, connectionPanel, onAction, preset.error, preset.name, tab, toolNames.length]);

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        showCloseButton={false}
        onOpenAutoFocus={(event) => {
          returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
          event.preventDefault();
          contentRef.current?.focus({ preventScroll: true });
        }}
        onCloseAutoFocus={(event) => {
          const target = returnFocusRef.current?.isConnected ? returnFocusRef.current : fallbackFocusRef?.current;
          if (target?.isConnected) {
            event.preventDefault();
            target.focus({ preventScroll: true });
          }
        }}
        className={cn(
          "flex w-[calc(100vw-2rem)] flex-col gap-0 overflow-hidden p-0 outline-none",
          connectionPanel ? "max-w-[32rem]" : "max-w-[42rem]",
          connectionPanel ? "max-h-[calc(100dvh-2rem)]" : "h-[min(34rem,calc(100dvh-2rem))]",
        )}
      >
        <div className={cn(
          "grid shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] gap-x-3 px-5 sm:px-6",
          connectionPanel ? "items-start pb-4 pt-5" : "items-center border-b border-border/45 py-3.5 sm:flex",
        )}>
          <div className={cn("row-span-2 shrink-0", connectionPanel && "max-[380px]:row-span-1")} aria-hidden>{icon}</div>
          <div className={cn("min-w-0 flex-1", connectionPanel && "max-[380px]:col-span-3 max-[380px]:row-start-2 max-[380px]:pt-3")}>
            <DialogTitle className={cn("text-[17px] leading-6 tracking-[-0.01em]", connectionPanel ? "break-words" : "truncate")}>
              {preset.display_name}
            </DialogTitle>
            <DialogDescription className={connectionPanel ? "mt-1 text-[13px] leading-5 text-muted-foreground" : "sr-only"}>
              {description}
            </DialogDescription>
          </div>
          {!connectionPanel && <div className="col-start-2 row-start-2 mt-1 sm:mt-0">
            <StatusPill tone={statusTone}>{statusLabel}</StatusPill>
          </div>}
          <div className={cn("col-start-3 row-start-1 row-span-2 -mr-2 flex shrink-0 items-center", connectionPanel && "max-[380px]:row-span-1")}>
          {connectionPanel && <Popover open={managedOverview} onOpenChange={(open) => onTabChange(open ? "overview" : "connection")} modal>
          <PopoverTrigger asChild><Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={tx("settings.mcp.overviewTab", "Overview")}
            title={tx("settings.mcp.overviewTab", "Overview")}
            className="touch-target h-10 w-10 rounded-full text-muted-foreground"
          ><Info className="h-4 w-4" aria-hidden /></Button></PopoverTrigger>
          <PopoverContent
            side="bottom" align="end" sideOffset={8} collisionPadding={24}
            aria-label={tx("settings.mcp.overviewTab", "Overview")}
            className="w-[min(24rem,calc(100vw-3rem))] p-4 duration-200 ease-out data-[state=open]:slide-in-from-top-1 data-[state=closed]:slide-out-to-top-1 motion-reduce:animate-none"
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-[13px] font-semibold">{tx("settings.mcp.overviewTab", "Overview")}</h3>
              <Button type="button" variant="ghost" size="icon" className="touch-target -mr-2 -mt-2 h-9 w-9 rounded-full text-muted-foreground"
                aria-label={tx("common.close", "Close")} onClick={() => onTabChange("connection")}>
                <X className="h-4 w-4" aria-hidden />
              </Button>
            </div>
            {overviewContent}
          </PopoverContent>
          </Popover>}
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={tx("common.close", "Close")}
            onClick={() => onOpenChange(false)}
            className="touch-target h-10 w-10 shrink-0 rounded-full text-muted-foreground"
          >
            <X className="h-4 w-4" aria-hidden />
          </Button>
          </div>
        </div>

        {!connectionPanel && <div className="shrink-0 border-b border-border/45 px-5 py-3 sm:px-6">
          <SegmentedControl
            value={tab}
            options={tabs}
            onChange={onTabChange}
            mode="tabs"
            ariaLabel={tx("settings.mcp.manageTabs", "MCP management sections")}
            className="w-full max-w-[22rem]"
            itemClassName="flex-1"
          />
        </div>}

        <div
          role={connectionPanel ? "region" : "tabpanel"}
          aria-label={activePanelLabel}
          className={cn(
            "min-h-0",
            connectionPanel
              ? "flex flex-col overflow-hidden"
              : "flex-1 overflow-y-auto overscroll-contain px-5 py-5 scrollbar-thin scrollbar-track-transparent sm:px-6",
          )}
        >
          {connectionPanel ?? (tab === "overview" ? (
            <OverviewPanel
              preset={preset}
              description={description}
              knownToolCount={knownToolCount}
              selectedToolCount={selectedToolCount}
              onOpenTools={() => onTabChange("tools")}
              content={overviewContent}
            />
          ) : tab === "tools" ? (
            <ToolsPanel
              preset={preset}
              toolNames={toolNames}
              filteredTools={filteredTools}
              query={toolQuery}
              selectedTools={selectedTools}
              selectedToolCount={selectedToolCount}
              toolsBusy={toolsBusy}
              testBusy={testBusy}
              configuredInstalled={configuredInstalled}
              onQueryChange={setToolQuery}
              onToggleTool={toggleTool}
              onSelectAll={() => setDraftEnabledTools(["*"])}
              onClear={() => setDraftEnabledTools([])}
              onTest={inspectTools}
              onOpenConnection={() => onTabChange("connection")}
            />
          ) : (
            <ConnectionPanel
              preset={preset}
              values={values}
              busy={busy}
              connectBusy={reconnectBusy || enableBusy || oauthBusy}
              removeBusy={removeBusy}
              requiredFieldsComplete={requiredFieldsComplete}
              onFieldChange={onFieldChange}
              onConnect={connect}
              onRemove={() => {
                onOpenChange(false);
                onAction("remove", preset.name);
              }}
            />
          ))}
        </div>

        {!connectionPanel && tab === "tools" && toolsDirty ? (
          <div className="flex shrink-0 items-center justify-end border-t border-border/45 bg-background/95 px-5 py-3 sm:px-6">
            <Button
              type="button"
              disabled={toolsBusy || !toolNames.length}
              onClick={() => onToolsChange(preset.name, draftEnabledTools)}
              className="h-9 rounded-full px-4 text-[13px] font-semibold"
            >
              {toolsBusy ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
              ) : (
                <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden />
              )}
              {tx("settings.mcp.applyChanges", "Apply changes")}
            </Button>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function OverviewPanel({
  preset,
  description,
  knownToolCount,
  selectedToolCount,
  onOpenTools,
  content,
}: {
  preset: McpPresetInfo;
  description: string;
  knownToolCount: number;
  selectedToolCount: number;
  onOpenTools: () => void;
  content?: ReactNode;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className="space-y-6">
      <p className="max-w-[62ch] text-[15px] leading-6 text-foreground">
        {description}
      </p>
      {content}
      {!content && knownToolCount > 0 ? (
        <Button variant="ghost" className="touch-target -ml-3 text-muted-foreground" onClick={onOpenTools}>
          <AppActionsIcon className="mr-2 h-4 w-4" aria-hidden />
          {tx("settings.mcp.toolScope", "Tools")}
          <span className="ml-2 tabular-nums">{selectedToolCount} / {knownToolCount}</span>
        </Button>
      ) : null}
      {preset.docs_url ? (
        <a
          href={preset.docs_url}
          target="_blank"
          rel="noreferrer"
          className="touch-target inline-flex items-center gap-1.5 rounded-control text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {tx("settings.mcp.openDocs", "Open docs")}
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        </a>
      ) : null}
    </div>
  );
}

function ToolsPanel({
  preset,
  toolNames,
  filteredTools,
  query,
  selectedTools,
  selectedToolCount,
  toolsBusy,
  testBusy,
  configuredInstalled,
  onQueryChange,
  onToggleTool,
  onSelectAll,
  onClear,
  onTest,
  onOpenConnection,
}: {
  preset: McpPresetInfo;
  toolNames: string[];
  filteredTools: string[];
  query: string;
  selectedTools: Set<string>;
  selectedToolCount: number;
  toolsBusy: boolean;
  testBusy: boolean;
  configuredInstalled: boolean;
  onQueryChange: (value: string) => void;
  onToggleTool: (name: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
  onTest: () => void;
  onOpenConnection: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  if (!toolNames.length && testBusy) {
    return (
      <SkeletonStatus label={tx("settings.mcp.loadingTools", "Loading tools…")} className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="h-10 min-w-0 rounded-full bg-muted-foreground/20 sm:flex-1" />
          <div className="flex h-8 items-center justify-between gap-4 sm:justify-end">
            <div className="mr-auto h-3 w-20 rounded bg-muted-foreground/20 sm:mr-1" />
            <div className="h-3 w-6 rounded bg-muted-foreground/20" />
            <div className="h-3 w-9 rounded bg-muted-foreground/20" />
          </div>
        </div>
        <div className="overflow-hidden rounded-floating border border-border/55">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="flex min-h-11 items-center gap-3 border-b border-border/45 px-3.5 py-2.5 last:border-b-0">
              <div className="h-5 w-5 shrink-0 rounded-compact bg-muted-foreground/20" />
              <div className={cn("h-3.5 max-w-[70%] rounded bg-muted-foreground/20", index % 2 ? "w-40" : "w-52")} />
            </div>
          ))}
        </div>
      </SkeletonStatus>
    );
  }

  if (!toolNames.length) {
    return (
      <div
        className={cn(
          "flex flex-col gap-3 rounded-floating border px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between",
          preset.error ? "border-destructive/25 bg-destructive/5" : "border-border/55 bg-muted/25",
        )}
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-background text-muted-foreground">
            <AppActionsIcon className="h-4 w-4" aria-hidden />
          </div>
          <p
            role={preset.error ? "alert" : undefined}
            className={cn("min-w-0 text-[14px] font-medium", preset.error ? "text-destructive" : "text-foreground")}
          >
            {preset.error || tx("settings.mcp.noToolsAvailable", "No tools available")}
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={configuredInstalled ? onTest : onOpenConnection}
          className="h-9 shrink-0 rounded-full px-4 text-[13px] font-semibold"
        >
          {configuredInstalled ? (
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          ) : (
            <Server className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {configuredInstalled
            ? tx("settings.mcp.reloadTools", "Reload tools")
            : tx("settings.mcp.setup", "Connect")}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">{tx("settings.mcp.searchTools", "Search tools")}</span>
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={tx("settings.mcp.searchToolsPlaceholder", "Search tools")}
            className="h-10 rounded-full bg-muted/45 pl-9 text-[12.5px]"
          />
        </label>
        <div className="flex items-center justify-between gap-2 sm:justify-end">
          <span className="mr-auto text-[13px] tabular-nums text-muted-foreground sm:mr-1">
            {tx("settings.mcp.selectedCount", "{{count}} selected").replace("{{count}}", String(selectedToolCount))}
          </span>
          <Button type="button" size="sm" variant="ghost" disabled={toolsBusy} onClick={onSelectAll} className="h-8 rounded-full px-2.5 text-[12.5px] font-semibold">
            {tx("settings.mcp.allTools", "All")}
          </Button>
          <Button type="button" size="sm" variant="ghost" disabled={toolsBusy} onClick={onClear} className="h-8 rounded-full px-2.5 text-[12.5px] font-semibold text-muted-foreground">
            {tx("settings.mcp.noTools", "None")}
          </Button>
        </div>
      </div>

      <div className="overflow-hidden rounded-floating border border-border/55">
        {filteredTools.length ? filteredTools.map((toolName) => {
          const selected = selectedTools.has(toolName);
          return (
            <label
              key={toolName}
              className="flex min-h-11 cursor-pointer items-center gap-3 border-b border-border/45 px-3.5 py-2.5 transition-colors last:border-b-0 settings-hover has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-inset has-[:focus-visible]:ring-ring"
            >
              <span className="relative h-5 w-5 shrink-0">
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={toolsBusy}
                  onChange={() => onToggleTool(toolName)}
                  className="peer absolute inset-0 z-10 h-5 w-5 cursor-pointer opacity-0 disabled:cursor-not-allowed"
                />
                <span
                  aria-hidden
                  className={cn(
                    "pointer-events-none absolute inset-0 grid place-items-center rounded-compact border transition-colors",
                    selected
                      ? "border-foreground bg-foreground text-background"
                      : "border-border bg-background text-transparent",
                  )}
                >
                  <Check className="h-3 w-3" strokeWidth={2.75} />
                </span>
              </span>
              <code className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">
                {displayToolName(toolName, preset.name)}
              </code>
            </label>
          );
        }) : (
          <div className="px-4 py-10 text-center text-[12.5px] text-muted-foreground">
            {tx("settings.mcp.noMatchingTools", "No tools match this search.")}
          </div>
        )}
      </div>
    </div>
  );
}

function ConnectionPanel({
  preset,
  values,
  busy,
  connectBusy,
  removeBusy,
  requiredFieldsComplete,
  onFieldChange,
  onConnect,
  onRemove,
}: {
  preset: McpPresetInfo;
  values: Record<string, string>;
  busy: boolean;
  connectBusy: boolean;
  removeBusy: boolean;
  requiredFieldsComplete: boolean;
  onFieldChange: (presetName: string, fieldName: string, value: string) => void;
  onConnect: () => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const configuredInstalled = preset.installed && preset.configured;
  const hasFields = preset.required_fields.length > 0;
  const authentication = preset.auth === "oauth"
    ? "OAuth"
    : hasFields
      ? tx("settings.mcp.credentials", "Credentials")
      : tx("settings.mcp.none", "None");
  const connectionLabel = preset.transport === "stdio"
    ? tx("settings.mcp.command", "Command")
    : tx("settings.mcp.endpointLabel", "Endpoint");
  const connectLabel = configuredInstalled
    ? tx("settings.mcp.reconnect", "Reconnect")
    : tx("settings.mcp.setup", "Connect");
  return (
    <div className="space-y-5">
      <section aria-labelledby={`mcp-connection-${preset.name}`}>
        <h3 id={`mcp-connection-${preset.name}`} className="sr-only">
          {tx("settings.mcp.connectionDetails", "Connection details")}
        </h3>
        <div className="rounded-floating bg-muted/40 px-4 py-3.5">
          {preset.connection_summary ? (
            <div className="min-w-0">
              <p className="text-[12.5px] font-medium text-muted-foreground">{connectionLabel}</p>
              <code className="mt-1 block break-all text-[12.5px] leading-5 text-foreground">
                {preset.connection_summary}
              </code>
            </div>
          ) : null}
          <div className={cn(
            "flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted-foreground",
            preset.connection_summary && "mt-3 border-t border-border/45 pt-3",
          )}>
            <span>{formatTransport(preset.transport)}</span>
            <span>{authentication}</span>
            <div className="ml-auto flex items-center gap-1.5">
              {preset.docs_url ? (
                <a
                  href={preset.docs_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-8 items-center gap-1 rounded-full px-2 font-semibold text-foreground/65 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {tx("settings.mcp.openDocs", "Open docs")}
                  <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              ) : null}
              {configuredInstalled && preset.install_supported ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={onConnect}
                  className="h-8 rounded-full bg-background px-3 text-[12.5px] font-semibold"
                >
                  {connectBusy ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
                  ) : (
                    <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                  )}
                  {connectLabel}
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      {preset.error ? (
        <div role="alert" className="rounded-control bg-destructive/10 px-3.5 py-3 text-[12.5px] leading-5 text-destructive">
          {preset.error}
        </div>
      ) : null}

      {hasFields ? (
        <section>
          <h3 className="text-[13px] font-semibold text-foreground">
            {tx("settings.mcp.credentials", "Credentials")}
          </h3>
          <div className="mt-3 grid gap-3">
            {preset.required_fields.map((field) => {
              const inputId = `mcp-manage-${preset.name}-${field.name}`;
              return (
                <label key={field.name} htmlFor={inputId} className="min-w-0">
                  <span className="mb-1.5 flex items-center gap-2 text-[12.5px] font-medium text-muted-foreground">
                    {field.label}
                    {field.configured ? (
                      <span className="font-normal text-emerald-600 dark:text-emerald-300">
                        {tx("settings.mcp.configured", "Configured")}
                      </span>
                    ) : null}
                  </span>
                  <Input
                    id={inputId}
                    type={field.secret ? "password" : "text"}
                    value={values[field.name] ?? ""}
                    onChange={(event) => onFieldChange(preset.name, field.name, event.target.value)}
                    placeholder={field.configured ? tx("settings.mcp.keepExisting", "Leave blank to keep the current value") : field.placeholder}
                    className="h-10 rounded-full bg-muted/35 text-[12.5px]"
                  />
                </label>
              );
            })}
          </div>
        </section>
      ) : null}

      {!configuredInstalled && preset.install_supported ? (
        <div className="flex justify-end">
          <Button
            type="button"
            disabled={busy || !requiredFieldsComplete}
            onClick={onConnect}
            className="h-9 rounded-full px-4 text-[13px] font-semibold"
          >
            {connectBusy ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
            ) : (
              <Server className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {connectLabel}
          </Button>
        </div>
      ) : null}

      {preset.installed && preset.enabled === undefined ? (
        <section className="pt-1">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={onRemove}
            className="h-9 rounded-full px-3 text-[12.5px] font-semibold text-destructive hover:bg-destructive/10 hover:text-destructive"
          >
            {removeBusy ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
            ) : (
              <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {tx("settings.mcp.dangerZone", "Remove connection")}
          </Button>
        </section>
      ) : null}
    </div>
  );
}

function StatusPill({ children, tone }: { children: ReactNode; tone: "success" | "warning" | "neutral" }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
        tone === "success" && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
        tone === "warning" && "bg-destructive/10 text-destructive",
        tone === "neutral" && "bg-muted text-muted-foreground",
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full bg-current", tone === "neutral" && "opacity-55")} aria-hidden />
      {children}
    </span>
  );
}

function normalizeTools(tools: string[]): string[] {
  return tools.includes("*") ? ["*"] : [...tools].sort((left, right) => left.localeCompare(right));
}

function displayToolName(toolName: string, serverName: string): string {
  const wrappedPrefix = `mcp_${serverName}_`;
  return toolName.startsWith(wrappedPrefix) ? toolName.slice(wrappedPrefix.length) : toolName;
}

function formatTransport(transport: string): string {
  if (transport === "streamableHttp") return "Streamable HTTP";
  if (transport === "stdio") return "STDIO";
  if (transport === "sse") return "SSE";
  return transport || "MCP";
}
