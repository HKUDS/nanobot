import type { LucideIcon } from "lucide-react";

export type ChannelPresentation = {
  displayName: string;
  initials: string;
  color: string;
  icon?: LucideIcon;
  logoUrl?: string;
  setup?: ChannelCatalogSetupPresentation;
};

export type ChannelSetupPresentation = {
  mode?: "webui" | "credentials" | "connect";
  primaryActionLabel?: string;
  command?: string;
  docsUrl?: string;
  docsLabel?: string;
  docsLogoUrl?: string;
  officialUrl?: string;
  officialLabel?: string;
  summary?: string;
  tryIt?: string;
  steps: string[];
  fields?: ChannelConfigField[];
  manualFields?: ChannelConfigField[];
  actions?: ChannelSetupAction[];
  presets?: ChannelProviderPreset[];
};

export type ChannelCatalogSetupPresentation = {
  mode?: "webui" | "credentials" | "connect";
  command?: string;
  docsUrl?: string;
  docsLogoUrl?: string;
  fields?: ChannelFieldPresentation[];
  manualFields?: ChannelFieldPresentation[];
  actions?: ChannelSetupActionDefinition[];
  presets?: ChannelProviderPresetDefinition[];
};

export type ChannelFieldPresentation = {
  key: string;
};

export type ChannelSetupActionDefinition = Omit<ChannelSetupAction, "label">;

export type ChannelProviderPresetDefinition = Omit<ChannelProviderPreset, "label">;

export type ChannelSetupAction = {
  id: string;
  label: string;
  url?: string;
  copyText?: string;
  logoUrl?: string;
};

export type ChannelProviderPreset = {
  id: string;
  label: string;
  values: Record<string, string>;
};

export type ChannelConfigField = {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
  optional?: boolean;
  help?: string;
  inputType?: "text" | "number";
  defaultValue?: string;
  options?: ChannelConfigOption[];
};

export type ChannelConfigOption = {
  value: string;
  label: string;
};

const NANOBOT_DOCS_URL = "https://nanobot.wiki/docs/latest";
const CHAT_APPS_DOCS_URL = `${NANOBOT_DOCS_URL}/getting-started/chat-apps`;

export function chatAppGuideUrl(sectionId: string): string {
  return `${CHAT_APPS_DOCS_URL}#${sectionId}`;
}

export function docsUrlWithBase(
  url: string | undefined,
  chatAppsDocsUrl?: string,
): string | undefined {
  if (!url || !chatAppsDocsUrl) return url;
  if (!url.startsWith(CHAT_APPS_DOCS_URL)) return url;
  const anchor = url.includes("#") ? `#${url.split("#").pop()}` : "";
  return `${chatAppsDocsUrl.replace(/\/$/, "")}${anchor}`;
}
