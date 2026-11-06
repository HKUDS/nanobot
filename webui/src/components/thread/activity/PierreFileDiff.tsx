import { FileDiff, getSharedHighlighter, getSingularPatch, registerCustomTheme, type FileDiffMetadata, type FileDiffOptions, type RenderRange } from "@pierre/diffs";
import { WorkerPoolManager } from "@pierre/diffs/worker";
import { isSupportedLanguage } from "@pierre/highlights";
import { bundledLanguages } from "shiki/langs";
import { useCallback, useContext, useLayoutEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useThemeValue } from "@/hooks/useTheme";
import { CODE_TEXTMATE_THEME, CODE_THEME, CODE_THEME_NAME, codeHighlighterLanguage } from "@/lib/code-theme";
import { DiffViewportContext } from "./DiffViewportContext";
import type { DiffSyntaxHighlightProps } from "./DiffSyntaxHighlight";
import { DIFF_GAP_HEIGHT, diffRenderWindow, diffRowOffsets } from "./diff-render-window";
import { selectedDiffRows } from "./diff-selection";

const THEME = CODE_THEME_NAME;
const CACHE_ENTRIES = 16;
const CACHE_SOURCE_BYTES = 2 * 1024 * 1024;
const metadataCache = new Map<string, FileDiffMetadata>();
let sourceBytes = 0;
let revision = 0;
let pool: WorkerPoolManager | undefined;
let grammarPool: WorkerPoolManager | undefined;
let preparation: Promise<void> | undefined;

registerCustomTheme(THEME, async () => CODE_THEME, "zed");
registerCustomTheme(THEME, async () => CODE_TEXTMATE_THEME, "textmate");

export function prepareDiffRenderer(): Promise<void> {
  return preparation ??= (async () => {
    await getSharedHighlighter({ themes: [THEME], langs: ["text"], preferredHighlighter: "highlights" });
    pool = new WorkerPoolManager({
      // The zero-worker pool owns the bounded AST cache; Highlights shares its main-thread engine with code blocks.
      workerFactory: () => { throw new Error("The Highlights cache does not create workers"); },
      poolSize: 0,
      totalASTLRUCacheSize: CACHE_ENTRIES,
      mainThreadMaxCharacters: Number.MAX_SAFE_INTEGER,
    }, { theme: THEME, preferredHighlighter: "highlights", lineDiffType: "word" });
  })();
}

function getGrammarPool(): WorkerPoolManager {
  return grammarPool ??= new WorkerPoolManager({
    workerFactory: () => new Worker(new URL("@pierre/diffs/worker/worker.js", import.meta.url), { type: "module" }),
    poolSize: 1, totalASTLRUCacheSize: CACHE_ENTRIES,
  }, { theme: THEME, preferredHighlighter: "shiki-js", lineDiffType: "word" });
}

export function getDiffMetadata(text: string, language: string): FileDiffMetadata {
  const alias = codeHighlighterLanguage(language);
  const lang = isSupportedLanguage(alias) || Object.hasOwn(bundledLanguages, alias)
    ? alias as NonNullable<FileDiffMetadata["lang"]> : "text";
  const key = `${lang}\0${text}`;
  const cached = metadataCache.get(key);
  if (cached) {
    metadataCache.delete(key);
    metadataCache.set(key, cached);
    return cached;
  }
  const metadata = getSingularPatch(text);
  metadata.lang = lang;
  const bytes = key.length * 2;
  if (bytes <= CACHE_SOURCE_BYTES) {
    while (metadataCache.size >= CACHE_ENTRIES || sourceBytes + bytes > CACHE_SOURCE_BYTES) {
      const [oldKey, oldMetadata] = metadataCache.entries().next().value!;
      metadataCache.delete(oldKey);
      sourceBytes -= oldKey.length * 2;
      pool?.evictDiffFromCache(oldMetadata.cacheKey!);
      grammarPool?.evictDiffFromCache(oldMetadata.cacheKey!);
    }
    metadata.cacheKey = `nanobot-diff-${++revision}`;
    metadataCache.set(key, metadata);
    sourceBytes += bytes;
  }
  return metadata;
}

export function PierreFileDiff({ text, language, diff, lineLimit }: DiffSyntaxHighlightProps) {
  const theme = useThemeValue();
  const { t } = useTranslation();
  const viewport = useContext(DiffViewportContext);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<FileDiff>();
  const metadata = useMemo(() => getDiffMetadata(text, language), [text, language]);
  const needsGrammar = !isSupportedLanguage(metadata.lang!);
  const gapLabel = useCallback((count: number) => `…  ${t("message.fileEditUnchangedLinesHidden", { count, defaultValue: "{{count}} unchanged lines hidden" })}`, [t]);
  const options = useMemo<FileDiffOptions<undefined, undefined>>(() => ({
    theme: THEME, themeType: theme, preferredHighlighter: "highlights", diffStyle: "unified", diffIndicators: "classic",
    disableFileHeader: true, lineDiffType: "word",
    // Function separators disable Pierre's incremental row updates and destroy native selections.
    hunkSeparators: "line-info",
    onPostRender: (node, _instance, phase) => {
      if (phase === "unmount") return;
      for (const gap of node.shadowRoot!.querySelectorAll<HTMLElement>("[data-separator]")) {
        const nextIndex = Number(gap.nextElementSibling?.getAttribute("data-line-index")?.split(",")[0]);
        const hunk = metadata.hunks.find(item => item.unifiedLineStart === nextIndex);
        const label = gap.querySelector<HTMLElement>("[data-unmodified-lines]");
        if (!hunk || !label) continue;
        const text = gapLabel(hunk.collapsedBefore);
        if (label.textContent !== text) label.textContent = text;
        if (gap.closest("[data-gutter]")) label.dataset.testid = "file-edit-diff-hunk-gap";
      }
    },
    unsafeCSS: `:host, pre, code { font: inherit; } pre { padding-block: 0; } [data-line], [data-column-number] { padding-block: 1px; } [data-separator] { height: ${DIFF_GAP_HEIGHT}px; margin: 0; padding: 0; } [data-separator-wrapper], [data-separator-content] { background: transparent; color: hsl(var(--muted-foreground)); } [data-separator-wrapper] { padding-inline: 8px; background: hsl(var(--muted) / .35); font-size: 11px; } [data-separator-first], [data-separator-last] { display: none; }`,
  }), [theme, gapLabel, metadata]);

  useLayoutEffect(() => {
    const wrapper = wrapperRef.current!;
    const instance = new FileDiff({ theme: THEME, preferredHighlighter: "highlights" }, needsGrammar ? getGrammarPool() : pool);
    instanceRef.current = instance;
    return () => { instance.cleanUp(); instanceRef.current = undefined; wrapper.replaceChildren(); };
  }, [needsGrammar]);

  useLayoutEffect(() => {
    const wrapper = wrapperRef.current!;
    const instance = instanceRef.current!;
    instance.setOptions(options);
    const scroller = viewport?.scroller.current;
    const eventTarget = scroller ?? window;
    let frame = 0;
    let previous: RenderRange | undefined;
    let forceRender = true;
    const render = () => {
      frame = 0;
      const lineHeight = Math.floor((parseFloat(getComputedStyle(wrapper).lineHeight) + 2) * 64) / 64;
      const offsets = diffRowOffsets(diff, lineLimit, lineHeight);
      const rootRect = scroller?.getBoundingClientRect();
      const wrapperTop = wrapper.getBoundingClientRect().top;
      const top = (rootRect?.top ?? 0) - wrapperTop;
      const height = rootRect?.height ?? window.innerHeight;
      const range = diffRenderWindow(diff, offsets, top - height, top + height * 2, lineHeight, selectedDiffRows(wrapper, metadata));
      if (!forceRender && previous && Object.keys(range).every(key => range[key as keyof RenderRange] === previous![key as keyof RenderRange])) return;
      previous = range;
      instance.render({ fileDiff: metadata, containerWrapper: wrapper, renderRange: range, forceRender });
      forceRender = false;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(render); };
    // This observer projects a read-only window; ThreadCameraController remains the sole scroll writer.
    const resize = new ResizeObserver(schedule);
    resize.observe(wrapper);
    if (scroller) resize.observe(scroller);
    if (viewport?.content.current) resize.observe(viewport.content.current);
    const typography = new MutationObserver(schedule);
    typography.observe(document.documentElement, { attributes: true, attributeFilter: ["data-reading-text-size"] });
    eventTarget.addEventListener("scroll", schedule, { passive: true });
    document.addEventListener("selectionchange", schedule);
    window.addEventListener("resize", schedule);
    render();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      typography.disconnect();
      eventTarget.removeEventListener("scroll", schedule);
      document.removeEventListener("selectionchange", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [diff, lineLimit, metadata, options, viewport]);

  return <div ref={wrapperRef} className="nanobot-file-diff font-mono text-code-dense" data-testid="syntax-highlighted-diff-hunk" data-language={language} />;
}
