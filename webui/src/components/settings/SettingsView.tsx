import { SettingsPage } from "@/components/settings/SettingsPage";
import type { SettingsExitGuard, SettingsSectionKey } from "@/components/settings/contracts";
import { useSettingsController } from "@/components/settings/useSettingsController";
import type { SendAttachment, SendOptions } from "@/hooks/useNanobotStream";
import type { ChatSummary, SettingsPayload, SkillSummary } from "@/lib/types";

export type { SettingsSectionKey } from "@/components/settings/contracts";

interface SettingsViewProps {
  registerExitGuard?: (guard: SettingsExitGuard | null) => void;
  theme: "light" | "dark";
  initialSection?: SettingsSectionKey;
  initialSettings?: SettingsPayload | null;
  showSidebar?: boolean;
  mainNavigationExpanded?: boolean;
  onToggleTheme: () => void;
  onBackToChat: () => void;
  onModelNameChange: (modelName: string | null) => void;
  onSettingsChange?: (payload: SettingsPayload) => void;
  skills?: SkillSummary[];
  onStartAutomationChat?: (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
    modelPreset?: string | null,
  ) => boolean | void | Promise<boolean | void>;
  titleOverrides?: Record<string, string>;
  sessions?: ChatSummary[];
  onSectionChange?: (section: SettingsSectionKey) => void;
  onLogout?: () => void;
  onRestart?: () => void;
  onNativeEngineRestart?: () => Promise<string>;
  isRestarting?: boolean;
  hostChromeInset?: boolean;
}

export function SettingsView({
  registerExitGuard,
  theme,
  initialSection = "overview",
  initialSettings = null,
  showSidebar = true,
  mainNavigationExpanded = false,
  onToggleTheme,
  onBackToChat,
  onModelNameChange,
  onSettingsChange,
  skills = [],
  onStartAutomationChat,
  titleOverrides,
  sessions,
  onSectionChange,
  onLogout,
  onRestart,
  onNativeEngineRestart,
  isRestarting = false,
  hostChromeInset = false,
}: SettingsViewProps) {
  const controller = useSettingsController({
    initialSection,
    initialSettings,
    onModelNameChange,
    onSettingsChange,
    onSectionChange,
    onRestart,
    onNativeEngineRestart,
  });

  return (
    <SettingsPage
      registerExitGuard={registerExitGuard}
      controller={controller}
      theme={theme}
      showSidebar={showSidebar}
      mainNavigationExpanded={mainNavigationExpanded}
      onToggleTheme={onToggleTheme}
      onBackToChat={onBackToChat}
      skills={skills}
      onStartAutomationChat={onStartAutomationChat}
      titleOverrides={titleOverrides}
      sessions={sessions}
      onLogout={onLogout}
      isRestarting={isRestarting}
      hostChromeInset={hostChromeInset}
    />
  );
}
