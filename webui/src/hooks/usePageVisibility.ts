import { useEffect, useState } from "react";

function pageIsVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

export function usePageVisibility(): boolean {
  const [visible, setVisible] = useState(pageIsVisible);

  useEffect(() => {
    const update = () => setVisible(pageIsVisible());
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  return visible;
}
