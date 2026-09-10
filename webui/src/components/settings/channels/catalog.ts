import type { ComponentType } from "react";

export type ChannelPresentation = {
  displayName: string;
  initials: string;
  color: string;
  icon?: ComponentType<{ className?: string; strokeWidth?: string | number }>;
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
  sectionLabels?: Record<string, string>;
  fields?: ChannelConfigField[];
  manualFields?: ChannelConfigField[];
  requirements?: ChannelSetupRequirement[];
  actions?: ChannelSetupAction[];
  presets?: ChannelProviderPreset[];
};

type ChannelCatalogSetupPresentation = {
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
  section?: string;
};

export type ChannelFieldSection =
  | "account"
  | "credentials"
  | "connection"
  | "access"
  | "behavior"
  | "security"
  | "advanced";

export type ChannelSetupRequirement = {
  alternatives: string[][];
};

type ChannelSetupActionDefinition = Omit<ChannelSetupAction, "label">;

export type ChannelProviderPresetDefinition = Omit<ChannelProviderPreset, "label">;

type ChannelSetupAction = {
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
  inputType?: "text" | "number" | "url" | "email" | "tel";
  kind?: "string" | "secret" | "int" | "bool" | "list" | "enum" | string;
  section?: string;
  defaultValue?: string;
  options?: ChannelConfigOption[];
};

type ChannelConfigOption = {
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
