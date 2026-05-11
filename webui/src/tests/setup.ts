import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

import i18n from "@/i18n";

// happy-dom doesn't ship with ``crypto.randomUUID``; shim a tiny v4-ish helper.
if (!("randomUUID" in globalThis.crypto)) {
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

// Bun's test runtime injects its own ``localStorage`` stub before happy-dom
// can install a working one, so we override both ``window.localStorage`` and
// ``globalThis.localStorage`` with a minimal in-memory Storage implementation
// so ``getItem``/``setItem`` are real functions in tests.
const installStorageShim = () => {
  const store = new Map<string, string>();
  const shim: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key) => (store.has(key) ? (store.get(key) as string) : null),
    key: (index) => Array.from(store.keys())[index] ?? null,
    removeItem: (key) => {
      store.delete(key);
    },
    setItem: (key, value) => {
      store.set(String(key), String(value));
    },
  };
  Object.defineProperty(window, "localStorage", {
    value: shim,
    configurable: true,
  });
  Object.defineProperty(globalThis, "localStorage", {
    value: shim,
    configurable: true,
  });
};

installStorageShim();

beforeEach(async () => {
  await i18n.changeLanguage("en");
  document.documentElement.lang = "en";
  document.title = "nanobot";
  localStorage.setItem("nanobot.locale", "en");
});
