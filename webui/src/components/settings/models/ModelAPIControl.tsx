import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SettingsRow } from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ModelAPIConfig } from "@/lib/types";

export function modelAPISelection(api: ModelAPIConfig | null | undefined): string {
  if (!api) return "auto";
  if (!api.supported_apis.includes("responses")) return "chat_completions";
  if (!api.supported_apis.includes("chat_completions")) return "responses";
  return (api.preferred_api ?? api.supported_apis[0]) === "responses"
    ? "prefer_responses"
    : "prefer_chat";
}

export function ModelAPIControl({
  value,
  onChange,
}: {
  value: ModelAPIConfig | null;
  onChange: (api: ModelAPIConfig | null) => void;
}) {
  const { t } = useTranslation();
  const options: Array<{ value: string; label: string; api: ModelAPIConfig | null }> = [
    { value: "auto", label: t("settings.models.apiAuto"), api: null },
    {
      value: "chat_completions", label: "Chat Completions",
      api: { supported_apis: ["chat_completions"], preferred_api: "chat_completions" },
    },
    {
      value: "responses", label: "Responses",
      api: { supported_apis: ["responses"], preferred_api: "responses" },
    },
    {
      value: "prefer_responses", label: t("settings.models.apiPreferResponses"),
      api: { supported_apis: ["responses", "chat_completions"], preferred_api: "responses" },
    },
    {
      value: "prefer_chat", label: t("settings.models.apiPreferChat"),
      api: { supported_apis: ["chat_completions", "responses"], preferred_api: "chat_completions" },
    },
  ];
  const selected = options.find((option) => option.value === modelAPISelection(value));
  return (
    <SettingsRow title={t("settings.models.requestAPI")} description={t("settings.models.requestAPIHelp")}>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            aria-label={t("settings.models.requestAPI")}
            className="h-9 w-full justify-between gap-3 rounded-full px-3 text-[13px]"
          >
            <span className="truncate">{selected?.label}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[220px]">
          {options.map((option) => (
            <DropdownMenuItem key={option.value} onSelect={() => onChange(option.api)}>
              {option.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </SettingsRow>
  );
}
