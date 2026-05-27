export interface DesktopRuntimeInfo {
  surface: "desktop";
  app_version: string;
  engine_status: "starting" | "ready" | "restarting" | "stopped" | "crashed";
  data_dir: string;
  logs_dir: string;
  config_path: string;
  workspace_path: string;
  python: string;
  api_base?: string;
}

export interface NanobotDesktopApi {
  getRuntimeInfo(): Promise<DesktopRuntimeInfo>;
  restartEngine(): Promise<void>;
  pickFolder(): Promise<string | null>;
  openLogs(): Promise<void>;
  exportDiagnostics(): Promise<string>;
  checkForUpdates(): Promise<{ supported: boolean; message?: string }>;
}

declare global {
  interface Window {
    nanobotDesktop?: NanobotDesktopApi;
  }
}

export function getDesktopApi(): NanobotDesktopApi | null {
  if (typeof window === "undefined") return null;
  return window.nanobotDesktop ?? null;
}

export function hasDesktopApi(): boolean {
  return getDesktopApi() !== null;
}
