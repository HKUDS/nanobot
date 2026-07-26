import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, CircleAlert, Download, Loader2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  fetchExtensions,
  runExtensionAction,
  searchExtensions,
  type ExtensionAction,
} from "@/lib/api";
import type {
  ExtensionDiagnosticInfo,
  ExtensionInfo,
  ExtensionMarketPackage,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

import { ExtensionDetailSheet } from "./ExtensionDetailSheet";
import {
  EmptyState,
  type ExtensionEcosystem,
  ExtensionMark,
  type ExtensionTab,
  filterExtensions,
  filterPackages,
  LoadingState,
  RuntimeBadge,
  StatusBadge,
} from "./extension-ui";

export function ExtensionsCatalog() {
  const { t } = useTranslation();
  const { token } = useClient();
  const [tab, setTab] = useState<ExtensionTab>("installed");
  const [ecosystem, setEcosystem] = useState<ExtensionEcosystem>("all");
  const [query, setQuery] = useState("");
  const [extensions, setExtensions] = useState<ExtensionInfo[]>([]);
  const [diagnostics, setDiagnostics] = useState<ExtensionDiagnosticInfo[]>([]);
  const [packages, setPackages] = useState<ExtensionMarketPackage[]>([]);
  const [selected, setSelected] = useState<ExtensionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchExtensions(token);
      setExtensions(payload.extensions);
      setDiagnostics(payload.diagnostics);
      setError(null);
      setSelected((current) =>
        current
          ? payload.extensions.find((item) => item.id === current.id) ?? null
          : null,
      );
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (tab !== "discover") return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setSearching(true);
      searchExtensions(token, query, ecosystem)
        .then((payload) => {
          if (!cancelled) {
            setPackages(payload.packages);
            setError(null);
          }
        })
        .catch((reason) => {
          if (!cancelled) setError((reason as Error).message);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [ecosystem, query, tab, token]);

  const installed = useMemo(
    () => extensions.filter((extension) => extension.scope !== "builtin"),
    [extensions],
  );
  const builtin = useMemo(
    () => extensions.filter((extension) => extension.scope === "builtin"),
    [extensions],
  );
  const installedIds = useMemo(
    () =>
      new Set(
        installed.flatMap((extension) =>
          [extension.id, extension.source_ref].filter(Boolean),
        ),
      ),
    [installed],
  );

  const mutate = useCallback(
    async (
      action: ExtensionAction,
      values: Record<string, unknown>,
      key: string,
    ) => {
      setBusy(key);
      try {
        await runExtensionAction(token, action, values);
        await refresh();
        setError(null);
      } catch (reason) {
        setError((reason as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [refresh, token],
  );

  const tabs: Array<{ key: ExtensionTab; count?: number }> = [
    { key: "installed", count: installed.length },
    { key: "discover" },
    { key: "builtin", count: builtin.length },
  ];

  return (
    <div className="space-y-5">
      <section className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div
          className="inline-flex w-fit rounded-[12px] bg-muted/55 p-1"
          aria-label={t("extensions.tabs.label")}
        >
          {tabs.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={tab === item.key}
              onClick={() => setTab(item.key)}
              className={cn(
                "h-8 rounded-[9px] px-3 text-[12px] font-medium text-muted-foreground transition-colors",
                tab === item.key && "bg-background text-foreground shadow-sm",
              )}
            >
              {t(`extensions.tabs.${item.key}`)}
              {item.count === undefined ? null : (
                <span className="ml-1.5 text-muted-foreground">{item.count}</span>
              )}
            </button>
          ))}
        </div>
        {tab === "discover" ? (
          <EcosystemFilter value={ecosystem} onChange={setEcosystem} />
        ) : null}
      </section>

      <label className="relative block">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t(
            tab === "discover"
              ? "extensions.searchMarket"
              : "extensions.searchInstalled",
          )}
          className="h-11 rounded-[14px] border-border/55 bg-settings-surface pl-10 text-[13px] shadow-none"
        />
      </label>

      {error ? (
        <div className="rounded-[14px] bg-destructive/10 px-3.5 py-3 text-[13px] text-destructive">
          {error}
        </div>
      ) : null}

      {tab === "discover" ? (
        <MarketList
          packages={filterPackages(packages, query)}
          installedIds={installedIds}
          loading={searching}
          busy={busy}
          onInstall={(item) =>
            void mutate(
              "install",
              { source: item.name, kind: "npm" },
              `install:${item.name}`,
            )
          }
        />
      ) : (
        <ExtensionList
          extensions={filterExtensions(tab === "builtin" ? builtin : installed, query)}
          diagnostics={diagnostics}
          loading={loading}
          emptyKey={tab}
          onSelect={setSelected}
        />
      )}

      <ExtensionDetailSheet
        extension={selected}
        diagnostics={diagnostics.filter(
          (diagnostic) => diagnostic.extension_id === selected?.id,
        )}
        busy={busy}
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        onAction={(action, values) =>
          mutate(action, values, `${action}:${selected?.id ?? ""}`)
        }
      />
    </div>
  );
}

function EcosystemFilter({
  value,
  onChange,
}: {
  value: ExtensionEcosystem;
  onChange: (value: ExtensionEcosystem) => void;
}) {
  const { t } = useTranslation();
  const items: ExtensionEcosystem[] = ["all", "nanobot", "pi", "openclaw"];
  return (
    <div className="flex items-center gap-1 overflow-x-auto">
      {items.map((item) => (
        <button
          key={item}
          type="button"
          aria-pressed={value === item}
          onClick={() => onChange(item)}
          className={cn(
            "h-8 shrink-0 rounded-full px-2.5 text-[12px] text-muted-foreground transition-colors",
            value === item && "bg-muted text-foreground",
          )}
        >
          {t(`extensions.ecosystem.${item}`)}
        </button>
      ))}
    </div>
  );
}

function ExtensionList({
  extensions,
  diagnostics,
  loading,
  emptyKey,
  onSelect,
}: {
  extensions: ExtensionInfo[];
  diagnostics: ExtensionDiagnosticInfo[];
  loading: boolean;
  emptyKey: "installed" | "builtin";
  onSelect: (extension: ExtensionInfo) => void;
}) {
  const { t } = useTranslation();
  if (loading) return <LoadingState />;
  if (!extensions.length) {
    return <EmptyState label={t(`extensions.empty.${emptyKey}`)} />;
  }
  const diagnosticIds = new Set(diagnostics.map((item) => item.extension_id));
  return (
    <section className="overflow-hidden rounded-[18px] bg-settings-surface">
      {extensions.map((extension, index) => (
        <button
          key={`${extension.scope}:${extension.id}`}
          type="button"
          onClick={() => onSelect(extension)}
          className={cn(
            "group flex w-full min-w-0 items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-muted/35",
            index > 0 && "border-t border-border/40",
          )}
        >
          <ExtensionMark runtime={extension.runtime} />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate text-[14px] font-medium text-foreground">
                {extension.name}
              </h3>
              <RuntimeBadge runtime={extension.runtime} />
            </div>
            <p className="mt-0.5 truncate text-[12px] text-muted-foreground">
              {extension.description || extension.id}
            </p>
          </div>
          {diagnosticIds.has(extension.id) ? (
            <CircleAlert className="h-4 w-4 shrink-0 text-amber-500" aria-hidden />
          ) : null}
          <StatusBadge extension={extension} />
        </button>
      ))}
    </section>
  );
}

function MarketList({
  packages,
  installedIds,
  loading,
  busy,
  onInstall,
}: {
  packages: ExtensionMarketPackage[];
  installedIds: Set<string>;
  loading: boolean;
  busy: string | null;
  onInstall: (item: ExtensionMarketPackage) => void;
}) {
  const { t } = useTranslation();
  if (loading) return <LoadingState />;
  if (!packages.length) return <EmptyState label={t("extensions.empty.discover")} />;
  return (
    <section className="overflow-hidden rounded-[18px] bg-settings-surface">
      {packages.map((item, index) => {
        const installed = installedIds.has(item.name);
        const actionKey = `install:${item.name}`;
        return (
          <div
            key={`${item.ecosystem}:${item.name}`}
            className={cn(
              "flex min-w-0 items-center gap-3 px-4 py-3.5",
              index > 0 && "border-t border-border/40",
            )}
          >
            <ExtensionMark runtime={item.ecosystem} />
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <h3 className="truncate text-[14px] font-medium text-foreground">
                  {item.name}
                </h3>
                <RuntimeBadge runtime={item.ecosystem} />
                <span className="shrink-0 text-[11px] text-muted-foreground">
                  {item.version}
                </span>
              </div>
              <p className="mt-0.5 line-clamp-1 text-[12px] text-muted-foreground">
                {item.description}
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={installed || busy === actionKey}
              aria-label={
                installed
                  ? t("extensions.installed")
                  : t("extensions.install", { name: item.name })
              }
              title={
                installed
                  ? t("extensions.installed")
                  : t("extensions.install", { name: item.name })
              }
              onClick={() => onInstall(item)}
              className="h-9 w-9 shrink-0 rounded-full bg-muted/55"
            >
              {busy === actionKey ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : installed ? (
                <Check className="h-4 w-4" aria-hidden />
              ) : (
                <Download className="h-4 w-4" aria-hidden />
              )}
            </Button>
          </div>
        );
      })}
    </section>
  );
}
