import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, Download, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  fetchExtensions,
  runExtensionAction,
  type ExtensionAction,
} from "@/lib/api";
import type { ExtensionDiagnosticInfo, ExtensionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

import { ExtensionDetailSheet } from "./ExtensionDetailSheet";
import {
  EmptyState,
  ExtensionMark,
  filterExtensions,
  LoadingState,
  StatusBadge,
} from "./extension-ui";

type InstallKind = "git" | "local";

export function ExtensionsCatalog() {
  const { t } = useTranslation();
  const { token } = useClient();
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [kind, setKind] = useState<InstallKind>("git");
  const [extensions, setExtensions] = useState<ExtensionInfo[]>([]);
  const [diagnostics, setDiagnostics] = useState<ExtensionDiagnosticInfo[]>([]);
  const [selected, setSelected] = useState<ExtensionInfo | null>(null);
  const [loading, setLoading] = useState(true);
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

  const visible = useMemo(
    () => filterExtensions(extensions, query),
    [extensions, query],
  );

  return (
    <div className="space-y-5">
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          const value = source.trim();
          if (!value) return;
          void mutate("install", { source: value, kind }, "install");
        }}
      >
        <select
          value={kind}
          onChange={(event) => setKind(event.target.value as InstallKind)}
          aria-label={t("extensions.installKind")}
          className="h-11 rounded-[14px] border border-border/55 bg-settings-surface px-3 text-[13px] text-foreground outline-none"
        >
          <option value="git">{t("extensions.source.git")}</option>
          <option value="local">{t("extensions.source.local")}</option>
        </select>
        <Input
          value={source}
          onChange={(event) => setSource(event.target.value)}
          placeholder={t(
            kind === "git"
              ? "extensions.installGitPlaceholder"
              : "extensions.installLocalPlaceholder",
          )}
          className="h-11 flex-1 rounded-[14px] border-border/55 bg-settings-surface text-[13px] shadow-none"
        />
        <Button
          type="submit"
          disabled={!source.trim() || busy === "install"}
          className="h-11 rounded-[14px] px-4"
        >
          <Download className="mr-2 h-4 w-4" aria-hidden />
          {t("extensions.installAction")}
        </Button>
      </form>

      <label className="relative block">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("extensions.searchInstalled")}
          className="h-11 rounded-[14px] border-border/55 bg-settings-surface pl-10 text-[13px] shadow-none"
        />
      </label>

      {error ? (
        <div className="rounded-[14px] bg-destructive/10 px-3.5 py-3 text-[13px] text-destructive">
          {error}
        </div>
      ) : null}

      <ExtensionList
        extensions={visible}
        diagnostics={diagnostics}
        loading={loading}
        onSelect={setSelected}
      />

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

function ExtensionList({
  extensions,
  diagnostics,
  loading,
  onSelect,
}: {
  extensions: ExtensionInfo[];
  diagnostics: ExtensionDiagnosticInfo[];
  loading: boolean;
  onSelect: (extension: ExtensionInfo) => void;
}) {
  const { t } = useTranslation();
  if (loading) return <LoadingState />;
  if (!extensions.length) {
    return <EmptyState label={t("extensions.empty.installed")} />;
  }
  const diagnosticIds = new Set(diagnostics.map((item) => item.extension_id));
  return (
    <section className="overflow-hidden rounded-[18px] bg-settings-surface">
      {extensions.map((extension, index) => (
        <button
          key={extension.id}
          type="button"
          onClick={() => onSelect(extension)}
          className={cn(
            "group flex w-full min-w-0 items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-muted/35",
            index > 0 && "border-t border-border/40",
          )}
        >
          <ExtensionMark />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate text-[14px] font-medium text-foreground">
                {extension.name}
              </h3>
            </div>
            <p className="mt-0.5 truncate text-[12px] text-muted-foreground">
              {extension.description || extension.id}
            </p>
          </div>
          {diagnosticIds.has(extension.id) ? (
            <CircleAlert
              className="h-4 w-4 shrink-0 text-amber-500"
              aria-hidden
            />
          ) : null}
          <StatusBadge extension={extension} />
        </button>
      ))}
    </section>
  );
}
