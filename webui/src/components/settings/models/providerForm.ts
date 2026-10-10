import type { ModelAPIConfig, SettingsPayload } from "@/lib/types";

export type ProviderAdvancedField = NonNullable<
  SettingsPayload["providers"][number]["advanced_fields"]
>[number];
export type ProviderForm = {
  displayName: string;
  apiKey: string;
  apiBase: string;
  api: ModelAPIConfig | null;
  proxy: string;
  extraHeaders: string;
  extraBody: string;
  extraQuery: string;
  thinkingStyle: string;
  region: string;
  profile: string;
};
export type CustomProviderDraft = ProviderForm & { name: string };
export const CUSTOM_PROVIDER_CREATION_KEY = "__custom_provider__";

export function providerJsonValue(value: Record<string, unknown> | null | undefined): string {
  return value && Object.keys(value).length > 0 ? JSON.stringify(value, null, 2) : "";
}

export function parseProviderObject(value: string): Record<string, unknown> | null {
  if (!value.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

export function providerFormFromRow(
  provider: SettingsPayload["providers"][number],
): ProviderForm {
  return {
    displayName: provider.is_custom ? provider.label : "",
    apiKey: "",
    apiBase: provider.api_base ?? provider.default_api_base ?? "",
    api: provider.api ?? null,
    proxy: provider.proxy ?? "",
    extraHeaders: providerJsonValue(provider.extra_headers),
    extraBody: providerJsonValue(provider.extra_body),
    extraQuery: providerJsonValue(provider.extra_query),
    thinkingStyle: provider.thinking_style ?? "",
    region: provider.region ?? "",
    profile: provider.profile ?? "",
  };
}

export function emptyCustomProviderDraft(): CustomProviderDraft {
  return {
    name: "",
    displayName: "",
    apiKey: "",
    apiBase: "",
    api: { supported_apis: ["chat_completions"], preferred_api: "chat_completions" },
    proxy: "",
    extraHeaders: "",
    extraBody: "",
    extraQuery: "",
    thinkingStyle: "",
    region: "",
    profile: "",
  };
}

