import { createContext, useContext, type ReactNode } from "react";

export type FilePreviewAvailabilityResolver = (path: string) => Promise<boolean>;

const FilePreviewAvailabilityContext = createContext<
  FilePreviewAvailabilityResolver | undefined
>(undefined);

export function FilePreviewAvailabilityProvider({
  children,
  resolve,
}: {
  children: ReactNode;
  resolve?: FilePreviewAvailabilityResolver;
}) {
  return (
    <FilePreviewAvailabilityContext.Provider value={resolve}>
      {children}
    </FilePreviewAvailabilityContext.Provider>
  );
}

export function useFilePreviewAvailabilityResolver() {
  return useContext(FilePreviewAvailabilityContext);
}
