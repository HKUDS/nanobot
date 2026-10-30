import type { ModelAPIConfig, ModelRequestAPI, SettingsPayload } from "@/lib/types";

export const MODEL_REQUEST_APIS = ["chat_completions", "responses", "anthropic_messages"] as const;

export const REQUEST_API_LABELS: Record<ModelRequestAPI, string> = {
  chat_completions: "Chat Completions",
  responses: "Responses",
  anthropic_messages: "Anthropic Messages",
};

export function modelAPIConfigurable(provider: SettingsPayload["providers"][number] | undefined): boolean {
  if (Array.isArray(provider?.request_apis)) {
    const supported = provider.request_apis;
    return MODEL_REQUEST_APIS.filter((api) => supported.includes(api)).length > 1;
  }
  return provider?.model_api_configurable === true;
}

export function preferredModelAPI(api: ModelAPIConfig | null | undefined): ModelRequestAPI | "auto" {
  return api?.preferred_api ?? api?.supported_apis[0] ?? "auto";
}

export function modelAPISelection(api: ModelAPIConfig | null | undefined): string {
  const preferred = preferredModelAPI(api);
  if (preferred === "responses" && api?.supported_apis.includes("chat_completions")) {
    return "prefer_responses";
  }
  if (preferred === "chat_completions" && api?.supported_apis.includes("responses")) {
    return "prefer_chat";
  }
  return preferred;
}
