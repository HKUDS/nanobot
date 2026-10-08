import { useTranslation } from "react-i18next";

import { MODEL_REQUEST_APIS, REQUEST_API_LABELS } from "@/components/settings/models/modelAPI";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { SettingsHint } from "@/components/settings/shared/SettingsHint";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { ModelAPIConfig, ModelRequestAPI } from "@/lib/types";

export function ProviderAPIControl({ value, onChange }: {
  value: ModelAPIConfig | null;
  onChange: (api: ModelAPIConfig) => void;
}) {
  const { t } = useTranslation();
  const supported = value?.supported_apis ?? [...MODEL_REQUEST_APIS];
  const preferred = value?.preferred_api ?? supported[0];
  return (
    <div className="space-y-3">
      <fieldset className="space-y-3 rounded-floating border border-border/60 p-3">
        <legend className="px-1 text-[12px] font-medium text-muted-foreground">
          <SettingsHint description={t("settings.providers.supportedAPIsDescription")}>
            {t("settings.providers.supportedAPIs")}
          </SettingsHint>
        </legend>
        {MODEL_REQUEST_APIS.map((api) => {
          const checked = supported.includes(api);
          return (
            <div key={api} className="flex items-center justify-between gap-3 text-[13px]">
              <span>{REQUEST_API_LABELS[api]}</span>
              <ToggleButton
                label={REQUEST_API_LABELS[api]}
                checked={checked}
                disabled={checked && supported.length === 1}
                onChange={(enabled) => {
                  const next = enabled ? [...supported, api] : supported.filter((item) => item !== api);
                  onChange({ supported_apis: next, preferred_api: next.includes(preferred) ? preferred : next[0] });
                }}
              />
            </div>
          );
        })}
      </fieldset>
      <div className="space-y-1.5">
        <span className="block px-3 text-[12px] font-medium text-muted-foreground">
          <SettingsHint description={t("settings.providers.defaultAPIDescription")}>
            {t("settings.providers.defaultAPI")}
          </SettingsHint>
        </span>
        <Select value={preferred} onValueChange={(api) => onChange({
          supported_apis: supported, preferred_api: api as ModelRequestAPI,
        })}>
          <SelectTrigger aria-label={t("settings.providers.defaultAPI")} className="w-full rounded-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MODEL_REQUEST_APIS.filter((api) => supported.includes(api)).map((api) => (
              <SelectItem key={api} value={api}>{REQUEST_API_LABELS[api]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
