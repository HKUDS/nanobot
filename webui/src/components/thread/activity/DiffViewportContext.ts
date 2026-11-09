import { createContext, type RefObject } from "react";

export const DiffViewportContext = createContext<{
  scroller: RefObject<HTMLElement>;
  content: RefObject<HTMLElement>;
} | null>(null);
