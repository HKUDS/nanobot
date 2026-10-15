import { Blocks, ExternalLink, Puzzle, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SETTINGS_SEARCH_INPUT_CLASS } from "@/components/settings/shared/SettingsControls";
import { SettingsTextEditor } from "@/components/settings/shared/SettingsTextEditor";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { WebUIExtensionSummary } from "@/lib/types";

interface ExtensionsCatalogSettingsProps {
  extensions: WebUIExtensionSummary[];
  onOpenExtension: (extensionId: string) => void;
  onToggleExtension?: (extensionId: string, enabled: boolean) => Promise<void> | void;
  onEditExtension?: (extensionId: string, config: Record<string, unknown>) => Promise<void> | void;
  onDeleteExtension?: (extensionId: string) => Promise<void> | void;
}

export function ExtensionsCatalogSettings({
  extensions,
  onOpenExtension,
  onToggleExtension,
  onEditExtension,
  onDeleteExtension,
}: ExtensionsCatalogSettingsProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "enabled" | "disabled">("all");
  const enabledCount = extensions.filter((extension) => extension.enabled !== false).length;
  const disabledCount = extensions.length - enabledCount;
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredExtensions = extensions.filter((extension) => {
    const enabled = extension.enabled !== false;
    if (filter === "enabled" && !enabled) return false;
    if (filter === "disabled" && enabled) return false;
    if (!normalizedQuery) return true;
    const haystack = `${extension.name} ${extension.id} ${extension.description}`.toLocaleLowerCase();
    return haystack.includes(normalizedQuery);
  });

  if (extensions.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
        <Puzzle className="h-10 w-10" aria-hidden />
        <p className="text-sm">{t("extensions.empty")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/70 bg-muted/30 px-4 py-3">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
            {t("extensions.label", { defaultValue: "Extensions" })}
          </p>
          <h2 className="mt-1 text-base font-semibold text-foreground">
            {t("extensions.installed", { count: extensions.length, defaultValue: "{{count}} installed" })}
          </h2>
        </div>
        <div className="flex items-center gap-2 text-[11px] font-medium">
          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-700 dark:text-emerald-300">
            {enabledCount} {t("extensions.enabled", { defaultValue: "enabled" })}
          </span>
          <span className="rounded-full border border-border/80 bg-background px-2.5 py-1 text-muted-foreground">
            {extensions.length} {t("extensions.total", { defaultValue: "total" })}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute start-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={t("extensions.search", { defaultValue: "Search extensions" })}
            placeholder={t("extensions.search", { defaultValue: "Search extensions" })}
            className={`h-12 ps-11 text-[15px] ${SETTINGS_SEARCH_INPUT_CLASS}`}
          />
        </div>
        <SegmentedControl
          value={filter}
          onChange={setFilter}
          options={([
            ["all", t("extensions.filterAll", { defaultValue: "All" }), extensions.length],
            ["enabled", t("extensions.filterEnabled", { defaultValue: "Enabled" }), enabledCount],
            ["disabled", t("extensions.filterDisabled", { defaultValue: "Disabled" }), disabledCount],
          ] as const).map(([value, label, count]) => ({
            value,
            label: (
              <>
                {label} <span className="ml-0.5 tabular-nums opacity-65">{count}</span>
              </>
            ),
          }))}
        />
      </div>

      {filteredExtensions.length ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filteredExtensions.map((extension) => {
            const enabled = extension.enabled !== false;
            const hasConfig = Boolean(extension.config && Object.keys(extension.config).length > 0);
            const skillName = typeof extension.config?.skill === "string" ? String(extension.config.skill) : undefined;

            return (
              <div
                key={extension.id}
                className={"flex h-full flex-col gap-3 rounded-2xl border border-border/70 bg-card p-4 shadow-sm transition-colors" + (enabled ? "" : " opacity-75")}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground">
                      <Blocks className="h-4.5 w-4.5" aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-semibold text-foreground">
                        {extension.name}
                      </h3>
                      <p className="truncate text-[11px] text-muted-foreground">
                        {extension.id} · {t("extensions.version", { version: extension.version })}
                      </p>
                    </div>
                  </div>
                  {onToggleExtension ? (
                    <ToggleButton
                      checked={enabled}
                      ariaLabel={t("extensions.toggle", {
                        name: extension.name,
                        defaultValue: "Toggle {{name}}",
                      })}
                      label={enabled ? t("settings.values.on", { defaultValue: "On" }) : t("settings.values.off", { defaultValue: "Off" })}
                      onChange={(next) => {
                        void onToggleExtension(extension.id, next);
                      }}
                    />
                  ) : null}
                </div>

                <p className="line-clamp-3 min-h-[2.75rem] text-xs leading-5 text-muted-foreground">
                  {extension.description}
                </p>

                <div className="flex flex-wrap gap-2 text-[10px] font-medium text-muted-foreground">
                  <span className="rounded-full border border-border/80 bg-background px-2 py-1">
                    {hasConfig ? t("extensions.configured", { defaultValue: "Configured" }) : t("extensions.default", { defaultValue: "Default" })}
                  </span>
                  {!enabled ? (
                    <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-amber-700 dark:text-amber-300">
                      {t("extensions.disabled", { defaultValue: "Disabled" })}
                    </span>
                  ) : null}
                  {skillName ? (
                    <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-2 py-1 text-violet-700 dark:text-violet-300">
                      {skillName}
                    </span>
                  ) : null}
                </div>

                <div className="mt-auto flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1 min-w-[110px]"
                    disabled={!enabled}
                    onClick={() => {
                      if (enabled) onOpenExtension(extension.id);
                    }}
                    aria-label={enabled ? `${t("extensions.open")} ${extension.name}` : `${t("extensions.open")} ${extension.name} (${t("extensions.disabled", { defaultValue: "Disabled" })})`}
                  >
                    <ExternalLink className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                    {t("extensions.open")}
                  </Button>
                  {onEditExtension ? (
                    <SettingsTextEditor
                      id={`edit-${extension.id}`}
                      title={`${extension.name} config`}
                      description={`${extension.name} configuration`}
                      value={JSON.stringify(extension.config ?? {}, null, 2) || "{}"}
                      placeholder='{"theme":"dark"}'
                      onSave={async (value) => {
                        let parsed: unknown;
                        try {
                          parsed = JSON.parse(value);
                        } catch {
                          throw new Error("Valid JSON is required.");
                        }
                        if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
                          throw new Error("Extension config must be a JSON object.");
                        }
                        await onEditExtension(extension.id, parsed as Record<string, unknown>);
                      }}
                    />
                  ) : null}
                </div>

                {onDeleteExtension ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full text-destructive hover:text-destructive"
                    onClick={() => void onDeleteExtension(extension.id)}
                  >
                    <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                    {t("extensions.delete", { defaultValue: "Delete" })}
                  </Button>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="px-3 py-12 text-center text-sm text-muted-foreground">
          {t("extensions.noResults", { defaultValue: "No extensions match your search." })}
        </div>
      )}
    </div>
  );
}
