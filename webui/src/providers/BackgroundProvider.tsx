import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useClient } from "@/providers/ClientProvider";
import { useObjectUrl } from "@/hooks/useObjectUrl";
import { fetchWithTimeout } from "@/lib/http";

interface BackgroundContextValue {
  hasBackground: boolean;
  image: Blob | null;
  blur: number;
  veil: number;
  setStyle: (blur: number, veil: number) => Promise<boolean>;
  busy: boolean;
  ready: boolean;
  loadError: boolean;
  retry: () => void;
  error: boolean;
  upload: (file: File) => Promise<boolean>;
  remove: () => Promise<boolean>;
  clearError: () => void;
}

const BackgroundContext = createContext<BackgroundContextValue | null>(null);

export function useBackground() {
  return useContext(BackgroundContext);
}

export function BackgroundProvider({ children }: { children: ReactNode }) {
  const { client, token, getToken } = useClient();
  const hasToken = !!token;
  const [image, setImage] = useState<Blob | null>(null);
  const imageUrl = useObjectUrl(image);
  const [blur, setBlurState] = useState(5);
  const [veil, setVeilState] = useState(88);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [imageStatus, setImageStatus] = useState<"loading" | "ready" | "error">("loading");
  const [styleStatus, setStyleStatus] = useState<"loading" | "ready" | "error">("loading");
  const versions = useRef({ image: 0, style: 0 });

  const loadImage = useCallback(async () => {
    const version = ++versions.current.image;
    setImageStatus(current => current === "error" ? "loading" : current);
    try {
      const response = await fetchWithTimeout("/api/settings/background", {
        headers: { Authorization: `Bearer ${getToken()}` }, credentials: "same-origin", cache: "no-store",
      });
      if (!response.ok && response.status !== 404) throw new Error(`HTTP ${response.status}`);
      const next = response.status === 404 ? null : await response.blob();
      if (versions.current.image === version) { setImage(next); setImageStatus("ready"); }
    } catch {
      if (versions.current.image === version) setImageStatus("error");
    }
  }, [getToken]);

  const loadStyle = useCallback(async () => {
    const version = ++versions.current.style;
    setStyleStatus(current => current === "error" ? "loading" : current);
    try {
      const response = await fetchWithTimeout("/api/settings/background-style", {
        headers: { Authorization: `Bearer ${getToken()}` }, credentials: "same-origin", cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const value: unknown = await response.json();
      if (!value || typeof value !== "object" || !("blur" in value) || !("veil" in value)
        || typeof value.blur !== "number" || !Number.isInteger(value.blur) || value.blur < 0 || value.blur > 20
        || typeof value.veil !== "number" || !Number.isInteger(value.veil) || value.veil < 0 || value.veil > 100) {
        throw new Error("Invalid background style");
      }
      if (versions.current.style === version) { setBlurState(value.blur); setVeilState(value.veil); setStyleStatus("ready"); }
    } catch {
      if (versions.current.style === version) setStyleStatus("error");
    }
  }, [getToken]);

  const refresh = useCallback(() => { void loadImage(); void loadStyle(); }, [loadImage, loadStyle]);

  useEffect(() => {
    if (!hasToken) return;
    refresh();
    return () => {
      versions.current.image++; versions.current.style++;
    };
  }, [hasToken, refresh]);

  useEffect(() => {
    if (!imageUrl) return;
    const root = document.documentElement;
    root.style.setProperty("--custom-background-image", `url("${imageUrl}")`);
    root.setAttribute("data-custom-background", "");
    return () => {
      root.style.removeProperty("--custom-background-image");
      root.removeAttribute("data-custom-background");
    };
  }, [imageUrl]);

  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--custom-background-blur", `${blur}px`);
    root.style.setProperty("--custom-background-tint", `${veil / 100}`);
    return () => {
      root.style.removeProperty("--custom-background-blur");
      root.style.removeProperty("--custom-background-tint");
    };
  }, [blur, veil]);

  const upload = async (file: File) => {
    setBusy(true); setError(false);
    const version = ++versions.current.image;
    try {
      await client.uploadBackground(file);
      if (versions.current.image === version) { setImage(file); setImageStatus("ready"); }
      return true;
    } catch { setError(true); return false; }
    finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true); setError(false);
    const version = ++versions.current.image;
    try {
      await client.requestMutation("background.delete", {});
      if (versions.current.image === version) { setImage(null); setImageStatus("ready"); }
      return true;
    } catch { setError(true); return false; }
    finally { setBusy(false); }
  };
  const setStyle = async (nextBlur: number, nextVeil: number) => {
    setBusy(true); setError(false);
    const version = ++versions.current.style;
    try {
      await client.requestMutation("background.style", { blur: nextBlur, veil: nextVeil });
      if (versions.current.style === version) { setBlurState(nextBlur); setVeilState(nextVeil); setStyleStatus("ready"); }
      return true;
    } catch { setError(true); return false; }
    finally { setBusy(false); }
  };
  return <BackgroundContext.Provider value={{ hasBackground: image !== null, image, blur, veil, setStyle, busy,
    ready: imageStatus === "ready" && styleStatus === "ready", loadError: imageStatus === "error" || styleStatus === "error",
    retry: refresh, error, upload, remove, clearError: () => setError(false) }}>
    {children}
  </BackgroundContext.Provider>;
}
