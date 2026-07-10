import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export function webuiManualChunk(id: string): string | undefined {
  if (id.includes("node_modules/refractor/lang/")) {
    return;
  }
  // Refractor reaches this HAST helper through hastscript. Keeping it with
  // Refractor prevents syntax-highlight <-> markdown-vendor circular chunks.
  if (
    id.includes("node_modules/react-syntax-highlighter")
    || id.includes("node_modules/refractor/core")
    || id.includes("node_modules/hast-util-parse-selector")
  ) {
    return "syntax-highlight";
  }
  if (
    id.includes("node_modules/react-markdown")
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
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    optimizeDeps: {
      // Keep dev reloads stable for dependencies that can rewrite generated
      // optimizer chunk filenames while a browser tab is still running. Do not
      // exclude the markdown/remark/rehype chain: Vite's pre-bundling is needed
      // there for CommonJS interop such as style-to-js.
      exclude: [
        "@radix-ui/react-dialog",
        "react-syntax-highlighter/dist/esm/prism-async-light",
        "react-syntax-highlighter/dist/esm/styles/prism/one-dark",
        "react-syntax-highlighter/dist/esm/styles/prism/one-light",
      ],
    },
    build: {
      outDir: path.resolve(__dirname, "../nanobot/web/dist"),
      emptyOutDir: true,
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
    },
  };
});
