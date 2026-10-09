import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { ModelAPIConfig, ModelRequestAPI } from "@/lib/types";

const APIS: Array<{ value: ModelRequestAPI; label: string }> = [
  { value: "chat_completions", label: "Chat Completions" },
  { value: "responses", label: "Responses" },
  { value: "anthropic_messages", label: "Anthropic Messages" },
];

export function ProviderAPIControl({ value, onChange }: {
  value: ModelAPIConfig | null;
  onChange: (api: ModelAPIConfig) => void;
}) {
  const { t } = useTranslation();
  if (value === null) {
    return (
      <Button variant="outline" className="rounded-full" onClick={() => onChange({
        supported_apis: ["chat_completions"], preferred_api: "chat_completions",
      })}>
        {t("settings.providers.declareAPIs")}
      </Button>
    );
  }
  const supported = value.supported_apis;
  const preferred = value.preferred_api ?? supported[0];
  return (
    <div className="space-y-3">
      <fieldset className="space-y-3 rounded-xl border border-border/60 p-3">
        <legend className="px-1 text-[12px] font-medium text-muted-foreground">
          {t("settings.providers.supportedAPIs")}
        </legend>
        {APIS.map((api) => {
          const checked = supported.includes(api.value);
          return (
            <div key={api.value} className="flex items-center justify-between gap-3 text-[13px]">
              <span>{api.label}</span>
              <ToggleButton
                label={api.label}
                checked={checked}
                disabled={checked && supported.length === 1}
                onChange={(enabled) => {
                  const next = enabled ? [...supported, api.value] : supported.filter((item) => item !== api.value);
                  onChange({ supported_apis: next, preferred_api: next.includes(preferred) ? preferred : next[0] });
                }}
              />
            </div>
          );
        })}
      </fieldset>
      <div className="space-y-1.5">
        <span className="text-[12px] font-medium text-muted-foreground">
          {t("settings.providers.defaultAPI")}
        </span>
        <Select value={preferred} onValueChange={(api) => onChange({
          supported_apis: supported, preferred_api: api as ModelRequestAPI,
        })}>
          <SelectTrigger aria-label={t("settings.providers.defaultAPI")} className="w-full rounded-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {APIS.filter((api) => supported.includes(api.value)).map((api) => (
              <SelectItem key={api.value} value={api.value}>{api.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
