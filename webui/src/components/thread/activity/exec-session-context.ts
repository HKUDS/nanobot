import { createContext } from "react";

/** Commands from exec events in the currently loaded transcript only. */
export const ExecSessionCommandsContext = createContext<ReadonlyMap<string, string>>(new Map());
