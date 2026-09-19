import { createContext, useContext } from "react";

export const FloatingPortalContext = createContext<HTMLElement | null>(null);
export const useFloatingPortal = () => useContext(FloatingPortalContext);
