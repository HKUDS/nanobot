import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { flushSync } from "react-dom";
import "./theme-transition.css";

import { useMediaQuery } from "@/hooks/useMediaQuery";

export type ThemePreference = "system" | "light" | "dark";
type Theme = "light" | "dark";
const STORAGE_KEY = "nanobot-webui.theme";
const ThemeContext = createContext<Theme>("light");

function readStored(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function resolveTheme(preference: ThemePreference, systemDark: boolean): Theme {
  return preference === "system" ? (systemDark ? "dark" : "light") : preference;
}

function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "dark") root.classList.add("dark");
  else root.classList.remove("dark");

  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  const color =
    theme === "dark"
      ? themeColor?.dataset.themeColorDark
      : themeColor?.dataset.themeColorLight;
  if (themeColor && color) themeColor.content = color;
}

export function useTheme(): {
  theme: Theme;
  preference: ThemePreference;
  toggle: () => void;
  setTheme: (value: ThemePreference) => void;
} {
  const [preference, setPreference] = useState(readStored);
  const systemDark = useMediaQuery("(prefers-color-scheme: dark)");
  const theme = resolveTheme(preference, systemDark);

  const switchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const viewTransition = useRef<ViewTransition | null>(null);
  const pendingPreference = useRef<{ value: ThemePreference } | null>(null);
  useEffect(() => () => {
    if (switchTimer.current !== null) clearTimeout(switchTimer.current);
    switchTimer.current = null;
    pendingPreference.current = null;
    viewTransition.current?.skipTransition();
    viewTransition.current = null;
    delete document.documentElement.dataset.themeTransition;
    delete document.documentElement.dataset.themeSnapshot;
  }, []);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const refresh = (event: StorageEvent) => {
      if (event.key !== null && event.key !== STORAGE_KEY) return;
      if (event.storageArea && event.storageArea !== window.localStorage) return;
      const value = readStored();
      if (pendingPreference.current) pendingPreference.current.value = value;
      else setPreference(value);
    };
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, []);

  const setTheme = useCallback((value: ThemePreference) => {
    const pending = pendingPreference.current;
    const selected = pending?.value ?? preference;
    if (value === selected) return;
    const next = resolveTheme(value, systemDark);
    const changesPalette = next !== resolveTheme(selected, systemDark);
    const root = document.documentElement;
    // Same-palette choices, such as switching to System, must remain selectable.
    if (changesPalette) {
      if (switchTimer.current !== null || viewTransition.current !== null) return;
      root.dataset.themeTransition = next;
      switchTimer.current = setTimeout(() => {
        switchTimer.current = null;
        if (viewTransition.current === null) delete root.dataset.themeTransition;
      }, 600);
    }

    if (pending) {
      // A native capture defers the React commit; retain the latest accepted preference.
      pending.value = value;
    } else if (changesPalette && document.startViewTransition
      && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const update = { value };
      pendingPreference.current = update;
      root.dataset.themeSnapshot = "";
      const transition = document.startViewTransition(() => {
        if (pendingPreference.current !== update) return;
        pendingPreference.current = null;
        flushSync(() => setPreference(update.value));
      });
      viewTransition.current = transition;
      // Browser-skipped captures still apply their update and must release the owner.
      void transition.ready.catch(() => {});
      const release = () => {
        if (viewTransition.current !== transition) return;
        viewTransition.current = null;
        delete root.dataset.themeSnapshot;
        if (switchTimer.current === null) delete root.dataset.themeTransition;
      };
      void transition.finished.then(release, release);
    } else {
      setPreference(value);
    }
    // Only user choices persist. Resolved system changes and other tabs never write back.
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // Browser-only preferences should never block the interface.
    }
  }, [preference, systemDark]);
  const toggle = useCallback(
    () => setTheme(theme === "dark" ? "light" : "dark"),
    [setTheme, theme],
  );
  return { theme, preference, toggle, setTheme };
}

export function ThemeProvider({ theme, children }: { theme: Theme; children: ReactNode }) {
  return createElement(ThemeContext.Provider, { value: theme }, children);
}

export function useThemeValue(): Theme {
  return useContext(ThemeContext);
}
