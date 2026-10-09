import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import { SettingsRow } from "@/components/settings/shared/SettingsControls";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { ModelAPIConfig, ProviderRequestAPI, SettingsPayload } from "@/lib/types";

export function modelAPIConfigurable(provider: SettingsPayload["providers"][number] | undefined): boolean {
  if (Array.isArray(provider?.request_apis)) {
    const supported = provider.request_apis;
    return (["chat_completions", "responses", "anthropic_messages"] as const)
      .filter((api) => supported.includes(api)).length > 1;
  }
  return provider?.model_api_configurable === true;
}

export function modelAPISelection(api: ModelAPIConfig | null | undefined): string {
  if (!api) return "auto";
  if (api.supported_apis.includes("anthropic_messages")) return "anthropic_messages";
  if (!api.supported_apis.includes("responses")) return "chat_completions";
  if (!api.supported_apis.includes("chat_completions")) return "responses";
  return (api.preferred_api ?? api.supported_apis[0]) === "responses"
    ? "prefer_responses"
    : "prefer_chat";
}

export function ModelAPIControl({
  provider,
  automaticAPI,
  value,
  onChange,
}: {
  provider: SettingsPayload["providers"][number] | undefined;
  automaticAPI?: ProviderRequestAPI;
  value: ModelAPIConfig | null;
  onChange: (api: ModelAPIConfig | null) => void;
}) {
  const { t } = useTranslation();
  const [pointerFocus, setPointerFocus] = useState(false);
  const requestAPIs = Array.isArray(provider?.request_apis) ? provider.request_apis : undefined;
  const configurable = modelAPIConfigurable(provider);
  const fixedAPI = requestAPIs?.length === 1 ? requestAPIs[0] : undefined;
  const labels = {
    responses: "Responses",
    chat_completions: "Chat Completions",
    anthropic_messages: "Anthropic Messages",
    bedrock_converse: "Bedrock Converse",
    transcription: t("settings.models.apiTranscription"),
  };
  const fixedLabel = fixedAPI ? labels[fixedAPI] : undefined;
  const selection = modelAPISelection(value);
  const selectedAPI = selection === "prefer_responses" ? "responses"
    : selection === "prefer_chat" ? "chat_completions" : selection;
  const allowChatFallback = selection === "prefer_responses";
  const options = [
    {
      value: "auto",
      label: automaticAPI
        ? `${t("settings.models.apiAuto")} (${labels[automaticAPI]})`
        : t("settings.models.apiAuto"),
    },
    ...(["responses", "chat_completions", "anthropic_messages"] as const)
      .filter((api) => requestAPIs ? requestAPIs.includes(api) : api !== "anthropic_messages")
      .map((api) => ({ value: api, label: labels[api] })),
  ];
  if (!configurable && !fixedLabel) return null;

  return (
    <div>
      <SettingsRow title={t("settings.models.requestAPI")}>
        {configurable ? (
          <Select value={selectedAPI} onValueChange={(api) => {
            if (api === selectedAPI) return;
            if (api === "auto") onChange(null);
            else if (api === "responses" || api === "chat_completions" || api === "anthropic_messages") {
              onChange({ supported_apis: [api], preferred_api: api });
            }
          }}>
            <SelectTrigger
              aria-label={t("settings.models.requestAPI")}
              className={cn("w-full rounded-full", pointerFocus && "focus-visible:ring-0")}
              onPointerDown={() => setPointerFocus(true)}
              onKeyDown={() => setPointerFocus(false)}
              onBlur={() => setPointerFocus(false)}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent
              onPointerUpCapture={() => setPointerFocus(true)}
              onPointerDownOutside={() => setPointerFocus(true)}
              onKeyDownCapture={() => setPointerFocus(false)}
              onEscapeKeyDown={() => setPointerFocus(false)}
            >
              {options.map((option) => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="block text-[13px] text-muted-foreground sm:text-right">{fixedLabel}</span>
        )}
      </SettingsRow>
      {configurable && selectedAPI === "responses" && (!requestAPIs || requestAPIs.includes("chat_completions")) ? (
        <div className="mx-4 mb-3 flex items-start justify-between gap-4 rounded-xl bg-muted/30 px-3 py-3 sm:mx-5">
          <div className="min-w-0">
            <p className="text-[13px] leading-5 text-foreground">{t("settings.models.apiFallback")}</p>
          </div>
          <div className="pt-0.5">
            <ToggleButton
              checked={allowChatFallback}
              label={t("settings.models.apiFallback")}
              onChange={(checked) => onChange({
                supported_apis: checked ? ["responses", "chat_completions"] : ["responses"],
                preferred_api: "responses",
              })}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
