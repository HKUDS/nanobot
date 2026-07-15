import { useEffect, useState } from "react";

export function useMediaQuery(query: string, fallback = false): boolean {
  const readMatch = () => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return fallback;
    }
    return window.matchMedia(query).matches;
  };

  const [matches, setMatches] = useState(readMatch);

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    )
      return;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return matches;
}
