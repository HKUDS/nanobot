import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = fileURLToPath(new URL("../../../../../", import.meta.url));
const webuiRoot = path.join(repoRoot, "webui");
const webuiDependencies = path.join(webuiRoot, "node_modules");

export default {
  root: webuiRoot,
  esbuild: {
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": path.join(webuiRoot, "src"),
      "@testing-library/react": path.join(webuiDependencies, "@testing-library/react"),
      "@testing-library/user-event": path.join(
        webuiDependencies,
        "@testing-library/user-event",
      ),
      "lucide-react": path.join(webuiDependencies, "lucide-react"),
      "react": path.join(webuiDependencies, "react"),
      "react-dom": path.join(webuiDependencies, "react-dom"),
      "react-i18next": path.join(webuiDependencies, "react-i18next"),
      "vitest": path.join(webuiDependencies, "vitest"),
    },
  },
  server: {
    fs: {
      allow: [repoRoot],
    },
  },
  test: {
    dir: repoRoot,
    environment: "happy-dom",
    globals: true,
    include: ["nanobot/channels/telegram/tests/webui/**/*.test.tsx"],
    setupFiles: [path.join(webuiRoot, "src/tests/setup.ts")],
  },
};
