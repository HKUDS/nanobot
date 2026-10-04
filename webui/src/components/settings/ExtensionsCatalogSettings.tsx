import { Blocks, ExternalLink, Puzzle, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SettingsTextEditor } from "@/components/settings/shared/SettingsTextEditor";
import { Button } from "@/components/ui/button";
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
  const enabledCount = extensions.filter((extension) => extension.enabled !== false).length;

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

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {extensions.map((extension) => {
          const enabled = extension.enabled !== false;
          const hasConfig = Boolean(extension.config && Object.keys(extension.config).length > 0);
          const skillName = typeof extension.config?.skill === "string" ? String(extension.config.skill) : undefined;

          return (
            <div
              key={extension.id}
              className="flex h-full flex-col gap-3 rounded-2xl border border-border/70 bg-card p-4 shadow-sm transition-colors"
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
                <span
                  className={[
                    "rounded-full border px-2 py-1 text-[10px] font-medium",
                    enabled
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                      : "border-border/80 bg-muted text-muted-foreground",
                  ].join(" ")}
                >
                  {enabled ? t("extensions.enabled", { defaultValue: "Enabled" }) : t("extensions.disabled", { defaultValue: "Disabled" })}
                </span>
              </div>

              <p className="line-clamp-3 min-h-[2.75rem] text-xs leading-5 text-muted-foreground">
                {extension.description}
              </p>

              <div className="flex flex-wrap gap-2 text-[10px] font-medium text-muted-foreground">
                <span className="rounded-full border border-border/80 bg-background px-2 py-1">
                  {hasConfig ? t("extensions.configured", { defaultValue: "Configured" }) : t("extensions.default", { defaultValue: "Default" })}
                </span>
                {skillName ? (
                  <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-2 py-1 text-violet-700 dark:text-violet-300">
                    {skillName}
                  </span>
                ) : null}
              </div>

              <div className="mt-auto flex flex-wrap gap-2">
                {onToggleExtension ? (
                  <Button
                    variant={enabled ? "outline" : "secondary"}
                    size="sm"
                    className="flex-1 min-w-[110px]"
                    onClick={() => void onToggleExtension(extension.id, !enabled)}
                  >
                    {enabled ? t("extensions.disable") : t("extensions.enable")}
                  </Button>
                ) : null}
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 min-w-[110px]"
                  onClick={() => onOpenExtension(extension.id)}
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
    </div>
  );
}
