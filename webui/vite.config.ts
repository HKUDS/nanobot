import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
const target = env.BLACKCAT_API_URL ?? "http://127.0.0.1:8765";
  const hmrPath = "/__blackcat_vite_hmr";
  const wsTarget = target.replace(/^http/, "ws");

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
      outDir: path.resolve(__dirname, "../blackcat/web/dist"),
      emptyOutDir: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes("node_modules/refractor/lang/")) {
              return;
            }
            if (
              id.includes("node_modules/react-syntax-highlighter")
              || id.includes("node_modules/refractor/core")
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
          },
        },
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
// Move Vite's HMR socket to a dedicated port so it doesn't collide with
      // the ``/`` proxy below (Vite HMR and the blackcat ws upgrade both sit on
      // the root path, which triggers spurious write-after-end errors as each
      // side tries to close the other's socket).
      hmr: {
        host: "127.0.0.1",
        path: hmrPath,
      },
      proxy: {
        "/webui": { target, changeOrigin: true },
        "/api": { target, changeOrigin: true },
        "/auth": { target, changeOrigin: true },
        // Forward only WebSocket upgrades on ``/`` to the blackcat gateway;
        // plain HTTP GETs on ``/`` must stay with Vite so it can serve the SPA.
        // ``bypass`` returning the original URL skips the proxy for that
        // request; returning undefined lets the proxy (and ws upgrade handler)
        // take it.
        "/": {
          target: wsTarget,
          ws: true,
          changeOrigin: true,
          bypass: (req) =>
            req.headers.upgrade === "websocket" ? undefined : req.url,
        },
      },
    },
    test: {
      environment: "happy-dom",
      globals: true,
      setupFiles: ["./src/tests/setup.ts"],
    },
  };
});
