import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Dev proxy: avoid browser CORS when calling token_issue HTTP route or WebSocket
 * on another origin. Set VITE_NANOBOT_PROXY_TARGET (e.g. http://127.0.0.1:8765).
 * Connect WebSocket to: ws://localhost:5173/nanobot-dev/?client_id=...
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_NANOBOT_PROXY_TARGET ?? "http://127.0.0.1:8765";

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/nanobot-dev": {
          target: proxyTarget,
          changeOrigin: true,
          ws: true,
          rewrite: (path) => {
            const stripped = path.replace(/^\/nanobot-dev/, "");
            if (!stripped || stripped === "") {
              return "/";
            }
            return stripped.startsWith("/") ? stripped : `/${stripped}`;
          },
        },
      },
    },
  };
});
