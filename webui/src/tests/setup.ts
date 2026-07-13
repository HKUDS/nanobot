import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

import i18n from "@/i18n";

function createTestStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.get(String(key)) ?? null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(String(key));
    },
    setItem(key: string, value: string) {
      store.set(String(key), String(value));
    },
  };
}

if (
  typeof window !== "undefined" &&
  (typeof globalThis.localStorage === "undefined" ||
    typeof globalThis.localStorage.setItem !== "function")
) {
  const storage = createTestStorage();
  Object.defineProperty(window, "localStorage", {
    value: storage,
    configurable: true,
  });
  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    configurable: true,
    writable: true,
  });
}

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

beforeEach(async () => {
  await i18n.changeLanguage("en");
  document.documentElement.lang = "en";
  document.title = "nanobot";
  localStorage.setItem("nanobot.locale", "en");
});
