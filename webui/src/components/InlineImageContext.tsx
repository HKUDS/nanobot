import { createContext, useCallback, useContext, useLayoutEffect, useState, type ReactNode } from "react";

const InlineImages = createContext<ReadonlyMap<string, number>>(new Map());
const RegisterImage = createContext<((url: string) => () => void) | undefined>(undefined);

/** Deduplicate only images actually rendered in this answer, not links or code examples. */
export function InlineImageProvider({ children }: { children: ReactNode }) {
  const [urls, setUrls] = useState<ReadonlyMap<string, number>>(new Map());
  const register = useCallback((url: string) => {
    const update = (delta: number) => setUrls((previous) => {
      const next = new Map(previous);
      const count = (next.get(url) ?? 0) + delta;
      if (count > 0) next.set(url, count);
      else next.delete(url);
      return next;
    });
    update(1);
    return () => update(-1);
  }, []);
  return <RegisterImage.Provider value={register}>
    <InlineImages.Provider value={urls}>{children}</InlineImages.Provider>
  </RegisterImage.Provider>;
}

export function useRegisterInlineImage(url?: string) {
  const register = useContext(RegisterImage);
  useLayoutEffect(() => url ? register?.(url) : undefined, [register, url]);
}

export function useInlineImages() {
  return useContext(InlineImages);
}
