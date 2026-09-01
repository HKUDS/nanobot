import type { SettingsPayload } from "@/lib/types";

export type ModelSetupIntent = "account" | "apiKey" | "local";

export type ModelSetupAvailability = Record<ModelSetupIntent, boolean>;

type Provider = SettingsPayload["providers"][number];

const LOCAL_MODEL_PROVIDERS = new Set([
  "atomic_chat",
  "lm_studio",
  "ollama",
  "ovms",
  "vllm",
]);

function isLocalModelProvider(provider: Provider): boolean {
  if (LOCAL_MODEL_PROVIDERS.has(provider.name)) return true;
  const apiBase = provider.api_base?.trim().toLowerCase() ?? "";
  return (
    apiBase.includes("localhost")
    || apiBase.includes("127.0.0.1")
    || apiBase.includes("[::1]")
  );
}

export function modelSetupIntentForProvider(provider: Provider): ModelSetupIntent {
  if (provider.auth_type === "oauth") return "account";
  return isLocalModelProvider(provider) ? "local" : "apiKey";
}

export function providerMatchesModelSetupIntent(
  provider: Provider,
  intent: ModelSetupIntent,
): boolean {
  return modelSetupIntentForProvider(provider) === intent;
}

export function modelSetupAvailability(
  providers: SettingsPayload["providers"] | null | undefined,
): ModelSetupAvailability {
  const configured = providers?.filter((provider) => provider.configured) ?? [];
  return {
    account: configured.some((provider) => modelSetupIntentForProvider(provider) === "account"),
    apiKey: configured.some((provider) => modelSetupIntentForProvider(provider) === "apiKey"),
    local: configured.some((provider) => modelSetupIntentForProvider(provider) === "local"),
  };
}
