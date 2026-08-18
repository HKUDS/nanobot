import type { SettingsPayload } from "@/lib/types";

export type SettingsSectionKey =
  | "overview"
  | "appearance"
  | "models"
  | "image"
  | "voice"
  | "browser"
  | "channels"
  | "apps"
  | "automations"
  | "skills"
  | "runtime"
  | "advanced";

export type PendingRestartSection = "runtime" | "browser" | "image";
export type PendingRestartSections = Record<PendingRestartSection, boolean>;

export type RestartAwarePayload = {
  requires_restart?: boolean;
  surface?: SettingsPayload["surface"];
  runtime_surface?: SettingsPayload["runtime_surface"];
  runtime_capabilities?: SettingsPayload["runtime_capabilities"];
};

export type ApplySettingsPayload = (
  payload: SettingsPayload,
  options?: { preserveAgentForm?: boolean },
) => void;

export type MaybeRestartHostEngine = (payload: RestartAwarePayload) => Promise<void>;
