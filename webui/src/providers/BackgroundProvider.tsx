import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useClient } from "@/providers/ClientProvider";
import { useObjectUrl } from "@/hooks/useObjectUrl";

interface BackgroundContextValue {
  hasBackground: boolean;
  image: Blob | null;
  blur: number;
  veil: number;
  setStyle: (blur: number, veil: number) => Promise<boolean>;
  busy: boolean;
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
  const { client, token } = useClient();
  const [image, setImage] = useState<Blob | null>(null);
  const imageUrl = useObjectUrl(image);
  const [blur, setBlurState] = useState(5);
  const [veil, setVeilState] = useState(88);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    const response = await fetch("/api/settings/background", {
      headers: { Authorization: `Bearer ${token}` }, credentials: "same-origin", cache: "no-store",
    });
    if (response.status === 404) { setImage(null); return; }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    setImage(await response.blob());
  }, [token]);

  useEffect(() => {
    if (!token) return;
    void load().catch(() => setImage(null));
    void fetch("/api/settings/background-style", { headers: { Authorization: `Bearer ${token}` }, credentials: "same-origin", cache: "no-store" })
      .then(async response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const value: unknown = await response.json();
        if (value && typeof value === "object" && "blur" in value && typeof value.blur === "number"
          && Number.isInteger(value.blur) && value.blur >= 0 && value.blur <= 20) setBlurState(value.blur);
        if (value && typeof value === "object" && "veil" in value && typeof value.veil === "number"
          && Number.isInteger(value.veil) && value.veil >= 0 && value.veil <= 100) setVeilState(value.veil);
      }).catch(() => setError(true));
  }, [load, token]);

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
    try { await client.uploadBackground(file); await load(); return true; }
    catch { setError(true); return false; }
    finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true); setError(false);
    try { await client.requestMutation("background.delete", {}); setImage(null); return true; }
    catch { setError(true); return false; }
    finally { setBusy(false); }
  };
  const setStyle = async (nextBlur: number, nextVeil: number) => {
    setBusy(true); setError(false);
    try { await client.requestMutation("background.style", { blur: nextBlur, veil: nextVeil }); setBlurState(nextBlur); setVeilState(nextVeil); return true; }
    catch { setError(true); return false; }
    finally { setBusy(false); }
  };
  return <BackgroundContext.Provider value={{ hasBackground: image !== null, image, blur, veil, setStyle, busy, error, upload, remove, clearError: () => setError(false) }}>
    {children}
  </BackgroundContext.Provider>;
}
