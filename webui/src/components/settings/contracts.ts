import type { SettingsPayload } from "@/lib/types";

export type SettingsExitGuard = (leave: () => void) => void;

export type SettingsSectionKey =
  | "overview"
  | "about"
  | "appearance"
  | "models"
  | "capabilities"
  | "image"
  | "voice"
  | "browser"
  | "channels"
  | "apps"
  | "automations"
  | "memory"
  | "skills"
  | "runtime"
  | "advanced";

export function isCapabilitySection(section: SettingsSectionKey): boolean {
  return ["capabilities", "image", "voice", "browser", "memory"].includes(section);
}

type PendingRestartSection = "runtime" | "browser" | "image";
export type PendingRestartSections = Record<PendingRestartSection, boolean>;

export type RestartAwarePayload = {
  requires_restart?: boolean;
  surface?: SettingsPayload["surface"];
  runtime_surface?: SettingsPayload["runtime_surface"];
  runtime_capabilities?: SettingsPayload["runtime_capabilities"];
};

export type ApplySettingsPayload = (
  payload: SettingsPayload,
  options?: { preserveAgentForm?: boolean; preserveCapabilityForms?: boolean },
) => void;

export type MaybeRestartHostEngine = (payload: RestartAwarePayload) => Promise<void>;
