import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/input";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ToggleButton } from "@/components/ui/toggle-button";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import { foundationExamples } from "./foundations";
import { sharedExamples } from "./shared-views";
import { foundationPath, type ComponentSource } from "./inventory";

export const examples = [...foundationExamples, ...sharedExamples];

function selectedPath(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get("component") ?? `${foundationPath}button.tsx`;
}

export function Gallery() {
  const { theme, setTheme } = useTheme();
  const [inventory, setInventory] = useState<ComponentSource[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("All");
  const [selected, setSelected] = useState(selectedPath);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void fetch("/__nanobot_components", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load the inventory. Check the Vite terminal and retry.");
        const data: ComponentSource[] = await response.json();
        setInventory(data);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    const change = () => setSelected(selectedPath());
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);

  const groups = ["All", "Foundations", ...new Set(inventory.map((item) => item.group).filter((item) => item !== "Foundations"))];
  const search = query.trim().toLowerCase();
  const filtered = inventory.filter((item) => (group === "All" || item.group === group)
    && `${item.path} ${item.exports.join(" ")} ${examples.find((example) => example.files.includes(item.path))?.title ?? ""}`.toLowerCase().includes(search));
  const current = inventory.find((item) => item.path === selected) ?? inventory[0];
  const example = current && examples.find((item) => item.files.includes(current.path));

  return <ThemeProvider theme={theme}>
    <div className="component-gallery">
      <header className="gallery-header">
        <div className="flex min-w-0 items-center gap-3">
          <img src="/brand/nanobot_icon_192.png" alt="" className="h-9 w-9" />
          <div><h1 className="text-base font-semibold">Component gallery · 组件图鉴</h1>
            <p className="text-xs text-muted-foreground">Nanobot internal UI reference</p></div>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs"><span>Dark mode</span>
            <ToggleButton checked={theme === "dark"} onChange={(dark) => setTheme(dark ? "dark" : "light")} label="Dark mode" /></label>
          <LanguageSwitcher />
        </div>
      </header>
      <div className="gallery-workspace">
        <aside className="gallery-sidebar" aria-label="Component navigation">
          <SearchInput type="search" aria-label="Search components" placeholder="Search name, path / 搜索组件" value={query} onChange={(event) => setQuery(event.target.value)} />
          <label className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">Category
            <select aria-label="Component category" value={group} onChange={(event) => setGroup(event.target.value)}
              className="min-w-0 flex-1 rounded-control border bg-background px-2 py-2 text-foreground">
              {groups.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <p className="my-3 text-xs text-muted-foreground" role="status">{loading ? "Reading source inventory…" : `${filtered.length} / ${inventory.length} source modules`}</p>
          <nav className="gallery-source-list" aria-label="Component sources">
            {filtered.map((item) => <a key={item.path} href={`#${new URLSearchParams({ component: item.path })}`}
              aria-current={current?.path === item.path ? "page" : undefined}
              className={cn("block rounded-control px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
                current?.path === item.path ? "bg-sidebar-selected text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
              <span className="block truncate">{item.name}</span><span className="block truncate text-[11px] opacity-70">{item.group}</span>
            </a>)}
            {!loading && filtered.length === 0 ? <p className="px-3 py-5 text-sm text-muted-foreground">No matching components.</p> : null}
          </nav>
          <Button variant="ghost" size="sm" className="mt-3 w-full" disabled={loading} onClick={() => setReload((value) => value + 1)}>Refresh inventory</Button>
        </aside>
        <main className="gallery-main">
          {error ? <div role="alert" className="rounded-control border border-destructive/30 p-4 text-sm text-destructive">{error}</div> : null}
          {current ? <article className="mx-auto max-w-5xl" key={current.path}>
            <p className="mb-2 text-xs text-muted-foreground">{current.group}</p>
            <h2 className="text-2xl font-semibold tracking-tight">{example?.title ?? current.name}</h2>
            <p className="mt-3 break-all font-mono text-xs text-muted-foreground">{current.path}</p>
            {example ? <>
              <p className="mt-5 text-sm leading-6 text-muted-foreground">{example.description}</p>
              <section aria-label="Component preview" className="gallery-preview mt-6"><example.Preview /></section>
              <section className="mt-8 space-y-3"><h3 className="text-sm font-semibold">Usage · 使用方法</h3>
                <p className="text-sm leading-6 text-muted-foreground">{example.options}</p><pre className="gallery-code"><code>{example.code}</code></pre>
                {example.files.length > 1 ? <p className="text-xs leading-5 text-muted-foreground">This example composes: {example.files.map((file) => file.split("/").pop()).join(", ")}</p> : null}
              </section>
            </> : <p className="mt-6 rounded-control bg-muted/50 p-4 text-sm leading-6 text-muted-foreground">
              This module belongs to the {current.group.toLowerCase()} interface. Its live screen owns application state and gateway actions.
              Use the source and references below to find its existing composition. 此条目提供源码与引用位置，完整交互在所属功能中查看。
            </p>}
            <section className="mt-8 space-y-3"><h3 className="text-sm font-semibold">Exports · 导出</h3>
              <p className="break-words font-mono text-xs leading-6 text-muted-foreground">{current.exports.join(", ") || "Internal module"}</p>
            </section>
            <section className="mt-8 space-y-3"><h3 className="text-sm font-semibold">Direct references · 使用位置</h3>
              <p className="text-xs leading-5 text-muted-foreground">Imports and re-exports in product source; tests and this gallery are excluded. Plugin registration may also load modules indirectly.</p>
              {current.usedBy.length ? <ul className="space-y-2">{current.usedBy.map((file) => <li key={file} className="break-all font-mono text-xs text-muted-foreground">{file}</li>)}</ul>
                : <p className="text-sm text-muted-foreground">No direct source references found.</p>}
            </section>
            <details className="mt-8 rounded-control border p-4"><summary className="cursor-pointer text-sm font-semibold">Source code · 源码</summary>
              <pre className="gallery-code mt-4 max-h-[32rem]"><code>{current.source}</code></pre></details>
          </article> : !error ? <p className="text-sm text-muted-foreground">{loading ? "Loading components…" : "No component source files found."}</p> : null}
        </main>
      </div>
    </div>
  </ThemeProvider>;
}
