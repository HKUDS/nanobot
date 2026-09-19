import { createContext, useContext } from "react";

export const ThreadVisibilityContext = createContext(true);
export function useThreadVisibility(): boolean {
  return useContext(ThreadVisibilityContext);
}
