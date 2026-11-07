import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import {
  parseProviderObject,
  type ProviderAdvancedField,
  type ProviderForm,
} from "@/components/settings/models/providerForm";
import { SettingsTextEditor } from "@/components/settings/shared/SettingsTextEditor";
import { ApiError } from "@/lib/api";

const PARAMETER_FIELDS = [
  { field: "extra_headers", formKey: "extraHeaders", titleKey: "settings.providers.extraHeaders", placeholder: '{"X-Header":"value"}' },
  { field: "extra_query", formKey: "extraQuery", titleKey: "settings.providers.extraQuery", placeholder: '{"api-version":"2024-02-01"}' },
  { field: "extra_body", formKey: "extraBody", titleKey: "settings.providers.extraBody", placeholder: '{"service_tier":"priority"}' },
] as const;

export type RequestParameterDraft = Pick<ProviderForm, "extraHeaders" | "extraQuery" | "extraBody">;

function parameterSummary(value: string, inherit: boolean, t: TFunction): string {
  const parsed = parseProviderObject(value);
  if (parsed && !Object.keys(parsed).length) {
    return t(inherit ? "settings.providers.useProviderSettings" : "settings.values.notConfigured");
  }
  return parsed
    ? t("settings.providers.parameterCount", { count: Object.keys(parsed).length })
    : t("settings.values.configured");
}

export function ProviderParameterFields({ fields, form, onChange, onSave, inherit = false, draft = false, disabled = false }: {
  fields: ProviderAdvancedField[];
  form: RequestParameterDraft;
  onChange: (value: Partial<RequestParameterDraft>) => void;
  onSave?: (value: Partial<RequestParameterDraft>) => Promise<void>;
  inherit?: boolean;
  draft?: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const visible = PARAMETER_FIELDS.filter((item) => fields.includes(item.field));
  if (!visible.length) return null;

  return (
    <div className="min-w-0 overflow-hidden rounded-floating border border-border/60 md:col-span-2">
      {visible.map((item) => {
        const title = t(item.titleKey);
        return (
          <SettingsTextEditor key={item.field} title={title}
            disabled={disabled}
            saveLabel={draft ? t("settings.providers.applyToDraft") : undefined}
            description={draft ? t("settings.providers.draftHint") : undefined}
            value={form[item.formKey]} placeholder={item.placeholder}
            onSave={async (value) => {
              const parsed = parseProviderObject(value);
              if (!parsed) throw new Error(t("settings.providers.invalidObject"));
              if (item.field !== "extra_body" && Object.values(parsed).some((entry) => typeof entry !== "string")) {
                throw new Error(t("settings.providers.stringValuesRequired"));
              }
              const update = { [item.formKey]: value };
              try {
                if (onSave) await onSave(update);
                else onChange(update);
              } catch (error) {
                // The gateway alone can tell whether a mask has a saved value to retain.
                if (item.field !== "extra_body" && error instanceof ApiError && error.status === 400
                  && Object.entries(parsed).some(([key, entry]) => entry === "••••••••"
                    && error.message === `${item.field}.${key}: Input should be a valid string`)) {
                  throw new Error(t("settings.providers.maskedSecretMissing"), { cause: error });
                }
                throw error;
              }
            }}
            trigger={
              <button type="button" className="settings-hover flex min-h-12 w-full items-center gap-3 border-b border-border/60 px-3 py-3 text-left text-[13px] leading-5 last:border-b-0">
                <span className="min-w-0 flex-1 font-medium">{title}</span>
                <span className="min-w-0 text-right text-muted-foreground">{parameterSummary(form[item.formKey], inherit, t)}</span>
                <span className="shrink-0 text-muted-foreground">{t("settings.actions.edit")}</span>
              </button>
            }
          />
        );
      })}
    </div>
  );
}
