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

type Theme = "light" | "dark";
const STORAGE_KEY = "nanobot-webui.theme";
const ThemeContext = createContext<Theme>("light");

function readStored(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
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
  toggle: () => void;
  setTheme: (t: Theme) => void;
} {
  const [theme, setThemeState] = useState<Theme>(() => {
    const stored = readStored();
    if (stored) return stored;
    if (typeof window !== "undefined" && window.matchMedia) {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    }
    return "light";
  });

  const switchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const viewTransition = useRef<ViewTransition | null>(null);
  useEffect(() => () => {
    if (switchTimer.current !== null) clearTimeout(switchTimer.current);
    switchTimer.current = null;
    viewTransition.current?.skipTransition();
    viewTransition.current = null;
    delete document.documentElement.dataset.themeTransition;
    delete document.documentElement.dataset.themeSnapshot;
  }, []);

  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    if (next === theme || switchTimer.current !== null || viewTransition.current !== null) return;
    const root = document.documentElement;
    root.dataset.themeTransition = next;
    switchTimer.current = setTimeout(() => {
      switchTimer.current = null;
      if (viewTransition.current === null) delete root.dataset.themeTransition;
    }, 600);

    if (!document.startViewTransition || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setThemeState(next);
      return;
    }

    root.dataset.themeSnapshot = "";
    const transition = document.startViewTransition(() => {
      flushSync(() => setThemeState(next));
    });
    viewTransition.current = transition;
    // Hidden documents and competing browser transitions can skip the animation;
    // the theme update still runs, and input must be released in either case.
    void transition.ready.catch(() => {});
    const release = () => {
      if (viewTransition.current !== transition) return;
      viewTransition.current = null;
      delete root.dataset.themeSnapshot;
      if (switchTimer.current === null) delete root.dataset.themeTransition;
    };
    void transition.finished.then(release, release);
  }, [theme]);
  const toggle = useCallback(
    () => setTheme(theme === "dark" ? "light" : "dark"),
    [setTheme, theme],
  );
  return { theme, toggle, setTheme };
}

export function ThemeProvider({ theme, children }: { theme: Theme; children: ReactNode }) {
  return createElement(ThemeContext.Provider, { value: theme }, children);
}

export function useThemeValue(): Theme {
  return useContext(ThemeContext);
}
