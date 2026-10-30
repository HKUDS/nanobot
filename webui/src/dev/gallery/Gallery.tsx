import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/input";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { ToggleButton } from "@/components/ui/toggle-button";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import { foundationExamples } from "./foundations";
import { sharedExamples } from "./shared-views";
import { settingsExamples } from "./settings";
import { providerExamples } from "./providers";
import { conversationExamples } from "./conversation";
import { shellExamples } from "./shell";
import { standaloneExamples } from "./standalone";
import { remoteExamples } from "./remote";
import { contentExamples } from "./content";
import { runtimeSettingsExamples } from "./runtime-settings";
import { channelExamples, withChannelEntries } from "./channels";
import { feishuWhatsAppChannelExamples } from "./channels-feishu-whatsapp";
import { linearChannelExamples } from "./channels-linear";
import { qqChannelExamples } from "./channels-qq";
import { weixinChannelExamples } from "./channels-weixin";
import { foundationPath, type ComponentSource } from "./inventory";
import { useGalleryTranslation } from "./i18n";

export const examples = [...foundationExamples, ...sharedExamples, ...settingsExamples, ...providerExamples, ...conversationExamples, ...shellExamples, ...standaloneExamples, ...remoteExamples, ...contentExamples, ...runtimeSettingsExamples,
  ...channelExamples, ...withChannelEntries([...feishuWhatsAppChannelExamples, ...linearChannelExamples, ...qqChannelExamples, ...weixinChannelExamples])];
const examplesByPath = new Map(examples.flatMap((example) => example.files.map((file) => [file, example] as const)));
const groupKeys: Record<string, string> = {
  All: "all", "Shared views & shell": "shared", Icons: "icons", Hosts: "hosts", Settings: "settings",
  "Settings / shared": "settingsShared", Conversation: "conversation", Foundations: "foundations", Workbench: "workbench",
};

function selectedPath(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get("component") ?? `${foundationPath}button.tsx`;
}

export function Gallery() {
  const { theme, setTheme } = useTheme();
  const { t } = useGalleryTranslation();
  const [inventory, setInventory] = useState<ComponentSource[]>([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("All");
  const [selected, setSelected] = useState(selectedPath);
  const [view, setView] = useState<"previews" | "all">(() => examplesByPath.has(selectedPath()) ? "previews" : "all");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    void fetch("/__nanobot_components", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Inventory request failed: ${response.status}`);
        const data: ComponentSource[] = await response.json();
        setInventory(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    const change = () => {
      const next = selectedPath();
      setSelected(next);
      if (!examplesByPath.has(next)) setView("all");
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);

  useEffect(() => { document.title = t("ui.pageTitle"); }, [t]);

  const exampleTitle = (example: (typeof examples)[number]) => t(example.title, example.titleValues);
  const groupLabel = (name: string): string => {
    return name.startsWith("Channels / ")
      ? t("ui.groups.channel", { channel: name.slice("Channels / ".length) })
      : t(`ui.groups.${groupKeys[name]}`);
  };
  const previewCount = inventory.filter((item) => examplesByPath.has(item.path)).length;
  const browsable = view === "previews" ? inventory.filter((item) => examplesByPath.has(item.path)) : inventory;
  const groups = ["All", ...new Set(browsable.map((item) => item.group))];
  const search = query.trim().toLowerCase();
  const filtered = browsable.filter((item) => {
    const example = examplesByPath.get(item.path);
    return (group === "All" || item.group === group)
      && `${item.path} ${item.exports.join(" ")} ${example ? exampleTitle(example) : ""}`.toLowerCase().includes(search);
  });
  const current = browsable.find((item) => item.path === selected) ?? browsable[0];
  const example = current && examplesByPath.get(current.path);
  const relatedExamples = current && !example ? examples.filter((item) => item.files.some((file) =>
    current.usedBy.includes(file) || inventory.find((source) => source.path === file)?.usedBy.includes(current.path))) : [];

  return <ThemeProvider theme={theme}>
    <div className="component-gallery">
      <header className="gallery-header">
        <div className="flex min-w-0 items-center gap-3">
          <img src="/brand/nanobot_icon_192.png" alt="" className="h-9 w-9" />
          <div><h1 className="text-base font-semibold">{t("ui.title")}</h1>
            <p className="text-xs text-muted-foreground">{t("ui.subtitle")}</p></div>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs"><span>{t("ui.darkMode")}</span>
            <ToggleButton checked={theme === "dark"} onChange={(dark) => setTheme(dark ? "dark" : "light")} label={t("ui.darkMode")} /></label>
          <LanguageSwitcher />
        </div>
      </header>
      <div className="gallery-workspace">
        <aside className="gallery-sidebar" aria-label={t("ui.navigation")}>
          <SegmentedControl value={view} ariaLabel={t("ui.inventoryView")} className="mb-4 w-full"
            options={[{ value: "previews", label: t("ui.previews") }, { value: "all", label: t("ui.allSource") }]}
            onChange={(next) => {
              setView(next);
              setGroup("All");
              if (next === "previews" && !examplesByPath.has(selected)) {
                const first = inventory.find((item) => examplesByPath.has(item.path));
                if (first) window.location.hash = new URLSearchParams({ component: first.path }).toString();
              }
            }} />
          <SearchInput type="search" aria-label={t("ui.search")} placeholder={t("ui.searchPlaceholder")} value={query} onChange={(event) => setQuery(event.target.value)} />
          <label className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">{t("ui.category")}
            <select aria-label={t("ui.componentCategory")} value={group} onChange={(event) => setGroup(event.target.value)}
              className="min-w-0 flex-1 rounded-control border bg-background px-2 py-2 text-foreground">
              {groups.map((item) => <option key={item} value={item}>{groupLabel(item)}</option>)}
            </select>
          </label>
          <p className="my-3 text-xs leading-5 text-muted-foreground" role="status">{loading ? t("ui.readingInventory")
            : view === "previews" ? t("ui.previewCount", { visible: filtered.length, total: previewCount })
              : t("ui.sourceCount", { visible: filtered.length, total: inventory.length, previews: previewCount })}</p>
          <nav className="gallery-source-list" aria-label={t("ui.sources")}>
            {filtered.map((item) => <a key={item.path} href={`#${new URLSearchParams({ component: item.path })}`}
              aria-current={current?.path === item.path ? "page" : undefined}
              className={cn("block rounded-control px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
                current?.path === item.path ? "bg-sidebar-selected text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
              <span className="flex items-center justify-between gap-2"><span className="truncate">{item.name}</span>
                {view === "all" ? <span className="shrink-0 text-[10px] opacity-70">{examplesByPath.has(item.path) ? t("ui.previewBadge") : t("ui.sourceOnlyBadge")}</span> : null}</span>
              <span className="block truncate text-[11px] opacity-70">{groupLabel(item.group)}</span>
            </a>)}
            {!loading && filtered.length === 0 ? <div className="space-y-3 px-3 py-5 text-sm text-muted-foreground">
              <p>{t(view === "previews" ? "ui.noPreviews" : "ui.noSources")}</p>
              {query || group !== "All" ? <Button variant="outline" size="sm" onClick={() => { setQuery(""); setGroup("All"); }}>{t("ui.clearFilters")}</Button> : null}
              {view === "previews" ? <Button variant="ghost" size="sm" onClick={() => { setView("all"); setGroup("All"); }}>{t("ui.searchAllSource")}</Button> : null}
            </div> : null}
          </nav>
          <Button variant="ghost" size="sm" className="mt-3 w-full" disabled={loading} onClick={() => setReload((value) => value + 1)}>{t("ui.refreshInventory")}</Button>
        </aside>
        <main className="gallery-main">
          {error ? <div role="alert" className="rounded-control border border-destructive/30 p-4 text-sm text-destructive">{t("ui.inventoryFailure")}</div> : null}
          {current ? <article className="mx-auto max-w-5xl" key={current.path}>
            <p className="mb-2 text-xs text-muted-foreground">{groupLabel(current.group)}</p>
            <h2 className="text-2xl font-semibold tracking-tight">{example ? exampleTitle(example) : current.name}</h2>
            <p className="mt-3 break-all font-mono text-xs text-muted-foreground">{current.path}</p>
            {example ? <>
              <p className="mt-5 text-sm leading-6 text-muted-foreground">{t(example.description)}</p>
              <section aria-label={t("ui.componentPreview")} className="gallery-preview mt-6"><example.Preview /></section>
              <section className="mt-8 space-y-3"><h3 className="text-sm font-semibold">{t("ui.usage")}</h3>
                <p className="text-sm leading-6 text-muted-foreground">{t(example.options)}</p><pre className="gallery-code"><code>{example.code}</code></pre>
                {example.files.length > 1 ? <p className="text-xs leading-5 text-muted-foreground">{t("ui.composedModules", { modules: example.files.map((file) => file.split("/").pop()).join(", ") })}</p> : null}
              </section>
            </> : <section className="mt-6 space-y-3 rounded-control border p-4">
              <h3 className="text-sm font-semibold">{t("ui.sourceOnlyTitle")}</h3>
              <p className="text-sm leading-6 text-muted-foreground">{t("ui.sourceOnlyDescription")}</p>
              {relatedExamples.length > 0 ? <div className="space-y-2">
                <p className="text-xs text-muted-foreground">{t("ui.relatedPreviews")}</p>
                <ul className="space-y-2">{relatedExamples.map((item) => <li key={item.files[0]}>
                  <a className="text-sm underline underline-offset-4" href={`#${new URLSearchParams({ component: item.files[0] })}`}>{exampleTitle(item)}</a>
                </li>)}</ul>
              </div> : null}
            </section>}
            <section className="mt-8 space-y-3"><h3 className="text-sm font-semibold">{t("ui.exports")}</h3>
              <p className="break-words font-mono text-xs leading-6 text-muted-foreground">{current.exports.join(", ") || t("ui.internalModule")}</p>
            </section>
            <section className="mt-8 space-y-3"><h3 className="text-sm font-semibold">{t("ui.references")}</h3>
              <p className="text-xs leading-5 text-muted-foreground">{t("ui.referencesDescription")}</p>
              {current.usedBy.length ? <ul className="space-y-2">{current.usedBy.map((file) => <li key={file} className="break-all font-mono text-xs text-muted-foreground">{file}</li>)}</ul>
                : <p className="text-sm text-muted-foreground">{t("ui.noReferences")}</p>}
            </section>
            <details className="mt-8 rounded-control border p-4"><summary className="cursor-pointer text-sm font-semibold">{t("ui.sourceCode")}</summary>
              <pre className="gallery-code mt-4 max-h-[32rem]"><code>{current.source}</code></pre></details>
          </article> : !error ? <p className="text-sm text-muted-foreground">{t(loading ? "ui.loadingComponents" : "ui.noComponentFiles")}</p> : null}
        </main>
      </div>
    </div>
  </ThemeProvider>;
}
