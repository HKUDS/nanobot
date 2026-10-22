import { SettingsPage } from "@/components/settings/SettingsPage";
import type { SettingsExitGuard, SettingsSectionKey } from "@/components/settings/contracts";
import { useSettingsController } from "@/components/settings/useSettingsController";
import type { SendAttachment, SendOptions } from "@/hooks/useNanobotStream";
import type { ChatSummary, SettingsPayload, SkillSummary, WebUIExtensionSummary } from "@/lib/types";

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
  skillsLoading?: boolean;
  skillsError?: boolean;
  extensions?: WebUIExtensionSummary[];
  onOpenExtension?: (extensionId: string) => void;
  onToggleExtension?: (extensionId: string, enabled: boolean) => Promise<void> | void;
  onEditExtension?: (extensionId: string, config: Record<string, unknown>) => Promise<void> | void;
  onDeleteExtension?: (extensionId: string) => Promise<void> | void;
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
  skillsLoading = false,
  skillsError = false,
  extensions = [],
  onOpenExtension,
  onToggleExtension,
  onEditExtension,
  onDeleteExtension,
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
      skillsLoading={skillsLoading}
      skillsError={skillsError}
      extensions={extensions}
      onOpenExtension={onOpenExtension}
      onToggleExtension={onToggleExtension}
      onEditExtension={onEditExtension}
      onDeleteExtension={onDeleteExtension}
      onStartAutomationChat={onStartAutomationChat}
      titleOverrides={titleOverrides}
      sessions={sessions}
      onLogout={onLogout}
      isRestarting={isRestarting}
      hostChromeInset={hostChromeInset}
    />
  );
}
