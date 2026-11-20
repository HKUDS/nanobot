import { defineConfig, loadEnv, transformWithEsbuild, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readStartupLayout, StartupSkeleton } from "./src/components/StartupSkeleton";
import { componentGallery } from "./src/dev/gallery/inventory-plugin";

function startupSkeleton(): Plugin {
  return {
    name: "nanobot-startup-skeleton",
    transformIndexHtml: {
      order: "post",
      handler(html) {
        if (!html.includes("<!--startup-shell-->")) return html;
        const css = ["src/components/content-column.css", "src/components/settings/shared/catalog-layout.css", "src/components/startup-skeleton.css"]
          .map((file) => readFileSync(path.resolve(__dirname, file), "utf8")).join("\n");
        const initialize = `var shell = document.querySelector('.startup-shell'); var layout = (${readStartupLayout.toString()})();
          shell.dataset.startupSurface = layout.surface; shell.dataset.startupSection = layout.section;
          shell.dataset.sidebarExpanded = String(layout.sidebarExpanded); shell.dataset.existingChat = String(layout.existingChat);
          shell.dataset.calendarWeeks = String(layout.calendarWeeks);
          shell.style.setProperty('--startup-sidebar-width', (layout.sidebarExpanded ? layout.sidebarWidth : 56) + 'px');`;
        return html.replace("<!--startup-style-->", `<style>${css}</style>`)
          .replace("<!--startup-shell-->", renderToStaticMarkup(createElement(StartupSkeleton)))
          .replace("<!--startup-script-->", `<script>${initialize}</script>`)
          .replace(/<link rel="stylesheet"/g, '<link rel="preload" as="style" data-app-stylesheet');
      },
    },
  };
}

const GZIP_MIN_BYTES = 4 * 1024;
const GZIP_ASSET_PATTERN = /\.(?:css|html|js|json|mjs|svg)$/i;
const LAZY_FEATURE_CHUNK_PREFIXES = ["markdown-vendor-", "markdown-diagrams-", "MermaidBlock-", "HighlightedCode-", "code-highlighter-", "PierreFileDiff-", "katex-"];

export function entryLazyFeatureImports(imports: string[]): string[] {
  return imports.filter((fileName) =>
    LAZY_FEATURE_CHUNK_PREFIXES.some((prefix) => path.basename(fileName).startsWith(prefix)),
  );
}

function guardWebuiChunkBoundaries(): Plugin {
  return {
    name: "nanobot-guard-webui-chunk-boundaries",
    apply: "build",
    generateBundle(_options, bundle) {
      for (const output of Object.values(bundle)) {
        if (output.type !== "chunk") continue;
        if (output.isEntry) {
          const unexpected = entryLazyFeatureImports(output.imports);
          if (unexpected.length > 0) {
            this.error(`WebUI entry chunk statically imports lazy features: ${unexpected.join(", ")}`);
          }
        }
        if (!output.moduleIds.some((id) => /\/(?:PierreFileDiff\.tsx|code-highlighter-grammars\.ts)$/.test(id))) continue;
        const visited = new Set<string>();
        const pending = [output.fileName];
        for (const fileName of pending) {
          if (visited.has(fileName)) continue;
          visited.add(fileName);
          if (path.basename(fileName).startsWith("markdown-vendor-")) {
            this.error(`${output.fileName} statically loads the Markdown parser via ${fileName}`);
          }
          const dependency = bundle[fileName];
          if (dependency?.type === "chunk") pending.push(...dependency.imports);
        }
      }
    },
  };
}

const PIERRE_WORKER_MODULES = "/node_modules/@pierre/diffs/dist/worker/";

function specializePierreDiffWorker(): Plugin {
  return {
    name: "nanobot-specialize-pierre-diff-worker",
    enforce: "pre",
    transform(code, id) {
      if (!id.includes(PIERRE_WORKER_MODULES) || !code.includes("__DIFFS_WORKER__")) return;
      // Pierre's pool resolves grammars and themes on the main thread and sends them to the worker.
      return transformWithEsbuild(code, id, {
        loader: "js",
        define: { __DIFFS_WORKER__: "true" },
        minifySyntax: true,
      });
    },
    generateBundle(_options, bundle) {
      const chunks = Object.values(bundle).filter((output) => output.type === "chunk");
      if (!chunks.some((chunk) => chunk.isEntry && chunk.facadeModuleId?.includes(PIERRE_WORKER_MODULES))) return;
      if (chunks.some((chunk) => chunk.moduleIds.some((id) => /\/node_modules\/@shikijs\/(?:langs|themes)\//.test(id)))) {
        this.error("Pierre diff Worker bundles Shiki grammars or themes that should come from the main thread");
      }
    },
  };
}

export function writeCompressedWebuiAssets(outputDir: string, fileNames: string[]): void {
  for (const fileName of fileNames) {
    if (!GZIP_ASSET_PATTERN.test(fileName)) continue;
    const outputPath = path.resolve(outputDir, fileName);
    const bytes = readFileSync(outputPath);
    if (bytes.byteLength < GZIP_MIN_BYTES) continue;
    const compressed = gzipSync(bytes, { level: 9 });
    if (compressed.byteLength >= bytes.byteLength) continue;
    writeFileSync(`${outputPath}.gz`, compressed);
  }
}

export function gzipWebuiAssets(): Plugin {
  return {
    name: "nanobot-gzip-webui-assets",
    apply: "build",
    writeBundle(options, bundle) {
      const outputDir = options.dir ?? (options.file ? path.dirname(options.file) : undefined);
      if (!outputDir) {
        throw new Error("WebUI gzip build requires a Rollup output directory");
      }
      writeCompressedWebuiAssets(outputDir, Object.keys(bundle));
    },
  };
}

const HTML_SERIALIZER_PACKAGES = [
  "hast-util-to-html", "hast-util-whitespace", "property-information", "html-void-elements",
  "comma-separated-tokens", "space-separated-tokens", "stringify-entities", "ccount",
  "character-entities-html4", "character-entities-legacy", "zwitch",
];

export function webuiManualChunk(id: string): string | undefined {
  const locale = /\/webui\/locales\/([^/]+)\.json$/.exec(id)?.[1]
    ?? /\/src\/i18n\/locales\/([^/]+)\/common\.json$/.exec(id)?.[1];
  if (locale) return `locale-${locale}`;
  // Clipboard actions are shared with lazy Markdown and must not pull it into the shell.
  if (id.endsWith("/src/lib/clipboard.ts")) return "clipboard";
  if (id.endsWith("/src/lib/markdown-math.ts")
    || id.includes("node_modules/rehype-katex/")
    // The micromark barrel also exports an HTML renderer that imports KaTeX.
    || (id.includes("node_modules/micromark-extension-math/") && id.endsWith("/html.js"))) {
    return "markdown-math";
  }
  if (
    id.includes("node_modules/react/")
    || id.includes("node_modules/react-dom/")
    || id.includes("node_modules/scheduler/")
    || id.includes("node_modules/clsx/")
    || id.includes("vite/preload-helper")
  ) {
    return "react-vendor";
  }
  // Streamdown retains a lazy viewer shell, not the native Mermaid engine.
  if (id.includes("node_modules/streamdown/dist/mermaid-")) return "markdown-diagrams";
  if (id.includes("node_modules/streamdown/dist/highlighted-body-")) return "markdown-code";
  // Keep the serializer and its dependencies together so syntax highlighting never loads the Markdown parser.
  if (HTML_SERIALIZER_PACKAGES.some((name) => id.includes(`/node_modules/${name}/`))) return "html-serializer";
  if (
    id.includes("node_modules/streamdown")
    || id.includes("node_modules/remend")
    || id.includes("node_modules/remark-")
    || id.includes("node_modules/rehype-")
    || id.includes("node_modules/unified")
    || id.includes("node_modules/mdast-")
    || id.includes("node_modules/hast-")
    || id.includes("node_modules/micromark")
    || id.includes("node_modules/unist-")
  ) {
    return "markdown-vendor";
  }
  if (id.includes("node_modules/katex")) {
    return "katex";
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.NANOBOT_API_URL ?? "http://127.0.0.1:8765";
  const hmrPath = "/__nanobot_vite_hmr";

  return {
    plugins: [react(), startupSkeleton(), componentGallery(path.resolve(__dirname, "..")), guardWebuiChunkBoundaries(), gzipWebuiAssets()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
      // Channel-owned UI lives beside the Python package, outside webui/.
      // Resolve its shared frontend dependencies from this app's root.
      dedupe: ["react", "react-dom", "lucide-react", "react-i18next", "qrcode"],
    },
    optimizeDeps: {
      // Pre-bundle Dialog up front, including lazy settings/sheets. Excluding
      // it splits its layer/focus state from optimized Popover and DropdownMenu,
      // so nested overlays can dismiss the wrong layer in development.
      include: [
        "@radix-ui/react-dialog",
        "@pierre/diffs", "@pierre/diffs/worker", "@pierre/highlights",
        "shiki/core", "shiki/langs", "shiki/engine/javascript",
        // Vite's HTML scan does not follow the lazy Worker entry. Discovering
        // these imports on first render would reload the page and lose UI state.
        "pele/lazy", "saxes", "css-tree/parser", "css-tree/walker", "css-tree/generator",
      ],
    },
    worker: { format: "es", plugins: () => [specializePierreDiffWorker()] },
    build: {
      outDir: path.resolve(__dirname, "../nanobot/web/dist"),
      emptyOutDir: true,
      manifest: "asset-manifest.json",
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks: webuiManualChunk,
        },
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      fs: {
        allow: [path.resolve(__dirname, "..")],
      },
      // Keep Vite's HMR socket on a dedicated path. Nanobot's app WebSocket is
      // opened directly from the browser to the gateway, so the dev server
      // should never proxy WebSocket upgrades.
      hmr: {
        host: "127.0.0.1",
        path: hmrPath,
      },
      proxy: {
        "/webui": { target, changeOrigin: true },
        "/api": { target, changeOrigin: true },
        "/auth": { target, changeOrigin: true },
      },
    },
    test: {
      environment: "happy-dom",
      globals: true,
      setupFiles: ["./src/tests/setup.ts"],
      include: [
        "src/**/*.{test,spec}.{ts,tsx}",
        "../nanobot/channels/*/tests/webui/**/*.{test,spec}.{ts,tsx}",
      ],
      coverage: {
        provider: "v8",
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/tests/**", "src/dev/**", "src/**/*.d.ts"],
        reporter: ["text", "json-summary"],
        thresholds: {
          statements: 85,
          branches: 80,
          functions: 80,
          lines: 85,
        },
      },
    },
  };
});
