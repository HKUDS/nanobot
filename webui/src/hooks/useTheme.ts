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
  const theme: Theme = preference === "system" ? (systemDark ? "dark" : "light") : preference;

  const switchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (switchTimer.current !== null) {
      clearTimeout(switchTimer.current);
      switchTimer.current = null;
      delete document.documentElement.dataset.themeTransition;
    }
  }, []);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const refresh = (event: StorageEvent) => {
      if (event.key !== null && event.key !== STORAGE_KEY) return;
      if (event.storageArea && event.storageArea !== window.localStorage) return;
      setPreference(readStored());
    };
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, []);

  const setTheme = useCallback((value: ThemePreference) => {
    if (value === preference) return;
    const next = value === "system" ? (systemDark ? "dark" : "light") : value;
    // Changing preference without changing the palette must not start or block a transition.
    if (next !== theme) {
      if (switchTimer.current !== null) return;
      document.documentElement.dataset.themeTransition = next;
      switchTimer.current = setTimeout(() => {
        delete document.documentElement.dataset.themeTransition;
        switchTimer.current = null;
      }, 600);
    }
    setPreference(value);
    // Only user choices persist. Resolved system changes and other tabs never write back.
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // Browser-only preferences should never block the interface.
    }
  }, [preference, systemDark, theme]);
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
