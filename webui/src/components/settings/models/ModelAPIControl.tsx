import { useId } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import { SettingsRow } from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ModelAPIConfig, SettingsPayload } from "@/lib/types";

export function modelAPIConfigurable(provider: SettingsPayload["providers"][number] | undefined): boolean {
  if (Array.isArray(provider?.request_apis)) {
    return provider.request_apis.includes("chat_completions") && provider.request_apis.includes("responses");
  }
  return provider?.model_api_configurable === true;
}

export function modelAPISelection(api: ModelAPIConfig | null | undefined): string {
  if (!api) return "auto";
  if (!api.supported_apis.includes("responses")) return "chat_completions";
  if (!api.supported_apis.includes("chat_completions")) return "responses";
  return (api.preferred_api ?? api.supported_apis[0]) === "responses"
    ? "prefer_responses"
    : "prefer_chat";
}

export function ModelAPIControl({
  provider,
  value,
  onChange,
}: {
  provider: SettingsPayload["providers"][number] | undefined;
  value: ModelAPIConfig | null;
  onChange: (api: ModelAPIConfig | null) => void;
}) {
  const { t } = useTranslation();
  const helpId = useId();
  const fallbackHelpId = useId();
  const requestAPIs = Array.isArray(provider?.request_apis) ? provider.request_apis : undefined;
  const configurable = modelAPIConfigurable(provider);
  const fixedAPI = requestAPIs?.length === 1 ? requestAPIs[0] : undefined;
  const fixedLabels = {
    responses: "Responses",
    chat_completions: "Chat Completions",
    anthropic_messages: "Anthropic Messages",
    bedrock_converse: "Bedrock Converse",
    transcription: t("settings.models.apiTranscription"),
  };
  const fixedLabel = fixedAPI ? fixedLabels[fixedAPI] : undefined;
  const selection = modelAPISelection(value);
  const selectedAPI = selection === "prefer_responses" ? "responses"
    : selection === "prefer_chat" ? "chat_completions" : selection;
  const allowChatFallback = selection === "prefer_responses";
  const options = [
    {
      value: "auto", label: t("settings.models.apiAuto"),
      help: t("settings.models.requestAPIHelp"),
    },
    {
      value: "responses", label: "Responses",
      help: t("settings.models.apiResponsesHelp"),
    },
    {
      value: "chat_completions", label: "Chat Completions",
      help: t("settings.models.apiChatHelp"),
    },
  ];
  const selected = options.find((option) => option.value === selectedAPI);
  const help = !configurable
    ? t("settings.models.apiProviderManagedHelp", { provider: provider?.label })
    : selectedAPI === "responses"
      ? t(allowChatFallback ? "settings.models.apiResponsesFallbackHelp" : "settings.models.apiResponsesOnlyHelp")
      : selected?.help;
  if (!configurable && !fixedLabel) return null;

  return (
    <div>
      <SettingsRow title={t("settings.models.requestAPI")}>
        {configurable ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="outline"
                aria-label={t("settings.models.requestAPI")}
                aria-describedby={helpId}
                className="h-9 w-full justify-between gap-3 rounded-full px-3 text-[13px]"
              >
                <span className="truncate">{selected?.label}</span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-[min(340px,calc(100vw-2rem))]">
              <DropdownMenuRadioGroup value={selectedAPI} onValueChange={(api) => {
                if (api === selectedAPI) return;
                if (api === "auto") onChange(null);
                else if (api === "responses" || api === "chat_completions") {
                  onChange({ supported_apis: [api], preferred_api: api });
                }
              }}>
                {options.map((option) => (
                  <DropdownMenuRadioItem
                    key={option.value}
                    value={option.value}
                    aria-label={option.label}
                    className="items-start py-2.5"
                  >
                    <span>
                      <span className="block text-[13px]">{option.label}</span>
                      <span className="mt-0.5 block text-[12px] leading-5 text-muted-foreground">
                        {option.help}
                      </span>
                    </span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <span className="block text-[13px] text-muted-foreground sm:text-right">{fixedLabel}</span>
        )}
      </SettingsRow>
      <p id={helpId} className="-mt-1 px-4 pb-3 text-[12px] leading-5 text-muted-foreground sm:px-5">
        {help}
      </p>
      {configurable && selectedAPI === "responses" ? (
        <div className="mx-4 mb-3 flex items-start justify-between gap-4 rounded-xl bg-muted/30 px-3 py-3 sm:mx-5">
          <div className="min-w-0">
            <p className="text-[12px] font-medium leading-5 text-foreground">{t("settings.models.apiFallback")}</p>
            <p id={fallbackHelpId} className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
              {t("settings.models.apiFallbackHelp")}
            </p>
          </div>
          <div className="pt-0.5">
            <ToggleButton
              checked={allowChatFallback}
              aria-describedby={fallbackHelpId}
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
