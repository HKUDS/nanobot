import ReactDOM from "react-dom/client";

import App from "./App";
import "./globals.css";
import "./i18n";
import { initializeLoopbackRuntimeHost } from "./lib/runtime";

const PRELOAD_RECOVERY_KEY = "nanobot-webui.preload-recovery-at";
const PRELOAD_RECOVERY_WINDOW_MS = 10_000;

// A long-lived tab can request a lazy chunk removed by a newer deployment.
// Reload through the no-cache HTML entry once, then preserve the plain-text
// fallback if a persistent network or deployment error survives the refresh.
window.addEventListener("vite:preloadError", (event) => {
  try {
    const now = Date.now();
    const previousAttempt = Number(window.sessionStorage.getItem(PRELOAD_RECOVERY_KEY));
    if (Number.isFinite(previousAttempt) && now - previousAttempt < PRELOAD_RECOVERY_WINDOW_MS) {
      return;
    }
    window.sessionStorage.setItem(PRELOAD_RECOVERY_KEY, String(now));
  } catch {
    return;
  }
  event.preventDefault();
  window.location.reload();
});

// `crypto.randomUUID` is only defined in secure contexts (HTTPS or localhost).
// LAN access over plain HTTP leaves it undefined, which crashes components that
// generate client-side message IDs. Shim a v4-ish fallback so call sites stay
// uniform across secure and non-secure contexts.
if (typeof globalThis.crypto !== "undefined" && !("randomUUID" in globalThis.crypto)) {
  Object.defineProperty(globalThis.crypto, "randomUUID", {
    value: () =>
      "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      }),
    configurable: true,
  });
}

const root = document.getElementById("root");
if (!root) throw new Error("root element missing");

initializeLoopbackRuntimeHost();

/* StrictMode disabled: dev double-invokes state updaters; delta accumulation must stay pure — see useNanobotStream. */
ReactDOM.createRoot(root).render(<App />);
